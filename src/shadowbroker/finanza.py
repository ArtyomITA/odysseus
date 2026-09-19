"""I briefing finanziari: mercati, appalti federali, movimenti degli interni.

Stessa filosofia del resto del ponte: **Python decide cosa e' importante**, il
modello lo riceve gia' ordinato. Qui pero' c'e' una differenza che conta.

Gli altri briefing leggono layer che ShadowBroker aggiorna da solo. Questi
leggono in parte quelli (`stocks`, `finnhub_news`, `unusual_whales`) e in parte
chiamano **Finnhub direttamente**, perche' ShadowBroker non usa gli endpoint che
servono: dei 22 gratuiti ne chiama quattro, e due sono negati dal piano.

Cosa aggiunge ognuno:

    mercati()   l'anomalia si vede da sola: sei titoli che salgono e uno che
                scende e' informazione, sei che salgono no
    appalti()   contratti federali CON IL LUOGO -> vanno sulla mappa
    insider()   MSPR, un numero gia' normalizzato da -100 a +100

Le trappole trovate nei dati veri, tutte gestite qui dentro:

    * i contratti arrivano **duplicati** (stesso importo, stessa data, due righe)
    * `performanceState` e' **spesso vuoto**: 5 righe su 19 nel campione reale
    * il codice transazione `A` e' un'**assegnazione a prezzo zero**, non un
      acquisto: contarla falserebbe il segno del segnale
    * `/stock/lobbying` e `/stock/usa-spending` rispondono 200 con zero righe se
      la finestra e' stretta — sono dati trimestrali, non giornalieri
"""

from __future__ import annotations

import json
import re
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.shadowbroker.store import get_store

logger = logging.getLogger(__name__)

FINNHUB = "https://finnhub.io/api/v1"

# I sei della difesa: sono quelli su cui un movimento ha valore geopolitico e
# non solo finanziario. Gli altri titoli restano nel layer `stocks` per il
# contesto, ma non si va a chiedere i loro contratti federali.
DIFESA = ("RTX", "LMT", "NOC", "GD", "BA", "PLTR")

NOMI = {
    "RTX": "RTX (Raytheon)", "LMT": "Lockheed Martin", "NOC": "Northrop Grumman",
    "GD": "General Dynamics", "BA": "Boeing", "PLTR": "Palantir",
    "NVDA": "Nvidia", "AMD": "AMD", "TSM": "TSMC", "INTC": "Intel",
    "GOOGL": "Google", "AMZN": "Amazon", "MSFT": "Microsoft", "AAPL": "Apple",
    "TSLA": "Tesla", "META": "Meta", "NFLX": "Netflix", "SMCI": "Supermicro",
    "ARM": "ARM", "ASML": "ASML",
}

# Centro approssimativo degli stati americani. Serve a mettere sulla mappa i
# contratti federali: `performanceState` e' un nome di stato, non una coordinata.
# Approssimare al centro dello stato e' onesto perche' il dato **e'** a
# granularita' di stato — fingere una precisione maggiore sarebbe peggio.
STATI_USA: Dict[str, Tuple[float, float]] = {
    "ALABAMA": (32.8, -86.8), "ALASKA": (64.0, -152.0), "ARIZONA": (34.3, -111.7),
    "ARKANSAS": (34.9, -92.4), "CALIFORNIA": (37.2, -119.5), "COLORADO": (39.0, -105.5),
    "CONNECTICUT": (41.6, -72.7), "DELAWARE": (39.0, -75.5),
    "DISTRICT OF COLUMBIA": (38.9, -77.0), "FLORIDA": (28.6, -82.4),
    "GEORGIA": (32.6, -83.4), "HAWAII": (20.3, -156.4), "IDAHO": (44.4, -114.6),
    "ILLINOIS": (40.0, -89.2), "INDIANA": (39.9, -86.3), "IOWA": (42.0, -93.5),
    "KANSAS": (38.5, -98.4), "KENTUCKY": (37.5, -85.3), "LOUISIANA": (31.1, -92.0),
    "MAINE": (45.4, -69.2), "MARYLAND": (39.0, -76.8), "MASSACHUSETTS": (42.3, -71.8),
    "MICHIGAN": (44.3, -85.4), "MINNESOTA": (46.3, -94.3), "MISSISSIPPI": (32.7, -89.7),
    "MISSOURI": (38.4, -92.5), "MONTANA": (47.0, -109.6), "NEBRASKA": (41.5, -99.8),
    "NEVADA": (39.3, -116.6), "NEW HAMPSHIRE": (43.7, -71.6), "NEW JERSEY": (40.2, -74.7),
    "NEW MEXICO": (34.4, -106.1), "NEW YORK": (43.0, -75.5),
    "NORTH CAROLINA": (35.5, -79.4), "NORTH DAKOTA": (47.4, -100.5),
    "OHIO": (40.3, -82.8), "OKLAHOMA": (35.6, -97.5), "OREGON": (43.9, -120.6),
    "PENNSYLVANIA": (40.9, -77.8), "RHODE ISLAND": (41.7, -71.6),
    "SOUTH CAROLINA": (33.9, -80.9), "SOUTH DAKOTA": (44.4, -100.2),
    "TENNESSEE": (35.8, -86.4), "TEXAS": (31.5, -99.3), "UTAH": (39.3, -111.7),
    "VERMONT": (44.1, -72.7), "VIRGINIA": (37.5, -78.9), "WASHINGTON": (47.4, -120.5),
    "WEST VIRGINIA": (38.6, -80.6), "WISCONSIN": (44.6, -89.7), "WYOMING": (43.0, -107.6),
}


