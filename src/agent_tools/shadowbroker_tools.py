"""Strumenti OSINT: quello che il modello puo' chiedere a ShadowBroker.

Dieci strumenti al posto dei 62 loro. Non e' per risparmiare token — quelli
costano 105 l'uno, e passare da 6 a 10 costa 500 token in tutto. E' per non
mettere il modello davanti a scelte che non sa fare: il loro catalogo ha
`get_summary`, `get_layer_slice`, `search_telemetry`, `get_telemetry`,
`get_report`, `brief_area`, `entities_near`, `route_query` — otto modi diversi
di chiedere "cosa succede", di cui due lo uccidono e uno mente sul raggio.

Misure che giustificano ogni scelta qui dentro:

    catalogo loro, 62 strumenti          12.374 token   (25% del contesto)
    catalogo nostro, 10 strumenti        ~1.100 token   (2,2%)
    domanda ingenua sui conflitti        47.891 token   (97%)
    stesso briefing, fatto qui            1.592 token   (3,2%, media misurata)

Quattro strumenti restituiscono **briefing gia' ordinati**: il modello non
sceglie cosa e' importante, lo riceve. Gli altri sei servono per approfondire
(`osint_dettaglio`, `osint_testo`), cercare (`osint_cerca`, `osint_recon`) e
agire sulla mappa (`osint_mappa`).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Tetto oltre il quale una risposta viene tagliata comunque, qualunque cosa
# abbia chiesto il modello. E' un paracadute, non un obiettivo: un briefing
# normale sta sotto i 2.500 token (media misurata 1.019).
#
# ~6.000 token su 48K, cioe' il 12% del contesto. Alto di proposito: meglio una
# risposta ricca che una tagliata a meta', e il margine serve alle domande su
# zone dense (`osint_zona` su una capitale tocca 2.300 token da solo). Se un
# giorno servisse ancora piu' respiro, questa e' l'unica manopola da girare.
_MAX_CARATTERI = int(os.getenv("OSINT_MAX_CARATTERI", "21600"))


def _args(content: str) -> Dict[str, Any]:
    """Gli argomenti arrivano come stringa JSON, o come testo semplice."""
    raw = (content or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except json.JSONDecodeError:
            pass
    # Testo semplice: quasi sempre un luogo o una parola chiave.
    return {"_testo": raw}


def _numero(v: Any, predefinito: float, minimo: float, massimo: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return predefinito
    return max(minimo, min(massimo, n))


def _consegna(dati: Any) -> Dict[str, Any]:
    """Serializza e applica il tetto, dichiarando il taglio se avviene."""
    testo = json.dumps(dati, ensure_ascii=False, indent=1, default=str)
    if len(testo) > _MAX_CARATTERI:
        testo = testo[:_MAX_CARATTERI] + (
            '\n… TAGLIATO: la risposta superava il tetto. '
            'Chiedi meno elementi o restringi la zona.'
        )
    return {"output": testo, "exit_code": 0}


def _errore(messaggio: str) -> Dict[str, Any]:
    return {"error": messaggio, "exit_code": 1}


def _errore_scrittura(etichetta: str, e: Exception) -> Dict[str, Any]:
    """Errore di una SCRITTURA sul canale OpenClaw.

    Il caso frequente e' il tier: il backend risponde 403 con
    "command '…' requires full access tier". Non si ritenta — ritentare da
    soli con lo stesso tier produce solo un secondo 403.
    """
    testo = str(e)
    if "requires full" in testo or "HTTP 403" in testo:
        return _errore(
            f"{etichetta}: ShadowBroker non accetta le scritture con l'accesso attuale. "
            f"Apri il pannello AI di ShadowBroker e porta l'accesso a 'full' "
            f"(OPENCLAW_ACCESS_TIER=full), poi richiedimelo. Non riprovo da solo."
        )
    return _errore(f"{etichetta}: {testo[:180]}")


def _non_raggiungibile(e: Exception) -> Dict[str, Any]:
    return _errore(
        f"ShadowBroker non risponde ({type(e).__name__}). "
        f"Vanno avviati backend (porta 8000) e cruscotto (porta 3000). Dettaglio: {str(e)[:150]}"
    )


class _Base:
    """Esegue in un thread: il ponte usa un client HTTP bloccante, e in un
    gestore async fermerebbe il ciclo di eventi per tutta la durata."""

    async def execute(self, content: str, ctx: dict) -> dict:
        import asyncio
        try:
            return await asyncio.to_thread(self.run, _args(content), ctx or {})
        except Exception as e:
            logger.exception("[osint] %s fallito", type(self).__name__)
            return _non_raggiungibile(e)

    def run(self, a: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


# ── briefing ─────────────────────────────────────────────────────────────

class SituazioneTool(_Base):
    def run(self, a, ctx):
        from src.shadowbroker import briefing
        from src.shadowbroker.client import get_client
        dati = briefing.situazione(
            quanti=int(_numero(a.get("quanti"), 8, 3, 20)),
            con_testo=bool(a.get("con_testo", False)),
        )
        # Proattivo (20 ago): la panoramica riferisce gli avvisi che il
        # watchdog ha gia' spinto, cosi' emergono da soli. Best-effort: se il
        # canale non risponde, la panoramica esce lo stesso.
        try:
            avvisi = get_client().avvisi_watchdog(timeout=6)
            if avvisi and isinstance(dati, dict):
                dati["avvisi_sorveglianza"] = {
                    "quanti": len(avvisi), "avvisi": avvisi[:8],
                    "nota": "avvisi dalle sorveglianze attive: riferiscili all'utente",
                }
        except Exception:
            pass
        return _consegna(dati)


class NotizieTool(_Base):
    """Notizie per luogo/soggetto/tema, e il testo vero di un articolo.

    Assorbe il vecchio osint_testo (fuso il 20 ago): con un `url` o un `id`
    restituisce il corpo dell'articolo invece del solo elenco. Nessuna fonte
    ShadowBroker porta il body, gli URL si': si recupera dalla pagina.
    """

    def run(self, a, ctx):
        from src.shadowbroker import briefing
        # Caso "leggimi questo": url esplicito, o id di un evento gia' visto.
        urls = a.get("urls") or a.get("url")
        if isinstance(urls, str):
            urls = [u.strip() for u in urls.split(",") if u.strip()]
        ident = a.get("id")
        testo_grezzo = a.get("_testo")
        if urls or ident or (testo_grezzo and str(testo_grezzo).startswith("http")):
            return self._leggi(urls, ident, a)
        # Caso normale: briefing di notizie.
        return _consegna(briefing.notizie(
            luogo=a.get("luogo") or a.get("_testo"),
            soggetto=a.get("soggetto"),
            tema=a.get("tema"),
            giorni=_numero(a.get("giorni"), 2, 0.25, 30),
            raggio_km=_numero(a.get("raggio_km"), 400, 10, 5000),
            quante=int(_numero(a.get("quante"), 8, 3, 25)),
            con_testo=bool(a.get("leggi_testo", a.get("con_testo", True))),
        ))

    def _leggi(self, urls, ident, a):
        from src.shadowbroker import testo as mod_testo
        from src.shadowbroker.store import get_store
        if not urls and ident:
            e = get_store().dettaglio(str(ident).strip())
            if e is None:
                return _errore(f"identificativo '{ident}' non trovato: rifai la domanda, "
                               f"gli id valgono finche' l'elemento resta in memoria")
            urls = e.get("_urls_list") or ([e["link"]] if e.get("link") else [])
        if not urls:
            uno = a.get("_testo")
            if uno and str(uno).startswith("http"):
                urls = [str(uno)]
        if not urls:
            return _errore("osint_notizie: per leggere il testo serve un url o un id valido")
        r = mod_testo.recupera_testo(
            [str(u) for u in urls],
            max_tentativi=int(_numero(a.get("tentativi"), 3, 1, 6)),
            max_caratteri=int(_numero(a.get("max_caratteri"), 1500, 200, 6000)),
        )
        return _consegna(r)


class MilitareTool(_Base):
    def run(self, a, ctx):
        from src.shadowbroker import briefing
        return _consegna(briefing.militare(
            luogo=a.get("luogo") or a.get("_testo"),
            raggio_km=_numero(a.get("raggio_km"), 1000, 10, 10000),
            quanti=int(_numero(a.get("quanti"), 15, 3, 40)),
        ))


class AllerteTool(_Base):
    def run(self, a, ctx):
        from src.shadowbroker import briefing
        return _consegna(briefing.allerte(
            luogo=a.get("luogo") or a.get("_testo"),
            raggio_km=_numero(a.get("raggio_km"), 1000, 10, 10000),
            quante=int(_numero(a.get("quante"), 15, 3, 30)),
        ))


class ZonaTool(_Base):
    def run(self, a, ctx):
        from src.shadowbroker import briefing
        luogo = a.get("luogo") or a.get("_testo")
        if not luogo:
            return _errore("osint_zona: serve un luogo (nome, oppure 'lat,lng')")
        return _consegna(briefing.zona(
            luogo=luogo,
            raggio_km=_numero(a.get("raggio_km"), 200, 5, 3000),
            per_layer=int(_numero(a.get("per_layer"), 5, 1, 15)),
        ))


# ── approfondimento ──────────────────────────────────────────────────────

class DettaglioTool(_Base):
    """La scheda **intera** di un elemento. E' il motivo per cui comprimere non
    significa perdere: il magazzino conserva il record completo."""

    def run(self, a, ctx):
        from src.shadowbroker.store import get_store
        ident = a.get("id") or a.get("_testo")
        if not ident:
            return _errore("osint_dettaglio: serve l'identificativo, es. 'gdelt:32e4e3'")
        elemento = get_store().dettaglio(str(ident).strip())
        if elemento is None:
            return _errore(
                f"identificativo '{ident}' non trovato. Gli identificativi vengono dai "
                f"briefing e valgono finche' l'elemento resta in memoria: rifai la domanda."
            )
        return _consegna(elemento)


# ── ricerca ──────────────────────────────────────────────────────────────

class CercaTool(_Base):
    """Un'entita' precisa: aereo, nave, persona, sigla, matricola.

    Composizione annidata di tre loro comandi (vedi `shadowbroker/entita.py`):
    `get_entity_profile` per la scheda, `correlate_entity` per il contesto gia'
    valutato, `entity_expand` per sanzioni e collegamenti. Le sezioni ridondanti
    (`trail`, `lookup`) vengono scartate: `movement` e `identity` le riassumono,
    e da sole valgono 787 dei 1.182 token della risposta grezza.
    """

    def run(self, a, ctx):
        from src.shadowbroker import entita
        q = a.get("query") or a.get("_testo")
        if not q:
            return _errore("osint_cerca: serve qualcosa da cercare")
        return _consegna(entita.scheda(
            str(q),
            con_contesto=bool(a.get("contesto", False)),
            con_relazioni=bool(a.get("relazioni", False)),
            raggio_km=_numero(a.get("raggio_km"), 300, 10, 2000),
        ))


class ReconTool(_Base):
    """Ricerca tecnica: IP, dominio, certificati, BGP, sanzioni, CVE.

    Gira lato server con protezione SSRF: il browser non contatta mai
    direttamente i servizi esterni.
    """

    _TIPI = {"ip", "dns", "whois", "certs", "bgp", "sanctions", "cve", "mac",
             "github", "leaks", "threats", "espandi"}
    _ALIAS = {"sanzioni": "sanctions", "dominio": "dns", "certificati": "certs",
              "minacce": "threats", "violazioni": "leaks",
              "expand": "espandi", "entity_expand": "espandi", "grafo": "espandi"}
    # `entity_expand` vuole sapere COSA e' il valore. Il modello lo dira' quasi
    # mai, quindi si indovina: un IP si riconosce da solo, il resto e' un nome
    # di azienda finche' non si dice il contrario.
    _ENTITA = {"aircraft", "vessel", "company", "person", "ip", "country"}
    _ENTITA_ALIAS = {"aereo": "aircraft", "nave": "vessel", "azienda": "company",
                     "societa": "company", "persona": "person", "paese": "country"}

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        tipo = str(a.get("tipo") or "").strip().lower()
        tipo = self._ALIAS.get(tipo, tipo)
        valore = a.get("valore") or a.get("_testo")
        if not valore:
            return _errore("osint_recon: serve un valore (indirizzo IP, dominio, CVE…)")
        if tipo not in self._TIPI:
            return _errore(f"osint_recon: tipo '{tipo}' sconosciuto. Ammessi: {', '.join(sorted(self._TIPI))}")
        if tipo == "espandi":
            return self._espandi(get_client(), str(valore), a)
        try:
            r = get_client().comando(
                "osint_lookup", {"tool": tipo, "query": valore, tipo: valore}, timeout=60)
        except Exception as e:
            return _errore(f"osint_recon {tipo}: {str(e)[:200]}")
        return _consegna({"tipo": tipo, "valore": valore, "risultato": r})

    def _espandi(self, client, valore: str, a: Dict[str, Any]) -> Dict[str, Any]:
        """Grafo delle relazioni intorno a un'entita' (`entity_expand`)."""
        ent = str(a.get("entita") or a.get("entity") or "").strip().lower()
        ent = self._ENTITA_ALIAS.get(ent, ent)
        if ent and ent not in self._ENTITA:
            return _errore(f"osint_recon espandi: entita' '{ent}' sconosciuta. "
                           f"Ammesse: {', '.join(sorted(self._ENTITA))}")
        if not ent:
            pezzi = valore.split(".")
            if len(pezzi) == 4 and all(p.isdigit() for p in pezzi):
                ent = "ip"
            else:
                ent = "company"
        try:
            r = client.comando("entity_expand", {"type": ent, "id": valore}, timeout=60)
        except Exception as e:
            return _errore(f"osint_recon espandi: {str(e)[:200]}")
        return _consegna({"tipo": "espandi", "entita": ent, "valore": valore, "grafo": r})


# ── mappa ────────────────────────────────────────────────────────────────

# Nomi dei layer come li conosce il modello (e il cruscotto) tradotti nelle
# chiavi dei fetcher, che sono un'altra cosa: `military`, non
# `military_flights`. Servono alle override lato server
# (`PUT /api/ai/layer-overrides`): `set_layers` accende la CASELLA nel
# browser, l'override accende la SORGENTE. Senza la seconda, un layer che
# l'operatore tiene spento lato server (firms, datacenters, power_plants,
# cctv sono spenti di fabbrica) si accende vuoto. Le chiavi che non compaiono
# qui non hanno un interruttore lato server: si saltano, il cruscotto basta.
_LIVELLI_SERVER: Dict[str, list] = {
    "gdelt": ["global_incidents"],
    "news": ["global_incidents"],
    "telegram_osint": ["telegram_osint"],
    "military_flights": ["military"],
    "tracked_flights": ["tracked"],
    "commercial_flights": ["flights"],
    "private_jets": ["jets", "private"],
    "ships": ["ships_military", "ships_cargo", "ships_civilian", "ships_passenger"],
    "satellites": ["satellites"],
    "earthquakes": ["earthquakes"],
    "firms_fires": ["firms"],
    "weather_alerts": ["weather_alerts"],
    "internet_outages": ["internet_outages"],
    "military_bases": ["military_bases"],
    "power_plants": ["power_plants"],
    "datacenters": ["datacenters"],
    "frontlines": ["ukraine_frontline"],
    "correlations": ["correlations"],
    "sigint": ["sigint_meshtastic", "sigint_aprs"],
    "sar_anomalies": ["sar"],
}

# 5 minuti, rinfrescati a ogni chiamata: l'override e' pensata per essere
# ri-messa dall'agente che tiene aperto un overlay, non per durare a lungo.
_TTL_LIVELLI_S = 300.0

# Le note sulla mappa non hanno un colore libero: il backend ha cinque
# CATEGORIE e da quelle ricava il colore. Il modello pero' dira' "rosso", non
# "warning", quindi si accettano entrambi.
_CATEGORIA_NOTA: Dict[str, str] = {
    "rosso": "warning", "red": "warning", "warning": "warning",
    "ambra": "contradiction", "giallo": "contradiction", "amber": "contradiction",
    "contradiction": "contradiction",
    "blu": "observation", "blue": "observation", "observation": "observation",
    "viola": "hypothesis", "purple": "hypothesis", "hypothesis": "hypothesis",
    "ciano": "analysis", "cyan": "analysis", "analysis": "analysis",
}


def _accendi_sorgenti(client, accesi) -> Optional[Dict[str, Any]]:
    """Accende lato server le sorgenti dei layer chiesti. Best-effort.

    Non e' un fallback: viaggia INSIEME a `set_layers`. Se fallisce, il
    cruscotto accende comunque le sue caselle, e questa resta una nota.
    """
    chiavi: Dict[str, bool] = {}
    for nome in accesi or []:
        for k in _LIVELLI_SERVER.get(str(nome).strip().lower(), []):
            chiavi[k] = True
    if not chiavi:
        return None
    try:
        r = client.accendi_livelli_server(chiavi, ttl_s=_TTL_LIVELLI_S)
    except Exception as e:
        return {"applicate": False, "perche": str(e)[:120]}
    return {"applicate": sorted((r or {}).get("overrides") or chiavi),
            "scadenza_s": int(_TTL_LIVELLI_S)}


class MappaTool(_Base):
    """Comanda la mappa che l'utente sta guardando.

    Le azioni finiscono in una coda lato ShadowBroker che il cruscotto svuota.
    `centra` e `evidenzia` sono i due modi di dire "sto parlando di questo".
    """

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        from src.shadowbroker import geo
        from src.shadowbroker.store import get_store

        azione = str(a.get("azione") or "").strip().lower()
        client = get_client()

        if azione in ("centra", "focus", "vola"):
            lat, lng = a.get("lat"), a.get("lng")
            if lat is None or lng is None:
                # Il modello puo' dare un nome, o l'identificativo di qualcosa
                # che ha appena citato: entrambi si risolvono qui.
                bersaglio = a.get("luogo") or a.get("id") or a.get("_testo")
                punto = None
                if bersaglio:
                    e = get_store().dettaglio(str(bersaglio).strip())
                    punto = geo.coordinate_di(e) if e else geo.risolvi_posto(str(bersaglio))
                if punto is None:
                    return _errore("osint_mappa centra: servono lat/lng, un luogo noto, o un identificativo")
                lat, lng = punto
            try:
                r = client.comando("map_focus", {
                    "lat": float(lat), "lng": float(lng),
                    "zoom": _numero(a.get("zoom"), 6, 1, 18),
                }, timeout=15)
            except Exception as e:
                return _errore(f"osint_mappa centra: {str(e)[:180]}")
            return _consegna({"azione": "centra", "lat": lat, "lng": lng, "esito": r})

        if azione in ("livelli", "layers", "mostra_solo"):
            accesi = a.get("accendi") or a.get("livelli") or a.get("solo") or []
            spenti = a.get("spegni") or []
            if isinstance(accesi, str):
                accesi = [p.strip() for p in accesi.split(",") if p.strip()]
            if isinstance(spenti, str):
                spenti = [p.strip() for p in spenti.split(",") if p.strip()]
            if not accesi and not spenti:
                return _errore("osint_mappa livelli: indica quali accendere o spegnere")
            try:
                r = client.comando("set_layers", {
                    "on": accesi, "off": spenti,
                    "solo": bool(a.get("solo_questi", bool(accesi) and not spenti)),
                }, timeout=15)
            except Exception as e:
                return _errore(f"osint_mappa livelli: {str(e)[:180]}")
            fuori = {"azione": "livelli", "accesi": accesi, "spenti": spenti, "esito": r}
            sorgenti = _accendi_sorgenti(client, accesi)
            if sorgenti:
                fuori["sorgenti_server"] = sorgenti
            return _consegna(fuori)

        if azione in ("preset", "profilo"):
            from src.shadowbroker.schemi import PRESET_MAPPA
            nome = str(a.get("preset") or a.get("nome") or a.get("_testo") or "").strip().lower()
            livelli = PRESET_MAPPA.get(nome)
            if not livelli:
                return _errore(
                    f"osint_mappa preset: '{nome}' sconosciuto. "
                    f"Ammessi: {', '.join(sorted(PRESET_MAPPA))}")
            try:
                r = client.comando("set_layers", {"on": livelli, "solo": True}, timeout=15)
            except Exception as e:
                return _errore(f"osint_mappa preset: {str(e)[:180]}")
            fuori = {"azione": "preset", "nome": nome, "accesi": livelli, "esito": r}
            sorgenti = _accendi_sorgenti(client, livelli)
            if sorgenti:
                fuori["sorgenti_server"] = sorgenti
            return _consegna(fuori)

        if azione in ("evidenzia", "highlight"):
            ids = a.get("ids") or a.get("id") or a.get("_testo")
            if isinstance(ids, str):
                ids = [p.strip() for p in ids.split(",") if p.strip()]
            if not ids:
                return _errore("osint_mappa evidenzia: serve almeno un identificativo")
            # Gli identificativi sono nostri (`gdelt:32e4e3`): il cruscotto
            # ragiona per posizione, quindi si traducono in punti.
            store = get_store()
            punti = []
            for i in ids:
                e = store.dettaglio(str(i))
                c = geo.coordinate_di(e) if e else None
                if c:
                    punti.append({"id": str(i), "lat": c[0], "lng": c[1],
                                  "etichetta": geo.etichetta(e)})
            if not punti:
                return _errore("nessuno degli identificativi ha una posizione da evidenziare")
            try:
                r = client.comando("highlight", {"punti": punti}, timeout=15)
            except Exception as e:
                return _errore(f"osint_mappa evidenzia: {str(e)[:180]}")
            return _consegna({"azione": "evidenzia", "quanti": len(punti), "esito": r})

        if azione in ("ripristina", "reset"):
            try:
                r = client.comando("set_layers", {"reset": True}, timeout=15)
            except Exception as e:
                return _errore(f"osint_mappa ripristina: {str(e)[:180]}")
            # Le caselle tornano come le aveva l'operatore; le override
            # scadrebbero da sole, ma tenerle vive dopo un ripristino
            # significherebbe continuare a far girare fetcher che lui aveva
            # spento.
            try:
                client.azzera_livelli_server()
            except Exception:
                pass
            return _consegna({"azione": "ripristina", "esito": r})

        # ── note sulla mappa (zone di analisi) ───────────────────────────
        # Quadrati tratteggiati sul layer correlations, con dentro il testo
        # scritto da noi. Restano finche' qualcuno non li cancella: sono
        # SCRITTURE, tier `full`.

        if azione in ("nota", "note", "cancella_nota", "annota", "zone"):
            if azione in ("note", "zone"):
                try:
                    r = client.comando("list_analysis_zones", {}, timeout=15)
                except Exception as e:
                    return _errore(f"osint_mappa note: {str(e)[:180]}")
                return _consegna({"azione": "note", "note": r})

            if azione == "cancella_nota":
                zid = a.get("id") or a.get("_testo")
                if not zid:
                    return _errore("osint_mappa cancella_nota: serve l'id della nota (da azione='note')")
                try:
                    r = client.comando("delete_analysis_zone", {"zone_id": str(zid)}, timeout=15)
                except Exception as e:
                    return _errore_scrittura("osint_mappa cancella_nota", e)
                return _consegna({"azione": "cancella_nota", "id": zid, "esito": r})

            testo = a.get("testo") or a.get("_testo")
            if not testo:
                return _errore("osint_mappa nota: serve il testo della nota")
            punto = _punto_da(a)
            if not punto:
                return _errore("osint_mappa nota: servono lat e lng (o un luogo noto)")
            colore = str(a.get("colore") or a.get("categoria") or "analysis").strip().lower()
            categoria = _CATEGORIA_NOTA.get(colore, "analysis")
            try:
                r = client.comando("place_analysis_zone", {
                    "lat": punto[0], "lng": punto[1],
                    "title": str(testo)[:80],
                    "body": str(testo),
                    "category": categoria,
                }, timeout=20)
            except Exception as e:
                return _errore_scrittura("osint_mappa nota", e)
            return _consegna({"azione": "nota", "lat": punto[0], "lng": punto[1],
                              "categoria": categoria, "esito": r})

        return _errore("osint_mappa: azione ammessa fra centra, livelli, evidenzia, "
                       "preset, ripristina, nota, note, cancella_nota")


# ── finanza ──────────────────────────────────────────────────────────────

class MercatiTool(_Base):
    def run(self, a, ctx):
        from src.shadowbroker import finanza
        titolo = a.get("titolo") or a.get("simbolo") or a.get("ticker")
        return _consegna(finanza.mercati(
            quante_notizie=int(_numero(a.get("quante_notizie"), 8, 3, 20)),
            titolo=str(titolo).strip() if titolo else None,
        ))


class AppaltiTool(_Base):
    """Contratti federali. L'unico dato finanziario che finisce sulla mappa."""

    def run(self, a, ctx):
        from src.shadowbroker import finanza
        titolo = a.get("titolo") or a.get("_testo")
        if titolo and str(titolo).upper() not in finanza.DIFESA:
            # Un nome di azienda al posto della sigla e' l'errore piu' probabile.
            titolo = None
        return _consegna(finanza.appalti(
            mesi=_numero(a.get("mesi"), 12, 1, 60),
            quanti=int(_numero(a.get("quanti"), 12, 3, 30)),
            titolo=str(titolo).upper() if titolo else None,
        ))


