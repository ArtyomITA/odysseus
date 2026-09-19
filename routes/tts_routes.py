# routes/tts_routes.py
"""
TTS API routes — multi-provider (local Kokoro, API endpoint, browser).
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class TTSRequest(BaseModel):
    text: str
    format: str = "audio"  # "audio" or "base64"

def setup_tts_routes(tts_service):
    """Setup TTS routes with the provided TTS service"""
    router = APIRouter(prefix="/api/tts", tags=["tts"])

    @router.get("/stats")
    async def get_tts_stats():
        """Get TTS service statistics"""
        try:
            return tts_service.get_stats()
        except Exception as e:
            logger.error(f"Failed to get TTS stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/stream")
    def stream_speech(text: str = Query(..., min_length=1, max_length=5000)):
        """Progressive audio: the browser starts playing while the rest arrives.

        GET on purpose. An <audio> element fed a URL plays it as it downloads;
        the same bytes fetched into a Blob first cannot start until the last
        byte lands, which is what made every sentence wait 2-3 seconds.

        Sync handler: the underlying client is blocking, and FastAPI runs sync
        handlers in a threadpool — an async one would pin the event loop for
        the whole synthesis, once per sentence.
        """
        if not tts_service.available:
            raise HTTPException(status_code=503,
                                detail={"message": "TTS service not available"})

        sorgente = tts_service.synthesize_stream(text)

        # The content type has to be decided before the first byte goes out, so
        # the first chunk is pulled here and re-injected. PocketTTS answers WAV
        # even when mp3 is requested; a real OpenAI endpoint answers mp3.
        try:
            primo = next(sorgente)
        except StopIteration:
            raise HTTPException(status_code=500,
                                detail={"message": "Synthesis failed"})

        is_mp3 = primo[:3] == b"ID3" or (
            len(primo) >= 2 and primo[0] == 0xFF and (primo[1] & 0xE0) == 0xE0)
        mime = "audio/mpeg" if is_mp3 else "audio/wav"

        def flusso():
            yield primo
            yield from sorgente

        return StreamingResponse(
            flusso(),
            media_type=mime,
            headers={
                "Cache-Control": "no-store",
                # Some proxies buffer a response until it ends unless told not to,
                # which would silently restore the very delay this removes.
                "X-Accel-Buffering": "no",
                "Content-Disposition": "inline; filename=speech.wav",
            },
        )

    @router.post("/synthesize")
    def synthesize_speech(request: TTSRequest):
        """Synthesize speech from text.

        Deliberately sync: tts_service uses a blocking HTTP client, so an async
        handler would stall the event loop for the whole synthesis — once per
        sentence with read-aloud on. FastAPI runs sync handlers in a threadpool.
        """
        try:
            if not tts_service.available:
                raise HTTPException(
                    status_code=503,
                    detail={"message": "TTS service not available"}
                )
            
            if request.format == "base64":
                audio_b64 = tts_service.synthesize_to_base64(request.text)
                if not audio_b64:
                    raise HTTPException(
                        status_code=500,
                        detail={"message": "Synthesis failed"}
                    )
                return {"audio": audio_b64}
            
            else:  # audio format
                audio_data = tts_service.synthesize(request.text)
                if not audio_data:
                    raise HTTPException(
                        status_code=500,
                        detail={"message": "Synthesis failed"}
                    )
                
                # Detect format from magic bytes (MP3: ID3 tag or sync word ff e0+)
                is_mp3 = audio_data[:3] == b'ID3' or (len(audio_data) >= 2 and audio_data[0] == 0xff and (audio_data[1] & 0xe0) == 0xe0)
                mime = "audio/mpeg" if is_mp3 else "audio/wav"
                return Response(
                    content=audio_data,
                    media_type=mime,
                    headers={
                        "Content-Disposition": "inline; filename=speech.mp3" if "mpeg" in mime else "inline; filename=speech.wav"
                    }
                )
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Synthesis error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"message": f"Synthesis failed: {str(e)}"}
            )

    @router.post("/clear-cache")
    async def clear_tts_cache():
        """Clear TTS cache"""
        try:
            tts_service.clear_cache()
            return {"success": True, "message": "Cache cleared"}
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
