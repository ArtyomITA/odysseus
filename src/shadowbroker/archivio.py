"""Archivio storico finanziario — il RAG dedicato al profilo Financial.

Perche' esiste: tutti i layer finanziari vivono in memoria e il piano gratuito
di Finnhub nega `/stock/candle`. Un riavvio perde tutto, e «cosa e' successo a
RTX nelle ultime due settimane» diventa irrispondibile. O il passato lo
conserviamo noi al passaggio, o non esiste.

Riusa l'infrastruttura RAG di Odysseus (ChromaDB + fastembed) ma su una
collection separata, `financial_rag`: le notizie di mercato non devono
inquinare i documenti personali, ne' viceversa.

COSA ENTRA (e cosa no) — i filtri sono il punto delicato:

  notizie   titolo obbligatorio, dedup per URL, niente piu' vecchio di 14
            giorni all'ingresso. Testo = titolo + sommario; il prezzo NON
            entra (una quotazione salvata ieri e' un numero sbagliato oggi).
  picchi    solo il movimento come EVENTO datato: «2026-08-02: AMZN +15.3%,
            con/senza notizia». E' l'unica forma in cui un prezzo ha senso
            storico.
  appalti   un documento per contratto, solo quelli veri (i quadro sono gia'
            filtrati a monte), dedup per id.
  insider   solo decisioni di mercato (codici P/S), un documento per
            transazione.

L'ingestione e' **opportunistica** (ogni volta che un briefing gira) piu' un
giro di fondo ogni 10 minuti sulle notizie. Embedding fatto in un thread
separato: il briefing non aspetta l'indice.

RAM: il modello di embedding (~150 MB) resta residente dopo il primo uso.
`stato()` misura l'RSS del processo e, sopra la soglia, avvisa e propone
`comprimi()` — che fonde i documenti piu' vecchi di 30 giorni in digest
settimanali per ticker e cancella gli originali. Propone, non esegue.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COLLECTION = "financial_rag"

# Oltre questa RSS del processo Odysseus si avvisa. Non e' un tetto duro:
# e' il punto in cui su 16 GB di RAM totale conviene sapere che l'archivio
# c'entra. Regolabile senza toccare il codice.
RAM_SOGLIA_MB = float(os.getenv("FIN_RAG_RAM_MB", "2800"))
# Oltre questo numero di documenti la compressione viene proposta comunque.
DOC_SOGLIA = int(os.getenv("FIN_RAG_MAX_DOC", "20000"))
# All'ingresso: niente notizie piu' vecchie di cosi'.
_MAX_ETA_INGRESSO_GIORNI = 14
_ETA_COMPRESSIONE_GIORNI = 30
_RETENTION_GIORNI = 90

_lanes: Optional[list] = None
_lanes_lock = threading.Lock()


def _prendi_lanes() -> list:
    """Lazy: il modello di embedding si carica al primo uso, non all'avvio."""
    global _lanes
    with _lanes_lock:
        if _lanes is None:
            from src.embedding_lanes import build_embedding_lanes
            _lanes = build_embedding_lanes(COLLECTION)
            if not _lanes:
                raise RuntimeError("nessuna lane di embedding disponibile")
            logger.info("[fin-rag] pronte %d lane per %s",
                        len(_lanes), COLLECTION)
        return _lanes


def _epoca(iso: Optional[str]) -> int:
    """ISO -> epoch. Senza data si usa adesso: meglio impreciso che scartato."""
    if iso:
        try:
            return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
        except (ValueError, TypeError):
            pass
    return int(time.time())


def _id_doc(seme: str) -> str:
    return "fin_" + hashlib.sha1(seme.encode("utf-8")).hexdigest()[:16]


