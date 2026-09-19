"""I briefing: dove Python decide cosa e' importante.

Questo modulo e' il 90% del lavoro. Il modello non sceglie mai cosa conta — lo
riceve gia' deciso, ordinato e con le motivazioni.

Il motivo e' che ShadowBroker **ha gia' calcolato le classifiche**, e sono
migliori di qualunque cosa un 9B possa improvvisare leggendo righe di JSON:

    threat_level     fusione pesata a 7 componenti -> 0-100 + livello + motivi
    correlations     eventi che si sovrappongono in piu' layer, con `drivers`
    tracked_flights  113 aerei su 139 gia' classificati (Plane-Alert, 16.077 velivoli)
    GT analytics     1.641 regioni con probabilita' per dominio e interpretazione
    gdelt            `num_articles` = quanto il mondo ne parla; `goldstein` = quanto e' grave

Ogni briefing dichiara **cosa non ha potuto vedere**. Un layer vuoto per
mancanza di chiave non e' "niente da segnalare": e' un buco, e va detto,
altrimenti il modello afferma con sicurezza che non succede nulla.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.shadowbroker import geo, sagome, testo as mod_testo
from src.shadowbroker.store import get_store

logger = logging.getLogger(__name__)

# Layer che dovrebbero avere dati; se sono vuoti e' un buco da dichiarare, non
# un "tutto tranquillo". Con il motivo, quando lo conosciamo.
BUCHI_NOTI = {
    "prediction_markets": "mercati predittivi assenti — e pesano il 25% di threat_level, che risulta quindi sottostimato",
    "fishing_activity": "manca la chiave GFW_API_TOKEN",
    "sar_anomalies": "richiede un account NASA Earthdata",
    "cctv": "nessuna telecamera caricata",
    "gps_jamming": "nessuna zona rilevata ora (pesa il 10% di threat_level)",
    "liveuamap": "feed vuoto",
    "financial": "mercati finanziari non caricati",
    "volcanoes": "feed vuoto",
    "ukraine_alerts": "feed allerte aeree vuoto",
}


def _ora() -> datetime:
    return datetime.now(timezone.utc)


def _limite_data(giorni: float) -> str:
    """GDELT usa AAAAMMGG."""
    return (_ora() - timedelta(days=giorni)).strftime("%Y%m%d")


def _pubblicato_dopo(elemento: Dict[str, Any], soglia: datetime) -> Optional[bool]:
    """True/False, oppure None quando la data manca o non si legge.

    None non e' False: un elemento senza data non va escluso in silenzio da una
    finestra temporale — va segnalato.
    """
    p = elemento.get("published")
    if isinstance(p, str) and p:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(p) >= soglia
        except Exception:
            pass
    ed = elemento.get("event_date")
    if isinstance(ed, (str, int)):
        try:
            return str(ed) >= soglia.strftime("%Y%m%d")
        except Exception:
            pass
    return None


# ── mattoni ──────────────────────────────────────────────────────────────

def _voce_gdelt(e: Dict[str, Any], con_urls: bool = True) -> Dict[str, Any]:
    """Un cluster GDELT ridotto a cio' che serve per rispondere."""
    titoli = mod_testo.titoli_puliti(e.get("_headlines_list") or [], e.get("_urls_list") or [])
    leggibili = [t for t in titoli if t["leggibile"]]
    voce: Dict[str, Any] = {
        "id": e.get("_id"),
        "dove": e.get("name"),
        "articoli": e.get("num_articles"),
        "fonti": e.get("num_sources"),
        "gravita": e.get("goldstein"),      # -10..+10, negativo = conflittuale
        "tono": round(e["avg_tone"], 1) if isinstance(e.get("avg_tone"), (int, float)) else None,
        "data": e.get("event_date"),
        "attori": e.get("actors"),
        "titoli": [t["titolo"] for t in leggibili[:4]],
    }
    if e.get("_km") is not None:
        voce["km"] = e["_km"]
    if con_urls:
        voce["urls"] = [t["url"] for t in titoli[:5]]
    illeggibili = len(titoli) - len(leggibili)
    if illeggibili:
        # Dichiarato, non nascosto: quegli articoli esistono, solo il titolo
        # non e' ricavabile dall'URL.
        voce["titoli_non_ricavabili"] = illeggibili
    return {k: v for k, v in voce.items() if v not in (None, [], "")}


def _voce_volo(e: Dict[str, Any]) -> Dict[str, Any]:
    voce = {
        "id": e.get("_id"),
        "sigla": e.get("callsign") or e.get("registration"),
        "tipo": e.get("model") or e.get("military_type") or e.get("alert_type"),
        "operatore": e.get("alert_operator") or e.get("operator") or e.get("force"),
        "categoria": e.get("alert_category"),
        "tag": e.get("alert_tags"),
        "lat": e.get("lat"), "lng": e.get("lng"),
        "quota_m": round(e["alt"]) if isinstance(e.get("alt"), (int, float)) else None,
        "da": e.get("origin_name"), "a": e.get("dest_name"),
        "in_attesa": e.get("holding") or None,
    }
    if e.get("_km") is not None:
        voce["km"] = e["_km"]
    return {k: v for k, v in voce.items() if v not in (None, [], "", "UNKNOWN")}


