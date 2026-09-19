"""Sagome: che campi tenere di ogni layer, e cosa buttare.

Misurato dove finiscono davvero i token:

    military_flights   `trail` (la scia, array di coordinate)    83,5%
    news               `summary` (prosa)                          64%
    frontlines         il poligono GeoJSON                       100%

Tutto il resto — sigla, tipo, posizione, quota, operatore, partenza,
destinazione, punteggi — e' il 16% e costa quasi niente.

    25 aerei, tutto grezzo              5.135 token
    25 aerei, solo campi strutturati      780 token

Da cui la regola unica: **via gli array voluminosi e la prosa, tieni ogni campo
strutturato**. Le coordinate e i collegamenti non si toccano mai: costano l'1%
e sono esattamente cio' che serve per indicare sulla mappa e citare la fonte.

Niente e' perso davvero: il magazzino (store.py) conserva l'elemento intero,
recuperabile per identificativo con `osint_dettaglio`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Sagoma:
    """Come ridurre un elemento di un layer.

    `tieni` vuoto = tieni tutto tranne quello in `butta`. Utile per i layer
    piccoli dove non vale la pena elencare i campi.
    """
    tieni: Sequence[str] = ()
    butta: Sequence[str] = ()
    tronca: Dict[str, int] = field(default_factory=dict)
    # Campo su cui ordinare in senso decrescente quando si compone una lista.
    ordina_per: Optional[str] = None

    def applica(self, elemento: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(elemento, dict):
            return {}
        if self.tieni:
            fuori = {k: v for k, v in elemento.items() if k in self.tieni}
        else:
            fuori = {k: v for k, v in elemento.items() if k not in self.butta}
        for campo, limite in self.tronca.items():
            v = fuori.get(campo)
            if isinstance(v, str) and len(v) > limite:
                fuori[campo] = v[:limite].rstrip() + "…"
        # I valori nulli sono puro involucro: a 40 elementi per 6 campi vuoti
        # sono centinaia di token che non dicono niente.
        return {k: v for k, v in fuori.items() if v not in (None, "", [], {})}


# `trail` e' l'83,5% del payload dei voli: la scia serve a disegnare la linea
# sulla mappa, non a rispondere a una domanda.
_VOLO = Sagoma(
    tieni=("icao24", "callsign", "registration", "model", "military_type", "force",
           "operator", "country", "lat", "lng", "alt", "speed", "heading",
           "origin_name", "dest_name", "holding", "aircraft_category",
           "alert_category", "alert_operator", "alert_tags", "alert_type", "alert_link"),
)

SAGOME: Dict[str, Sagoma] = {
    # ── movimenti ────────────────────────────────────────────────────────
    "military_flights": _VOLO,
    "tracked_flights": _VOLO,
    "private_jets": _VOLO,
    "commercial_flights": _VOLO,
    "private_flights": _VOLO,
    "flights": _VOLO,
    "ships": Sagoma(
        tieni=("name", "type", "country", "lat", "lng", "heading", "speed", "desc",
               "position_confidence", "estimated", "is_fallback", "last_osint_update"),
    ),
    "trains": Sagoma(
        tieni=("name", "number", "operator", "route", "status", "country",
               "lat", "lng", "speed_kmh", "heading"),
    ),
    "satellites": Sagoma(
        tieni=("name", "mission", "sat_type", "country", "lat", "lng", "alt_km", "speed_knots"),
    ),

    # ── eventi e notizie ─────────────────────────────────────────────────
    # `_snippets_list` esiste ma il feed non lo popola mai; `html` e' markup
    # per il loro popup; `_urls_list` si tiene, e' la chiave per recuperare il
    # testo vero dell'articolo.
    "gdelt": Sagoma(
        butta=("html", "_snippets_list", "event_code", "quad_class"),
        ordina_per="num_articles",
    ),
    "news": Sagoma(
        tieni=("title", "link", "published", "source", "risk_score", "oracle_score",
               "sentiment", "machine_assessment", "breaking", "cluster_count", "coords"),
        ordina_per="oracle_score",
    ),
    "telegram_osint": Sagoma(
        tieni=("title", "description", "summary", "channel", "source", "link",
               "published", "risk_score", "coords", "lat", "lng"),
        tronca={"description": 400, "summary": 400},
        ordina_per="risk_score",
    ),

    # ── allerte ──────────────────────────────────────────────────────────
    "weather_alerts": Sagoma(
        tieni=("event", "headline", "severity", "urgency", "certainty", "expires", "id"),
        tronca={"headline": 200},
    ),
    "earthquakes": Sagoma(tieni=("id", "mag", "place", "lat", "lng"), ordina_per="mag"),
    "firms_fires": Sagoma(
        tieni=("lat", "lng", "frp", "confidence", "acq_date", "brightness"),
        ordina_per="frp",
    ),
    "internet_outages": Sagoma(
        tieni=("country_name", "region_name", "severity", "level", "datasource", "lat", "lng"),
        ordina_per="severity",
    ),
    "correlations": Sagoma(ordina_per="score"),
    "malware_threats": Sagoma(),
    "cyber_threats": Sagoma(),
    "scm_suppliers": Sagoma(),
    "wastewater": Sagoma(
        tieni=("name", "site_name", "city", "country", "lat", "lng",
               "alert_count", "pathogens", "collection_date"),
        ordina_per="alert_count",
    ),
    "space_weather": Sagoma(),

    # ── infrastrutture (grandi, quasi solo anagrafica) ───────────────────
    "power_plants": Sagoma(tieni=("name", "country", "lat", "lng", "capacity_mw", "fuel_type", "owner")),
    "datacenters": Sagoma(tieni=("name", "company", "city", "country", "lat", "lng")),
    "military_bases": Sagoma(tieni=("name", "country", "branch", "operator", "lat", "lng")),
    "airports": Sagoma(tieni=("name", "iata", "lat", "lng", "type")),
    "kiwisdr": Sagoma(tieni=("name", "location", "bands", "users", "users_max", "lat", "lon", "url")),
    "sigint": Sagoma(
        tieni=("callsign", "station_type", "comment", "source", "lat", "lng",
               "altitude_ft", "confidence", "status", "timestamp"),
        tronca={"comment": 160, "raw_message": 160},
    ),
}

# Ordine predefinito quando la sagoma non ne dichiara uno: si prova in questa
# sequenza il primo campo presente.
_ORDINE_DI_RIPIEGO = ("num_articles", "score", "risk_score", "oracle_score",
                      "mag", "frp", "severity", "count")

# `severity` e' testuale in alcuni layer: va reso ordinabile.
_PESO_GRAVITA = {"extreme": 4, "severe": 3, "high": 3, "moderate": 2,
                 "medium": 2, "minor": 1, "low": 1, "unknown": 0}


def chiave_ordinamento(elemento: Dict[str, Any], campo: str) -> float:
    v = elemento.get(campo)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return float(_PESO_GRAVITA.get(v.strip().lower(), 0))
    return 0.0


def sagoma_di(layer: str) -> Sagoma:
    return SAGOME.get(layer, Sagoma())


def comprimi(layer: str, elementi: List[Dict[str, Any]],
             massimo: Optional[int] = None) -> List[Dict[str, Any]]:
    """Riduce e ordina una lista di elementi di un layer.

    Ordina **prima** di tagliare: tagliare per primi significherebbe tenere i
    primi N per ordine di arrivo invece dei piu' importanti.
    """
    if not elementi:
        return []
    s = sagoma_di(layer)
    campo = s.ordina_per
    if not campo and elementi:
        campione = elementi[0]
        campo = next((c for c in _ORDINE_DI_RIPIEGO if c in campione), None)
    ordinati = list(elementi)
    if campo:
        ordinati.sort(key=lambda e: chiave_ordinamento(e, campo), reverse=True)
    if massimo is not None:
        ordinati = ordinati[:massimo]
    return [s.applica(e) for e in ordinati]
