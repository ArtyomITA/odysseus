"""Vista (gli occhi): avvio on-demand di Holo e stato per il loader in chat.

Il browser non puo' parlare con la porta di Holo (CSP connect-src 'self'),
e comunque non deve: il VLM e' un dettaglio del server. Qui solo tre cose:
avvia (idempotente, bloccante finche' pronto e caldo), stato, ferma.
"""

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import _auth_disabled, effective_user

logger = logging.getLogger(__name__)


def setup_vista_routes() -> APIRouter:
    router = APIRouter(prefix="/api/vista")

    def _require_user(request: Request) -> str:
        owner = effective_user(request) or ""
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        if (not owner and not _auth_disabled() and auth_mgr is not None
                and getattr(auth_mgr, "is_configured", False)):
            raise HTTPException(401, "Not authenticated")
        return owner

    @router.get("/stato")
    def vista_stato(request: Request) -> Dict[str, Any]:
        _require_user(request)
        from src.vista.client import get_vista
        v = get_vista()
        s = v.stato()
        s["attiva"] = v.attiva
        return s

    @router.post("/avvia")
    async def vista_avvia(request: Request) -> Dict[str, Any]:
        """Avvia Holo (se serve) e attende che sia pronto e caldo. Il loader
        in chat mostra l'attesa; il primo prefill paga 10-19s di init encoder,
        meglio pagarli qui che al primo messaggio dell'utente."""
        _require_user(request)
        from src.vista.client import VistaNonDisponibile, get_vista
        v = get_vista()
        generation = v.imposta_attiva(True)
        try:
            s = await asyncio.to_thread(v.avvia, True, generation)
        except VistaNonDisponibile as e:
            raise HTTPException(503, str(e))
        s["attiva"] = True
        return s

    @router.post("/ferma")
    async def vista_ferma(request: Request) -> Dict[str, Any]:
        _require_user(request)
        from src.vista.client import get_vista
        v = get_vista()
        generation = v.imposta_attiva(False)
        await asyncio.to_thread(v.ferma, generation)
        s = v.stato()
        s["attiva"] = False
        return s

    return router