def _voce_news(e: Dict[str, Any]) -> Dict[str, Any]:
    voce = {
        "id": e.get("_id"),
        "titolo": e.get("title"),
        "fonte": e.get("source"),
        "quando": e.get("published"),
        "rischio": e.get("risk_score"),
        "oracolo": e.get("oracle_score"),
        "giudizio": e.get("machine_assessment"),
        "url": e.get("link"),
        "in_evidenza": e.get("breaking") or None,
    }
    c = geo.coordinate_di(e)
    if c:
        voce["lat"], voce["lng"] = round(c[0], 3), round(c[1], 3)
    if e.get("_km") is not None:
        voce["km"] = e["_km"]
    return {k: v for k, v in voce.items() if v not in (None, [], "")}


def _buchi(conteggi: Dict[str, int], interessanti: List[str]) -> List[str]:
    fuori = []
    for layer in interessanti:
        if conteggi.get(layer, 0) == 0:
            motivo = BUCHI_NOTI.get(layer)
            fuori.append(f"{layer}: {motivo}" if motivo else f"{layer}: nessun dato ora")
    return fuori


# ── briefing 1: situazione globale ───────────────────────────────────────

def situazione(quanti: int = 8, con_testo: bool = False) -> Dict[str, Any]:
    """"Cosa sta succedendo di importante adesso" / "fammi una classifica".

    Unisce le quattro classifiche gia' calcolate. Il modello riceve numeri e
    motivazioni, non righe grezze da interpretare.
    """
    store = get_store()

    # Un solo giro HTTP a cache fredda. Riepilogo, i quattro layer e la
    # classifica GT sono indipendenti fra loro — nessuno usa il risultato di un
    # altro — quindi partono insieme sul canale batch, che lato ShadowBroker li
    # esegue in parallelo. Se il batch cade, `istantanea` torna da sola alle tre
    # chiamate singole di prima; un singolo comando caduto degrada solo la sua
    # sezione, come prima.
    istantanea = store.istantanea(
        ["gdelt", "threat_level", "correlations", "news"],
        extra=[{"cmd": "gt_top_alerts", "args": {}}],
    )
    conteggi = istantanea["conteggi"]
    dati = istantanea["layer"]
    gt, gt_errore = istantanea["extra"][0]

    fuori: Dict[str, Any] = {"tipo": "situazione_globale", "ora_utc": _ora().isoformat(timespec="seconds")}

    # Livello di minaccia globale — gia' calcolato, motivazioni comprese.
    tl = (dati.get("threat_level") or [{}])[0]
    if tl:
        fuori["minaccia_globale"] = {
            "punteggio": tl.get("score"),
            "livello": tl.get("level"),
            "perche": tl.get("drivers") or [],
            "scala": "0-100; livelli GREEN < BLUE < YELLOW < ORANGE < RED",
        }

    # Cosa domina la copertura mondiale. `num_articles` e' la misura piu' onesta
    # di "importante": quanti giornali al mondo ne stanno parlando.
    gdelt = dati.get("gdelt") or []
    top = sorted(gdelt, key=lambda e: -(e.get("num_articles") or 0))[:quanti]
    voci = [_voce_gdelt(e) for e in top]
    if con_testo:
        mod_testo.arricchisci(voci, quante=3)
    fuori["piu_coperti"] = voci
    fuori["nota_classifica"] = (
        f"ordinati per numero di articoli nel mondo; {len(gdelt)} eventi geolocalizzati in totale"
    )

    # Anomalie fra layer diversi.
    corr = dati.get("correlations") or []
    if corr:
        fuori["anomalie"] = [{
            "tipo": c.get("type"), "gravita": c.get("severity"), "punteggio": c.get("score"),
            "perche": c.get("drivers"), "dove": geo.etichetta(c),
            "lat": c.get("lat"), "lng": c.get("lng"),
        } for c in sorted(corr, key=lambda c: -(c.get("score") or 0))[:5]]

    # Notizie giudicate critiche dal loro oracolo.
    news = dati.get("news") or []
    critiche = [n for n in news if (n.get("oracle_score") or 0) >= 7]
    critiche.sort(key=lambda n: -(n.get("oracle_score") or 0))
    if critiche:
        fuori["notizie_critiche"] = [_voce_news(n) for n in critiche[:5]]

    # GT: classifica per regione. Le regioni arrivano come coordinate grezze,
    # qui diventano nomi.
    try:
        if gt_errore:
            raise RuntimeError(gt_errore)
        allerte = (gt or {}).get("alerts") or []
        if allerte:
            fuori["regioni_a_rischio"] = [{
                "dove": geo.nome_del_posto(a["lat"], a["lng"]) or a.get("region_label"),
                "rischio": round(a.get("risk") or 0, 3),
                "conflitto": round(a.get("conflict") or 0, 2),
                "disordini": round(a.get("unrest") or 0, 2),
                "contagio": round(a.get("contagion") or 0, 2),
                "accensione": a.get("ignition"),
                "lat": a.get("lat"), "lng": a.get("lng"),
            } for a in allerte[:6]]
            fuori["nota_gt"] = (
                f"{gt.get('engine_regions', '?')} regioni analizzate, "
                f"{gt.get('tracked_regions', '?')} tracciate (probabilita' 0-1)"
            )
    except Exception as e:
        fuori["gt_non_disponibile"] = str(e)[:150]

    buchi = _buchi(conteggi, ["prediction_markets", "gps_jamming", "liveuamap", "cctv", "financial"])
    if buchi:
        fuori["non_osservabile"] = buchi
    return fuori