class InsiderTool(_Base):
    def run(self, a, ctx):
        from src.shadowbroker import finanza
        titolo = a.get("titolo") or a.get("_testo")
        if titolo and str(titolo).upper() not in finanza.DIFESA:
            titolo = None
        return _consegna(finanza.insider(
            quanti=int(_numero(a.get("quanti"), 12, 3, 30)),
            titolo=str(titolo).upper() if titolo else None,
        ))


class ArchivioTool(_Base):
    """L'archivio storico: quello che i layer in-memory perdono a ogni riavvio.

    Il free tier nega /stock/candle, quindi il passato non si puo' richiedere:
    o lo abbiamo conservato noi, o non esiste. `src/shadowbroker/archivio.py`
    conserva; questo strumento interroga.
    """

    def run(self, a, ctx):
        from src.shadowbroker import archivio
        query = a.get("query") or a.get("_testo")
        if not query:
            return _errore("fin_archivio: serve una query, es. 'contratti RTX'")
        return _consegna(archivio.cerca(
            query=str(query),
            quanti=int(_numero(a.get("quanti"), 6, 1, 15)),
            giorni=_numero(a.get("giorni"), 0, 0, 365) or None,
        ))


class WebTool(_Base):
    """Ricerca web generale, con il motore che Odysseus usa fuori profilo.

    Nei profili la dotazione e' chiusa apposta; senza questa via d'uscita una
    domanda che i feed non coprono ("chi e' il ministro della difesa di X?")
    morirebbe in un "non osservabile". Stessa ricerca, stessa cache, stesso
    filtro URL del resto di Odysseus: nessun canale nuovo verso fuori.
    """

    def run(self, a, ctx):
        from services.search.core import searxng_search_results
        query = a.get("query") or a.get("_testo")
        if not query:
            return _errore("osint_web: serve una query, es. 'Sweden defense minister'")
        quanti = int(_numero(a.get("quanti"), 6, 1, 10))
        recenti = a.get("recenti")
        if recenti not in ("day", "week", "month"):
            recenti = None
        grezzi = searxng_search_results(str(query), count=quanti, time_filter=recenti) or []
        # Stesse chiavi difensive usate dal ripiego web di briefing.notizie().
        voci = []
        for r in grezzi:
            if not isinstance(r, dict) or not r.get("title"):
                continue
            voci.append({
                "titolo": r.get("title"),
                "url": r.get("url") or r.get("href"),
                "estratto": (r.get("snippet") or r.get("body") or r.get("content") or "")[:300] or None,
            })
        if not voci:
            return _consegna({
                "risultati": [],
                "nota": ("zero risultati: riprova con parole chiave inglesi "
                         "piu' semplici, o dichiara che il web non copre la domanda"),
            })
        return _consegna({
            "risultati": voci[:quanti],
            "nota": "fonte: web aperto, non i feed della piattaforma. "
                    "Per il testo intero di una pagina: `osint_testo` sull'url.",
        })