# ── chiave e chiamate ────────────────────────────────────────────────────

_PERCORSI_CHIAVE = (
    "d:/assistenteeee/shadowbroker/backend/data/operator_api_keys.env",
    "d:/assistenteeee/shadowbroker/backend/.env",
)
_chiave_cache: Optional[str] = None


def chiave() -> str:
    """La chiave Finnhub, dal file che l'interfaccia scrive.

    Non da `backend/.env`: quello contiene una copia piu' vecchia, e chi cerca
    li' conclude che la chiave e' sbagliata mentre invece funziona. L'ordine di
    ricerca sotto mette per primo il file giusto.
    """
    global _chiave_cache
    if _chiave_cache is not None:
        return _chiave_cache
    k = os.getenv("FINNHUB_API_KEY", "").strip()
    if not k:
        for percorso in _PERCORSI_CHIAVE:
            try:
                with open(percorso, encoding="utf-8") as f:
                    for riga in f:
                        if riga.startswith("FINNHUB_API_KEY="):
                            k = riga.split("=", 1)[1].strip().strip("\"'")
                            break
            except OSError:
                continue
            if k:
                break
    _chiave_cache = k
    return k


def _chiama(percorso: str, parametri: Dict[str, Any], timeout: float = 15.0) -> Any:
    k = chiave()
    if not k:
        raise RuntimeError("FINNHUB_API_KEY non configurata")
    p = dict(parametri)
    p["token"] = k
    url = f"{FINNHUB}{percorso}?{urllib.parse.urlencode(p)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── mercati ──────────────────────────────────────────────────────────────

