"""Catalogo di navigazione degli strumenti, per l'utente nella chat.

Non e' il prompt del modello (quello sono gli schemi in schemi.py). E' la
scheda "cosa posso fare" pensata per una persona: raggruppata per dominio,
in italiano semplice, con domande-esempio invece di firme. Il modello vede
gli schemi; l'utente vede questo.

La verita' di quali strumenti esistono resta negli schemi: qui si aggiunge
solo la presentazione (gruppo, frase, esempi). Se un tool degli schemi non
compare qui, `verifica_copertura()` lo segnala — cosi' la scheda non mente
per omissione.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Gruppi in ordine di presentazione. Ogni tool: frase per l'utente + 1-2
# domande-esempio + se fa cose che SCRIVONO (serve tier full).
_GRUPPI: List[Dict[str, Any]] = [
    {
        "titolo": "Panoramica del mondo",
        "icona": "🌍",
        "tool": [
            {"nome": "osint_situazione", "frase": "Cosa conta adesso, in classifica",
             "esempi": ["cosa succede di importante nel mondo", "quanto è grave la situazione"]},
            {"nome": "osint_allerte", "frase": "Allarmi vivi: meteo, sismi, blackout, incendi",
             "esempi": ["ci sono allarmi urgenti", "che allerte ci sono in Turchia"]},
            {"nome": "osint_rischio", "frase": "Dove il rischio geopolitico sta salendo (modello)",
             "esempi": ["dove sta salendo il rischio", "dammi il dossier di rischio del Sahel"]},
        ],
    },
    {
        "titolo": "Notizie e articoli",
        "icona": "📰",
        "tool": [
            {"nome": "osint_notizie", "frase": "Notizie per luogo, soggetto o tema — e il testo vero di un articolo",
             "esempi": ["ultime notizie sull'Ucraina", "cercami news su Boeing", "leggimi cosa dice quell'articolo"]},
            {"nome": "osint_web", "frase": "Ricerca sul web aperto, quando i feed non sanno",
             "esempi": ["chi è il ministro della difesa della Svezia", "cosa produce questa azienda"]},
        ],
    },
    {
        "titolo": "Cosa si muove",
        "icona": "✈️",
        "tool": [
            {"nome": "osint_militare", "frase": "Aerei e navi militari in movimento adesso",
             "esempi": ["quali forze militari si muovono", "ci sono aerei spia in volo"]},
            {"nome": "osint_zona", "frase": "Tutto quello che c'è intorno a un punto",
             "esempi": ["cosa c'è vicino a Odessa"]},
            {"nome": "osint_cerca", "frase": "Il profilo di una entità precisa (aereo, nave, azienda)",
             "esempi": ["dov'è Air Force One", "trova lo yacht di X"]},
            {"nome": "osint_dettaglio", "frase": "La scheda intera di qualcosa già citato",
             "esempi": ["dammi tutti i dettagli di quell'aereo"]},
        ],
    },
    {
        "titolo": "La mappa",
        "icona": "🗺️",
        "tool": [
            {"nome": "osint_mappa", "frase": "Guida la mappa: centra, evidenzia, accendi livelli, preset",
             "esempi": ["mostrami sulla mappa dov'è", "accendi solo voli militari e navi"],
             "scrive": True},
        ],
    },
    {
        "titolo": "Sorveglianza e storia",
        "icona": "🛰️",
        "tool": [
            {"nome": "osint_sorveglianza", "frase": "Tieni d'occhio qualcosa e fatti avvisare",
             "esempi": ["avvisami se decolla un aereo militare da qui", "tieni d'occhio questa nave"],
             "scrive": True},
            {"nome": "osint_storico", "frase": "Time Machine: com'era la mappa nel passato",
             "esempi": ["com'era la situazione 3 ore fa", "salva lo stato adesso"],
             "scrive": True},
        ],
    },
    {
        "titolo": "Indagine tecnica",
        "icona": "🔎",
        "tool": [
            {"nome": "osint_recon", "frase": "IP, dominio, certificati, CVE, sanzioni",
             "esempi": ["chi c'è dietro questo IP", "dammi i dati di questo CVE"]},
        ],
    },
    {
        "titolo": "Mercati e difesa",
        "icona": "📈",
        "profilo": "Financial",
        "tool": [
            {"nome": "fin_mercati", "frase": "Prezzi difesa/tech/cripto, wire finanziario, anomalia del giorno",
             "esempi": ["come vanno i mercati", "come sta messa la difesa"]},
            {"nome": "fin_appalti", "frase": "Contratti federali di difesa: chi ha vinto, quanto, dove",
             "esempi": ["che commesse militari sono state assegnate"]},
            {"nome": "fin_insider", "frase": "Movimenti insider e indice MSPR",
             "esempi": ["qual è l'MSPR di Palantir", "chi sta vendendo azioni dentro la difesa"]},
            {"nome": "fin_archivio", "frase": "Lo storico finanziario conservato (notizie, picchi, contratti)",
             "esempi": ["cosa è successo a RTX nelle ultime due settimane"]},
        ],
    },
]


def catalogo_navigazione(profilo: str = "intelligence") -> Dict[str, Any]:
    """La scheda 'cosa posso fare', filtrata sul profilo attivo.

    profilo: 'intelligence' o 'financial'. I gruppi 'Financial' compaiono solo
    nel profilo finanziario; il resto è OSINT/Intelligence.
    """
    from src.agent_tools.shadowbroker_tools import OSINT_TOOL_NAMES, FINANCE_TOOL_NAMES
    attivi = FINANCE_TOOL_NAMES if str(profilo).lower().startswith("fin") else OSINT_TOOL_NAMES
    gruppi_out: List[Dict[str, Any]] = []
    for g in _GRUPPI:
        tool_out = [t for t in g["tool"] if t["nome"] in attivi]
        if tool_out:
            gruppi_out.append({
                "titolo": g["titolo"], "icona": g["icona"],
                "profilo": g.get("profilo", "Intelligence"),
                "tool": tool_out,
            })
    return {"profilo": profilo, "gruppi": gruppi_out}


def verifica_copertura() -> Dict[str, Any]:
    """Ogni tool degli schemi compare nella scheda? (per non mentire per omissione)"""
    from src.shadowbroker.schemi import OSINT_TOOL_SCHEMAS, FINANCE_TOOL_SCHEMAS
    negli_schemi = {s["function"]["name"] for s in OSINT_TOOL_SCHEMAS + FINANCE_TOOL_SCHEMAS}
    presentati = {t["nome"] for g in _GRUPPI for t in g["tool"]}
    return {
        "schemi": sorted(negli_schemi),
        "mancanti_nella_scheda": sorted(negli_schemi - presentati),
        "fantasma_nella_scheda": sorted(presentati - negli_schemi),
        "ok": negli_schemi == presentati,
    }