def _aggiungi(documenti: List[Dict[str, Any]]) -> int:
    """Inserisce solo cio' che non c'e' gia'. Ritorna quanti nuovi.

    documenti: [{"id":..., "testo":..., "meta": {...}}]. I metadati devono
    essere scalari (vincolo Chroma).
    """
    if not documenti:
        return 0
    # Dedup DENTRO il batch: due notizie con lo stesso URL (o due picchi dello
    # stesso giorno) producono lo stesso id, e Chroma rifiuta l'intero add con
    # "Expected IDs to be unique" — successo gia' alla prima sera.
    unici: Dict[str, Dict[str, Any]] = {}
    for d in documenti:
        unici.setdefault(d["id"], d)
    documenti = list(unici.values())
    lanes = _prendi_lanes()
    nuovi_tot = 0
    for lane in lanes:
        ids = [d["id"] for d in documenti]
        try:
            gia = set((lane.collection.get(ids=ids) or {}).get("ids") or [])
        except Exception:
            gia = set()
        freschi = [d for d in documenti if d["id"] not in gia]
        if not freschi:
            continue
        try:
            lane.collection.add(
                ids=[d["id"] for d in freschi],
                embeddings=lane.encode([d["testo"] for d in freschi]),
                documents=[d["testo"] for d in freschi],
                metadatas=[d["meta"] for d in freschi],
            )
            nuovi_tot = max(nuovi_tot, len(freschi))
        except Exception as e:
            logger.warning("[fin-rag] inserimento fallito (%s): %s", lane.name, e)
    return nuovi_tot


def _in_thread(fn, *args) -> None:
    """L'ingestione non deve mai far aspettare un briefing."""
    threading.Thread(target=fn, args=args, daemon=True).start()


# ── ingestione ───────────────────────────────────────────────────────────

def ingerisci_notizie(voci: List[Dict[str, Any]]) -> int:
    """Dal layer `finnhub_news`. Filtri: titolo, eta', dedup per URL."""
    ora = time.time()
    documenti = []
    for v in voci or []:
        if not isinstance(v, dict):
            continue
        titolo = (v.get("title") or "").strip()
        if not titolo:
            continue
        quando = _epoca(v.get("published"))
        if ora - quando > _MAX_ETA_INGRESSO_GIORNI * 86400:
            continue
        url = (v.get("url") or "").strip()
        ticker = (v.get("ticker") or "").strip().upper()
        sommario = (v.get("summary") or "").strip()[:400]
        testo = f"[{ticker}] {titolo}" if ticker else titolo
        if sommario:
            testo += f" — {sommario}"
        documenti.append({
            "id": _id_doc(url or titolo),
            "testo": testo,
            "meta": {
                "tipo": "notizia", "ticker": ticker,
                "fonte": (v.get("source") or "").strip(),
                "url": url, "quando_ts": quando,
                "quando": datetime.fromtimestamp(quando, tz=timezone.utc).date().isoformat(),
            },
        })
    return _aggiungi(documenti)


def ingerisci_picchi(picchi: List[Dict[str, Any]]) -> int:
    """Il movimento come evento datato — l'unica forma storica di un prezzo."""
    oggi = datetime.now(timezone.utc).date().isoformat()
    adesso = int(time.time())
    documenti = []
    for p in picchi or []:
        simbolo = (p.get("simbolo") or "").strip().upper()
        var = p.get("variazione_pct")
        if not simbolo or var is None:
            continue
        con_notizia = "con notizia collegata" if p.get("ha_notizia") else "senza notizia collegata"
        documenti.append({
            "id": _id_doc(f"picco|{oggi}|{simbolo}"),
            "testo": (f"{oggi}: picco di {p.get('nome') or simbolo} ({simbolo}) "
                      f"{var:+.2f}%, {con_notizia}."),
            "meta": {"tipo": "picco", "ticker": simbolo,
                     "variazione_pct": float(var),
                     "quando_ts": adesso, "quando": oggi},
        })
    return _aggiungi(documenti)


def ingerisci_appalti(contratti: List[Dict[str, Any]]) -> int:
    """Campi come li produce `finanza.appalti()`: titolo, oggetto, importo_milioni."""
    documenti = []
    for c in contratti or []:
        ident = c.get("id") or ""
        simbolo = (c.get("titolo") or "").strip().upper()
        oggetto = (c.get("oggetto") or "").strip()[:300]
        if not ident or not oggetto:
            continue
        quando = _epoca(c.get("data"))
        importo = c.get("importo_milioni")
        luogo = c.get("stato_usa") or ""
        testo = f"Contratto federale {simbolo}: {oggetto}"
        if importo:
            testo += f" — {importo} M$"
        if luogo:
            testo += f" ({luogo})"
        agenzia = (c.get("agenzia") or "").strip()
        if agenzia:
            testo += f" [{agenzia}]"
        documenti.append({
            "id": _id_doc(f"appalto|{ident}"),
            "testo": testo,
            "meta": {"tipo": "appalto", "ticker": simbolo,
                     "quando_ts": quando,
                     "quando": datetime.fromtimestamp(quando, tz=timezone.utc).date().isoformat()},
        })
    return _aggiungi(documenti)


