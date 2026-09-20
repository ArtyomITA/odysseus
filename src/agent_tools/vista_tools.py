"""Handler dei tool `vista_*` — gli occhi del cervello testuale.

Stessa forma dei tool ShadowBroker (_Base: run() in thread, ritorno
{"output"}/{"error"}). Holo guarda, qui si orchestra: scomposizione in UNA
domanda per chiamata, zoom automatico sui target piccoli, frame singoli per il
video. Al modello arriva solo testo/JSON.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from src.agent_tools.shadowbroker_tools import _Base, _args, _consegna, _errore  # noqa: F401

logger = logging.getLogger(__name__)

_IMMAGINI = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VIDEO = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


def _allegato_recente(ctx: Dict[str, Any], nome: str = "", estensioni=_IMMAGINI) -> Optional[Dict[str, Any]]:
    """Cerca l'allegato nell'indice upload: per nome se dato, altrimenti il piu'
    recente dell'owner con estensione compatibile."""
    try:
        from src.constants import UPLOAD_DIR
        indice = os.path.join(UPLOAD_DIR, "uploads.json")
        with open(indice, encoding="utf-8") as f:
            voci = json.load(f)
    except Exception:
        return None
    owner = ctx.get("owner")
    nome_l = (nome or "").strip().lower()
    candidati = []
    for v in voci.values():
        p = v.get("path") or ""
        if not p or not os.path.exists(p):
            continue
        if os.path.splitext(p)[1].lower() not in estensioni:
            continue
        if owner and v.get("owner") and v.get("owner") != owner:
            continue
        orig = (v.get("original_name") or "").lower()
        if nome_l and nome_l not in orig and nome_l not in os.path.basename(p).lower():
            continue
        candidati.append(v)
    if not candidati:
        return None
    candidati.sort(key=lambda v: v.get("last_accessed") or v.get("uploaded_at") or "", reverse=True)
    return candidati[0]


def _apri(percorso: str):
    from PIL import Image
    return Image.open(percorso).convert("RGB")


def _vista_pronta():
    from src.vista.client import VistaNonDisponibile, get_vista
    v = get_vista()
    if not v.attiva:
        raise VistaNonDisponibile(
            "Gli occhi Holo non sono attivi in questo profilo/chat."
        )
    v.avvia(attendi=True)
    return v


async def _snapshot_mcp() -> Dict[str, Any]:
    """Albero a11y di Windows-MCP (Snapshot), in-loop. Ritorna {"albero": str}
    o {"errore": str}. Mai solleva: se il server non c'e', gli occhi bastano."""
    try:
        from src.tool_utils import get_mcp_manager
        mm = get_mcp_manager()
        if not mm:
            return {"errore": "Windows-MCP non collegato"}
        nome = next((t["qualified_name"] for t in mm.get_all_tools() if t.get("name") == "Snapshot"), None)
        if not nome:
            # Testo in inglese: lo legge il modello. Senza albero non puo'
            # cliccare nulla, e deve dirlo invece di indovinare dalle sole
            # parole degli occhi (che non fanno OCR).
            logger.warning(
                "[vista] Snapshot non disponibile: Windows-MCP non collegato "
                "(controlla Impostazioni > MCP, lo stato del server 'windows')"
            )
            return {"errore": (
                "The Windows-MCP server is not connected, so there is no "
                "clickable UI tree and no window list. Do not guess window "
                "names from the screen description: say the PC control server "
                "is offline and that it must be reconnected in Settings > MCP."
            )}
        r = await mm.call_tool(nome, {})
        if r.get("error"):
            return {"errore": str(r["error"])[:200]}
        return {"albero": (r.get("stdout") or r.get("output") or "")}
    except Exception as e:
        return {"errore": f"{type(e).__name__}: {str(e)[:160]}"}


def _compatta_albero(albero: str, max_righe: int = 120) -> str:
    """Tiene intestazione finestre + UI Tree, taglia a max_righe righe dichiarando
    il taglio. Il Snapshot intero su un desktop pieno sono ~4000 token: troppi
    per un contesto da 49K insieme alla descrizione degli occhi."""
    righe = [r.rstrip() for r in (albero or "").splitlines() if r.strip()]
    if len(righe) <= max_righe:
        return "\n".join(righe)
    return "\n".join(righe[:max_righe]) + f"\n… [{len(righe) - max_righe} righe omesse: chiedi uno Snapshot mirato se serve]"