# ── categorie nuove: facciate sui comandi OpenClaw (20 ago) ───────────────
#
# Non tool nuovi da zero: verbi che smistano verso comandi che il backend
# gia' espone, con la solita compressione. Le AZIONI di lettura (elenca,
# classifica, dossier) girano con `OPENCLAW_ACCESS_TIER=restricted`; quelle
# di scrittura (cattura, aggiungi) richiedono tier `full` e tornano 403
# altrimenti — il messaggio d'errore lo dichiara.

class RischioTool(_Base):
    """Modello di rischio geopolitico (GT analytics). Facciata sui comandi gt_*.

    Diverso da osint_allerte (incidenti VIVI adesso): qui e' il modello che
    guarda avanti, regione per regione. Va acceso con GT_ANALYTICS_ENABLED.
    """

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "classifica").strip().lower()
        try:
            if azione in ("dossier", "regione"):
                reg = a.get("regione") or a.get("_testo")
                if not reg:
                    return _errore("osint_rischio dossier: serve una regione")
                d = c.comando("gt_dossier", {"region": str(reg)}, timeout=30)
                return _consegna({"azione": "dossier", "regione": reg, "dossier": d})
            if azione in ("ricalcola", "analizza", "aggiorna"):
                d = c.comando("gt_analyze", {}, timeout=60)
                return _consegna({"azione": "ricalcola", "risultato": d})
            quante = int(_numero(a.get("quante"), 10, 3, 30))
            d = c.comando("gt_top_alerts", {"limit": quante}, timeout=30)
            return _consegna({"azione": "classifica", "top": d})
        except Exception as e:
            return _errore(
                f"osint_rischio {azione}: {str(e)[:180]}. "
                f"Il modello GT va acceso con GT_ANALYTICS_ENABLED.")