def ingerisci_insider(voci: List[Dict[str, Any]]) -> int:
    """Solo decisioni di mercato: P e S. Le assegnazioni non sono storia utile.

    Campi come li produce `finanza.insider()` in `movimenti_recenti`."""
    documenti = []
    for v in voci or []:
        if not v.get("decisione_di_mercato"):
            continue
        simbolo = (v.get("titolo") or "").strip().upper()
        nome = (v.get("persona") or "").strip()
        azioni = v.get("azioni") or 0
        codice = (v.get("codice") or "").strip().upper()
        data = v.get("data") or ""
        if not simbolo or codice not in ("P", "S"):
            continue
        verso = "acquisto" if codice == "P" else "vendita"
        quando = _epoca(data)
        documenti.append({
            "id": _id_doc(f"insider|{simbolo}|{data}|{nome}|{azioni}"),
            "testo": (f"{data}: {verso} insider su {simbolo}"
                      + (f" di {nome}" if nome else "")
                      + (f", {azioni} azioni" if azioni else "") + "."),
            "meta": {"tipo": "insider", "ticker": simbolo,
                     "quando_ts": quando, "quando": str(data)},
        })
    return _aggiungi(documenti)


def ingerisci_da_briefing(tipo: str, dati: Dict[str, Any]) -> None:
    """Aggancio opportunistico: chiamato dai briefing, lavora in un thread.

    Il briefing consegna al modello e va avanti; l'archivio si aggiorna
    dietro. Un errore qui non deve MAI rompere una risposta."""
    def lavoro():
        try:
            if tipo == "mercati":
                n = ingerisci_picchi(dati.get("picchi") or [])
                from src.shadowbroker.store import get_store
                notizie = get_store()._dati.get("finnhub_news") or []
                n += ingerisci_notizie(notizie)
            elif tipo == "appalti":
                n = ingerisci_appalti(dati.get("contratti") or [])
            elif tipo == "insider":
                n = ingerisci_insider(dati.get("movimenti_recenti") or [])
            else:
                return
            if n:
                logger.info("[fin-rag] %s: %d documenti nuovi", tipo, n)
        except Exception as e:
            logger.warning("[fin-rag] ingestione %s fallita: %s", tipo, e)
    _in_thread(lavoro)


async def giro_di_fondo() -> None:
    """Ogni 10 minuti: notizie fresche nell'archivio anche se nessuno chiede.

    Va agganciato al lifespan di app.py. Prende il layer dal magazzino (che a
    sua volta rispetta il TTL), quindi non aggiunge chiamate a Finnhub."""
    import asyncio
    await asyncio.sleep(90)  # lasciare respirare l'avvio
    while True:
        try:
            from src.shadowbroker.store import get_store
            voci = await asyncio.to_thread(get_store().carica, "finnhub_news")
            n = await asyncio.to_thread(ingerisci_notizie, voci or [])
            if n:
                logger.info("[fin-rag] giro di fondo: %d notizie nuove", n)
        except Exception as e:
            logger.debug("[fin-rag] giro di fondo saltato: %s", e)
        await asyncio.sleep(600)


# ── interrogazione ───────────────────────────────────────────────────────

