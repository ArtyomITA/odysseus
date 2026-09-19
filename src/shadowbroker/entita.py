"""Schede delle entita': composizione annidata dei comandi di ShadowBroker.

Sondando tutti e 62 i comandi e' emerso che tre di loro sono molto piu' ricchi
di quanto sembrasse, e vanno **composti**, non sostituiti:

`get_entity_profile` (1.182 token) restituisce una scheda gia' articolata:

    identity         116 tok   sigla, matricola, icao24, proprietario, tag  <- il meglio
    position          29 tok   posizione, quota, velocita', rotta
    movement          93 tok   primo/ultimo punto, durata, numero di rilevazioni
    aircraft_state     5 tok   in circuito di attesa si/no
    notes             71 tok   avvertenze oneste, gia' in inglese leggibile
    related_news      14 tok   notizie collegate
    nearby_context     1 tok   cosa c'e' intorno
    trail            355 tok   le briciole grezze     <- ridondante, `movement` le riassume
    lookup           432 tok   i risultati di ricerca <- ridondante, `identity` e' il distillato
    recommended_next  74 tok   quale comando chiamare dopo <- serve a NOI, non al modello

Tenendo solo la parte utile si passa da 1.182 a ~350 token senza perdere niente
di sostanziale.

`correlate_entity` (1.690 token) aggiunge il contesto:

    claim_level    "evidence_pack_not_verdict"  <- loro stessi dicono che non e' un verdetto
    signals         86 tok   inferenze GIA' VALUTATE, con confidenza e motivo in chiaro
    evidence     1.465 tok   le entita' vicine, grezze  <- si riassume

`signals` e' il pezzo prezioso: *"10 other live tracked entities within 300 km"*,
confidenza 0.5. E' un giudizio gia' formato, non righe da interpretare.

`entity_expand` (273 token) collega un'entita' a sanzioni OFAC e voci Wikidata.

Da cui la composizione: una domanda su un'entita' fa **una** chiamata di base e
ne aggiunge altre solo se servono, e il modello riceve la sintesi delle tre.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.shadowbroker.client import get_client

logger = logging.getLogger(__name__)

# Sezioni della scheda da consegnare al modello. Le altre sono ridondanti
# rispetto a queste (vedi il modulo docstring), non meno importanti.
_SEZIONI_UTILI = ("status", "entity_kind", "identity", "position", "movement",
                  "aircraft_state", "route", "notes", "related_news", "nearby_context")


def _pulisci(d: Any) -> Any:
    """Toglie i vuoti a ogni livello: su una scheda sono ~80 token di nulla."""
    if isinstance(d, dict):
        fuori = {}
        for k, v in d.items():
            v2 = _pulisci(v)
            if v2 not in (None, "", [], {}):
                fuori[k] = v2
        return fuori
    if isinstance(d, list):
        return [_pulisci(x) for x in d if _pulisci(x) not in (None, "", [], {})]
    return d


def scheda(query: str, con_contesto: bool = False,
           con_relazioni: bool = False, raggio_km: float = 300) -> Dict[str, Any]:
    """La scheda di un'entita': aereo, nave, persona, societa'.

    `con_contesto` aggiunge le inferenze di `correlate_entity` (cosa c'e'
    intorno e con che confidenza). `con_relazioni` aggiunge il grafo con le
    sanzioni OFAC. Entrambi costano una chiamata in piu': si accendono solo
    quando la domanda li richiede davvero.
    """
    client = get_client()
    fuori: Dict[str, Any] = {"cercato": query}

    # 1. La scheda di base. Un solo comando che gia' contiene identita',
    #    posizione, movimento e notizie collegate.
    try:
        p = client.comando("get_entity_profile", {"query": query, "compact": True}, timeout=45)
    except Exception as e:
        p = None
        fuori["scheda_non_disponibile"] = str(e)[:150]

    if isinstance(p, dict):
        for sez in _SEZIONI_UTILI:
            v = _pulisci(p.get(sez))
            if v in (None, "", [], {}):
                continue
            if sez == "related_news":
                # Arriva come {results, version, truncated}: senza `results` e'
                # solo involucro, e il modello lo leggerebbe come "ci sono
                # notizie collegate".
                risultati = v.get("results") if isinstance(v, dict) else None
                if not risultati:
                    continue
                v = risultati[:4]
            if sez == "movement" and isinstance(v, dict):
                # I timestamp assoluti e i due angoli non servono a rispondere:
                # bastano da quanto e' osservato e quanti rilevamenti.
                v = {k: x for k, x in v.items()
                     if k in ("point_count", "duration_minutes", "bearing_deg")}
            fuori[sez] = v
        # `movement` riassume la scia: si aggiunge solo il verso, che e' la cosa
        # che un umano chiede subito dopo "dov'e'".
        mov_grezzo = p.get("movement") or {}
        primo, ultimo = mov_grezzo.get("first_point"), mov_grezzo.get("last_point")
        if isinstance(primo, dict) and isinstance(ultimo, dict):
            try:
                import math
                dlat = ultimo["lat"] - primo["lat"]
                dlng = ultimo["lng"] - primo["lng"]
                if abs(dlat) > 1e-6 or abs(dlng) > 1e-6:
                    ang = (math.degrees(math.atan2(dlng, dlat)) + 360) % 360
                    rose = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ovest", "ovest", "nord-ovest"]
                    fuori.setdefault("movement", {})["verso"] = rose[int((ang + 22.5) % 360 // 45)]
            except Exception:
                pass
        # Se non e' stata trovata nessuna entita', si ripiega sulla ricerca
        # per sigla — `get_entity_profile` e' esatto, `find_flights` e' fuzzy.
        if not fuori.get("identity"):
            for cmd in ("find_flights", "find_ships"):
                try:
                    r = client.comando(cmd, {"query": query, "compact": True}, timeout=25)
                    risultati = (r or {}).get("results") or []
                    if risultati:
                        fuori["candidati"] = risultati[:6]
                        fuori["nota_candidati"] = (
                            "nessuna corrispondenza esatta: questi sono i piu' simili, "
                            "vanno proposti come ipotesi"
                        )
                        break
                except Exception:
                    continue

    # 2. Contesto: cosa c'e' intorno, gia' valutato da loro.
    if con_contesto:
        try:
            c = client.comando("correlate_entity",
                               {"query": query, "radius_km": raggio_km, "compact": True},
                               timeout=45)
        except Exception as e:
            c = None
            fuori["contesto_non_disponibile"] = str(e)[:120]
        if isinstance(c, dict):
            ctx: Dict[str, Any] = {}
            # `signals` sono inferenze gia' pronte, con confidenza e motivo.
            segnali = c.get("signals") or []
            if segnali:
                ctx["segnali"] = [{
                    "cosa": s.get("type"),
                    "confidenza": s.get("confidence"),
                    "perche": s.get("reason"),
                    "da": s.get("evidence_layers"),
                } for s in segnali]
            # `evidence` pesa 1.465 token grezzi: si tengono i piu' vicini.
            ev = c.get("evidence") or {}
            vicine = ev.get("proximate_entities") or []
            if vicine:
                vicine = sorted(vicine, key=lambda x: x.get("distance_km") or 9e9)[:6]
                ctx["entita_vicine"] = [{
                    "chi": v.get("label"), "cosa": v.get("type"),
                    "km": round(v.get("distance_km") or 0, 1), "layer": v.get("source_layer"),
                } for v in vicine]
                ctx["entita_vicine_totali"] = len(ev.get("proximate_entities") or [])
            eventi = ev.get("proximate_events") or ev.get("nearby_events") or []
            if eventi:
                ctx["eventi_vicini"] = eventi[:4]
            # ShadowBroker stesso marca questa risposta come non conclusiva:
            # va riportato, altrimenti il modello la presenta come un fatto.
            if c.get("claim_level"):
                ctx["livello_di_certezza"] = c["claim_level"]
                ctx["avvertenza"] = (
                    "co-locazione = indizio, non prova di intenzione o causa"
                )
            if ctx:
                fuori["contesto"] = ctx

    # 3. Relazioni: sanzioni OFAC, collegamenti Wikidata.
    if con_relazioni:
        tipo = (fuori.get("entity_kind")
                or ("aircraft" if fuori.get("identity", {}).get("icao24") else "country"))
        try:
            g = client.comando("entity_expand",
                               {"entity_type": tipo, "query": query}, timeout=45)
        except Exception as e:
            g = None
            fuori["relazioni_non_disponibili"] = str(e)[:120]
        if isinstance(g, dict):
            nodi = g.get("nodes") or []
            sanzioni = [n for n in nodi if n.get("type") == "sanction"]
            altri = [n for n in nodi if n.get("type") != "sanction"]
            rel: Dict[str, Any] = {}
            if sanzioni:
                rel["sanzioni_ofac"] = [{
                    "chi": s.get("label"),
                    "programmi": (s.get("properties") or {}).get("programs"),
                } for s in sanzioni[:8]]
                rel["sanzioni_totali"] = len(sanzioni)
            if altri:
                rel["collegamenti"] = [{"chi": n.get("label"), "cosa": n.get("type")}
                                       for n in altri[:8]]
            if rel:
                fuori["relazioni"] = rel

    return fuori