# ── briefing 2: notizie di una zona / su un tema ─────────────────────────

# I dati (GDELT, RSS) sono indicizzati in inglese, ma il modello — nonostante
# la regola — ogni tanto cerca in italiano: `tema="guerra conflitto"` filtrava
# TUTTO a zero e il turno moriva li'. Tradurre le parole comuni qui costa
# niente ed e' piu' robusto di qualunque regola nel prompt. Frase multi-parola
# = OR sulle singole parole, ognuna tradotta se la conosciamo.
_TEMA_IT_EN = {
    "guerra": "war", "conflitto": "conflict", "conflitti": "conflict",
    "attacco": "attack", "attacchi": "attack", "difesa": "defense",
    "missile": "missile", "missili": "missile", "droni": "drone",
    "drone": "drone", "bombardamento": "bombing", "esplosione": "explosion",
    "mercati": "market", "mercato": "market", "borsa": "stock",
    "petrolio": "oil", "gas": "gas", "energia": "energy",
    "sanzioni": "sanctions", "nucleare": "nuclear", "spia": "spy",
    "terremoto": "earthquake", "incendio": "fire", "alluvione": "flood",
    "elezioni": "election", "protesta": "protest", "proteste": "protest",
    "ucraina": "ukraine", "cina": "china", "iran": "iran",
    "israele": "israel", "gaza": "gaza", "taiwan": "taiwan",
}


def _espandi_tema(tema: str) -> List[str]:
    """'guerra conflitto' -> ['guerra', 'war', 'conflitto', 'conflict']."""
    fuori: List[str] = []
    for parola in str(tema).lower().split():
        if parola not in fuori:
            fuori.append(parola)
        tradotta = _TEMA_IT_EN.get(parola)
        if tradotta and tradotta not in fuori:
            fuori.append(tradotta)
    return fuori or [str(tema).lower()]


