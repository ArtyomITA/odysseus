"""Memoria delle sequenze riuscite — few-shot dinamico dai turni veri.

Idea (Agent Workflow Memory, arXiv:2409.07429): un modello piccolo orchestra
molto meglio se vede COME una domanda simile e' stata risolta davvero, invece
di dover inventare la strategia. Qui:

  * `registra()` — a fine turno riuscito (>=1 tool, risposta vera, niente
    round esauriti) si appende una riga JSONL: domanda + sequenza strumenti.
  * `suggerisci()` — alla domanda successiva si cerca la traccia piu' simile
    (overlap di parole, zero LLM) e la si restituisce come stringa-guida.

Il suggerimento va appeso IN CODA AL MESSAGGIO UTENTE, mai nel system: il
system e' il prefisso della cache KV (32x su questa macchina) e deve restare
identico fra i turni. La coda cambia comunque a ogni domanda.

File append-only, potato quando supera il tetto. Niente lock sofisticati:
una riga persa non e' un problema, e' statistica.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PERCORSO = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "data", "tracce_riuscite.jsonl"))

_MAX_RIGHE = 800
_TAGLIO_A = 500
_MIN_OVERLAP = 2

_lock = threading.Lock()
_cache: List[Dict[str, Any]] = []
_cache_mtime: float = -1.0

_STOPWORD = {
    "come", "cosa", "quali", "quale", "sono", "stati", "state", "della",
    "delle", "degli", "nell", "nelle", "negli", "sulla", "sulle", "con",
    "per", "che", "una", "uno", "gli", "dei", "the", "and", "ultime",
    "ultimi", "oggi", "adesso", "fammi", "dimmi", "mostrami", "rispetto",
}


def _parole(testo: str) -> set:
    return {p for p in re.findall(r"[a-zà-ù]{3,}", (testo or "").lower())
            if p not in _STOPWORD}


def registra(domanda: str, strumenti: List[str]) -> None:
    """Appende una traccia. Mai sollevare: e' un contorno, non il piatto."""
    try:
        seq = [s for s in strumenti if s and s != "?"]
        if not seq or not (domanda or "").strip():
            return
        # Sequenza compressa: le ripetizioni consecutive non insegnano niente.
        compressa = [seq[0]]
        for s in seq[1:]:
            if s != compressa[-1]:
                compressa.append(s)
        riga = {
            "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "domanda": str(domanda).strip()[:200],
            "strumenti": compressa[:10],
        }
        os.makedirs(os.path.dirname(_PERCORSO), exist_ok=True)
        with _lock:
            with open(_PERCORSO, "a", encoding="utf-8") as f:
                f.write(json.dumps(riga, ensure_ascii=False) + "\n")
            _pota_se_serve()
    except Exception as e:
        logger.debug("[tracce] registrazione saltata: %s", e)


def _pota_se_serve() -> None:
    try:
        with open(_PERCORSO, "r", encoding="utf-8") as f:
            righe = f.readlines()
        if len(righe) > _MAX_RIGHE:
            with open(_PERCORSO, "w", encoding="utf-8") as f:
                f.writelines(righe[-_TAGLIO_A:])
    except OSError:
        pass


def _carica() -> List[Dict[str, Any]]:
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(_PERCORSO)
    except OSError:
        return []
    with _lock:
        if mtime != _cache_mtime:
            fuori = []
            try:
                with open(_PERCORSO, "r", encoding="utf-8") as f:
                    for riga in f:
                        try:
                            v = json.loads(riga)
                            if isinstance(v, dict) and v.get("strumenti"):
                                fuori.append(v)
                        except json.JSONDecodeError:
                            continue
                _cache = fuori
                _cache_mtime = mtime
            except OSError:
                return _cache
        return _cache


def suggerisci(domanda: str) -> Optional[str]:
    """La sequenza della traccia piu' simile, come stringa 'a -> b -> c'.

    None se nessuna traccia supera l'overlap minimo: meglio nessun esempio
    che un esempio fuorviante."""
    try:
        chiavi = _parole(domanda)
        if not chiavi:
            return None
        migliore, punteggio = None, 0
        for t in _carica():
            comune = len(chiavi & _parole(t.get("domanda") or ""))
            if comune > punteggio:
                migliore, punteggio = t, comune
        if migliore is None or punteggio < _MIN_OVERLAP:
            return None
        return " -> ".join(migliore["strumenti"])
    except Exception as e:
        logger.debug("[tracce] suggerimento saltato: %s", e)
        return None