class SorveglianzaTool(_Base):
    """Watchdog persistente: allerta quando qualcosa si muove/appare.

    Facciata su list/add/remove/clear_watches e watch_area (geofence).
    aggiungi/rimuovi/pulisci sono SCRITTURE: servono tier `full`.
    """

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "elenca").strip().lower()
        try:
            if azione in ("avvisi", "alert", "notifiche"):
                # Avvisi che il watchdog ha gia' spinto verso di noi (proattivi).
                return _consegna({"azione": "avvisi", "avvisi": c.avvisi_watchdog(timeout=8)})
            if azione in ("elenca", "lista", "list"):
                return _consegna({"azione": "elenca",
                                  "watch": c.comando("list_watches", {}, timeout=15)})
            if azione in ("rimuovi", "remove", "cancella"):
                wid = a.get("id") or a.get("_testo")
                if not wid:
                    return _errore("osint_sorveglianza rimuovi: serve l'id (da 'elenca')")
                return _consegna({"azione": "rimuovi",
                                  "esito": c.comando("remove_watch", {"id": str(wid)}, timeout=15)})
            if azione in ("pulisci", "clear", "svuota"):
                return _consegna({"azione": "pulisci",
                                  "esito": c.comando("clear_watches", {}, timeout=15)})
            # aggiungi (default se c'e' un bersaglio)
            luogo = a.get("luogo")
            bersaglio = a.get("bersaglio") or a.get("_testo")
            if luogo:
                from src.shadowbroker import geo
                punto = geo.risolvi_posto(str(luogo))
                if not punto:
                    return _errore(f"osint_sorveglianza: luogo '{luogo}' non risolto")
                r = c.comando("watch_area", {
                    "lat": punto[0], "lng": punto[1],
                    "radius_km": _numero(a.get("raggio_km"), 100, 5, 3000),
                }, timeout=20)
                return _consegna({"azione": "aggiungi", "tipo": "area",
                                  "luogo": luogo, "esito": r})
            if not bersaglio:
                return _errore("osint_sorveglianza aggiungi: serve un bersaglio "
                               "(aereo/callsign/nave/parola-chiave) o un luogo")
            r = c.comando("track_entity", {"query": str(bersaglio)}, timeout=20)
            return _consegna({"azione": "aggiungi", "bersaglio": bersaglio, "esito": r})
        except Exception as e:
            return _errore(
                f"osint_sorveglianza {azione}: {str(e)[:180]}. "
                f"Le scritture (aggiungi/rimuovi/pulisci) richiedono "
                f"OPENCLAW_ACCESS_TIER=full.")