def notizie(luogo: Optional[str] = None, tema: Optional[str] = None,
            giorni: float = 2, raggio_km: float = 400,
            quante: int = 10, con_testo: bool = True,
            soggetto: Optional[str] = None) -> Dict[str, Any]:
    """"Ultime notizie sull'Ucraina", "cercami news su Boeing".

    Passa dal layer gdelt **grezzo**, non dal loro `/api/ai/news-near`: quello
    ignora il raggio se non si chiama esattamente `radius`, e non porta le date
    dei singoli eventi. Qui distanza e finestra temporale si applicano davvero.

    `soggetto` = azienda/persona/organizzazione che DEVE comparire nel testo.
    Nato da un bug misurato: il modello metteva "Boeing" in `luogo`, il
    geocoder non lo risolveva, e la ricerca globale per solo-tema pescava
    proteste in Svezia. Il soggetto non si geocodifica: si CERCA nel testo —
    e se `luogo` non e' un posto, diventa soggetto da solo. Con un soggetto,
    Python aggrega da solo le tre fonti: gdelt, wire finanziario
    (finnhub_news), e web come ripiego se il raccolto e' magro.
    """
    store = get_store()
    dati = store.carica_molti(["gdelt", "news", "telegram_osint"])
    gdelt = dati.get("gdelt") or []

    fuori: Dict[str, Any] = {
        "tipo": "notizie",
        "ora_utc": _ora().isoformat(timespec="seconds"),
        "finestra": f"ultimi {giorni:g} giorni",
    }

    candidati = gdelt
    centro: Optional[Tuple[float, float]] = None
    if luogo:
        centro = geo.risolvi_posto(luogo)
        if centro is None:
            # Non e' un posto: quasi sempre e' il SOGGETTO messo nel campo
            # sbagliato. Convertire in silenzio no: si dichiara.
            soggetto = f"{soggetto} {luogo}".strip() if soggetto else luogo
            fuori["luogo_come_soggetto"] = (
                f"'{luogo}' non e' un posto riconosciuto: letto come "
                f"soggetto da cercare nel testo."
            )
            luogo = None
        else:
            fuori["centro"] = {"nome": luogo, "lat": centro[0], "lng": centro[1],
                               "raggio_km": raggio_km}
            candidati = geo.entro(candidati, centro[0], centro[1], raggio_km)

    if soggetto:
        fuori["soggetto"] = soggetto
        parole_sogg = [p for p in str(soggetto).lower().split() if len(p) >= 3]

        def _con_soggetto(e: Dict[str, Any]) -> bool:
            campi = [e.get("name") or ""]
            campi += [str(x) for x in (e.get("actors") or [])]
            campi += [str(x) for x in (e.get("_headlines_list") or [])]
            testo = " ".join(campi).lower()
            return any(p in testo for p in parole_sogg)

        candidati = [e for e in candidati if _con_soggetto(e)]

    limite = _limite_data(giorni)
    nella_finestra, senza_data = [], 0
    for e in candidati:
        ed = e.get("event_date")
        if ed is None:
            senza_data += 1
            nella_finestra.append(e)
        elif str(ed) >= limite:
            nella_finestra.append(e)

    if tema:
        parole = _espandi_tema(tema)

        def pertinente(e: Dict[str, Any], campi_extra: Tuple[str, ...] = ()) -> bool:
            campi = [e.get("name") or ""]
            campi += [str(x) for x in (e.get("actors") or [])]
            campi += [str(x) for x in (e.get("_headlines_list") or [])]
            for c in campi_extra:
                v = e.get(c)
                if v:
                    campi.append(str(v))
            testo = " ".join(campi).lower()
            return any(p in testo for p in parole)

        fuori["tema"] = tema
        if parole != [tema.lower()]:
            fuori["tema_espanso"] = parole

        # Scala a tre gradini. Un filtro che restituisce zero secco manda un
        # modello piccolo in spirale di sinonimi (misurato: 9/9 a vuoto, 36%
        # delle chiamate sprecate). Quindi: prima il match normale, poi una
        # ricerca APPROFONDITA (finestra x3 e piu' campi), e se fallisce anche
        # quella si consegna il non-filtrato dichiarando l'incapacita' e le
        # alternative — mai il buco.
        filtrati = [e for e in nella_finestra if pertinente(e)]
        if filtrati:
            nella_finestra = filtrati
        else:
            giorni_larghi = min(giorni * 3, 14)
            limite_largo = _limite_data(giorni_larghi)
            larghi = [e for e in candidati
                      if e.get("event_date") is None
                      or str(e.get("event_date")) >= limite_largo]
            profondi = [e for e in larghi
                        if pertinente(e, ("title", "description", "summary"))]
            if profondi:
                nella_finestra = profondi
                fuori["tema_approfondito"] = (
                    f"tema trovato solo allargando a {giorni_larghi:g} giorni "
                    f"e piu' campi. Dillo nella risposta."
                )
            else:
                coda = ("Sotto: i piu' coperti senza filtro. "
                        if nella_finestra else
                        "Zero eventi gdelt qui: usa le sezioni "
                        "notizie_finanziarie/web se presenti. ")
                fuori["tema_non_trovato"] = (
                    f"tema fallito anche in modalita' approfondita "
                    f"({giorni_larghi:g} giorni, tutti i campi): {parole} "
                    f"non e' nelle chiavi indicizzate. Strumento NON capace "
                    f"su questo tema: dillo all'utente, NON riprovare con "
                    f"sinonimi. {coda}"
                    f"Alternative valide: `luogo` (sempre indicizzato), o "
                    f"`osint_situazione` poi `osint_testo` sugli id."
                )

    nella_finestra.sort(key=lambda e: -(e.get("num_articles") or 0))
    voci = [_voce_gdelt(e) for e in nella_finestra[:quante]]
    if con_testo:
        mod_testo.arricchisci(voci, quante=3)
    fuori["eventi"] = voci
    fuori["trovati"] = len(nella_finestra)
    if len(nella_finestra) > quante:
        fuori["nota_taglio"] = f"mostrati {quante} di {len(nella_finestra)}, ordinati per copertura"
    if senza_data:
        fuori["nota_date"] = f"{senza_data} eventi senza data: inclusi comunque, non scartati in silenzio"

    # Con un soggetto, le altre due fonti: SEMPRE il wire finanziario, e il
    # web come ripiego se gdelt e' magro. L'aggregazione la fa Python, non il
    # modello: "cercami news su X" deve essere UNA mossa, non tre.
    if soggetto:
        wire = store.carica("finnhub_news") or []
        fin_trovate = []
        for v in wire:
            blob = (f"{v.get('title') or ''} {v.get('summary') or ''} "
                    f"{v.get('ticker') or ''}").lower()
            if any(p in blob for p in parole_sogg):
                fin_trovate.append({
                    "titolo": v.get("title"),
                    "ticker": v.get("ticker") or None,
                    "fonte": v.get("source"),
                    "quando": v.get("published"),
                    "url": v.get("url"),
                })
        if fin_trovate:
            fuori["notizie_finanziarie"] = fin_trovate[:5]

        if len(nella_finestra) < 3:
            try:
                from services.search.core import searxng_search_results
                filtro_tempo = "week" if giorni > 2 else "day"
                grezzi_web = searxng_search_results(
                    f"{soggetto} news", count=6, time_filter=filtro_tempo) or []
                voci_web = []
                for r in grezzi_web:
                    if not isinstance(r, dict) or not r.get("title"):
                        continue
                    voci_web.append({
                        "titolo": r.get("title"),
                        "url": r.get("url") or r.get("href"),
                        "estratto": (r.get("snippet") or r.get("body") or "")[:200] or None,
                    })
                if voci_web:
                    fuori["web"] = voci_web[:6]
                    fuori["nota_web"] = (
                        "gdelt magro sul soggetto: integrate dal web. Per il "
                        "testo intero: `osint_testo` sull'url."
                    )
            except Exception as e:
                logger.warning("[briefing] ripiego web fallito: %s", e)

    # Il layer news e' piccolo (54) e solo il 40% geolocalizzato, ma ha titoli
    # puliti e data al minuto: complementare, non alternativo.
    news = dati.get("news") or []
    if centro:
        vicine = geo.entro(news, centro[0], centro[1], raggio_km, senza_coordinate="escludi")
    else:
        vicine = news
    if tema:
        parole_rss = _espandi_tema(tema)
        vicine = [n for n in vicine
                  if any(p in (n.get("title") or "").lower() for p in parole_rss)]
    vicine.sort(key=lambda n: -(n.get("oracle_score") or 0))
    if vicine:
        fuori["notizie_rss"] = [_voce_news(n) for n in vicine[:5]]
    elif centro:
        fuori["nota_rss"] = (
            f"nessuna notizia RSS geolocalizzata entro {raggio_km:g} km "
            f"(il feed ha {len(news)} articoli, di cui pochi con coordinate)"
        )

    # Telegram: l'unica fonte con il testo vero del messaggio.
    tg = dati.get("telegram_osint") or []
    if centro and tg:
        tg = geo.entro(tg, centro[0], centro[1], raggio_km)
    if tg:
        tg.sort(key=lambda t: -(t.get("risk_score") or 0))
        fuori["telegram"] = [{
            "id": t.get("_id"),
            "titolo": t.get("title"),
            "testo": (t.get("description") or t.get("summary") or "")[:300] or None,
            "canale": t.get("channel") or t.get("source"),
            "rischio": t.get("risk_score"),
            "url": t.get("link"),
            "km": t.get("_km"),
        } for t in tg[:4]]
    return fuori


