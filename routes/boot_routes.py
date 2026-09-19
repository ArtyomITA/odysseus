"""Proxy verso Vergilius Boot (porta 7001) per il selettore di profilo in alto.

Il browser non puo' parlare con :7001 (CSP connect-src 'self'): stesso motivo
delle rotte ShadowBroker. Qui solo stato e cambio profilo; il boot fa il lavoro
(spegne/avvia servizi, riavvia Odysseus con il nuovo profilo).
"""

import json
import logging
import urllib.request
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import _auth_disabled, effective_user

logger = logging.getLogger(__name__)
BOOT = "http://127.0.0.1:7001"


def setup_boot_routes() -> APIRouter:
    router = APIRouter(prefix="/api/boot")

    def _require_user(request: Request) -> str:
        owner = effective_user(request) or ""
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        if (not owner and not _auth_disabled() and auth_mgr is not None
                and getattr(auth_mgr, "is_configured", False)):
            raise HTTPException(401, "Not authenticated")
        return owner

    def _get(percorso: str) -> Dict[str, Any]:
        with urllib.request.urlopen(BOOT + percorso, timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))

    @router.get("/status")
    def boot_status(request: Request) -> Dict[str, Any]:
        _require_user(request)
        try:
            return _get("/api/status")
        except Exception as e:
            return {"ok": False, "boot": False, "detail": str(e)[:120]}

    @router.post("/profile")
    async def boot_profile(request: Request) -> Dict[str, Any]:
        """Cambio profilo a caldo. Il boot riavvia Odysseus: la pagina deve
        aspettare il loader e ricaricarsi (lo fa boot.html su :7001)."""
        _require_user(request)
        corpo = await request.json()
        profilo = str((corpo or {}).get("profile") or "").strip().lower()
        if not profilo:
            raise HTTPException(422, "profile richiesto")
        req = urllib.request.Request(BOOT + "/api/profile", data=json.dumps({"profile": profilo, "change": True}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise HTTPException(e.code, e.read().decode("utf-8", "replace")[:200])
        except Exception as e:
            raise HTTPException(503, f"boot non raggiungibile: {str(e)[:120]}")

    return router