class StoricoTool(_Base):
    """Time Machine: com'era la mappa nel passato. Facciata su timemachine_*.

    'cattura' e' una scrittura (tier full); 'elenca'/'riproduci' sono letture.
    Per lo storico FINANZIARIO c'e' fin_archivio, non questo.
    """

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "elenca").strip().lower()
        try:
            if azione in ("cattura", "salva", "snapshot"):
                r = c.comando("take_snapshot", {"profile": "openclaw"}, timeout=30)
                return _consegna({"azione": "cattura", "esito": r})
            if azione in ("riproduci", "playback", "rivedi"):
                sid = a.get("id") or a.get("_testo")
                if not sid:
                    return _errore("osint_storico riproduci: serve l'id snapshot (da 'elenca')")
                r = c.comando("timemachine_playback", {"snapshot_id": str(sid)}, timeout=30)
                return _consegna({"azione": "riproduci", "id": sid, "dati": r})
            r = c.comando("timemachine_list", {}, timeout=15)
            return _consegna({"azione": "elenca", "snapshot": r})
        except Exception as e:
            return _errore(
                f"osint_storico {azione}: {str(e)[:180]}. "
                f"'cattura' richiede OPENCLAW_ACCESS_TIER=full.")


# ── capacita' ShadowBroker gia' presenti, mai esposte al modello (20 ago) ──
#
# Queste NON passano dal canale OpenClaw: sono endpoint HTTP diretti della
# piattaforma (geocode, feed cyber, radio, satellite). Su loopback l'auth e'
# bypassata (compreso require_local_operator). client.http_get / http_post.