def cerca(query: str, quanti: int = 6, giorni: Optional[float] = None) -> Dict[str, Any]:
    """La faccia di `fin_archivio`."""
    try:
        lanes = _prendi_lanes()
    except Exception as e:
        return {"tipo": "archivio_finanziario", "errore":
                f"archivio non disponibile: {e}"}
    where = None
    if giorni:
        where = {"quando_ts": {"$gte": int(time.time() - giorni * 86400)}}
    risultati: List[Dict[str, Any]] = []
    visti = set()
    for lane in lanes:
        try:
            r = lane.collection.query(
                query_embeddings=lane.encode([query]),
                n_results=max(quanti * 2, 8),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.warning("[fin-rag] query fallita (%s): %s", lane.name, e)
            continue
        for i, doc in enumerate((r.get("documents") or [[]])[0]):
            ident = (r.get("ids") or [[]])[0][i]
            if ident in visti:
                continue
            visti.add(ident)
            meta = (r.get("metadatas") or [[]])[0][i] or {}
            risultati.append({
                "testo": doc,
                "tipo": meta.get("tipo"),
                "ticker": meta.get("ticker") or None,
                "quando": meta.get("quando"),
                "fonte": meta.get("fonte") or None,
                "url": meta.get("url") or None,
                "distanza": round((r.get("distances") or [[]])[0][i], 3),
            })
        break  # la prima lane sana basta: sono indici della stessa cosa
    risultati.sort(key=lambda x: x.get("distanza") or 9)
    fuori: Dict[str, Any] = {
        "tipo": "archivio_finanziario",
        "query": query,
        "risultati": risultati[:quanti],
    }
    if not risultati:
        fuori["vuoto"] = (
            "nessun documento per questa ricerca. Archivio cresce con l'uso: "
            "contiene solo cio' che e' passato dai briefing. Non significa "
            "che non sia successo nulla."
        )
    s = stato()
    if s.get("avviso"):
        fuori["avviso"] = s["avviso"]
    return fuori


def stato() -> Dict[str, Any]:
    """Documenti, eta', RSS del processo. Con proposta di compressione."""
    fuori: Dict[str, Any] = {"collection": COLLECTION}
    try:
        lanes = _prendi_lanes()
        fuori["documenti"] = max((lane.count() for lane in lanes), default=0)
    except Exception as e:
        return {"collection": COLLECTION, "errore": str(e)[:120]}
    try:
        import psutil
        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        fuori["rss_processo_mb"] = round(rss_mb)
    except Exception:
        rss_mb = 0.0
    if rss_mb > RAM_SOGLIA_MB or fuori.get("documenti", 0) > DOC_SOGLIA:
        fuori["avviso"] = (
            f"consumo elevato (RSS {fuori.get('rss_processo_mb', '?')} MB, "
            f"{fuori.get('documenti', 0)} documenti). Proposta: "
            f"archivio.comprimi() — digest settimanali oltre "
            f"{_ETA_COMPRESSIONE_GIORNI} giorni; via i dettagli, restano "
            f"gli eventi."
        )
    return fuori


def comprimi() -> Dict[str, Any]:
    """Fonde in digest settimanali per ticker cio' che ha piu' di 30 giorni.

    Deterministico, niente LLM: il digest e' la concatenazione datata dei
    testi. Si perde la ricerca fine sul singolo articolo vecchio, resta la
    memoria che l'evento c'e' stato. Va invocato di proposito — mai da solo."""
    lanes = _prendi_lanes()
    soglia = int(time.time() - _ETA_COMPRESSIONE_GIORNI * 86400)
    taglio = int(time.time() - _RETENTION_GIORNI * 86400)
    fusi, cancellati = 0, 0
    for lane in lanes:
        try:
            vecchi = lane.collection.get(
                where={"quando_ts": {"$lt": soglia}},
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning("[fin-rag] lettura vecchi fallita (%s): %s", lane.name, e)
            continue
        ids = vecchi.get("ids") or []
        if not ids:
            continue
        gruppi: Dict[str, List[str]] = {}
        for i, ident in enumerate(ids):
            meta = (vecchi.get("metadatas") or [])[i] or {}
            ts = int(meta.get("quando_ts") or 0)
            if ts < taglio:
                cancellati += 1
                continue  # oltre la retention: si cancella e basta
            settimana = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%G-W%V")
            chiave = f"{meta.get('ticker') or 'MERCATO'}|{settimana}"
            gruppi.setdefault(chiave, []).append(
                f"[{meta.get('quando')}] {(vecchi.get('documents') or [])[i]}")
        digest = []
        for chiave, testi in gruppi.items():
            ticker, settimana = chiave.split("|", 1)
            digest.append({
                "id": _id_doc(f"digest|{chiave}"),
                "testo": f"Digest {ticker} settimana {settimana}: " + " • ".join(testi)[:3000],
                "meta": {"tipo": "digest", "ticker": ticker,
                         "quando_ts": soglia, "quando": settimana},
            })
        try:
            if digest:
                lane.collection.add(
                    ids=[d["id"] for d in digest],
                    embeddings=lane.encode([d["testo"] for d in digest]),
                    documents=[d["testo"] for d in digest],
                    metadatas=[d["meta"] for d in digest],
                )
            lane.collection.delete(ids=ids)
            fusi += len(digest)
        except Exception as e:
            logger.warning("[fin-rag] compressione fallita (%s): %s", lane.name, e)
    return {"digest_creati": fusi, "cancellati_oltre_retention": cancellati}