# ── briefing 3: movimenti militari ───────────────────────────────────────

# I tag vengono dal database Plane-Alert (16.077 velivoli) e sono gia' scritti
# in inglese leggibile. Attenzione: `alert_tags` e' una **stringa** separata da
# virgole, non una lista — iterarla direttamente da' i singoli caratteri.
GRUPPI_TAG = {
    "VIP / governativi": ("VIP", "Office In The Sky", "Head of State"),
    "rifornimento in volo": ("Air2Air", "Tanker"),
    "trasporto tattico": ("Tactical Airlift", "Globemaster", "Airlift"),
    "sorveglianza / ISR": ("ISR", "Surveillance", "Recon", "Sensitive Mission",
                           "SIGINT", "Spy", "Eye In The Sky"),
    "caccia": ("Fighter", "Fast Jet", "Fighter Jet"),
    "elicotteri": ("Helicopter", "Rotary", "Chopper"),
}

# `tracked_flights` NON e' un elenco di velivoli militari: e' la lista
# Plane-Alert dei velivoli *notevoli*. Le categorie osservate comprendono
# "Flying Doctors" (24), "Aerial Firefighter" (16), "As Seen on TV" (13),
# "Dogs with Jobs" (4). Chiedendo "quali forze militari si muovono" restituire
# ambulanze aeree e Labcorp sarebbe una risposta sbagliata.
CATEGORIE_MILITARI = (
    "usaf", "navy", "army", "marine", "air force", "coast guard", "coastguard",
    "government", "state/law", "military", "toy soldiers", "hired gun",
    "police forces", "nato", "raf", "defence", "defense",
)


def _e_militare(t: Dict[str, Any]) -> bool:
    campi = " ".join(str(t.get(c) or "") for c in
                     ("alert_category", "alert_operator", "force", "military_type")).lower()
    return any(k in campi for k in CATEGORIE_MILITARI)


def _tag_lista(v: Any) -> List[str]:
    """`alert_tags` arriva come stringa "VIP, Office In The Sky, Not A Bus"."""
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    if isinstance(v, (list, tuple)):
        return [str(p).strip() for p in v if str(p).strip()]
    return []