def _punto_da(a: Dict[str, Any]):
    """Ricava (lat, lng) da lat/lng espliciti, 'lat,lng' testuale, o un luogo."""
    from src.shadowbroker import geo
    lat, lng = a.get("lat"), a.get("lng")
    if lat is not None and lng is not None:
        try:
            return float(lat), float(lng)
        except (TypeError, ValueError):
            pass
    grezzo = a.get("luogo") or a.get("_testo") or ""
    s = str(grezzo).strip()
    if "," in s:
        pezzi = s.split(",", 1)
        try:
            return float(pezzi[0].strip()), float(pezzi[1].strip())
        except ValueError:
            pass
    if s:
        p = geo.risolvi_posto(s)
        if p:
            return p[0], p[1]
    return None


class GeocodeTool(_Base):
    """Risolve nomi di luogo in coordinate e viceversa (endpoint /api/geocode)."""

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "cerca").strip().lower()
        try:
            if azione in ("inverso", "reverse"):
                lat, lng = a.get("lat"), a.get("lng")
                if lat is None or lng is None:
                    pt = _punto_da(a)
                    if not pt:
                        return _errore("osint_geocode inverso: servono lat e lng")
                    lat, lng = pt
                r = c.http_get("/api/geocode/reverse", {"lat": float(lat), "lng": float(lng)}, timeout=15)
                return _consegna({"azione": "inverso", "lat": lat, "lng": lng, "luogo": r})
            luogo = a.get("luogo") or a.get("_testo")
            if not luogo:
                return _errore("osint_geocode cerca: serve un nome di luogo")
            r = c.http_get("/api/geocode/search",
                           {"q": str(luogo), "limit": int(_numero(a.get("quanti"), 5, 1, 10))}, timeout=15)
            return _consegna({"azione": "cerca", "luogo": luogo, "risultati": r})
        except Exception as e:
            return _errore(f"osint_geocode {azione}: {str(e)[:180]}")


