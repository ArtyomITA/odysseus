"""Geografia: distanze vere e nomi dei posti.

Esiste perche' i filtri geografici di ShadowBroker non sono affidabili, e i due
difetti sono del tipo peggiore — non danno errore, danno il numero sbagliato:

  * `/api/ai/news-near` legge **solo** `radius`. Passando `radius_km` o
    `radius_miles` il valore viene ignorato e si ricade su 500 miglia:
    "notizie entro 50 km da Kyiv" restituisce Mosca e Varsavia.

  * `brief_area` mescola due cose in una risposta. `nearby` e' davvero locale,
    ma `context_layers` sono i **primi N mondiali senza filtro**. Chiedendo la
    zona di Kyiv i terremoti restituiti erano in Filippine, Indonesia e Cina —
    un modello che legge quel blocco dira' che c'e' stato un 5.1 vicino a Kyiv.

Da cui: **ogni distanza viene ricalcolata qui**, e ogni elemento consegnato al
modello porta con se' quanto dista, cosi' puo' dire "a 480 km" invece di far
finta che sia li'.

I nomi dei posti servono perche' GT etichetta le regioni con le coordinate
grezze (`"12.86,30.22"`), che a voce non significano niente.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

RAGGIO_TERRA_KM = 6371.0088
KM_PER_MIGLIO = 1.609344


def distanza_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distanza sul grande cerchio (haversine)."""
    p = math.radians
    dlat = p(lat2 - lat1)
    dlng = p(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(dlng / 2) ** 2)
    return 2 * RAGGIO_TERRA_KM * math.asin(math.sqrt(min(1.0, a)))