def militare(luogo: Optional[str] = None, raggio_km: float = 1000,
             quanti: int = 20) -> Dict[str, Any]:
    """"Quali forze militari si stanno muovendo ora".

    `tracked_flights` e' la fonte buona: 113 velivoli su 139 arrivano gia'
    classificati per categoria, operatore e tag.
    """
    store = get_store()
    dati = store.carica_molti(["tracked_flights", "military_flights", "ships"])

    fuori: Dict[str, Any] = {"tipo": "movimenti_militari",
                             "ora_utc": _ora().isoformat(timespec="seconds")}

    tracciati = dati.get("tracked_flights") or []
    militari = dati.get("military_flights") or []

    centro = geo.risolvi_posto(luogo) if luogo else None
    if luogo and centro is None:
        fuori["luogo_non_riconosciuto"] = luogo
    if centro:
        fuori["centro"] = {"nome": luogo, "lat": centro[0], "lng": centro[1], "raggio_km": raggio_km}
        tracciati = geo.entro(tracciati, centro[0], centro[1], raggio_km)
        militari = geo.entro(militari, centro[0], centro[1], raggio_km)

    con_alert = [t for t in tracciati if t.get("alert_category") or t.get("alert_tags")]
    mil = [t for t in con_alert if _e_militare(t)]
    civili = [t for t in con_alert if not _e_militare(t)]
    fuori["totali"] = {
        "velivoli_notevoli_tracciati": len(tracciati),
        "di_cui_militari_o_governativi": len(mil),
        "voli_militari_da_adsb": len(militari),
    }

    # Raggruppamento per ruolo: piu' utile di un elenco piatto quando la
    # domanda e' "cosa si sta muovendo".
    gruppi: Dict[str, List[Dict[str, Any]]] = {}
    assegnati = set()
    for t in mil:
        tag = " ".join(_tag_lista(t.get("alert_tags"))).lower()
        for nome, chiavi in GRUPPI_TAG.items():
            if any(k.lower() in tag for k in chiavi):
                # Dentro un gruppo, `tag` e `categoria` ripetono il nome del
                # gruppo stesso: a 6 gruppi per 8 velivoli sono ~900 token di
                # pura ridondanza.
                v = _voce_volo(t)
                v.pop("tag", None)
                v.pop("categoria", None)
                gruppi.setdefault(nome, []).append(v)
                assegnati.add(t.get("_id"))
                break
    if gruppi:
        fuori["per_ruolo"] = {
            k: {"quanti": len(v), "primi": v[:4]}
            for k, v in sorted(gruppi.items(), key=lambda kv: -len(kv[1]))
        }

    # Per operatore: risponde a "di chi sono".
    per_operatore: Dict[str, int] = {}
    for t in mil:
        op = t.get("alert_operator") or t.get("alert_category") or "ignoto"
        per_operatore[op] = per_operatore.get(op, 0) + 1
    if per_operatore:
        fuori["per_operatore"] = dict(sorted(per_operatore.items(), key=lambda kv: -kv[1])[:10])

    restanti = [t for t in mil if t.get("_id") not in assegnati]
    if restanti:
        rimasti = max(0, quanti - len(assegnati))
        if rimasti:
            fuori["altri_militari"] = [_voce_volo(t) for t in restanti[:rimasti]]

    # I civili notevoli si contano ma non si elencano: la domanda era militare,
    # e sommergere la risposta di ambulanze aeree la rende inutile.
    if civili:
        from collections import Counter
        fuori["esclusi_perche_civili"] = {
            "quanti": len(civili),
            "categorie": dict(Counter(c.get("alert_category") or "?" for c in civili).most_common(6)),
        }

    if militari:
        fuori["voli_militari_non_tracciati"] = [_voce_volo(m) for m in militari[:8]]

    in_attesa = [t for t in tracciati + militari if t.get("holding")]
    if in_attesa:
        # Un aereo che gira in tondo e' un segnale: attesa, sorveglianza, o
        # aeroporto chiuso.
        fuori["in_circuito_di_attesa"] = [_voce_volo(t) for t in in_attesa[:5]]

    navi = dati.get("ships") or []
    if centro and navi:
        navi = geo.entro(navi, centro[0], centro[1], raggio_km)
    if navi:
        fuori["navi_militari"] = [{
            "id": n.get("_id"), "nome": n.get("name"), "tipo": n.get("type"),
            "dove": n.get("desc"), "lat": n.get("lat"), "lng": n.get("lng"),
            "affidabilita_posizione": n.get("position_confidence"),
            "stimata": bool(n.get("estimated")),
            "km": n.get("_km"),
        } for n in navi[:8]]
        fuori["nota_navi"] = (
            "le posizioni delle portaerei sono STIME ricavate da notizie, non AIS"
        )
    return fuori


# ── briefing 4: allerte ──────────────────────────────────────────────────

_PESO_GRAVITA = {"extreme": 5, "severe": 4, "high": 4, "moderate": 3,
                 "medium": 3, "minor": 2, "low": 2}