class CyberTool(_Base):
    """Threat intel cyber: botnet C2 (abuse.ch), CISA KEV, indice rischio-paese."""

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "tutto").strip().lower()
        try:
            if azione in ("malware", "botnet", "c2"):
                return _consegna({"azione": "malware", "dati": c.http_get("/api/malware", timeout=20)})
            if azione in ("vulnerabilita", "vuln", "kev", "cve"):
                return _consegna({"azione": "vulnerabilita", "dati": c.http_get("/api/cyber-threats", timeout=20)})
            if azione in ("rischio_paese", "paese", "country"):
                return _consegna({"azione": "rischio_paese", "dati": c.http_get("/api/country-risk", timeout=20)})
            # tutto: sintesi delle tre fonti
            out = {"azione": "tutto"}
            for chiave, path in (("malware", "/api/malware"),
                                 ("vulnerabilita", "/api/cyber-threats"),
                                 ("rischio_paese", "/api/country-risk")):
                try:
                    out[chiave] = c.http_get(path, timeout=20)
                except Exception as e:
                    out[chiave] = {"errore": str(e)[:120]}
            return _consegna(out)
        except Exception as e:
            return _errore(f"osint_cyber {azione}: {str(e)[:180]}")


class RadioTool(_Base):
    """SIGINT/radio: scanner pubblici vicini, ricevitori KiwiSDR vicini, ACARS/HFDL."""

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "scanner").strip().lower()
        try:
            if azione in ("acars", "datalink", "hfdl"):
                aereo = a.get("aereo") or a.get("_testo") or ""
                s = str(aereo).strip()
                if not s:
                    return _errore("osint_radio acars: serve un aereo (icao24, matricola o callsign)")
                # euristica: hex 6 char = icao24; con lettere/numeri e '-' = registration; altrimenti callsign
                par = {}
                if len(s) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in s):
                    par["icao24"] = s.lower()
                elif "-" in s or (s[:1].isalpha() and any(ch.isdigit() for ch in s)):
                    par["registration"] = s.upper()
                else:
                    par["callsign"] = s.upper()
                r = c.http_get("/api/aviation/datalink/messages", par, timeout=20)
                return _consegna({"azione": "acars", "aereo": s, "messaggi": r})
            pt = _punto_da(a)
            if not pt:
                return _errore(f"osint_radio {azione}: serve un luogo (nome o 'lat,lng')")
            lat, lng = pt
            if azione in ("kiwisdr", "sdr"):
                r = c.http_get("/api/sigint/nearest-sdr", {"lat": lat, "lng": lng}, timeout=20)
                return _consegna({"azione": "kiwisdr", "lat": lat, "lng": lng, "ricevitori": r})
            # scanner (default)
            r = c.http_get("/api/radio/nearest-list",
                           {"lat": lat, "lng": lng, "limit": int(_numero(a.get("quanti"), 5, 1, 20))}, timeout=20)
            return _consegna({"azione": "scanner", "lat": lat, "lng": lng, "scanner": r})
        except Exception as e:
            return _errore(f"osint_radio {azione}: {str(e)[:180]}")


class SatelliteTool(_Base):
    """Analisi satellitare on-demand: anomalia termica SWIR, previsione passaggi."""

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        import math
        c = get_client()
        azione = str(a.get("azione") or "termico").strip().lower()
        pt = _punto_da(a)
        if not pt:
            return _errore(f"osint_satellite {azione}: serve un luogo (nome o 'lat,lng')")
        lat, lng = pt
        try:
            if azione in ("passaggi", "overflight", "overflights"):
                raggio = _numero(a.get("raggio_km"), 100, 10, 500)
                dlat = raggio / 111.0
                dlng = raggio / max(1.0, 111.0 * math.cos(math.radians(lat)))
                corpo = {"s": lat - dlat, "n": lat + dlat, "w": lng - dlng, "e": lng + dlng,
                         "hours": int(_numero(a.get("ore"), 24, 1, 72))}
                r = c.http_post("/api/satellites/overflights", corpo, timeout=30)
                return _consegna({"azione": "passaggi", "lat": lat, "lng": lng, "passaggi": r})
            # termico (default)
            r = c.http_get("/api/thermal/verify",
                           {"lat": lat, "lng": lng, "radius_km": _numero(a.get("raggio_km"), 10, 1, 100)}, timeout=40)
            return _consegna({"azione": "termico", "lat": lat, "lng": lng, "termico": r})
        except Exception as e:
            return _errore(f"osint_satellite {azione}: {str(e)[:180]}")


