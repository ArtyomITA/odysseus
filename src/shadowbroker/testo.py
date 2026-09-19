"""Recupero del testo degli articoli, e riparazione dei titoli.

Nessuna fonte di notizie di ShadowBroker porta il corpo dell'articolo:

    news (RSS)      titolo pulito, data completa, NESSUN testo
    gdelt           titolo ricavato dallo slug URL, `_snippets_list` sempre vuoto
    telegram_osint  testo vero, ma pochi elementi

Quello che c'e' sempre sono gli **URL** — fino a 10 per cluster GDELT. Provato:
recuperando la pagina si ottiene un riassunto vero e utilizzabile. Su due URL
di prova uno ha risposto e uno era dietro paywall, quindi si tenta in sequenza
finche' uno risponde.

Sui titoli ricavati dallo slug: **non si buttano.** Lo slug e' quasi sempre il
titolo vero messo li' dall'editore (`/russia-pounds-kyiv-with-missiles/` ->
"Russia Pounds Kyiv With Missiles"). Illeggibili sono solo i casi in cui l'URL
non ha uno slug descrittivo ma un identificativo. Quelli si **marcano**, non si
cancellano: l'articolo resta, con il suo URL, e se entra fra i primi il titolo
vero si va a prendere dalla pagina.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_RE_ID_LUNGO = re.compile(r"^[A-Za-z0-9]{16,}$")
# Con i sottodomini: `news.webindia123.com` e' un dominio quanto `kyivpost.com`.
_RE_DOMINIO = re.compile(
    r"^(?:[\w-]+\.)+(?:com|org|net|io|co|uk|ua|ru|de|fr|it|au|ca|az|in|pk|info|news|tv|me)$",
    re.I,
)
_RE_DATA_URL = re.compile(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})/")
_GENERICI = {"articles", "article", "news", "story", "index", "post", "home", "world"}


def titolo_illeggibile(t: Any) -> bool:
    """Il titolo e' un identificativo o un residuo, non una frase.

    Prudente di proposito: nel dubbio si tiene. Una prima versione di questa
    funzione toglieva gli spazi prima di controllare e finiva per scartare
    "Russia Pounds Kyiv With Missiles" — cioe' cancellava proprio le notizie.
    """
    if not isinstance(t, str):
        return True
    t = t.strip()
    if len(t) < 10:
        return True
    if t.lower() in _GENERICI:
        return True
    if _RE_DOMINIO.match(t):
        return True
    if " " not in t:
        return bool(_RE_ID_LUNGO.match(t)) or len(t) < 20
    parole = t.split()
    if len(parole) < 3:
        return True
    # Identificativo mascherato: molte parole lunghe senza vocali.
    strane = sum(1 for p in parole if len(p) > 6 and not re.search(r"[aeiouAEIOU]", p))
    return strane >= len(parole) / 2


def data_da_url(url: str) -> Optional[str]:
    """Molte testate mettono la data nel percorso: `/2026/07/31/`.

    Conferma utile perche' i cluster GDELT non portano la data dei singoli
    articoli — solo `event_date` a livello di cluster.
    """
    m = _RE_DATA_URL.search(url or "")
    if not m:
        return None
    anno, mese, giorno = m.groups()
    return f"{anno}-{int(mese):02d}-{int(giorno):02d}"


def dominio(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/:]+)", url or "", re.I)
    return m.group(1) if m else ""


def titoli_puliti(titoli: List[Any], urls: List[str]) -> List[Dict[str, Any]]:
    """Accoppia titoli e URL, marcando (non scartando) quelli illeggibili.

    Restituisce elementi `{titolo, url, fonte, data, leggibile}`. Chi consuma
    decide: se `leggibile` e' falso e l'articolo conta, si recupera il titolo
    vero dalla pagina.
    """
    fuori: List[Dict[str, Any]] = []
    visti = set()
    for i, u in enumerate(urls or []):
        t = titoli[i] if i < len(titoli or []) else None
        leggibile = not titolo_illeggibile(t)
        # Deduplica sul titolo: GDELT ripete lo stesso pezzo da testate diverse
        # ("Poland Protests To Russian Ambassador" compariva due volte).
        chiave = (t or "").strip().lower()
        if leggibile and chiave in visti:
            continue
        if leggibile:
            visti.add(chiave)
        fuori.append({
            "titolo": (t or "").strip() if leggibile else None,
            "url": u,
            "fonte": dominio(u),
            "data": data_da_url(u),
            "leggibile": leggibile,
        })
    return fuori


# ── recupero della pagina ────────────────────────────────────────────────

def _estrai(url: str, max_caratteri: int) -> Optional[Tuple[str, str]]:
    """(titolo, testo) da una pagina, oppure None.

    Usa il recuperatore di Odysseus, che gia' gestisce codifiche, timeout e
    l'estrazione del contenuto leggibile.
    """
    try:
        from src.search.content import fetch_webpage_content
    except Exception as e:
        logger.warning("[shadowbroker] recuperatore pagine non disponibile: %s", e)
        return None
    try:
        r = fetch_webpage_content(url, timeout=10)
    except Exception as e:
        logger.info("[shadowbroker] %s non recuperabile: %s", dominio(url), type(e).__name__)
        return None
    if not isinstance(r, dict):
        return None
    testo = (r.get("content") or "").strip()
    titolo = (r.get("title") or "").strip()
    if not testo:
        return None
    return titolo, testo[:max_caratteri]


def recupera_testo(urls: List[str], max_tentativi: int = 3,
                   max_caratteri: int = 1200) -> Dict[str, Any]:
    """Prova gli URL in ordine finche' uno risponde.

    Un paywall o un blocco anti-bot non e' un errore: si passa al prossimo. Il
    risultato dichiara sempre **quale** URL ha risposto e quanti sono stati
    tentati, cosi' la risposta puo' citare la fonte vera.
    """
    tentati: List[str] = []
    for u in (urls or [])[:max_tentativi]:
        tentati.append(dominio(u))
        r = _estrai(u, max_caratteri)
        if r:
            titolo, testo = r
            return {
                "ok": True,
                "titolo": titolo or None,
                "testo": testo,
                "url": u,
                "fonte": dominio(u),
                "data": data_da_url(u),
                "tentati": tentati,
            }
    return {
        "ok": False,
        "motivo": "nessuna delle pagine e' leggibile (paywall, blocco anti-bot, o richiede JavaScript)",
        "tentati": tentati,
    }


def arricchisci(voci: List[Dict[str, Any]], quante: int = 3,
                max_caratteri: int = 800) -> List[Dict[str, Any]]:
    """Aggiunge il testo vero alle prime `quante` voci di un briefing.

    Deliberatamente poche: ogni recupero e' una richiesta di rete verso un sito
    esterno, e il testo costa contesto. Le voci non arricchite restano
    complete di titolo, fonte e URL — nessuna perde informazione, solo la
    prosa.
    """
    for voce in voci[:quante]:
        urls = voce.get("urls") or ([voce["url"]] if voce.get("url") else [])
        if not urls:
            continue
        r = recupera_testo(urls, max_caratteri=max_caratteri)
        if r.get("ok"):
            voce["testo"] = r["testo"]
            voce["fonte_testo"] = r["fonte"]
            if r.get("titolo") and not voce.get("titolo"):
                voce["titolo"] = r["titolo"]
            if r.get("data") and not voce.get("data"):
                voce["data"] = r["data"]
        else:
            voce["testo_non_disponibile"] = r.get("motivo")
    return voci
