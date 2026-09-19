"""ShadowBroker workspace glue.

Vergilius embeds the ShadowBroker OSINT dashboard (a separate Next.js app) as an
iframe inside the Odysseus chat area. Two things the browser cannot do for
itself, and therefore have to live here:

  * **Where is it?** The frontend must not hardcode a port. It asks this module,
    which reads the environment so a port change is a config edit, not a code
    edit.

  * **Is it up?** Odysseus' own CSP is `connect-src 'self'`, so the page cannot
    fetch `localhost:3000` to check. And an iframe's load result is unreadable
    across origins — a dead dashboard and a slow one look identical. The probe
    runs server-side, where neither limit applies, so the panel can say
    "non raggiungibile" instead of showing a white rectangle forever.

Nothing here proxies ShadowBroker's data. The browser talks to the dashboard
directly; this is only discovery and liveness.
"""

import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Request

from src.auth_helpers import _auth_disabled, effective_user

logger = logging.getLogger(__name__)

# Both default to the ports ShadowBroker's own dev setup uses.
DEFAULT_URL = "http://127.0.0.1:3000"
DEFAULT_API = "http://127.0.0.1:8000"

# Loopback, so latency should be nil — but the ShadowBroker frontend runs the
# Next.js dev server, which recompiles on demand and routinely takes over a
# second to answer `/`. At 1.5s the panel declared "non raggiungibile" on a
# service that was simply busy compiling.
_PROBE_TIMEOUT = 5.0


def shadowbroker_url() -> str:
    return (os.getenv("SHADOWBROKER_URL") or DEFAULT_URL).rstrip("/")


def shadowbroker_api() -> str:
    return (os.getenv("SHADOWBROKER_API_URL") or DEFAULT_API).rstrip("/")


def setup_shadowbroker_routes() -> APIRouter:
    router = APIRouter(prefix="/api")
    _register(router)
    return router