class SarTool(_Base):
    """Radar ad apertura sintetica: anomalie, scene, aree sorvegliate (AOI).

    Facciata sui comandi sar_*. Il radar vede di notte e attraverso le nuvole:
    e' l'unico layer che risponde quando il satellite ottico non puo'. Va
    acceso lato ShadowBroker con MESH_SAR_OPENCLAW_ENABLED; se e' spento, il
    backend lo dichiara e quel messaggio arriva all'utente tale e quale.

    aggiungi_area / rimuovi_area / sorveglia / centra sono SCRITTURE: tier
    `full`.
    """

    def run(self, a, ctx):
        from src.shadowbroker.client import get_client
        c = get_client()
        azione = str(a.get("azione") or "stato").strip().lower()
        area = str(a.get("area") or a.get("aoi") or a.get("id") or "").strip().lower()
        quante = int(_numero(a.get("quante"), 25, 1, 100))

        letture = {"stato", "anomalie", "scene", "copertura", "aree"}
        scritture = {"aggiungi_area", "rimuovi_area", "sorveglia", "centra"}
        if azione not in letture | scritture:
            return _errore(f"osint_sar: azione '{azione}' sconosciuta. "
                           f"Ammesse: {', '.join(sorted(letture | scritture))}")

        try:
            if azione == "stato":
                return _consegna({"azione": "stato", "sar": c.comando("sar_status", {}, timeout=20)})

            if azione == "anomalie":
                punto = _punto_da(a)
                if punto:
                    r = c.comando("sar_anomalies_near", {
                        "lat": punto[0], "lng": punto[1],
                        "radius_km": _numero(a.get("raggio_km"), 50, 1, 2000),
                        "limit": quante,
                    }, timeout=30)
                    return _consegna({"azione": "anomalie", "lat": punto[0], "lng": punto[1],
                                      "anomalie": r})
                r = c.comando("sar_anomalies_recent", {"limit": quante}, timeout=30)
                return _consegna({"azione": "anomalie", "anomalie": r})

            if azione == "scene":
                r = c.comando("sar_scene_search",
                              {"aoi_id": area, "limit": quante} if area else {"limit": quante},
                              timeout=30)
                return _consegna({"azione": "scene", "area": area or None, "scene": r})

            if azione == "copertura":
                r = c.comando("sar_coverage_for_aoi",
                              {"aoi_id": area} if area else {}, timeout=30)
                return _consegna({"azione": "copertura", "area": area or None, "copertura": r})

            if azione == "aree":
                return _consegna({"azione": "aree", "aree": c.comando("sar_aoi_list", {}, timeout=20)})
        except Exception as e:
            return _errore(f"osint_sar {azione}: {str(e)[:220]}")

        # ── scritture ───────────────────────────────────────────────────
        try:
            if azione == "aggiungi_area":
                punto = _punto_da(a)
                if not punto:
                    return _errore("osint_sar aggiungi_area: servono lat e lng (o un luogo noto)")
                nome = str(a.get("nome") or a.get("luogo") or a.get("_testo") or area or "").strip()
                ident = area or "".join(ch if ch.isalnum() else "_" for ch in nome.lower())[:32]
                if not ident:
                    return _errore("osint_sar aggiungi_area: serve un nome per l'area")
                r = c.comando("sar_aoi_add", {
                    "id": ident, "name": nome or ident,
                    "center_lat": punto[0], "center_lon": punto[1],
                    "radius_km": _numero(a.get("raggio_km"), 25, 1, 500),
                }, timeout=30)
                return _consegna({"azione": "aggiungi_area", "area": ident, "esito": r})

            if not area:
                return _errore(f"osint_sar {azione}: serve l'area (l'id da azione='aree')")

            if azione == "rimuovi_area":
                r = c.comando("sar_aoi_remove", {"id": area}, timeout=20)
                return _consegna({"azione": "rimuovi_area", "area": area, "esito": r})
            if azione == "sorveglia":
                r = c.comando("sar_watch_anomaly", {"aoi_id": area}, timeout=20)
                return _consegna({"azione": "sorveglia", "area": area, "esito": r})
            # centra
            r = c.comando("sar_focus_aoi", {"aoi_id": area,
                                            "zoom": _numero(a.get("zoom"), 8, 1, 18)}, timeout=20)
            return _consegna({"azione": "centra", "area": area, "esito": r})
        except Exception as e:
            return _errore_scrittura(f"osint_sar {azione}", e)


SHADOWBROKER_TOOL_HANDLERS = {
    "osint_situazione": SituazioneTool().execute,
    "osint_notizie": NotizieTool().execute,
    "osint_militare": MilitareTool().execute,
    "osint_allerte": AllerteTool().execute,
    "osint_zona": ZonaTool().execute,
    "osint_dettaglio": DettaglioTool().execute,
    "osint_cerca": CercaTool().execute,
    "osint_recon": ReconTool().execute,
    "osint_mappa": MappaTool().execute,
    "osint_web": WebTool().execute,
    "osint_rischio": RischioTool().execute,
    "osint_sorveglianza": SorveglianzaTool().execute,
    "osint_storico": StoricoTool().execute,
    "osint_geocode": GeocodeTool().execute,
    "osint_cyber": CyberTool().execute,
    "osint_radio": RadioTool().execute,
    "osint_satellite": SatelliteTool().execute,
    "osint_sar": SarTool().execute,
    "fin_mercati": MercatiTool().execute,
    "fin_appalti": AppaltiTool().execute,
    "fin_insider": InsiderTool().execute,
    "fin_archivio": ArchivioTool().execute,
}

# Intelligence: i dieci OSINT piu' `fin_mercati` da solo. Prima c'erano dentro
# tutti e tre i tool di finanza; appalti e insider pero' sono domande che
# nessuno fa "per sbaglio" fuori dal profilo Financial, e ogni schema in piu'
# e' un candidato in piu' su cui un 9B puo' inciampare. `fin_mercati` resta:
# "come vanno i mercati" e' una domanda da intelligence generale, e senza lo
# strumento il modello risponderebbe a memoria.
OSINT_TOOL_NAMES = frozenset(SHADOWBROKER_TOOL_HANDLERS) - {
    "fin_appalti", "fin_insider", "fin_archivio",
}

# Il profilo finanziario: i quattro strumenti di finanza piu' quelli che
# servono per mostrare e per incrociare. Senza la mappa non potrebbe indicare
# niente; senza le notizie non potrebbe rispondere a "collega questo a cosa
# succede nel mondo".
FINANCE_TOOL_NAMES = frozenset({
    "fin_mercati", "fin_appalti", "fin_insider", "fin_archivio",
    "osint_mappa",       # per evidenziare i contratti
    "osint_notizie",     # per incrociare con la geopolitica e leggere un articolo
    "osint_dettaglio",   # per la scheda intera di qualcosa gia' citato
    "osint_web",         # background che wire e archivio non hanno (CEO, prodotti)
})
