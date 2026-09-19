# routes/stt_routes.py
"""STT API routes — multi-provider (local Whisper, API endpoint, browser)."""

import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect

from src.upload_limits import read_upload_limited, STT_MAX_AUDIO_BYTES

logger = logging.getLogger(__name__)

# Il riconoscitore in streaming vive nel ponte voce, non qui: e' li' che stanno
# sherpa-onnx e i 700 MB di modello. Odysseus fa solo da tramite, e lo fa per un
# motivo preciso: la CSP dichiara `connect-src 'self'`, quindi il browser non
# puo' aprire una WebSocket verso :8013 direttamente. Passare da qui evita di
# allargare la CSP per una cosa che si puo' inoltrare.
PONTE_WS = os.getenv("VOICE_BRIDGE_WS", "ws://127.0.0.1:8013/v1/audio/stream")


def setup_stt_routes(stt_service):
    """Setup STT routes with the provided STT service"""
    router = APIRouter(prefix="/api/stt", tags=["stt"])

    @router.websocket("/stream")
    async def stream_transcription(client: WebSocket):
        """Inoltra il microfono al ponte e il testo indietro, in tempo reale."""
        await client.accept()

        lingua = client.query_params.get("lingua", "it")
        try:
            import websockets
        except ImportError:
            await client.send_json({"errore": "websockets non installato sul server"})
            await client.close()
            return

        try:
            ponte = await websockets.connect(f"{PONTE_WS}?lingua={lingua}",
                                             max_size=None, open_timeout=5)
        except Exception as e:
            logger.warning(f"Voice bridge unreachable for streaming STT: {e}")
            await client.send_json({"errore": "ponte voce non raggiungibile"})
            await client.close()
            return

        async def verso_ponte():
            while True:
                msg = await client.receive()
                if msg.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect()
                if msg.get("bytes") is not None:
                    await ponte.send(msg["bytes"])
                elif msg.get("text") is not None:
                    await ponte.send(msg["text"])

        async def verso_client():
            async for risposta in ponte:
                await client.send_text(risposta)

        # Le due direzioni corrono insieme; la prima che finisce chiude l'altra,
        # altrimenti resterebbe un compito appeso a una connessione morta.
        compiti = [asyncio.create_task(verso_ponte()),
                   asyncio.create_task(verso_client())]
        try:
            _, in_sospeso = await asyncio.wait(
                compiti, return_when=asyncio.FIRST_COMPLETED)
            for c in in_sospeso:
                c.cancel()
        except Exception:
            logger.exception("streaming STT relay failed")
        finally:
            try:
                await ponte.close()
            except Exception:
                pass
            try:
                await client.close()
            except Exception:
                pass

    @router.get("/stats")
    async def get_stt_stats():
        """Get STT service statistics"""
        try:
            return stt_service.get_stats()
        except Exception as e:
            logger.error(f"Failed to get STT stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/transcribe")
    async def transcribe_audio(file: UploadFile = File(...)):
        """Transcribe uploaded audio file to text"""
        try:
            if not stt_service.available:
                raise HTTPException(
                    status_code=503,
                    detail={"message": "STT service not available or set to browser mode"}
                )

            audio_bytes = await read_upload_limited(file, STT_MAX_AUDIO_BYTES, "Audio file")
            if not audio_bytes:
                raise HTTPException(status_code=400, detail={"message": "Empty audio file"})

            text = stt_service.transcribe(audio_bytes)
            if text is None:
                raise HTTPException(
                    status_code=500,
                    detail={"message": "Transcription failed"}
                )

            return {"text": text}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"message": f"Transcription failed: {str(e)}"}
            )

    return router