def _register(router: APIRouter) -> None:
    def _require_user(request: Request) -> str:
        """Same gate the model list uses: authenticated, or single-user mode."""
        owner = effective_user(request) or ""
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        if (
            not owner
            and not _auth_disabled()
            and auth_mgr is not None
            and getattr(auth_mgr, "is_configured", False)
        ):
            from fastapi import HTTPException

            raise HTTPException(401, "Not authenticated")
        return owner

    @router.get("/shadowbroker/config")
    def shadowbroker_config(request: Request) -> Dict[str, Any]:
        """Where the dashboard lives, for the iframe and the pop-out button."""
        _require_user(request)
        return {
            "url": shadowbroker_url(),
            "api": shadowbroker_api(),
            "enabled": True,
        }

    @router.post("/shadowbroker/preset")
    async def shadowbroker_preset(request: Request) -> Dict[str, Any]:
        """Accende sulla mappa un insieme di livelli gia' scelto.

        Serve all'interruttore Financial: quando si accende il profilo, la
        mappa deve trovarsi gia' con addosso quello che serve, cosi' il modello
        da li' in poi puo' limitarsi a **evidenziare** invece di spegnere —
        che e' la differenza fra far risaltare qualcosa e cancellare il
        contesto che l'operatore si e' costruito.

        Passa da qui e non dal browser perche' la CSP dichiara
        `connect-src 'self'`: la pagina non puo' parlare con la porta 8000.
        """
        _require_user(request)
        try:
            corpo = await request.json()
        except Exception:
            corpo = {}
        nome = str((corpo or {}).get("preset") or "financial").strip().lower()

        try:
            from src.shadowbroker.schemi import PRESET_MAPPA
            from src.shadowbroker.client import get_client
        except Exception as exc:
            return {"ok": False, "detail": f"ponte non disponibile: {type(exc).__name__}"}

        livelli = PRESET_MAPPA.get(nome)
        if not livelli:
            return {"ok": False, "detail": f"preset '{nome}' sconosciuto",
                    "ammessi": sorted(PRESET_MAPPA)}
        try:
            import asyncio
            esito = await asyncio.to_thread(
                get_client().comando, "set_layers",
                {"on": livelli, "solo": True}, 15)
        except Exception as exc:
            # La mappa spenta non deve impedire di usare il profilo: gli
            # strumenti funzionano lo stesso, semplicemente non si vede nulla.
            logger.info("[shadowbroker] preset %s non applicato: %s", nome, exc)
            return {"ok": False, "detail": f"{type(exc).__name__}"}
        return {"ok": True, "preset": nome, "livelli": livelli, "esito": esito}

    @router.post("/shadowbroker/start")
    async def shadowbroker_start(request: Request) -> Dict[str, Any]:
        """Avvia backend e cruscotto ShadowBroker se sono spenti.

        Il pannello offline mostrava i due comandi da copiare a mano; il
        pulsante ▶ li lancia da qui. Processi DETACHED: sopravvivono a un
        riavvio di Odysseus, esattamente come se lanciati da un terminale.
        Log di avvio accanto ai rispettivi progetti.
        """
        _require_user(request)
        import socket
        import subprocess
        from urllib.parse import urlparse

        def _su(porta: int) -> bool:
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=1.0):
                    return True
            except OSError:
                return False

        porta_api = urlparse(shadowbroker_api()).port or 8000
        porta_ui = urlparse(shadowbroker_url()).port or 3000
        base = os.getenv("SHADOWBROKER_DIR", "d:/assistenteeee/shadowbroker")
        cartella_backend = os.path.join(base, "backend")
        cartella_frontend = os.path.join(base, "frontend")
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        flags = 0x00000008 | 0x00000200

        avviati = []
        try:
            if not _su(porta_api):
                log_b = open(os.path.join(cartella_backend, "avvio-backend.log"), "ab")
                subprocess.Popen(
                    [os.path.join(cartella_backend, "venv", "Scripts", "python.exe"), "main.py"],
                    cwd=cartella_backend, stdout=log_b, stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                avviati.append("backend")
            if not _su(porta_ui):
                log_f = open(os.path.join(cartella_frontend, "avvio-frontend.log"), "ab")
                subprocess.Popen(
                    ["cmd", "/c", "npm", "run", "dev:frontend"],
                    cwd=cartella_frontend, stdout=log_f, stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                avviati.append("frontend")
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:150]}",
                    "avviati": avviati}
        return {"ok": True, "avviati": avviati,
                "gia_su": {"backend": "backend" not in avviati and _su(porta_api),
                           "frontend": "frontend" not in avviati and _su(porta_ui)}}

    @router.post("/vergilius/spegni")
    async def vergilius_spegni(request: Request) -> Dict[str, Any]:
        """Spegne l'intero stack dal pulsante ⏻ della barra utente.

        Lo script parte DETACHED e riceve -TranneOdysseus: uccide llama,
        ChromaDB, voce e ShadowBroker ma non la porta 7000 — cosi' questa
        risposta arriva intera al browser. Odysseus esce da solo un attimo
        dopo, con os._exit: a quel punto non c'e' piu' niente da chiudere
        con garbo, e un shutdown ordinato di uvicorn aspetterebbe le
        connessioni aperte (compresa quella del pannello) restando appeso.
        """
        _require_user(request)
        import subprocess
        import threading

        script = os.getenv(
            "VERGILIUS_SPEGNI_SCRIPT",
            r"d:\assistenteeee\scripts\spegni-tutto.ps1",
        )
        if not os.path.exists(script):
            return {"ok": False, "detail": f"script non trovato: {script}"}
        comando = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", script, "-TranneOdysseus"]
        log_spegni = open(r"d:\assistenteeee\logs\spegni.log", "ab")
        try:
            # NO_WINDOW | NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB.
            # NON DETACHED_PROCESS: powershell senza console muore in culla
            # (log vuoto, zero kill — misurato). NO_WINDOW gli da' una
            # console nascosta e vive. Il breakaway serve se Odysseus sta
            # dentro un Job: un figlio nel Job muore col padre e lo
            # spegnimento resterebbe a meta'.
            subprocess.Popen(
                comando, creationflags=0x08000000 | 0x00000200 | 0x01000000,
                stdout=log_spegni, stderr=subprocess.STDOUT,
            )
        except OSError:
            # Job senza permesso di breakaway: si riparte senza, e il timer
            # lungo sotto da' comunque allo script il tempo di finire.
            try:
                subprocess.Popen(
                    comando, creationflags=0x08000000 | 0x00000200,
                    stdout=log_spegni, stderr=subprocess.STDOUT,
                )
            except Exception as exc:
                return {"ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:150]}"}
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:150]}"}

        def _esci():
            logger.info("[vergilius] spegnimento richiesto dal pulsante: esco")
            os._exit(0)

        # 10 s: lo script impiega ~5 a uccidere tutto e verificare. Se siamo
        # in un Job che ha negato il breakaway, deve FINIRE prima di noi.
        threading.Timer(10.0, _esci).start()
        return {"ok": True, "detail": "spegnimento avviato: Odysseus esce fra 10 secondi"}

    @router.get("/shadowbroker/strumenti")
    def shadowbroker_strumenti(request: Request, profile: str = "intelligence") -> Dict[str, Any]:
        """La scheda 'cosa posso fare' per l'utente: strumenti del profilo attivo
        raggruppati per dominio, in italiano semplice con domande-esempio.

        Non e' il prompt del modello (quello sono gli schemi); e' la navigazione
        pensata per una persona, cosi' l'utente sa cosa puo' chiedere senza
        leggere 17 nomi tecnici.
        """
        _require_user(request)
        try:
            from src.shadowbroker.navigazione import catalogo_navigazione
        except Exception as exc:
            return {"ok": False, "detail": f"navigazione non disponibile: {type(exc).__name__}"}
        return {"ok": True, **catalogo_navigazione(profile)}

    @router.get("/shadowbroker/rules")
    def shadowbroker_rules(request: Request, profile: str = "financial") -> Dict[str, Any]:
        """Il testo delle regole del profilo attivo, per la finestra regole.

        Le regole vivono in `schemi.py` e vengono iniettate nel prompt di
        sistema; il frontend non le vedeva. Questa route le serve cosi' come
        il modello le riceve — nessuna parafrasi, l'operatore legge lo stesso
        contratto che vincola il modello.
        """
        _require_user(request)
        try:
            from src.shadowbroker.schemi import REGOLE_FINANCE, REGOLE_OSINT
        except Exception as exc:
            return {"ok": False, "detail": f"schemi non disponibili: {type(exc).__name__}"}
        nome = str(profile or "financial").strip().lower()
        testo = REGOLE_FINANCE if nome == "financial" else REGOLE_OSINT
        return {"ok": True, "profile": nome, "rules": testo}

    @router.get("/shadowbroker/financial-config")
    async def financial_config_get(request: Request) -> Dict[str, Any]:
        """Proxy verso il backend ShadowBroker: la CSP `connect-src 'self'`
        impedisce alla pagina di parlare con la porta 8000."""
        _require_user(request)
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(shadowbroker_api() + "/api/financial/config")
                return r.json()
        except Exception as exc:
            return {"ok": False, "detail": f"backend: {type(exc).__name__}"}

    @router.post("/shadowbroker/financial-config")
    async def financial_config_set(request: Request) -> Dict[str, Any]:
        """Inoltra le scelte del popup Financial al backend ShadowBroker."""
        _require_user(request)
        try:
            corpo = await request.json()
        except Exception:
            corpo = {}
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.post(shadowbroker_api() + "/api/financial/config",
                                 json=corpo or {})
                return r.json()
        except Exception as exc:
            return {"ok": False, "detail": f"backend: {type(exc).__name__}"}

    @router.get("/shadowbroker/probe")
    def shadowbroker_probe(request: Request) -> Dict[str, Any]:
        """Liveness of both halves — the dashboard and its own backend.

        Reported separately on purpose: the map can render fine while the
        FastAPI side is down, and the panel says so rather than pretending
        everything is healthy.
        """
        _require_user(request)
        result = {"frontend": False, "backend": False, "detail": ""}
        try:
            r = httpx.get(shadowbroker_url() + "/", timeout=_PROBE_TIMEOUT)
            # Any HTTP answer means something is serving; Next.js may redirect
            # or 404 the root depending on routing, and that is still "up".
            result["frontend"] = r.status_code < 500
        except Exception as exc:
            result["detail"] = f"frontend: {type(exc).__name__}"
        try:
            r = httpx.get(shadowbroker_api() + "/api/ai/status", timeout=_PROBE_TIMEOUT)
            result["backend"] = r.status_code < 500
        except Exception as exc:
            detail = f"backend: {type(exc).__name__}"
            result["detail"] = f"{result['detail']}; {detail}" if result["detail"] else detail
        return result