def allerte(luogo: Optional[str] = None, raggio_km: float = 1000,
            quante: int = 15) -> Dict[str, Any]:
    """"Quali sono gli allarmi più importanti adesso".

    Mette insieme le fonti che hanno una gravita' dichiarata dal server, e le
    ordina fra loro. Ogni voce dice da dove viene.
    """
    store = get_store()
    dati = store.carica_molti([
        "weather_alerts", "earthquakes", "internet_outages",
        "correlations", "news", "space_weather", "firms_fires", "wastewater",
        "gps_jamming", "ukraine_alerts", "crowdthreat",
    ])
    conteggi = store.riepilogo()
    centro = geo.risolvi_posto(luogo) if luogo else None

    fuori: Dict[str, Any] = {"tipo": "allerte", "ora_utc": _ora().isoformat(timespec="seconds")}
    if luogo and centro is None:
        fuori["luogo_non_riconosciuto"] = luogo
    if centro:
        fuori["centro"] = {"nome": luogo, "lat": centro[0], "lng": centro[1], "raggio_km": raggio_km}

    voci: List[Dict[str, Any]] = []

    def aggiungi(elementi, costruttore, peso_fn):
        lista = elementi
        if centro:
            lista = geo.entro(lista, centro[0], centro[1], raggio_km)
        for e in lista:
            v = costruttore(e)
            if v:
                v["_peso"] = peso_fn(e)
                voci.append(v)

    aggiungi(dati.get("weather_alerts") or [],
             lambda e: {"fonte": "meteo", "id": e.get("_id"), "cosa": e.get("event"),
                        "testo": e.get("headline"), "gravita": e.get("severity"),
                        "urgenza": e.get("urgency"), "certezza": e.get("certainty"),
                        "scade": e.get("expires"), "km": e.get("_km")},
             lambda e: _PESO_GRAVITA.get(str(e.get("severity", "")).lower(), 1)
                       + (1 if str(e.get("urgency", "")).lower() == "immediate" else 0))

    aggiungi(dati.get("earthquakes") or [],
             lambda e: {"fonte": "sismico", "id": e.get("_id"),
                        "cosa": f"terremoto M{e.get('mag')}", "testo": e.get("place"),
                        "lat": e.get("lat"), "lng": e.get("lng"), "km": e.get("_km")},
             lambda e: (e.get("mag") or 0) - 1.5)

    aggiungi(dati.get("internet_outages") or [],
             lambda e: {"fonte": "rete", "id": e.get("_id"),
                        "cosa": f"blackout internet {e.get('region_name') or e.get('country_name')}",
                        "gravita": e.get("severity"), "testo": e.get("level"),
                        "lat": e.get("lat"), "lng": e.get("lng"), "km": e.get("_km")},
             lambda e: _PESO_GRAVITA.get(str(e.get("severity", "")).lower(), 2))

    aggiungi(dati.get("correlations") or [],
             lambda e: {"fonte": "correlazione", "id": e.get("_id"), "cosa": e.get("type"),
                        "testo": "; ".join(e.get("drivers") or []), "gravita": e.get("severity"),
                        "punteggio": e.get("score"), "lat": e.get("lat"), "lng": e.get("lng"),
                        "km": e.get("_km")},
             lambda e: _PESO_GRAVITA.get(str(e.get("severity", "")).lower(), 2) + 1)

    critiche = [n for n in (dati.get("news") or []) if (n.get("oracle_score") or 0) >= 7]
    aggiungi(critiche,
             lambda e: {"fonte": "notizia", "id": e.get("_id"), "cosa": e.get("title"),
                        "testo": e.get("machine_assessment"), "url": e.get("link"),
                        "quando": e.get("published"), "km": e.get("_km")},
             lambda e: (e.get("oracle_score") or 0) / 2)

    incendi = sorted(dati.get("firms_fires") or [],
                     key=lambda f: -(f.get("frp") or 0))[:40]
    aggiungi(incendi,
             lambda e: ({"fonte": "incendio", "id": e.get("_id"),
                         "cosa": f"incendio, potenza {round(e.get('frp') or 0)} MW",
                         "lat": e.get("lat"), "lng": e.get("lng"), "km": e.get("_km")}
                        if (e.get("frp") or 0) >= 50 else None),
             lambda e: min(5, (e.get("frp") or 0) / 200))

    sw = dati.get("space_weather") or []
    if sw and isinstance(sw[0], dict):
        kp = sw[0].get("kp_index")
        if isinstance(kp, (int, float)) and kp >= 5:
            voci.append({"fonte": "meteo spaziale", "cosa": f"tempesta geomagnetica Kp {kp}",
                         "testo": sw[0].get("kp_text"), "_peso": kp - 1})

    # Feed gia' attivi ma mai portati nel briefing (agganciati 20 ago).
    aggiungi(dati.get("gps_jamming") or [],
             lambda e: {"fonte": "jamming GPS", "id": e.get("_id"),
                        "cosa": f"interferenza GPS {e.get('region') or e.get('region_name') or ''}".strip(),
                        "gravita": e.get("severity") or e.get("intensity") or e.get("level"),
                        "lat": e.get("lat"), "lng": e.get("lng"), "km": e.get("_km")},
             lambda e: _PESO_GRAVITA.get(str(e.get("severity", "")).lower(), 2) + 1)

    aggiungi(dati.get("ukraine_alerts") or [],
             lambda e: ({"fonte": "allarme aereo (UA)", "id": e.get("_id"),
                         "cosa": f"allarme aereo {e.get('region') or e.get('oblast') or e.get('location_title') or ''}".strip(),
                         "lat": e.get("lat"), "lng": e.get("lng"), "km": e.get("_km")}
                        if (e.get("active") is None or e.get("active")) else None),
             lambda e: 3)

    aggiungi(dati.get("crowdthreat") or [],
             lambda e: {"fonte": "segnalazione", "id": e.get("_id"),
                        "cosa": e.get("category") or e.get("type") or "segnalazione",
                        "testo": e.get("title") or e.get("description") or e.get("summary"),
                        "gravita": e.get("severity"), "lat": e.get("lat"), "lng": e.get("lng"),
                        "km": e.get("_km")},
             lambda e: _PESO_GRAVITA.get(str(e.get("severity", "")).lower(), 1) + 0.5)

    voci.sort(key=lambda v: -(v.get("_peso") or 0))
    for v in voci:
        v.pop("_peso", None)
    fuori["allerte"] = [{k: x for k, x in v.items() if x not in (None, "", [])}
                        for v in voci[:quante]]
    fuori["trovate"] = len(voci)
    if len(voci) > quante:
        fuori["nota_taglio"] = f"mostrate {quante} di {len(voci)}, ordinate per gravita'"

    # Gli aerei classificati sono allerte in senso proprio, ma vanno contati a
    # parte: sono decine e sommergerebbero le altre.
    tracciati = store.carica("tracked_flights")
    con_alert = [t for t in tracciati if t.get("alert_category")]
    if con_alert:
        fuori["velivoli_segnalati"] = {
            "quanti": len(con_alert),
            "dettaglio": "usa osint_militare per l'elenco",
        }

    buchi = _buchi(conteggi, ["gps_jamming", "ukraine_alerts", "volcanoes", "cctv"])
    if buchi:
        fuori["non_osservabile"] = buchi
    return fuori