class SchermoTool(_Base):
    """vista_schermo — SEMPRE entrambi: albero a11y (coordinate cliccabili) +
    descrizione neutra degli occhi (contenuto, testo, badge). Scelta dell'utente
    (22 ago): niente preferenza tra i due, il cervello li legge insieme."""

    async def execute(self, content: str, ctx: dict) -> dict:
        import asyncio
        a = _args(content)
        try:
            snap_task = asyncio.create_task(_snapshot_mcp())
            occhi = await asyncio.to_thread(self._occhi, a)
            snap = await snap_task
            d = dict(occhi)
            if snap.get("albero"):
                d["albero_ui"] = _compatta_albero(snap["albero"])
                d["come_usare_albero"] = "Ogni riga '(x,y) tipo \"etichetta\"' si clicca con mcp__windows__Click(loc=[x, y])."
            else:
                d["albero_ui"] = ""
                d["albero_nota"] = snap.get("errore", "albero non disponibile")
            return _consegna(d)
        except Exception as e:
            logger.exception("[vista] vista_schermo fallito")
            return _errore(f"vista_schermo: {str(e)[:180]}")

    def _occhi(self, a: Dict[str, Any]) -> Dict[str, Any]:
        v = _vista_pronta()
        im = v.screenshot()
        # Niente domande chiuse agli occhi (yes-bias misurato): solo focus.
        focus = (a.get("focus") or a.get("domanda") or a.get("_testo") or "").strip()
        d = v.descrivi_schermo(im, focus=focus)
        d["schermo"] = f"{im.width}x{im.height}"
        if focus:
            d["focus_richiesto"] = focus
        d["nota"] = "Riferisci all'utente in italiano."
        return d

    def run(self, a: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        try:
            d = self._occhi(a)
            # Il JSON degli occhi e' in inglese e trascina la lingua della
            # risposta (misurato nell'E2E: primo turno in inglese). La nota sta
            # nell'output del tool, non nel prompt: cache KV intatta.
            d["nota"] = "Riferisci all'utente in italiano."
            return _consegna(d)
        except Exception as e:
            return _errore(f"vista_schermo: {str(e)[:180]}")


class TrovaTool(_Base):
    """vista_trova — coordinate pixel di UN elemento sullo schermo attuale."""

    def run(self, a: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        elemento = (a.get("elemento") or a.get("_testo") or "").strip()
        if not elemento:
            return _errore("vista_trova: serve 'elemento' (descrizione breve in inglese dell'elemento da trovare)")
        try:
            v = _vista_pronta()
            im = v.screenshot()
            r = v.trova(im, elemento)
            if not r.get("trovato"):
                r["suggerimento"] = ("Elemento non localizzato. Prova una descrizione piu' visiva "
                                     "(colore, posizione: 'the blue button at the bottom right') o usa Snapshot.")
            else:
                r["come_usare"] = f"Click at x={r['x']} y={r['y']} (screen {r['larghezza']}x{r['altezza']})."
            r["elemento"] = elemento
            return _consegna(r)
        except Exception as e:
            return _errore(f"vista_trova: {str(e)[:180]}")


class ImmagineTool(_Base):
    """vista_immagine — descrizione JSON o UNA domanda su un'immagine allegata."""

    def run(self, a: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        nome = (a.get("file") or "").strip()
        domanda = (a.get("domanda") or "").strip()
        if not nome and not domanda and a.get("_testo"):
            domanda = a["_testo"].strip()
        voce = _allegato_recente(ctx, nome, _IMMAGINI)
        if voce is None and nome and os.path.exists(nome) and os.path.splitext(nome)[1].lower() in _IMMAGINI:
            voce = {"path": nome, "original_name": os.path.basename(nome)}
        if voce is None:
            return _errore("vista_immagine: nessuna immagine allegata trovata. Chiedi all'utente di allegarla.")
        try:
            v = _vista_pronta()
            im = _apri(voce["path"])
            if domanda:
                r = v.domanda(im, domanda)
                return _consegna({"file": voce.get("original_name"), "domanda": domanda, "risposta": r["risposta"]})
            d = v.descrivi_immagine(im)
            d["file"] = voce.get("original_name")
            d["dimensioni"] = f"{im.width}x{im.height}"
            return _consegna(d)
        except Exception as e:
            return _errore(f"vista_immagine: {str(e)[:180]}")


class VideoTool(_Base):
    """vista_video — frame campionati, una descrizione per frame con timestamp."""

    def run(self, a: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        nome = (a.get("file") or a.get("_testo") or "").strip()
        try:
            fps = float(a.get("fps") or 0.5)
        except (TypeError, ValueError):
            fps = 0.5
        fps = max(0.1, min(2.0, fps))
        voce = _allegato_recente(ctx, nome, _VIDEO)
        if voce is None and nome and os.path.exists(nome) and os.path.splitext(nome)[1].lower() in _VIDEO:
            voce = {"path": nome, "original_name": os.path.basename(nome)}
        if voce is None:
            return _errore("vista_video: nessun video allegato trovato. Chiedi all'utente di allegarlo.")
        try:
            v = _vista_pronta()
            d = v.descrivi_video(voce["path"], fps=fps)
            d["file"] = voce.get("original_name")
            d["istruzione"] = "Racconta tu la sequenza in ordine di t_s; i frame sono descritti indipendentemente."
            return _consegna(d)
        except Exception as e:
            return _errore(f"vista_video: {str(e)[:180]}")


VISTA_TOOL_HANDLERS = {
    "vista_schermo": SchermoTool().execute,
    "vista_trova": TrovaTool().execute,
    "vista_immagine": ImmagineTool().execute,
    "vista_video": VideoTool().execute,
}

VISTA_TOOL_NAMES = frozenset(VISTA_TOOL_HANDLERS)
