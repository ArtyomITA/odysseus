"""Client Holo: avvio on-demand del llama-server CPU, grounding, descrizione,
screenshot. Bloccante (urllib): va chiamato da thread (come _Base.execute).

Processo Holo:
- porta dedicata (VISTA_PORT, default 8095), CUDA_VISIBLE_DEVICES="" cosi'
  la VRAM della 1080 resta tutta a Ling (misurato: zero contesto CUDA);
- --reasoning off + --chat-template-kwargs enable_thinking=false AL LANCIO
  (per-request e' ignorato silenziosamente da llama.cpp);
- --image-min-tokens 1024 (warning llama.cpp: sotto, il grounding Qwen-VL
  degrada); max 2304 = 1080p a risoluzione nativa;
- warm-up con una chiamata finta: il primo prefill paga 10-19s di init encoder.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8095
DEFAULT_SERVER = r"d:\assistenteeee\llama-cuda124-new\llama-server.exe"
DEFAULT_MODELLO = r"d:\assistenteeee\models\vlm\Holo-3.1-0.8B.Q6_K.gguf"
DEFAULT_MMPROJ = r"d:\assistenteeee\models\vlm\Holo-3.1-0.8B.mmproj-f16.gguf"
DEFAULT_THREADS = "6"

_TIMEOUT_CHIAMATA = 90.0
_TIMEOUT_AVVIO = 240.0

# Prompt ufficiale H Company (hub.hcompany.ai/element-localization.md):
# temp 0, thinking off, JSON {x,y} normalizzato 0-1000 sull'immagine inviata.
PROMPT_GROUNDING = (
    "Localize an element on the GUI image according to the provided target and output a click position.\n"
    " * You must output a valid JSON following the format: {\"x\": int, \"y\": int}\n"
    " Your target is:\n{target}"
)

# Soglia sotto cui un target viene considerato "piccolo" e si zooma in automatico.
_PAROLE_PICCOLO = ("checkbox", "check box", "icon", "icona", "close button", "x button", "the x ",
                   "badge", "toggle", "radio", "caret", "arrow", "chevron", "bell", "dot", "small")


class VistaNonDisponibile(RuntimeError):
    pass


class VistaClient:
    def __init__(self) -> None:
        self.port = int(os.getenv("VISTA_PORT") or DEFAULT_PORT)
        self.base = f"http://127.0.0.1:{self.port}"
        self.server = os.getenv("VISTA_SERVER") or DEFAULT_SERVER
        self.modello = os.getenv("VISTA_MODELLO") or DEFAULT_MODELLO
        self.mmproj = os.getenv("VISTA_MMPROJ") or DEFAULT_MMPROJ
        self.threads = os.getenv("VISTA_THREADS") or DEFAULT_THREADS
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._warmup_thread: Optional[threading.Thread] = None
        self._warmup_generation: Optional[int] = None
        self._lifecycle_generation = 0
        self._caldo = False
        self._ultimo_uso = 0.0
        # Modalita' "vista" accesa dall'utente (toggle in chat). Quando e' vera,
        # gli allegati immagine passano da Holo e i tool vista_* sono forzati.
        self.attiva = False

    def imposta_attiva(self, valore: bool) -> int:
        """Set the requested lifecycle state and invalidate stale workers."""
        with self._lock:
            nuovo = bool(valore)
            if self.attiva != nuovo:
                self.attiva = nuovo
                self._lifecycle_generation += 1
            return self._lifecycle_generation

    def generazione_attiva(self, generation: int) -> bool:
        with self._lock:
            return bool(
                self.attiva and generation == self._lifecycle_generation
            )

    # ------------------------------------------------------------ processo
    def pronto(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def stato(self) -> Dict[str, Any]:
        vivo = self._proc is not None and self._proc.poll() is None
        return {"pronto": self.pronto(), "processo": vivo, "caldo": self._caldo,
                "porta": self.port, "modello": os.path.basename(self.modello)}

    def avvia(
        self,
        attendi: bool = True,
        expected_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Avvia Holo se non gira. Idempotente. Ritorna lo stato."""
        with self._lock:
            if expected_generation is None:
                expected_generation = self._lifecycle_generation
            if (
                not self.attiva
                or expected_generation != self._lifecycle_generation
            ):
                raise VistaNonDisponibile("avvio Holo annullato da un cambio profilo")
            if self.pronto():
                pass  # already serving; an awaited call may still need warm-up
            elif self._proc is not None and self._proc.poll() is None:
                pass  # in avvio da una chiamata precedente
            else:
                if not os.path.exists(self.modello) or not os.path.exists(self.mmproj):
                    raise VistaNonDisponibile("modello Holo o mmproj non trovati in models/vlm")
                env = dict(os.environ, CUDA_VISIBLE_DEVICES="")
                cmd = [self.server, "--host", "127.0.0.1", "--port", str(self.port),
                       "-m", self.modello, "--mmproj", self.mmproj,
                       "-ngl", "0", "-t", self.threads, "-c", "8192", "--jinja",
                       "--reasoning", "off", "--chat-template-kwargs", '{"enable_thinking":false}',
                       "--image-min-tokens", "1024", "--image-max-tokens", "2304"]
                flags = 0x08000000 | 0x00000200 if os.name == "nt" else 0  # NO_WINDOW | NEW_PROCESS_GROUP
                log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
                os.makedirs(log_dir, exist_ok=True)
                log = open(os.path.join(log_dir, "vista-holo.log"), "ab")
                try:
                    proc = subprocess.Popen(
                        cmd,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=flags,
                    )
                finally:
                    # Popen duplicates/inherits the redirection handle it needs;
                    # keeping the parent's file object open leaks one handle on
                    # every Holo restart (especially visible on Windows).
                    log.close()
                self._proc = proc
                self._caldo = False
                logger.info("[vista] Holo avviato pid=%s porta=%s", self._proc.pid, self.port)
        if attendi:
            t0 = time.time()
            while not self.pronto():
                with self._lock:
                    if expected_generation != self._lifecycle_generation:
                        raise VistaNonDisponibile("avvio Holo annullato da un cambio profilo")
                    proc = self._proc
                if proc is not None and proc.poll() is not None:
                    raise VistaNonDisponibile(f"Holo terminato in avvio (exit {proc.returncode}), vedi logs/vista-holo.log")
                if time.time() - t0 > _TIMEOUT_AVVIO:
                    raise VistaNonDisponibile("Holo non risponde dopo l'avvio")
                time.sleep(0.5)
            with self._lock:
                if expected_generation != self._lifecycle_generation:
                    raise VistaNonDisponibile("warm-up Holo annullato da un cambio profilo")
            self._scalda(expected_generation=expected_generation)
        return self.stato()

    def avvia_in_background(
        self,
        expected_generation: Optional[int] = None,
    ) -> None:
        """Start/warm Holo once without spawning one waiter per UI poll."""
        with self._lock:
            if not self.attiva:
                return
            if expected_generation is None:
                expected_generation = self._lifecycle_generation
            if expected_generation != self._lifecycle_generation:
                return
            if self.pronto() and self._caldo:
                return
            if self._warmup_thread is not None and self._warmup_thread.is_alive():
                # Same generation: one worker is enough.  A newer generation
                # must not be swallowed by a stale off->on worker: both may
                # briefly wait on the same process, but lifecycle checks keep
                # the stale worker from warming or publishing state.
                if self._warmup_generation == expected_generation:
                    return
            generation = expected_generation

            def _worker() -> None:
                try:
                    self.avvia(attendi=True, expected_generation=generation)
                except Exception as exc:
                    logger.warning("[vista] avvio in background fallito: %s", exc)
                finally:
                    with self._lock:
                        if self._warmup_thread is threading.current_thread():
                            self._warmup_thread = None
                            self._warmup_generation = None

            self._warmup_thread = threading.Thread(
                target=_worker,
                name=f"vista-holo-warmup-{generation}",
                daemon=True,
            )
            self._warmup_generation = generation
            self._warmup_thread.start()

    def _scalda(self, expected_generation: Optional[int] = None) -> None:
        if self._caldo:
            return
        if (
            expected_generation is not None
            and expected_generation != self._lifecycle_generation
        ):
            return
        try:
            from PIL import Image
            im = Image.new("RGB", (64, 64), (128, 128, 128))
            self._chiama([im], "Describe briefly.", 5, 0.0)
            if (
                expected_generation is None
                or expected_generation == self._lifecycle_generation
            ):
                self._caldo = True
        except Exception as e:
            logger.warning("[vista] warm-up fallito: %s", e)

    def ferma(self, expected_generation: Optional[int] = None) -> None:
        with self._lock:
            if expected_generation is None:
                self.attiva = False
                self._lifecycle_generation += 1
                expected_generation = self._lifecycle_generation
            elif (
                expected_generation != self._lifecycle_generation
                or self.attiva
            ):
                return
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
                self._proc.wait(timeout=10)
            self._proc = None
            self._caldo = False

    # ------------------------------------------------------------ chiamata
    @staticmethod
    def _b64(im) -> str:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def _chiama(self, immagini: List[Any], prompt: str, max_tokens: int, temp: float,
                schema: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        content = [{"type": "image_url", "image_url": {"url": self._b64(im)}} for im in immagini]
        content.append({"type": "text", "text": prompt})
        corpo: Dict[str, Any] = {"model": "holo", "max_tokens": max_tokens, "temperature": temp,
                                 "messages": [{"role": "user", "content": content}]}
        if schema:
            corpo["response_format"] = {"type": "json_schema", "json_schema": {"name": "r", "schema": schema}}
        req = urllib.request.Request(f"{self.base}/v1/chat/completions", data=json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            # llama-server has one CPU-heavy Holo slot; serialising calls avoids
            # two chats oversubscribing the 4300GE and delaying Ling.
            with self._inference_lock:
                with urllib.request.urlopen(req, timeout=_TIMEOUT_CHIAMATA) as r:
                    d = json.loads(r.read().decode())
        except (urllib.error.URLError, OSError) as e:
            raise VistaNonDisponibile(f"Holo non raggiungibile: {e}") from e
        self._ultimo_uso = time.time()
        msg = d["choices"][0]["message"]
        return (msg.get("content") or "").strip(), d.get("timings", {})

    def _assicura(self) -> None:
        if not self.pronto():
            self.avvia(attendi=True)
        elif not self._caldo:
            self._scalda()

    # ------------------------------------------------------------ screenshot
    @staticmethod
    def screenshot():
        """Schermo primario, PIL Image RGB. Nessuna dipendenza oltre Pillow."""
        from PIL import ImageGrab
        return ImageGrab.grab().convert("RGB")

    # ------------------------------------------------------------ grounding
    def _ground_una(self, im, target: str) -> Tuple[Optional[float], Optional[float], str]:
        txt, _ = self._chiama([im], PROMPT_GROUNDING.replace("{target}", target), 40, 0.0)
        m = re.search(r'"x"\s*:\s*(\d+)\s*,\s*"y"\s*:\s*(\d+)', txt)
        if not m:
            return None, None, txt
        W, H = im.size
        return int(m.group(1)) / 1000 * W, int(m.group(2)) / 1000 * H, txt

    def trova(self, im, target: str, zoom: Optional[bool] = None) -> Dict[str, Any]:
        """Coordinate pixel del target sull'immagine `im`.

        zoom=None -> automatico: secondo passo (crop 400px ingrandito x2 attorno
        alla prima stima) se il target sembra piccolo. Misurato: recupera 2/3
        dei target < 30px mancati al primo colpo, costa +2.5-4s.
        """
        self._assicura()
        W, H = im.size
        t0 = time.time()
        px, py, grezzo = self._ground_una(im, target)
        if px is None:
            return {"trovato": False, "motivo": "risposta non interpretabile", "grezzo": grezzo[:80],
                    "larghezza": W, "altezza": H}
        passi = 1
        if zoom is None:
            zoom = any(p in target.lower() for p in _PAROLE_PICCOLO)
        if zoom:
            from PIL import Image
            cx, cy, R = int(px), int(py), 200
            box = (max(0, cx - R), max(0, cy - R), min(W, cx + R), min(H, cy + R))
            crop = im.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.LANCZOS)
            qx, qy, _ = self._ground_una(crop, target)
            if qx is not None:
                px, py = box[0] + qx / 2, box[1] + qy / 2
                passi = 2
        px, py = max(0, min(W - 1, px)), max(0, min(H - 1, py))
        return {"trovato": True, "x": int(round(px)), "y": int(round(py)), "larghezza": W, "altezza": H,
                "passi": passi, "secondi": round(time.time() - t0, 1)}

    # ------------------------------------------------------------ descrizione
    # Descrizione NEUTRA e dettagliata. Misurato (22 ago, Teams reale): le
    # domande chiuse ("ci sono messaggi non letti?") producono yes-bias e
    # invenzioni; il JSON senza domanda legge il testo vero dello schermo.
    # Il confronto con la richiesta dell'utente lo fa il cervello, non gli occhi.
    SCHEMA_SCHERMO = {
        "type": "object",
        "properties": {
            "app": {"type": "string"},
            "finestra_attiva": {"type": "string"},
            "tipo_contenuto": {"type": "string"},
            "contenuto_principale": {"type": "string"},
            "testo_leggibile": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            "contatori_e_badge": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "elementi_principali": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "dialog_o_popup": {"type": "string"},
        },
        "required": ["app", "finestra_attiva", "tipo_contenuto", "contenuto_principale", "testo_leggibile",
                     "contatori_e_badge", "elementi_principali", "dialog_o_popup"],
    }
    SCHEMA_IMMAGINE = {
        "type": "object",
        "properties": {
            "tipo": {"type": "string"},
            "descrizione": {"type": "string"},
            "soggetti": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "testo_visibile": {"type": "string"},
            "luogo_o_ambiente": {"type": "string"},
        },
        "required": ["tipo", "descrizione", "soggetti", "testo_visibile", "luogo_o_ambiente"],
    }

    def descrivi_schermo(self, im, focus: str = "") -> Dict[str, Any]:
        """Stato dello schermo come UI, JSON neutro e dettagliato.

        `focus` (opzionale) orienta l'attenzione ("notifications, unread counters,
        recent messages") SENZA porre una domanda chiusa: gli occhi descrivono,
        il cervello confronta con la richiesta dell'utente. Il livello "as a UI"
        e' fissato nel prompt (misurato: senza, descrive la foto dentro la pagina)."""
        self._assicura()
        prompt = ("You are the eyes of an AI agent controlling this computer. Describe this screenshot AS A USER INTERFACE, "
                  "in detail and factually. Fill every field: app (application or website name), finestra_attiva (title "
                  "of the foreground window), tipo_contenuto (web page / chat / document / editor / dialog / desktop / media), "
                  "contenuto_principale (2-3 sentences: what the main area shows), testo_leggibile (up to 12 short strings "
                  "of text actually readable on screen: headings, message previews, labels, dates), contatori_e_badge "
                  "(any numbers, badges, dots or counters shown on icons/tabs/chats, with where they are; empty if none), "
                  "elementi_principali (up to 8 interactive elements), dialog_o_popup ('none' or the title of any dialog, "
                  "popup or overlapping window and where it is). Report only what is visible; never assume.")
        if focus.strip():
            prompt += f" Pay particular attention to: {focus.strip()[:160]}."
        txt, t = self._chiama([im], prompt, 420, 0.1, self.SCHEMA_SCHERMO)
        return self._json(txt, t)

    def descrivi_immagine(self, im) -> Dict[str, Any]:
        self._assicura()
        prompt = ("Describe this image. Fill every field: tipo (photo / screenshot / drawing / diagram / document), "
                  "descrizione (2-3 factual sentences), soggetti (people, animals, objects — up to 8 short labels, never "
                  "guess identities), testo_visibile (any readable text, or 'none'), luogo_o_ambiente (setting). "
                  "Do not invent details that are not visible.")
        txt, t = self._chiama([im], prompt, 260, 0.1, self.SCHEMA_IMMAGINE)
        return self._json(txt, t)

    def domanda(self, im, domanda: str, max_tokens: int = 120) -> Dict[str, Any]:
        """UNA domanda libera sull'immagine. Chi chiama deve passare una sola
        domanda: a 0.8B i prompt composti ricevono risposta solo alla prima parte."""
        self._assicura()
        txt, t = self._chiama([im], domanda.strip() + " Answer factually in one or two sentences.", max_tokens, 0.1)
        return {"risposta": txt, "secondi": round(t.get("prompt_ms", 0) / 1000 + t.get("predicted_ms", 0) / 1000, 1)}

    @staticmethod
    def _json(txt: str, t: Dict[str, Any]) -> Dict[str, Any]:
        try:
            d = json.loads(txt)
        except Exception:
            m = re.search(r"\{.*\}", txt, re.S)
            d = json.loads(m.group(0)) if m else {"grezzo": txt[:300]}
        d["_secondi"] = round((t.get("prompt_ms", 0) + t.get("predicted_ms", 0)) / 1000, 1)
        return d

    # ------------------------------------------------------------ video
    def descrivi_video(self, percorso: str, fps: float = 0.5, max_frame: int = 12) -> Dict[str, Any]:
        """Frame via ffmpeg -> UNA chiamata Holo per frame -> lista con timestamp.
        Il ragionamento temporale lo fa il cervello testuale: misurato, 4 frame
        in una richiesta fanno ancorare Holo al primo frame."""
        import shutil
        import tempfile
        from PIL import Image
        ffmpeg = shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg.exe"
        if not os.path.exists(ffmpeg) and not shutil.which("ffmpeg"):
            raise VistaNonDisponibile("ffmpeg non trovato")
        self._assicura()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "f_%03d.png")
            subprocess.run([ffmpeg, "-v", "error", "-y", "-i", percorso, "-vf", f"fps={fps},scale='min(960,iw)':-2",
                            "-frames:v", str(max_frame), out], check=True, timeout=120,
                           creationflags=0x08000000 if os.name == "nt" else 0)
            nomi = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
            frame: List[Dict[str, Any]] = []
            for i, n in enumerate(nomi):
                im = Image.open(os.path.join(tmp, n)).convert("RGB")
                txt, _ = self._chiama([im], "Describe what is visible in this video frame in one factual sentence.", 60, 0.1)
                frame.append({"t_s": round(i / fps, 1), "descrizione": txt})
        return {"frame": frame, "fps_campionati": fps, "nota": "descrizioni indipendenti per frame; la sequenza va letta in ordine di t_s"}


_client: Optional[VistaClient] = None
_client_lock = threading.Lock()


def get_vista() -> VistaClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = VistaClient()
        return _client
