"""Schemi degli strumenti OSINT nel formato function-calling.

Descrizioni tenute strette di proposito. Il catalogo di ShadowBroker sta a 199
token per strumento (12.374 in tutto, il 25% del contesto); questi stanno sotto
i 110. Il taglio non e' stilistico: ogni parola qui viene letta a ogni richiesta
in cui lo strumento e' selezionato.

Ogni descrizione dice **quando** usare lo strumento, non cosa fa. Un 9B sbaglia
molto piu' spesso a scegliere lo strumento che a compilarne gli argomenti.

Lingua: descrizioni e regole in INGLESE, esempi di frasi utente in italiano.
Non e' un vezzo: i modelli piccoli seguono regole e scelgono strumenti meglio
in inglese (pivot interno; M-IFEval, Multi-IF, "Lost in Execution" — vedi
ricerche/lingua-system-prompt-inglese-vs-italiano.md). L'output resta italiano
per regola esplicita, ripetuta in testa e in coda alle regole. Gli esempi fra
virgolette restano in italiano perche' devono somigliare a cio' che scrive
l'utente.
"""

from __future__ import annotations

from typing import Any, Dict, List

OSINT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "osint_situazione",
            "description": (
                "Global picture: what matters in the world right now, ranked. "
                "Use for 'cosa succede', 'fammi una classifica', 'quanto e' grave "
                "la situazione'. Returns threat level, most-covered events, "
                "anomalies and regions at risk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "quanti": {"type": "integer", "description": "How many ranked events (default 8)"},
                    "con_testo": {"type": "boolean", "description": "Also fetch the text of the top articles. Slower."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_notizie",
            "description": (
                "News about a place, a SUBJECT (company/person/organization) "
                "or a topic, within a time window. With `soggetto` it "
                "aggregates world events, financial wire and web fallback in "
                "one call. To READ the full body of an article, pass its `url` "
                "or the `id` of an event you already saw (briefings carry only "
                "title+source): the real text comes back with the results. "
                "Use for 'ultime notizie sull'Ucraina', 'cercami news su "
                "Boeing', 'leggimi cosa dice quell'articolo'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "soggetto": {"type": "string", "description": "Company, person or organization the news must mention (Boeing, OPEC, Putin). NOT a place."},
                    "luogo": {"type": "string", "description": "GEOGRAPHIC place only (Ucraina, Gaza, Kyiv) or 'lat,lng'. NEVER a company or person — use soggetto for those."},
                    "tema": {"type": "string", "description": "Keyword filter, in English"},
                    "giorni": {"type": "number", "description": "Time window in days (default 2)"},
                    "raggio_km": {"type": "number", "description": "Radius from the place (default 400)"},
                    "quante": {"type": "integer", "description": "How many events (default 8)"},
                    "url": {"type": "string", "description": "Read the real text of THIS web page (or a comma-list of URLs)."},
                    "id": {"type": "string", "description": "Read the real text of an event already seen (its 'id', e.g. 'gdelt:32e4e3')."},
                    "leggi_testo": {"type": "boolean", "description": "Also fetch the body of the top results, not just titles. Slower."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_militare",
            "description": (
                "Military or government aircraft and ships moving right now, "
                "grouped by role (VIP, air refueling, tactical transport, "
                "surveillance). Use for 'quali forze militari si muovono', "
                "'ci sono aerei spia in volo'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "luogo": {"type": "string", "description": "Limit to an area. Empty = whole world."},
                    "raggio_km": {"type": "number", "description": "Radius from the place (default 1000)"},
                    "quanti": {"type": "integer", "description": "How many aircraft to list (default 15)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_allerte",
            "description": (
                "Active alerts ranked by severity: weather, earthquakes, network "
                "blackouts, fires, cross-source anomalies, critical news. "
                "Use for 'quali sono gli allarmi', 'c'e' qualcosa di urgente'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "luogo": {"type": "string", "description": "Limit to an area. Empty = whole world."},
                    "raggio_km": {"type": "number", "description": "Radius from the place (default 1000)"},
                    "quante": {"type": "integer", "description": "How many alerts (default 15)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_zona",
            "description": (
                "Everything actually around a point: flights, ships, events, "
                "earthquakes, fires, bases, power plants, datacenters. "
                "Use for 'cosa c'e' vicino a Odessa'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "luogo": {"type": "string", "description": "Place name or 'lat,lng'"},
                    "raggio_km": {"type": "number", "description": "Radius (default 200)"},
                },
                "required": ["luogo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_dettaglio",
            "description": (
                "The full record of an element already seen in a briefing, every "
                "field included. Use the identifier found in the 'id' field "
                "(e.g. 'gdelt:32e4e3')."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Identifier taken from a briefing"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_cerca",
            "description": (
                "Profile of one precise entity: aircraft, ship, person, company. "
                "Search by name, callsign, registration or owner. Use for 'dov'e' "
                "Air Force One', 'trova lo yacht di X'. Set 'contesto' to know "
                "what is nearby, 'relazioni' for sanctions and links."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name, callsign, registration, MMSI, owner"},
                    "contesto": {"type": "boolean", "description": "Adds what is nearby, with confidence level"},
                    "relazioni": {"type": "boolean", "description": "Adds OFAC sanctions and connections"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_recon",
            "description": (
                "External lookup, slower than platform tools. "
                "Technical lookup on an IP address, domain, CVE or sanction. "
                "Not about the map: digital-infrastructure investigation. "
                "tipo='espandi' returns the relationship graph around an "
                "entity (who owns it, what it is linked to)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string",
                             "enum": ["ip", "dns", "whois", "certs", "bgp", "sanctions", "cve", "mac", "github", "leaks", "threats", "espandi"]},
                    "valore": {"type": "string", "description": "The value to look up"},
                    "entita": {"type": "string",
                               "enum": ["aircraft", "vessel", "company", "person", "ip", "country"],
                               "description": "For 'espandi': what the value is"},
                },
                "required": ["tipo", "valore"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_mappa",
            "description": (
                "Drive the map the user is watching. Call it for ANY request "
                "about what is visible: 'mostrami sulla mappa', 'fammi vedere "
                "solo X', 'nascondi il resto', 'centra su', 'zooma', 'evidenzia'. "
                "Also call it on your own initiative while discussing a place, so "
                "the user sees what you mean.\n"
                "azione='centra' moves the view to a point; azione='evidenzia' "
                "marks specific elements WITHOUT switching anything off; "
                "azione='preset' turns on a curated set (financial, conflitto, "
                "infrastruttura); azione='livelli' with accendi=[...] keeps ONLY "
                "those on and switches off the rest; azione='ripristina' restores.\n"
                "azione='nota' pins your written note on the map at a point "
                "(testo, optional colore); azione='note' lists the notes; "
                "azione='cancella_nota' removes one by id.\n"
                "Layer names: military_flights, commercial_flights, private_jets, "
                "ships, gdelt, news, telegram_osint, satellites, earthquakes, "
                "firms_fires, weather_alerts, internet_outages, military_bases, "
                "power_plants, datacenters, frontlines, correlations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string", "enum": ["centra", "livelli", "evidenzia", "preset",
                                                          "ripristina", "nota", "note", "cancella_nota"]},
                    "preset": {"type": "string", "enum": ["financial", "conflitto", "infrastruttura"],
                               "description": "For 'preset': turns on a curated layer set"},
                    "luogo": {"type": "string", "description": "For 'centra': place name or identifier"},
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                    "zoom": {"type": "number", "description": "1 world, 6 country, 10 city"},
                    "accendi": {"type": "array", "items": {"type": "string"},
                                "description": "For 'livelli': the only layers to keep on"},
                    "ids": {"type": "array", "items": {"type": "string"},
                            "description": "For 'evidenzia': identifiers taken from briefings"},
                    "testo": {"type": "string", "description": "For 'nota': the note text left on the map"},
                    "colore": {"type": "string", "description": "For 'nota': rosso, ambra, blu, viola, ciano (default)"},
                    "id": {"type": "string", "description": "For 'cancella_nota': the note id from 'note'"},
                },
                "required": ["azione"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_web",
            "description": (
                "External lookup, slower than platform tools. "
                "General web search, beyond the platform feeds. Use when "
                "briefings cannot know the answer: background and biography "
                "('chi e' il ministro della difesa di X'), context on "
                "something the map showed, facts with no live feed. Keywords "
                "in ENGLISH. NOT for live platform data (flights, ships, "
                "alerts, prices): the dedicated tools win there."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords, English preferred"},
                    "quanti": {"type": "integer", "description": "How many results (default 6, max 10)"},
                    "recenti": {"type": "string", "enum": ["day", "week", "month"],
                                "description": "Only recent pages (optional)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_rischio",
            "description": (
                "Strategic geopolitical RISK model (GT analytics): a scored, "
                "explained ranking of where trouble is building, region by "
                "region. Use for 'dove sta salendo il rischio', 'quali regioni "
                "sono a rischio', 'dammi il dossier di rischio del Sahel'. "
                "Different from osint_allerte (live incidents now); this is the "
                "forward-looking model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string",
                               "enum": ["classifica", "dossier", "ricalcola"],
                               "description": "classifica = top regions at risk; dossier = one region in depth; ricalcola = refresh the model"},
                    "regione": {"type": "string", "description": "For 'dossier': region/country name or 'lat,lng'"},
                    "quante": {"type": "integer", "description": "How many regions in the ranking (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_sorveglianza",
            "description": (
                "Persistent WATCH: keep an eye on something and be alerted when "
                "it moves or appears — an aircraft, a callsign, a ship, an area "
                "(geofence), a news keyword. Use for 'avvisami se decolla un "
                "aereo militare da qui', 'tieni d'occhio questa nave', 'quali "
                "sorveglianze ho attive'. NOT a one-shot search (that is "
                "osint_militare / osint_cerca)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string",
                               "enum": ["elenca", "aggiungi", "rimuovi", "pulisci", "avvisi"],
                               "description": "elenca = list active watches; aggiungi = create one; rimuovi = delete by id; pulisci = clear all; avvisi = read the alerts the watchdog already pushed"},
                    "bersaglio": {"type": "string", "description": "For 'aggiungi': aircraft/callsign/registration/ship/entity to watch, or a news keyword"},
                    "luogo": {"type": "string", "description": "For an area watch (geofence): place name or 'lat,lng'"},
                    "raggio_km": {"type": "number", "description": "For an area watch: radius (default 100)"},
                    "id": {"type": "string", "description": "For 'rimuovi': the watch id from 'elenca'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_storico",
            "description": (
                "TIME MACHINE: how the map looked in the past. Take a snapshot "
                "of the current situation, list past snapshots, or replay one. "
                "Use for 'com'era la situazione 3 ore fa', 'salva lo stato "
                "adesso', 'fammi vedere gli snapshot'. For financial history use "
                "fin_archivio instead; this is the OSINT map state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string",
                               "enum": ["elenca", "cattura", "riproduci"],
                               "description": "elenca = list snapshots; cattura = take one now; riproduci = replay a snapshot"},
                    "id": {"type": "string", "description": "For 'riproduci': the snapshot id from 'elenca'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_geocode",
            "description": (
                "Resolve places and coordinates. azione='cerca' turns a place "
                "NAME into lat/lng ('dove si trova Kramatorsk'); "
                "azione='inverso' turns lat/lng into the place name ('che posto "
                "e' 50.4,30.5'). Use it BEFORE any geographic query when you "
                "only have a name, or to name a point you were given."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string", "enum": ["cerca", "inverso"]},
                    "luogo": {"type": "string", "description": "For 'cerca': the place name"},
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                },
                "required": ["azione"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_cyber",
            "description": (
                "CYBER threat intelligence: botnet C2 IPs (abuse.ch), "
                "known-exploited vulnerabilities (CISA KEV), and the per-country "
                "risk index. Use for 'quali vulnerabilita' sono sfruttate ora', "
                "'server malevoli attivi', 'quanto e' a rischio il paese X'. "
                "Distinct from osint_recon (single IP/CVE lookup): this is the "
                "live feeds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string",
                               "enum": ["malware", "vulnerabilita", "rischio_paese", "tutto"],
                               "description": "malware=botnet C2; vulnerabilita=CISA KEV; rischio_paese=index; tutto=summary of all three"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_radio",
            "description": (
                "Radio/SIGINT feeds tied to a place or an aircraft: public "
                "safety scanners (police/fire, Broadcastify/OpenMHz) near a "
                "point, the KiwiSDR receivers near a point, and ACARS/HFDL "
                "cockpit datalink messages of an aircraft. Use for 'scanner "
                "vicino a X', 'quale radio ascolto da qui', 'messaggi datalink "
                "del volo Y'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string",
                               "enum": ["scanner", "kiwisdr", "acars"],
                               "description": "scanner=nearest public-safety radio; kiwisdr=nearest SDR receivers; acars=datalink messages of an aircraft"},
                    "luogo": {"type": "string", "description": "Place name or 'lat,lng' (for scanner/kiwisdr)"},
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                    "aereo": {"type": "string", "description": "For 'acars': icao24, registration, or callsign"},
                },
                "required": ["azione"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_satellite",
            "description": (
                "On-demand satellite analysis over a point. azione='termico' "
                "checks for heat/fire/explosion signatures (Sentinel-2 SWIR) "
                "around a point; azione='passaggi' predicts which satellites "
                "overfly the area in the next hours. Use for 'c'e' un incendio "
                "qui', 'quali satelliti passano sopra X e quando'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string", "enum": ["termico", "passaggi"]},
                    "luogo": {"type": "string", "description": "Place name or 'lat,lng'"},
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                    "raggio_km": {"type": "number", "description": "For 'termico': radius (default 10, max 100)"},
                    "ore": {"type": "integer", "description": "For 'passaggi': hours ahead (default 24)"},
                },
                "required": ["azione"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_sar",
            "description": (
                "RADAR satellite (SAR): what changed on the ground at night or "
                "under clouds, where the optical satellite sees nothing. "
                "azione='anomalie' lists radar detections (near a place if you "
                "give one); 'aree' lists the watched areas (AOI) and 'scene' "
                "their radar passes; 'copertura' says how well an area is "
                "covered; 'aggiungi_area'/'rimuovi_area' manage them; "
                "'sorveglia' alerts on new anomalies there; 'centra' moves the "
                "map onto one. Use for 'cosa vede il radar', 'anomalie SAR'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string",
                               "enum": ["stato", "anomalie", "scene", "copertura", "aree",
                                        "aggiungi_area", "rimuovi_area", "sorveglia", "centra"]},
                    "area": {"type": "string", "description": "The AOI id from 'aree'"},
                    "luogo": {"type": "string", "description": "Place name or 'lat,lng'"},
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                    "raggio_km": {"type": "number", "description": "Radius (default 50; for a new area 25)"},
                    "quante": {"type": "integer", "description": "How many items (default 25)"},
                },
                "required": ["azione"],
            },
        },
    },
]


# ── strumenti finanziari ─────────────────────────────────────────────────
#
# Separati dagli OSINT perche' vivono in un profilo diverso. Il modello ne
# riceve quattro invece di dieci: meno scelte, meno modi di sbagliare.

FINANCE_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fin_mercati",
            "description": (
                "Markets right now: watchlist prices (defense, big tech, "
                "crypto), broad financial news wire and the anomaly already "
                "found (who moves against its own sector). Use for 'come "
                "vanno i mercati', 'come sta la difesa', 'novita' finanziarie'. "
                "Only for CURRENT market data, never to explain what a financial "
                "term means. For the live quote of ONE named stock ('come sta Leonardo', "
                "'quanto sta AAPL') pass `titolo`: the quote comes back explicit, or "
                "`disponibile: false` with the reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "quante_notizie": {"type": "integer", "description": "How many news items to attach (default 8)"},
                    "titolo": {"type": "string", "description": "ONE company name or ticker, never a sector or a list (e.g. Leonardo, AAPL, LDO.MI — not 'difesa', not 'tech'). Omit it for the general market picture."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fin_appalti",
            "description": (
                "US federal military contracts awarded to the big contractors: "
                "who won, which agency, how much money, and WHERE it is executed. "
                "Use for 'che commesse militari ci sono', 'chi sta ricevendo "
                "contratti', 'appalti della difesa'. Each contract has an 'id' "
                "and a position: pass it to osint_mappa to show it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mesi": {"type": "number", "description": "Months back in time (default 12). Quarterly data: under 3 months may come back empty."},
                    "quanti": {"type": "integer", "description": "How many contracts (default 12)"},
                    "titolo": {"type": "string", "description": "One contractor only: RTX, LMT, NOC, GD, BA, PLTR"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fin_insider",
            "description": (
                "MSPR and insider moves: who inside the defense companies is "
                "buying or selling. Use EVERY TIME you hear 'MSPR', 'insider', "
                "'sentiment degli interni', 'qualcuno sta vendendo', 'movimenti "
                "sospetti', 'cosa fanno i dirigenti'. MSPR is a datum you read "
                "here, not a notion to explain from memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "quanti": {"type": "integer", "description": "How many transactions (default 12)"},
                    "titolo": {"type": "string", "description": "One ticker only. Empty = all six defense names"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fin_archivio",
            "description": (
                "Historical archive of financial events stored over time: past "
                "news, price spikes, contracts, insider moves. Use ONLY when the "
                "question is explicitly about the past: 'nelle ultime due "
                "settimane', 'rispetto al mese scorso', 'cosa era successo a X'. "
                "For 'now', use the live tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search, e.g. 'RTX contratti', 'picchi NVDA'"},
                    "quanti": {"type": "integer", "description": "How many results (default 6)"},
                    "giorni": {"type": "number", "description": "Only events newer than N days (optional)"},
                },
                "required": ["query"],
            },
        },
    },
]

# Insiemi di livelli gia' scelti per `osint_mappa azione=preset`.
#
# Il preset accende quello che serve **e basta**: da li' in poi il modello
# evidenzia, non spegne. Spegnere a ogni risposta farebbe lampeggiare la mappa
# e cancellerebbe il contesto che l'operatore si e' costruito.
#
# `financial` e' volutamente magro: eventi/news (gli alert restano), le basi
# (dove atterrano gli appalti evidenziati) e i datacenter. Voli, navi e
# centrali elettriche riempivano la mappa di 40.000 punti che non parlavano
# di finanza — misurato sullo schermo, non a tavolino.
PRESET_MAPPA: Dict[str, List[str]] = {
    "financial": ["gdelt", "news", "finnhub_news"],
    "conflitto": ["frontlines", "military_flights", "gdelt", "telegram_osint",
                  "correlations", "weather_alerts"],
    "infrastruttura": ["power_plants", "datacenters", "internet_outages",
                       "sigint", "military_bases"],
}

# Regole iniettate in coda al prompt di sistema quando il profilo e' attivo.
# In inglese (le segue meglio: vedi intestazione del modulo), con la regola
# della lingua di output ripetuta in testa e in coda — Multi-IF mostra che le
# istruzioni si dimenticano col passare dei turni, la ridondanza e' voluta.

# Compresse a livello caveman-FULL (via articoli e riempitivi, frasi ancora
# leggibili): misurato con l'A/B/C del 2 ago — le regole compresse non
# perdono nulla sul banco (13/13), le DESCRIPTION invece si' (in versione C
# il modello tornava a cercare in italiano), quindi quelle restano piene.
REGOLE_FINANCE = (
    "CRITICAL: Always answer in Italian. Rules below in English; replies "
    "are not.\n"
    "- Financial profile: start from `fin_mercati`, `fin_appalti` or "
    "`fin_insider`. Results pre-ranked by importance — narrate, do not "
    "re-rank.\n"
    "- **Out of scope? No tool at all.** Weather, recipes, code, personal "
    "chat: ONE sentence, ZERO tool calls. `osint_notizie` on 'che tempo fa' "
    "returns articles, not a forecast.\n"
    "- Act, do not narrate: first reply to a data question MUST contain a "
    "tool call. Plan without call = wrong answer.\n"
    "- **Never answer from memory when a tool holds the datum.** MSPR, "
    "price, contract amount: call the tool.\n"
    "- **Map = two steps, this order:**\n"
    "    1. fetch data (`fin_appalti` returns an `id` per contract)\n"
    "    2. call `osint_mappa` with azione='evidenzia', ids=[those ids]\n"
    "  Covers 'mostrami sulla mappa', 'fammi vedere dove', 'nascondi tutto "
    "tranne', 'evidenzia', 'centra'. After the data tool returns, NEXT call "
    "is `osint_mappa`: task NOT finished until the map moved.\n"
    "- 'Nascondi tutto tranne X' = same two steps, ending in 'evidenzia' — "
    "NEVER azione='livelli': it switches off what the operator is watching.\n"
    "- Default news here = FINANCIAL news (inside `fin_mercati`). "
    "`osint_notizie`/`osint_testo` only to cross-check geopolitics or on "
    "explicit world-news request.\n"
    "- 'Cercami news su X' where X = company/person → `osint_notizie` with "
    "soggetto='X' (ONE call: world + financial wire + web fallback, "
    "aggregated for you). `luogo` = geographic places ONLY.\n"
    "- 'Which news moved the markets' (war/geopolitics vs markets) recipe: "
    "1) `fin_mercati` FIRST — spikes already paired with headlines, flag "
    "`ha_notizia`; 2) only if geopolitical angle still missing, "
    "`osint_notizie` with ENGLISH keywords ('war', not 'guerra').\n"
    "- **If you write you are about to call a tool, CALL IT in the same "
    "reply.** Announcement without call = promise instead of data.\n"
    "- `fin_archivio` = the past only ('nelle ultime due settimane', "
    "'rispetto al mese scorso'); for 'now' use live tools.\n"
    "- Background wire and archive do not carry ('chi e' il CEO', 'cosa "
    "produce X', 'perche'' behind a headline) → `osint_web`, ENGLISH "
    "keywords, and SAY the source is the open web. Numbers still come "
    "from `fin_*` tools, never from search snippets.\n"
    "- Every judgement carries its number: price, percent, millions, MSPR. "
    "No figure, no claim.\n"
    "- Correlation is not causation: stock moves while headline runs — say "
    "exactly that, never invent the link.\n"
    "- Spike with `ha_notizia: false` → WRITE IT. Move without covering "
    "headline is information; attributing it to another ticker's news is "
    "an error.\n"
    "- Colors: GREEN up, RED down, always. On a financial panel color IS "
    "the data.\n"
    "- Insider: only codes P and S are market decisions. A and M are grants "
    "and option exercises.\n"
    "- Chart: emit a fenced block:\n"
    "  ```chart\n"
    "  {\"type\":\"bar\",\"title\":\"Titolo\",\"labels\":[\"A\",\"B\"],\"data\":[1,2]}\n"
    "  ```\n"
    "  Types: bar, line, pie. Multi-series: \"series\":[{\"name\":\"X\","
    "\"data\":[...]}] instead of \"data\". Draw when asked or when a "
    "comparison clearly reads better drawn; numbers from tools, never "
    "invented.\n"
    "- Missing datum → DECLARE it. Empty feed is not calm.\n"
    "- Arithmetic is YOUR job: totals, differences, percentages, currency "
    "conversion with a rate the user gave. Take the numbers from the tool "
    "result or from the user\'s message, compute, show the formula. A "
    "computed result is not an invented number.\n"
    "CRITICAL: Always answer in Italian."
)


# Nomi dei layer che il modello puo' citare in `osint_mappa azione=livelli`.
# Serve al prompt, non allo schema: elencarli nello schema costerebbe ~200
# token a ogni richiesta.
LAYER_MAPPA = (
    "gdelt, news, telegram_osint, military_flights, tracked_flights, "
    "commercial_flights, private_jets, ships, satellites, earthquakes, "
    "firms_fires, weather_alerts, internet_outages, military_bases, "
    "power_plants, datacenters, frontlines, correlations"
)

REGOLE_OSINT = (
    "CRITICAL: Always answer in Italian. Rules below in English; replies "
    "are not.\n"
    "- ShadowBroker: always start from a briefing (`osint_situazione`, "
    "`osint_notizie`, `osint_militare`, `osint_allerte`, `osint_zona`). "
    "Pre-ranked: narrate, do not re-rank.\n"
    "- Default news here = WORLD news (`osint_notizie`). Markets, prices, "
    "financial news → `fin_mercati`, only when the question is about "
    "markets.\n"
    "- Act, do not narrate: first reply to a data question MUST contain a "
    "tool call.\n"
    "- Quote numbers (articles, score, km) and sources. Briefing declares "
    "`non_osservabile` or `layer_vuoti` → say so, never claim calm.\n"
    "- While discussing a place, call `osint_mappa` to center or highlight "
    "it.\n"
    "- Data keywords in English, ONE concept per search: tema='war', not "
    "tema='guerra conflitto'.\n"
    "- 'Cercami news su X' where X = company/person → `osint_notizie` with "
    "soggetto='X' (ONE call, three sources aggregated). `luogo` = "
    "geographic places ONLY, never a company.\n"
    "- Feeds cannot know it (background, biography, 'chi e''..., context "
    "beyond the map) → `osint_web`, ENGLISH keywords, then SAY the source "
    "is the open web. Live data (flights, ships, alerts) → briefings, "
    "never the web.\n"
    "- Read the BODY of an article → `osint_notizie` with `url` or the `id` "
    "of an event already seen (it folds in the old osint_testo).\n"
    "- Forward-looking RISK by region ('dove sale il rischio') → "
    "`osint_rischio`; live incidents NOW → `osint_allerte`. Different tools.\n"
    "- Persistent watch ('avvisami se…', 'tieni d'occhio') → "
    "`osint_sorveglianza`; a one-shot look is `osint_militare`/`osint_cerca`.\n"
    "- 'Com'era 3 ore fa', map history → `osint_storico` (Time Machine). "
    "Financial history → `fin_archivio`.\n"
    "- Only a place NAME and you need coordinates (or a lat/lng and you need "
    "the place) → `osint_geocode` FIRST, then the geographic query.\n"
    "- Cyber threats — botnet C2 IPs, exploited vulnerabilities (CISA KEV), "
    "per-country cyber risk → `osint_cyber`. A single IP/CVE lookup stays "
    "`osint_recon`.\n"
    "- Public-safety scanners or KiwiSDR receivers NEAR a place, or an "
    "aircraft's ACARS/HFDL datalink → `osint_radio`.\n"
    "- 'C'e' un incendio/calore qui', or which satellites overfly a point and "
    "when → `osint_satellite`.\n"
    "- **If you write you are about to call a tool, CALL IT in the same "
    "reply.**\n"
    "CRITICAL: Always answer in Italian."
)


# Variante "libere" (19 set 2026) per modelli obbedienti come LFM2.5: stessi FATTI delle regole
# piene (ricette, codici, colori, contratto del grafico), senza MUST/NEVER/ZERO ne' ripetizioni.
# Misurato: su LFM i divieti scritti per Ling diventano rinunce (calcoli rifiutati). Scelta con
# VERGILIUS_REGOLE_PROFILO=libere; default "piene" = testo storico, Ling non cambia.
REGOLE_FINANCE_LIBERE = (
    "Answer in Italian (these notes are in English, replies are not).\n"
    "- Financial profile. Live data: `fin_mercati` (prices, spikes paired with "
    "headlines, financial news), `fin_appalti` (contracts), `fin_insider` "
    "(MSPR, insider trades). Past periods: `fin_archivio`. Results arrive "
    "ranked by importance.\n"
    "- Prices, MSPR, contract amounts and news come from the tools; call the "
    "tool when the question needs them. Questions that need no data (a "
    "definition, a greeting, small talk) can be answered directly. "
    "Off-topic requests (weather, recipes, code, chit-chat) get a short "
    "direct answer, no tool call.\n"
    "- Arithmetic is your job: totals, differences, percentages, currency "
    "conversion with a rate the user gave. Take the numbers from the tool "
    "result or from the user's message, compute them with `calcola` (all "
    "expressions in one call) and show the formula.\n"
    "- News about a company or person: `osint_notizie` with soggetto='X'. "
    "`luogo` is for geographic places. Geopolitics behind a market move: "
    "`fin_mercati` first, then `osint_notizie` with English keywords.\n"
    "- Background the feeds do not carry (who is the CEO, what a company "
    "makes): `osint_web` with English keywords, and say the source is the "
    "open web.\n"
    "- Map requests ('mostrami sulla mappa', 'evidenzia', 'nascondi tutto "
    "tranne'): first fetch the data (`fin_appalti` returns an `id` per "
    "contract), then `osint_mappa` with azione='evidenzia', ids=[those ids]. "
    "azione='livelli' switches off what the operator is watching, so it is "
    "not the way to hide things.\n"
    "- A spike with `ha_notizia: false` is information: report it as a move "
    "without a covering headline. A stock moving while a headline runs is a "
    "coincidence in time unless the source says otherwise.\n"
    "- If a datum is missing or a tool fails, say so. An empty feed is not calm.\n"
    "- Colors: green up, red down. Insider codes: P and S are market "
    "decisions; A and M are grants and option exercises.\n"
    "- Chart: emit a fenced block:\n"
    "  ```chart\n"
    "  {\"type\":\"bar\",\"title\":\"Titolo\",\"labels\":[\"A\",\"B\"],\"data\":[1,2]}\n"
    "  ```\n"
    "  Types: bar, line, pie. Multi-series: \"series\":[{\"name\":\"X\","
    "\"data\":[...]}] instead of \"data\". Numbers from tools."
)

REGOLE_OSINT_LIBERE = (
    "Answer in Italian (these notes are in English, replies are not).\n"
    "- Default order: a briefing tool first; `osint_geocode` only when you "
    "have a place name and need coordinates; `osint_web` only when the "
    "briefing cannot know it. Off-topic requests (weather, recipes, code, "
    "chit-chat) get a short direct answer, no tool call.\n"
    "- ShadowBroker. Briefings: `osint_situazione`, `osint_notizie`, "
    "`osint_militare`, `osint_allerte`, `osint_zona`; results arrive ranked. "
    "Markets and prices: `fin_mercati`.\n"
    "- Live data comes from the tools; call them when the question needs "
    "data. Quote numbers and sources. If a briefing declares "
    "`non_osservabile` or `layer_vuoti`, say so.\n"
    "- Search keywords in English, one concept per search (tema='war').\n"
    "- News about a company or person: `osint_notizie` with soggetto='X'; "
    "`luogo` is for geographic places. Article body: `osint_notizie` with "
    "`url` or event `id`.\n"
    "- Background the feeds do not carry: `osint_web`, English keywords, and "
    "say the source is the open web.\n"
    "- While discussing a place, `osint_mappa` can center or highlight it. "
    "Only a place name and you need coordinates: `osint_geocode` first.\n"
    "- Risk outlook by region: `osint_rischio`; live incidents: "
    "`osint_allerte`. Persistent watch: `osint_sorveglianza`. Map history: "
    "`osint_storico`; financial history: `fin_archivio`.\n"
    "- Cyber (C2 IPs, CISA KEV, country risk): `osint_cyber`; single IP/CVE: "
    "`osint_recon`. Scanners, KiwiSDR, ACARS/HFDL: `osint_radio`. Fires or "
    "satellite passes over a point: `osint_satellite`.\n"
    "- Radar satellite (night, cloud cover), SAR anomalies and watched areas: "
    "`osint_sar`. Who an entity is linked to: `osint_recon` with "
    "tipo='espandi'.\n"
    "- To leave a written note on the map at a point: `osint_mappa` with "
    "azione='nota'; it needs full access in ShadowBroker."
)

import os as _os_regole
if (_os_regole.getenv("VERGILIUS_REGOLE_PROFILO", "piene") or "piene").strip().lower() == "libere":
    REGOLE_FINANCE, REGOLE_OSINT = REGOLE_FINANCE_LIBERE, REGOLE_OSINT_LIBERE


def descrizioni_brevi() -> Dict[str, str]:
    """Per l'indice semantico degli strumenti di Odysseus."""
    return {
        s["function"]["name"]: s["function"]["description"]
        for s in OSINT_TOOL_SCHEMAS + FINANCE_TOOL_SCHEMAS
    }