def _variazione(v: Dict[str, Any]) -> float:
    try:
        return float(v.get("change_percent") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# Albero dei titoli noti: mercato -> comparto -> nome -> simbolo. Serve dove la ricerca Finnhub
# "trova" ma sbaglia societa' (Leonardo -> Leonardo DRS, USA) o non trova nulla. Nomi in minuscolo.
ALBERO_TITOLI: Dict[str, Dict[str, Dict[str, str]]] = {
    "italia": {
        "difesa_industria": {"leonardo": "LDO.MI", "fincantieri": "FCT.MI", "prysmian": "PRY.MI",
                             "iveco": "IVG.MI", "stellantis": "STLAM.MI", "ferrari": "RACE.MI",
                             "pirelli": "PIRC.MI", "stmicroelectronics": "STMMI.MI"},
        "banche_assicurazioni": {"unicredit": "UCG.MI", "intesa sanpaolo": "ISP.MI", "intesa": "ISP.MI",
                                 "generali": "G.MI", "mediobanca": "MB.MI", "banco bpm": "BAMI.MI",
                                 "bper": "BPE.MI", "mps": "BMPS.MI", "monte dei paschi": "BMPS.MI",
                                 "poste italiane": "PST.MI", "unipol": "UNI.MI"},
        "energia_reti": {"eni": "ENI.MI", "enel": "ENEL.MI", "snam": "SRG.MI", "terna": "TRN.MI",
                         "saipem": "SPM.MI", "tenaris": "TEN.MI", "a2a": "A2A.MI", "italgas": "IG.MI"},
        "altro": {"telecom italia": "TIT.MI", "tim": "TIT.MI", "moncler": "MONC.MI", "campari": "CPR.MI",
                  "amplifon": "AMP.MI", "recordati": "REC.MI", "nexi": "NEXI.MI"},
        "indici": {"ftse mib": "FTSEMIB.MI"},
    },
    "europa": {
        "difesa": {"rheinmetall": "RHM.DE", "bae systems": "BA.L", "thales": "HO.PA", "airbus": "AIR.PA",
                   "saab": "SAAB-B.ST", "dassault aviation": "AM.PA", "safran": "SAF.PA"},
        "altro": {"asml": "ASML.AS", "sap": "SAP.DE", "siemens": "SIE.DE", "lvmh": "MC.PA",
                  "totalenergies": "TTE.PA", "shell": "SHEL.L", "volkswagen": "VOW3.DE", "nestle": "NESN.SW"},
    },
    "usa": {
        "tecnologia": {"apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "alphabet": "GOOGL",
                       "google": "GOOGL", "amazon": "AMZN", "meta": "META", "tesla": "TSLA",
                       "netflix": "NFLX", "amd": "AMD", "intel": "INTC", "palantir": "PLTR"},
        "difesa": {"lockheed martin": "LMT", "lockheed": "LMT", "rtx": "RTX", "raytheon": "RTX",
                   "northrop grumman": "NOC", "northrop": "NOC", "general dynamics": "GD",
                   "boeing": "BA", "l3harris": "LHX", "leonardo drs": "DRS"},
    },
    "cripto": {
        "principali": {"bitcoin": "BINANCE:BTCUSDT", "btc": "BINANCE:BTCUSDT", "ethereum": "BINANCE:ETHUSDT",
                       "eth": "BINANCE:ETHUSDT", "solana": "BINANCE:SOLUSDT", "xrp": "BINANCE:XRPUSDT",
                       "cardano": "BINANCE:ADAUSDT"},
    },
}


def _cerca_albero(nome: str) -> Optional[Tuple[str, str, str]]:
    """(simbolo, mercato, comparto) per nome esatto, poi per nome contenuto. None se assente."""
    n = " ".join(str(nome or "").lower().replace("s.p.a.", " ").replace(" spa", " ").split())
    if not n:
        return None
    parziale = None
    for mercato, comparti in ALBERO_TITOLI.items():
        for comparto, nomi in comparti.items():
            for k, sym in nomi.items():
                if k == n:
                    return sym, mercato, comparto
                if parziale is None and len(n) >= 4 and (k.startswith(n) or n.startswith(k + " ")):
                    parziale = (sym, mercato, comparto)
    return parziale


def _quota_yahoo(sym: str) -> Optional[Dict[str, Any]]:
    """Ripiego senza chiave per i mercati che la chiave Finnhub gratuita non copre (Milano, Xetra,
    Parigi, Londra). Prezzo e chiusura precedente dalle candele giornaliere."""
    import json as _json
    import urllib.parse
    import urllib.request
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?range=5d&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = _json.loads(r.read().decode("utf-8", "replace"))
    ris = ((d.get("chart") or {}).get("result") or [None])[0]
    if not ris:
        return None
    meta = ris.get("meta") or {}
    prezzo = meta.get("regularMarketPrice")
    chiusure = [c for c in (((ris.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c]
    prec = chiusure[-2] if len(chiusure) >= 2 else meta.get("chartPreviousClose")
    if not prezzo or not prec:
        return None
    return {"prezzo": round(float(prezzo), 4), "chiusura_precedente": round(float(prec), 4),
            "valuta": meta.get("currency") or "?", "borsa": meta.get("exchangeName"),
            "descrizione": meta.get("longName") or meta.get("shortName"),
            "massimo": meta.get("regularMarketDayHigh"), "minimo": meta.get("regularMarketDayLow")}


def quotazione_titolo(titolo: str) -> Dict[str, Any]:
    """Quotazione ESPLICITA di un titolo chiesto per nome o ticker.

    Ordine (19 set 2026): 1) ticker scritto come tale; 2) ricerca Finnhub per nome; 3) albero dei
    titoli noti, che VINCE sulla ricerca quando conosce il nome (la ricerca «trova» Leonardo DRS
    per «Leonardo», Maui Land per «Apple») e la sostituisce quando la ricerca e' vuota.
    Quotazione: Finnhub; se non copre il mercato, ripiego Yahoo. Ogni numero porta la sua unita':
    il modello confondeva variazione assoluta e percentuale.
    """
    q = str(titolo or "").strip()
    fuori: Dict[str, Any] = {"titolo_richiesto": q}
    if not q:
        fuori.update(disponibile=False, motivo="titolo vuoto")
        return fuori
    try:
        sym = q.upper()
        e_ticker = (" " not in q and q.isupper() and bool(re.fullmatch(r"[A-Z0-9.:\-]{1,16}", sym)))
        if not e_ticker:
            cands: List[Dict[str, Any]] = []
            try:
                r = _chiama("/search", {"q": q})
                cands = [c for c in (r.get("result") or []) if isinstance(c, dict) and c.get("symbol")]
            except Exception:  # noqa: BLE001  la ricerca e' un aiuto, non un requisito
                cands = []
            _ql = q.lower()

            def _voto(c):
                d = str(c.get("description") or "").lower()
                return (0 if d.startswith(_ql) else (1 if _ql in d.split() else 2),
                        0 if str(c.get("type") or "").lower().startswith("common") else 1,
                        1 if "." in c["symbol"] else 0, len(d))
            cands.sort(key=_voto)
            noto = _cerca_albero(q)
            if noto:
                sym = noto[0]
                fuori["mercato"], fuori["comparto"] = noto[1], noto[2]
                altri = [c for c in cands if c["symbol"] != sym][:4]
            elif cands:
                sym = cands[0]["symbol"]
                fuori["descrizione"] = cands[0].get("description")
                altri = cands[1:5]
            else:
                fuori.update(disponibile=False,
                             motivo="nessun simbolo trovato per questo nome, ne' nella ricerca ne' tra i titoli noti; "
                                    "chiedi all'utente il ticker esatto")
                return fuori
            if altri:
                fuori["altri_titoli_con_nome_simile"] = [f"{c['symbol']} = {c.get('description') or '?'}" for c in altri]
                fuori["avviso"] = f"quotato {sym}. Esistono altri titoli con nome simile: di' quale hai quotato."
        fuori["simbolo"] = sym
        prezzo = prec = None
        if "." not in sym or ":" in sym:
            try:
                v = _chiama("/quote", {"symbol": sym}) or {}
            except Exception:  # noqa: BLE001
                v = {}
            if isinstance(v, dict) and v.get("c"):
                prezzo, prec = v.get("c"), v.get("pc")
                fuori.update(fonte="Finnhub", valuta="USD", apertura=v.get("o"), massimo=v.get("h"), minimo=v.get("l"))
        if not prezzo and ":" not in sym:
            y = _quota_yahoo(sym)
            if y:
                prezzo, prec = y["prezzo"], y["chiusura_precedente"]
                fuori.update(fonte="Yahoo Finance", valuta=y["valuta"], borsa=y.get("borsa"),
                             massimo=y.get("massimo"), minimo=y.get("minimo"))
                if y.get("descrizione"):
                    fuori["descrizione"] = y["descrizione"]
        if not prezzo:
            fuori.update(disponibile=False,
                         motivo="quotazione non disponibile per questo simbolo da nessuna delle due fonti; "
                                "dillo all'utente, non stimare il prezzo")
            return fuori
        val = fuori.get("valuta") or "?"
        fuori.update(disponibile=True, prezzo=prezzo, chiusura_precedente=prec)
        if prec:
            d_ass = round(float(prezzo) - float(prec), 4)
            d_pct = round(d_ass / float(prec) * 100, 2)
            fuori["variazione_percento"] = d_pct
            fuori["variazione_in_valuta"] = d_ass
            fuori["leggi_cosi"] = (f"{fuori.get('descrizione') or q} ({sym}): {prezzo} {val}, oggi {d_pct:+.2f}% "
                                   f"rispetto alla chiusura precedente, cioe' {d_ass:+.2f} {val} per azione")
    except Exception as e:  # noqa: BLE001
        fuori.update(disponibile=False, motivo=f"errore della fonte dati: {type(e).__name__}")
    return fuori


def mercati(quante_notizie: int = 8, titolo: Optional[str] = None) -> Dict[str, Any]:
    """Come si muove la difesa, e cosa se ne dice.

    Il valore non sono i prezzi: sono le **anomalie**. Un titolo che va contro
    il proprio comparto ha quasi sempre una causa propria, e quella e' la cosa
    da raccontare. Il calcolo lo fa qui Python, cosi' il modello non deve
    guardare sei numeri e dedurre da solo quale e' strano.
    """
    store = get_store()
    dati = store.carica_molti(["stocks", "finnhub_news", "unusual_whales"])

    grezzo = dati.get("stocks") or []
    quotazioni: Dict[str, Dict[str, Any]] = grezzo[0] if (len(grezzo) == 1 and grezzo[0]) else {}
    if not quotazioni:
        for e in grezzo:
            if isinstance(e, dict):
                quotazioni.update({k: v for k, v in e.items() if isinstance(v, dict)})

    def gruppo(simboli) -> List[Dict[str, Any]]:
        fuori = []
        for s in simboli:
            v = quotazioni.get(s)
            if isinstance(v, dict) and v.get("price") is not None:
                fuori.append({
                    "simbolo": s, "nome": NOMI.get(s, s),
                    "prezzo": v.get("price"), "variazione_pct": _variazione(v),
                })
        return sorted(fuori, key=lambda x: -x["variazione_pct"])

    difesa = gruppo(DIFESA)
    altri = [s for s in quotazioni if s not in DIFESA]
    cripto = gruppo([s for s in altri if s in ("BTC", "ETH", "SOL", "XRP", "ADA")])
    tech = gruppo([s for s in altri if s not in ("BTC", "ETH", "SOL", "XRP", "ADA")])

    fuori: Dict[str, Any] = {
        "tipo": "mercati",
        "difesa": difesa,
        "tecnologia": tech[:8],
        "cripto": cripto,
    }

    # L'anomalia: chi va contro il proprio comparto.
    if len(difesa) >= 3:
        variazioni = [t["variazione_pct"] for t in difesa]
        media = sum(variazioni) / len(variazioni)
        salgono = sum(1 for v in variazioni if v > 0)
        contrarie = [t for t in difesa if (t["variazione_pct"] > 0) != (media > 0)]
        fuori["lettura_difesa"] = {
            "media_pct": round(media, 2),
            "in_rialzo": f"{salgono} su {len(difesa)}",
            "controcorrente": [
                {"simbolo": t["simbolo"], "nome": t["nome"], "variazione_pct": t["variazione_pct"],
                 "nota": "va contro il proprio comparto: probabile causa propria, non di settore"}
                for t in contrarie
            ],
        }

    # Le notizie si ordinano **sui picchi**, non per ordine di arrivo.
    #
    # Prima uscivano "quelle con un ticker, come capita": il risultato era che
    # il titolo che si muoveva di piu' restava senza notizia, e il modello
    # costruiva un nesso con l'unica notizia che aveva sottomano. Dando prima
    # quelle che spiegano i movimenti grossi, il nesso non serve inventarlo.
    tutti = difesa + tech + cripto
    peso = {t["simbolo"]: abs(t["variazione_pct"]) for t in tutti}

    notizie = dati.get("finnhub_news") or []
    notizie = sorted(
        notizie,
        key=lambda n: (-peso.get(n.get("ticker") or "", -1.0), n.get("published") or ""),
        reverse=False,
    )
    scelte = notizie[:quante_notizie]
    fuori["notizie"] = [
        {"titolo": n.get("title"), "fonte": n.get("source"),
         "titolo_azionario": n.get("ticker"), "quando": n.get("published"),
         "url": n.get("url")}
        for n in scelte
    ]
    fuori["notizie_disponibili"] = len(notizie)

    # I picchi senza spiegazione vanno **dichiarati**, non lasciati indovinare.
    coperti = {n.get("ticker") for n in scelte if n.get("ticker")}
    picchi = sorted(tutti, key=lambda t: -abs(t["variazione_pct"]))[:3]
    scoperti = [t["simbolo"] for t in picchi if t["simbolo"] not in coperti]
    fuori["picchi"] = [
        {"simbolo": t["simbolo"], "nome": t["nome"], "variazione_pct": t["variazione_pct"],
         "ha_notizia": t["simbolo"] in coperti}
        for t in picchi
    ]
    if scoperti:
        fuori["picchi_senza_notizia"] = (
            f"{', '.join(scoperti)}: nessuna notizia collegata disponibile. "
            f"Dillo — mai attribuire il movimento a notizia di altro titolo. "
            f"Per capire: `osint_notizie` sul nome azienda."
        )

    if not difesa:
        fuori["non_osservabile"] = (
            "layer 'stocks' vuoto: fetcher non ancora girato o chiave "
            "assente. Non significa mercati fermi."
        )
    if titolo:
        # IN TESTA, non in coda: l'harness taglia gli output lunghi e la risposta
        # alla domanda specifica dev'essere la prima cosa che il modello legge
        # (H3: tagliata a 3000 caratteri, il modello ha inventato il prezzo).
        quota = quotazione_titolo(str(titolo))
        # Notizie DEL titolo, separate da quelle generali (19 set: il modello attribuiva a Meta una
        # notizia su Netflix perche' l'elenco generale arrivava sotto la quotazione chiesta).
        _sym = str(quota.get("simbolo") or "").split(".")[0].split(":")[-1].replace("USDT", "")
        _parole = str(quota.get("descrizione") or titolo or "").lower().split()
        _nome = _parole[0] if _parole else ""
        sue = [n for n in notizie
               if (n.get("ticker") or "") == _sym
               or (len(_nome) >= 4 and _nome in str(n.get("title") or "").lower())]
        quota["notizie_di_questo_titolo"] = (
            [{"titolo": n.get("title"), "fonte": n.get("source"), "quando": n.get("published"), "url": n.get("url")}
             for n in sue[:5]]
            or "nessuna notizia collegata a questo titolo nel feed: dillo; per cercarne usa osint_notizie con soggetto")
        generali = fuori.pop("notizie", [])
        fuori["notizie_generali_di_mercato_NON_sul_titolo_richiesto"] = generali[:4]
        fuori = {"titolo_richiesto": quota, **fuori}
    # Archivio storico: i picchi di oggi diventano eventi consultabili domani.
    # Lavora in un thread, un errore li' non tocca questa risposta.
    from src.shadowbroker import archivio
    archivio.ingerisci_da_briefing("mercati", fuori)
    return fuori


# ── appalti ──────────────────────────────────────────────────────────────

def _importo(r: Dict[str, Any]) -> float:
    """Il valore piu' rappresentativo fra i quattro campi di importo.

    `totalValue` e `obligatedAmount` sono spesso 0 su contratti quadro;
    `potentialAmount` e' il tetto massimo ed e' quello che compare quando la
    stampa scrive "commessa da N milioni".
    """
    for campo in ("potentialAmount", "totalValue", "obligatedAmount", "outlayedAmount"):
        try:
            v = float(r.get(campo) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v:
            return v
    return 0.0


def _chiave_dedup(r: Dict[str, Any]) -> Tuple:
    """Due righe con stesso importo, agenzia e oggetto sono la stessa commessa.

    La data **non** entra nella chiave, e non e' una svista: nei dati veri lo
    stesso contratto compare fino a quattro volte con date di azione diverse
    (F119 CY25-CY27 a 5.390,7 M$, quattro righe). Sono ri-obbligazioni dello
    stesso programma, non commesse nuove. Tenendo la data si riempivano i primi
    posti con la stessa riga ripetuta.
    """
    return (r.get("symbol"), round(_importo(r)),
            (r.get("awardingAgencyName") or "").strip(),
            (r.get("awardDescription") or "").strip()[:60])


# Sopra questa soglia non e' una commessa: e' il **tetto di un contratto
# quadro**. OASIS+, Alliant, i GWAC: veicoli da cui poi si ordina, con un
# massimale nominale da mille miliardi e nessun luogo di esecuzione.
#
# Senza questo filtro i primi dieci posti erano tutti tetti — importi assurdi,
# zero mappabili, e le commesse vere (missili per il Qatar, motori F-22)
# sparivano sotto. Sono il 10% delle righe e il 100% del rumore.
TETTO_ASSURDO_MILIONI = 100_000.0

_VEICOLI = ("OASIS", "GWAC", "GOVERNMENT-WIDE ACQUISITION", "ALLIANT", "UMBRELLA",
            "FEDERAL SUPPLY SCHEDULE", "IDIQ", "BLANKET PURCHASE", "MULTIPLE AWARD",
            "IGF::")  # marcatore che compare nei veicoli, non nelle commesse


def _e_contratto_quadro(r: Dict[str, Any]) -> bool:
    if _importo(r) / 1e6 >= TETTO_ASSURDO_MILIONI:
        return True
    oggetto = (r.get("awardDescription") or "").upper()
    return any(v in oggetto for v in _VEICOLI)


def appalti(mesi: int = 12, quanti: int = 12,
            solo_difesa: bool = True, titolo: Optional[str] = None) -> Dict[str, Any]:
    """Contratti federali statunitensi assegnati ai contractor della difesa.

    E' l'unico dato finanziario che ha un **luogo**, quindi l'unico che puo'
    stare sulla mappa accanto a basi, voli e navi. Gli elementi vengono
    registrati nel magazzino con un identificativo `appalti:xxxxxx`, cosi' il
    modello puo' poi chiamare `osint_mappa evidenzia` citandoli.
    """
    oggi = date.today()
    da = (oggi - timedelta(days=int(mesi * 30.5))).isoformat()
    a = oggi.isoformat()

    simboli = [titolo.upper()] if titolo else list(DIFESA if solo_difesa else DIFESA)

    righe: List[Dict[str, Any]] = []
    falliti: List[str] = []
    for s in simboli:
        try:
            d = _chiama("/stock/usa-spending", {"symbol": s, "from": da, "to": a})
            righe.extend(d.get("data") or [])
        except Exception as e:
            falliti.append(f"{s}: {type(e).__name__}")
            logger.warning("[finanza] appalti %s: %s", s, e)

    # Prima i tetti dei contratti quadro, poi i duplicati, poi l'ordinamento.
    # L'ordine conta: deduplicare per ultimo lascerebbe passare quattro copie
    # della stessa riga fra le prime dieci.
    quadro = [r for r in righe if _e_contratto_quadro(r)]
    reali = [r for r in righe if not _e_contratto_quadro(r)]

    viste = set()
    unici = []
    for r in reali:
        k = _chiave_dedup(r)
        if k in viste:
            continue
        viste.add(k)
        unici.append(r)

    unici.sort(key=lambda r: -_importo(r))
    scelti = unici[:quanti]

    voci = []
    per_magazzino = []
    for r in scelti:
        stato = (r.get("performanceState") or "").strip().upper()
        punto = STATI_USA.get(stato)
        v = {
            "titolo": r.get("symbol"),
            "assegnataria": r.get("recipientName"),
            "importo_milioni": round(_importo(r) / 1e6, 2),
            "data": r.get("actionDate"),
            "agenzia": r.get("awardingAgencyName"),
            "sotto_agenzia": r.get("awardingSubAgencyName"),
            "oggetto": (r.get("awardDescription") or "")[:180],
            "url": r.get("permalink"),
        }
        if stato:
            v["stato_usa"] = stato
            v["distretto"] = r.get("performanceCongressionalDistrict")
        if punto:
            v["lat"], v["lng"] = punto[0], punto[1]
        else:
            v["luogo"] = "non dichiarato"
        voci.append(v)
        per_magazzino.append(dict(v, name=f"{r.get('symbol')} {r.get('actionDate')} "
                                          f"{round(_importo(r)/1e6)}M"))

    # Registrati nel magazzino: senza questo `osint_mappa evidenzia` non
    # troverebbe gli identificativi e risponderebbe "non trovato".
    ids = get_store().registra("appalti", per_magazzino)
    for v, i in zip(voci, ids):
        v["id"] = i

    con_luogo = sum(1 for v in voci if "lat" in v)
    fuori: Dict[str, Any] = {
        "tipo": "appalti_federali",
        "finestra_mesi": mesi,
        "contratti": voci,
        "totali_trovati": len(unici),
        "duplicati_scartati": len(reali) - len(unici),
        "contratti_quadro_esclusi": len(quadro),
        "nota_quadro": (
            "esclusi veicoli quadro (OASIS+, GWAC, schedule): massimali "
            "nominali fino a mille miliardi, nessun luogo, non commesse"
        ),
        "mappabili": f"{con_luogo} su {len(voci)}",
        "nota_luogo": (
            "luogo = stato di esecuzione, approssimato al centro: e' la "
            "granularita' del dato. Senza stato = forniture a catalogo."
        ),
        "nota_importo": "importo = valore potenziale massimo del contratto, non speso",
    }
    if falliti:
        fuori["non_osservabile"] = f"richieste fallite: {', '.join(falliti)}"
    if not voci:
        fuori["non_osservabile"] = (
            "nessun contratto nella finestra. Dati trimestrali: allarga "
            "`mesi` prima di concludere."
        )
    from src.shadowbroker import archivio
    archivio.ingerisci_da_briefing("appalti", fuori)
    return fuori


# ── insider ──────────────────────────────────────────────────────────────

# Codici del modulo 4 della SEC. `A` e `M` non sono decisioni di mercato:
# assegnazioni e esercizi di opzione avvengono a prezzo zero o prefissato.
CODICI = {
    "P": "acquisto sul mercato",
    "S": "vendita sul mercato",
    "A": "assegnazione (non e' un acquisto: prezzo zero)",
    "M": "esercizio di opzione",
    "F": "azioni trattenute per le tasse",
    "G": "donazione",
    "D": "cessione all'emittente",
}
DECISIONI_VERE = ("P", "S")


def insider(quanti: int = 12, titolo: Optional[str] = None) -> Dict[str, Any]:
    """Movimenti degli interni, con MSPR.

    MSPR (*Monthly Share Purchase Ratio*) va da -100 a +100 ed e' l'aggregato
    mensile degli acquisti netti. E' della stessa natura di `threat_level`: un
    numero **gia' normalizzato**, che il modello riceve invece di doversi
    inventare una soglia.
    """
    oggi = date.today()
    da = (oggi - timedelta(days=120)).isoformat()
    simboli = [titolo.upper()] if titolo else list(DIFESA)

    sentimento: List[Dict[str, Any]] = []
    falliti: List[str] = []
    for s in simboli:
        try:
            d = _chiama("/stock/insider-sentiment", {"symbol": s, "from": da, "to": oggi.isoformat()})
            for v in (d.get("data") or [])[-2:]:
                sentimento.append({
                    "titolo": s, "nome": NOMI.get(s, s),
                    "mese": f"{v.get('year')}-{int(v.get('month') or 0):02d}",
                    "mspr": round(float(v.get("mspr") or 0), 2),
                    "azioni_nette": v.get("change"),
                })
        except Exception as e:
            falliti.append(f"{s}: {type(e).__name__}")

    # Ordinati per **forza del segnale**, non per MSPR nudo.
    #
    # MSPR satura: vale +100 sia per un acquisto da 162 azioni sia per uno da
    # centomila, perche' e' un rapporto. Ordinando solo per quello, in cima
    # finivano quattro +100 da poche centinaia di azioni mentre una vendita da
    # 183.876 azioni con MSPR -63 restava sotto. Il rapporto dice *quanto
    # unanime* e' stato il mese, la quantita' dice *quanto pesa*: servono
    # entrambi. Il logaritmo evita che la sola dimensione schiacci il rapporto.
    import math

    def forza(v: Dict[str, Any]) -> float:
        try:
            azioni = abs(float(v.get("azioni_nette") or 0))
        except (TypeError, ValueError):
            azioni = 0.0
        return abs(v["mspr"]) * math.log10(10 + azioni)

    for v in sentimento:
        v["forza_segnale"] = round(forza(v), 1)
    sentimento.sort(key=lambda v: -v["forza_segnale"])

    movimenti: List[Dict[str, Any]] = []
    bersaglio = simboli[0] if titolo else (sentimento[0]["titolo"] if sentimento else DIFESA[0])
    try:
        d = _chiama("/stock/insider-transactions", {"symbol": bersaglio})
        for r in (d.get("data") or [])[:quanti]:
            codice = (r.get("transactionCode") or "").strip().upper()
            movimenti.append({
                "titolo": bersaglio,
                "persona": r.get("name"),
                "data": r.get("filingDate"),
                "codice": codice,
                "cosa_significa": CODICI.get(codice, "codice non catalogato"),
                "azioni": r.get("change"),
                "prezzo": r.get("transactionPrice"),
                "decisione_di_mercato": codice in DECISIONI_VERE,
            })
    except Exception as e:
        falliti.append(f"{bersaglio} transazioni: {type(e).__name__}")

    vere = [m for m in movimenti if m["decisione_di_mercato"]]
    fuori: Dict[str, Any] = {
        "tipo": "insider",
        "scala_mspr": (
            "-100 vendita decisa … +100 acquisto deciso; |50|+ segnale netto. "
            "E' un RAPPORTO: satura. +100 su 162 azioni pesa meno di -60 su "
            "180.000 — guarda sempre `azioni_nette`."
        ),
        "ordinamento": "per forza del segnale = |MSPR| pesato sulla quantita', non per MSPR nudo",
        "sentimento_mensile": sentimento[:10],
        "movimenti_recenti": movimenti,
        "movimenti_su": bersaglio,
        "di_cui_decisioni_di_mercato": f"{len(vere)} su {len(movimenti)}",
        "nota_codici": (
            "solo P e S = decisioni di mercato. A, M = assegnazioni ed "
            "esercizi a prezzo zero o prefissato: contarli come acquisti "
            "inverte il segnale."
        ),
    }
    if falliti:
        fuori["non_osservabile"] = ", ".join(falliti)
    from src.shadowbroker import archivio
    archivio.ingerisci_da_briefing("insider", fuori)
    return fuori