# ── briefing 5: tutto attorno a un punto ─────────────────────────────────

LAYER_ZONA = ["gdelt", "news", "military_flights", "tracked_flights", "earthquakes",
              "weather_alerts", "firms_fires", "internet_outages", "military_bases",
              "power_plants", "datacenters", "telegram_osint", "ships",
              "gps_jamming", "ukraine_alerts", "crowdthreat"]


def zona(luogo: str, raggio_km: float = 200, per_layer: int = 5) -> Dict[str, Any]:
    """"Cosa c'e' vicino a Odessa" — tutto quello che sta davvero li'.

    Non usa il loro `brief_area`: quello restituisce `nearby` (locale) mescolato
    a `context_layers` (i primi N **mondiali**, non filtrati). Chiedendo Kyiv i
    terremoti erano in Indonesia.
    """
    centro = geo.risolvi_posto(luogo)
    if centro is None:
        return {"tipo": "zona", "errore": f"luogo non riconosciuto: {luogo}",
                "suggerimento": "prova un nome piu' comune, o passa 'lat,lng'"}

    store = get_store()
    dati = store.carica_molti(LAYER_ZONA)
    lat, lng = centro

    fuori: Dict[str, Any] = {
        "tipo": "zona",
        "ora_utc": _ora().isoformat(timespec="seconds"),
        "centro": {"nome": luogo, "lat": lat, "lng": lng, "raggio_km": raggio_km},
        "vicino": {},
    }
    vuoti: List[str] = []
    for layer in LAYER_ZONA:
        elementi = dati.get(layer) or []
        if not elementi:
            vuoti.append(layer)
            continue
        dentro = geo.entro(elementi, lat, lng, raggio_km)
        if not dentro:
            continue
        if layer == "gdelt":
            ridotti = [_voce_gdelt(e, con_urls=False) for e in
                       sorted(dentro, key=lambda e: -(e.get("num_articles") or 0))[:per_layer]]
        elif layer in ("military_flights", "tracked_flights"):
            ridotti = [_voce_volo(e) for e in dentro[:per_layer]]
        elif layer == "news":
            ridotti = [_voce_news(e) for e in dentro[:per_layer]]
        else:
            ridotti = sagome.comprimi(layer, dentro, massimo=per_layer)
        fuori["vicino"][layer] = {"quanti": len(dentro), "primi": ridotti}
    if vuoti:
        fuori["layer_vuoti"] = vuoti
    fuori["nota"] = "distanze ricalcolate qui, non fornite da ShadowBroker"
    return fuori