def coordinate_di(elemento: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Estrae (lat, lng) da un elemento, qualunque forma abbia.

    ShadowBroker usa almeno quattro convenzioni: `lat`/`lng`, `lat`/`lon`,
    `coords` come coppia, e la `geometry` GeoJSON (dove l'ordine e'
    **lng, lat** — invertito rispetto a tutto il resto, ed e' un classico modo
    di finire in mezzo all'oceano).
    """
    if not isinstance(elemento, dict):
        return None

    lat = elemento.get("lat")
    lng = elemento.get("lng", elemento.get("lon"))
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)

    c = elemento.get("coords")
    if isinstance(c, (list, tuple)) and len(c) >= 2:
        if isinstance(c[0], (int, float)) and isinstance(c[1], (int, float)):
            return float(c[0]), float(c[1])

    g = elemento.get("geometry")
    if isinstance(g, dict):
        coord = g.get("coordinates")
        # Solo i punti: per poligoni e linee il centroide sarebbe fuorviante.
        if (isinstance(coord, (list, tuple)) and len(coord) >= 2
                and isinstance(coord[0], (int, float))
                and isinstance(coord[1], (int, float))):
            return float(coord[1]), float(coord[0])
    return None


def entro(elementi: Iterable[Dict[str, Any]], lat: float, lng: float,
          raggio_km: float, senza_coordinate: str = "escludi") -> List[Dict[str, Any]]:
    """Filtra per distanza vera e annota `_km` su ogni superstite.

    `senza_coordinate`:
      - `escludi`  (predefinito) — un elemento senza posizione non puo' essere
        dichiarato vicino. Silenzio meglio di una bugia.
      - `includi`  — lo tiene con `_km = None`, per i casi in cui l'assenza di
        coordinate e' comune e la pertinenza viene da altro (le notizie: solo
        17 su 40 sono geolocalizzate).
    """
    fuori: List[Dict[str, Any]] = []
    for e in elementi:
        c = coordinate_di(e)
        if c is None:
            if senza_coordinate == "includi":
                fuori.append({**e, "_km": None})
            continue
        d = distanza_km(lat, lng, c[0], c[1])
        if d <= raggio_km:
            fuori.append({**e, "_km": round(d)})
    fuori.sort(key=lambda x: (x.get("_km") is None, x.get("_km") or 0))
    return fuori


# ── nomi dei posti ───────────────────────────────────────────────────────
# `reverse_geocoder` e' fra le dipendenze di ShadowBroker (non di Odysseus),
# quindi puo' non esserci: l'import e' pigro e il fallimento e' silenzioso.

_rg = None
_rg_provato = False
_rg_lock = threading.Lock()


def _geocoder():
    global _rg, _rg_provato
    with _rg_lock:
        if _rg_provato:
            return _rg
        _rg_provato = True
        try:
            import reverse_geocoder  # type: ignore
            _rg = reverse_geocoder
            logger.info("[shadowbroker] reverse_geocoder disponibile")
        except Exception:
            _rg = None
            logger.info("[shadowbroker] reverse_geocoder assente: i posti restano coordinate")
        return _rg


_cache_nomi: Dict[Tuple[float, float], str] = {}


def nome_del_posto(lat: float, lng: float) -> str:
    """"Kadugli, Southern Kordofan, SD" da 12.86, 30.22.

    Torna stringa vuota quando non si puo' determinare: chi chiama deve
    ripiegare sulle coordinate, non inventare un nome.
    """
    chiave = (round(lat, 2), round(lng, 2))
    if chiave in _cache_nomi:
        return _cache_nomi[chiave]
    rg = _geocoder()
    nome = ""
    if rg is not None:
        try:
            r = rg.search((lat, lng), mode=1, verbose=False)[0]
            parti = [r.get("name"), r.get("admin1"), r.get("cc")]
            nome = ", ".join(p for p in parti if p)
        except Exception:
            nome = ""
    _cache_nomi[chiave] = nome
    return nome


def etichetta(elemento: Dict[str, Any]) -> str:
    """Il nome piu' leggibile disponibile per un elemento."""
    for campo in ("name", "place", "title", "region_label", "site_name", "callsign"):
        v = elemento.get(campo)
        if isinstance(v, str) and v.strip():
            return v.strip()
    c = coordinate_di(elemento)
    if c:
        n = nome_del_posto(*c)
        if n:
            return n
        return f"{c[0]:.2f}, {c[1]:.2f}"
    return "(senza posizione)"


# ── posti noti ───────────────────────────────────────────────────────────
# Per risolvere "Kyiv", "Gaza", "Stretto di Hormuz" senza dipendere da un
# servizio esterno per i casi frequenti. Non e' un geocoder completo: quando
# manca, si passa a Nominatim tramite ShadowBroker.

POSTI: Dict[str, Tuple[float, float]] = {
    "kyiv": (50.45, 30.52), "kiev": (50.45, 30.52), "ucraina": (49.0, 32.0),
    "ukraine": (49.0, 32.0), "odessa": (46.48, 30.73), "odesa": (46.48, 30.73),
    "kharkiv": (49.99, 36.23), "donetsk": (48.02, 37.80), "crimea": (45.3, 34.4),
    "mosca": (55.75, 37.62), "moscow": (55.75, 37.62), "russia": (55.75, 37.62),
    "bielorussia": (53.9, 27.57), "belarus": (53.9, 27.57), "minsk": (53.9, 27.57),
    "gaza": (31.5, 34.47), "israele": (31.78, 35.22), "israel": (31.78, 35.22),
    "libano": (33.89, 35.5), "lebanon": (33.89, 35.5), "beirut": (33.89, 35.5),
    "siria": (33.51, 36.28), "syria": (33.51, 36.28), "damasco": (33.51, 36.28),
    "iran": (35.69, 51.39), "teheran": (35.69, 51.39), "tehran": (35.69, 51.39),
    "iraq": (33.31, 44.36), "baghdad": (33.31, 44.36),
    "yemen": (15.35, 44.21), "sanaa": (15.35, 44.21),
    "mar rosso": (15.0, 42.0), "red sea": (15.0, 42.0),
    "hormuz": (26.57, 56.25), "stretto di hormuz": (26.57, 56.25),
    "golfo persico": (26.5, 52.0), "persian gulf": (26.5, 52.0),
    "taiwan": (23.7, 121.0), "cina": (39.9, 116.4), "china": (39.9, 116.4),
    "corea del nord": (39.03, 125.75), "north korea": (39.03, 125.75),
    "sudan": (15.5, 32.55), "khartoum": (15.5, 32.55),
    "libia": (32.89, 13.19), "libya": (32.89, 13.19),
    "sahel": (14.5, 0.0), "mali": (12.65, -8.0), "niger": (13.51, 2.11),
    "venezuela": (10.48, -66.9), "caracas": (10.48, -66.9),
    "afghanistan": (34.53, 69.17), "kabul": (34.53, 69.17),
    "pakistan": (33.68, 73.05), "india": (28.61, 77.21),
    "polonia": (52.23, 21.01), "poland": (52.23, 21.01), "varsavia": (52.23, 21.01),
    "baltico": (57.0, 20.0), "baltic": (57.0, 20.0),
    "italia": (41.9, 12.5), "italy": (41.9, 12.5), "roma": (41.9, 12.5),
    "londra": (51.51, -0.13), "london": (51.51, -0.13),
    "parigi": (48.86, 2.35), "paris": (48.86, 2.35),
    "berlino": (52.52, 13.4), "berlin": (52.52, 13.4),
    "washington": (38.9, -77.04), "new york": (40.71, -74.01),
    "europa": (50.0, 15.0), "europe": (50.0, 15.0),
    "medio oriente": (31.0, 40.0), "middle east": (31.0, 40.0),
}


def risolvi_posto(testo: str) -> Optional[Tuple[float, float]]:
    """Da un nome (o "lat,lng") a coordinate. None se non riconosciuto."""
    if not testo:
        return None
    t = testo.strip().lower()

    if "," in t:
        pezzi = [p.strip() for p in t.split(",")]
        if len(pezzi) == 2:
            try:
                lat, lng = float(pezzi[0]), float(pezzi[1])
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return lat, lng
            except ValueError:
                pass

    if t in POSTI:
        return POSTI[t]
    # Corrispondenza parziale: "notizie sull'ucraina" contiene "ucraina".
    for nome, coord in POSTI.items():
        if len(nome) >= 4 and nome in t:
            return coord
    return None
