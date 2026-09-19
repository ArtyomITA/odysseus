"""Magazzino dei layer in memoria.

Due lavori:

  * **Non riscaricare.** ShadowBroker aggiorna i layer su due velocita' (veloce
    ~60 s, lenta minuti/ore). Ricaricare gdelt a ogni domanda costerebbe secondi
    per niente, e il rate limiter ci punirebbe.

  * **Non perdere niente.** Qui l'elemento resta **intero**. Al modello va la
    versione ridotta dalle sagome, ma ogni elemento ha un identificativo stabile
    e `dettaglio(id)` restituisce il record completo. E' la risposta alla
    preoccupazione giusta — "cosi' perdiamo dati": non si perde, si mette in
    scala.

Gli identificativi devono reggere fra un aggiornamento e l'altro: se il modello
dice "approfondisci il numero 3" e nel frattempo il layer si e' aggiornato,
l'identificativo deve puntare ancora alla stessa cosa. Si costruiscono dai campi
naturali (icao24, id, link) e solo in ultima istanza dalla posizione.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.shadowbroker.client import LAYER_GEOMETRICI, ShadowBrokerClient, get_client

logger = logging.getLogger(__name__)

# Quanto tenere buono un layer prima di richiederlo. Allineato ai loro due
# livelli di aggiornamento: i voli si muovono, le centrali elettriche no.
TTL: Dict[str, float] = {
    "military_flights": 45, "tracked_flights": 45, "private_jets": 60,
    "commercial_flights": 60, "private_flights": 60, "flights": 45,
    "ships": 120, "trains": 90, "satellites": 60,
    "gdelt": 600, "news": 300, "telegram_osint": 600,
    "weather_alerts": 180, "earthquakes": 180, "firms_fires": 600,
    "internet_outages": 300, "correlations": 180, "threat_level": 120,
    "malware_threats": 900, "cyber_threats": 900, "scm_suppliers": 900,
    "wastewater": 3600, "space_weather": 300,
    "power_plants": 86400, "datacenters": 86400, "military_bases": 86400,
    "airports": 86400, "kiwisdr": 3600, "sigint": 300,
}
TTL_PREDEFINITO = 300.0

# Campi da cui ricavare un identificativo stabile, in ordine di preferenza.
_CAMPI_IDENTITA = ("icao24", "id", "hex", "mmsi", "link", "url", "callsign",
                   "registration", "name", "site_name", "title")


def _identificativo(layer: str, elemento: Dict[str, Any]) -> str:
    """Identificativo corto e stabile: `gdelt:a3f19c`.

    Corto perche' finisce nel contesto una volta per elemento; stabile perche'
    il modello puo' citarlo in un turno successivo.
    """
    seme = None
    for campo in _CAMPI_IDENTITA:
        v = elemento.get(campo)
        if isinstance(v, (str, int)) and str(v).strip():
            seme = f"{campo}={v}"
            break
    if seme is None:
        props = elemento.get("properties")
        if isinstance(props, dict):
            for campo in _CAMPI_IDENTITA:
                v = props.get(campo)
                if isinstance(v, (str, int)) and str(v).strip():
                    seme = f"{campo}={v}"
                    break
    if seme is None:
        # Ultima risorsa: l'elemento intero. Cambia se cambia un solo campo,
        # ma meglio un identificativo fragile che nessun identificativo.
        seme = json.dumps(elemento, sort_keys=True, default=str)[:400]
    h = hashlib.sha1(f"{layer}|{seme}".encode("utf-8")).hexdigest()[:6]
    return f"{layer}:{h}"


def _appiattisci(grezzo: Any) -> List[Dict[str, Any]]:
    """Da qualunque forma restituita da ShadowBroker a una lista di dizionari.

    Loro usano almeno quattro forme: lista di dizionari, lista di Feature
    GeoJSON, FeatureCollection, oggetto singolo. Le Feature vengono appiattite
    portando su `lat`/`lng` dalla geometria, cosi' il resto del codice non deve
    sapere da dove viene un elemento.
    """
    if grezzo is None:
        return []
    if isinstance(grezzo, dict):
        if grezzo.get("type") == "FeatureCollection":
            return _appiattisci(grezzo.get("features") or [])
        # Alcuni layer sono un oggetto solo (space_weather, threat_level).
        return [grezzo]
    if not isinstance(grezzo, list):
        return []

    fuori: List[Dict[str, Any]] = []
    for v in grezzo:
        if not isinstance(v, dict):
            continue
        if "properties" in v and "geometry" in v:
            piatto = dict(v.get("properties") or {})
            g = v.get("geometry") or {}
            c = g.get("coordinates")
            if (isinstance(c, (list, tuple)) and len(c) >= 2
                    and isinstance(c[0], (int, float)) and isinstance(c[1], (int, float))):
                piatto["lng"], piatto["lat"] = float(c[0]), float(c[1])
            elif isinstance(g, dict) and g.get("type"):
                # Poligoni e linee: si conserva il tipo, non la geometria —
                # e' quella che costa 18.769 token in `frontlines`.
                piatto["_geometria"] = g.get("type")
            fuori.append(piatto)
        else:
            fuori.append(v)
    return fuori


def _esito_batch(cmd: str, grezzo: Any) -> Tuple[Any, Optional[str]]:
    """Un elemento di `client.batch()` -> `(dati, errore)`.

    `batch()` non alza eccezioni per il singolo comando: un sotto-comando
    fallito arriva come dizionario con `ok: False` (il backend costruisce
    `{"cmd", "ok": False, "detail"}` sia per il comando sconosciuto sia per
    quello esploso in esecuzione). Qui si traduce nello **stesso** messaggio
    che avrebbe alzato `comando()`, cosi' chi legge non distingue fra il
    percorso batch e quello sequenziale — e un comando caduto degrada solo la
    propria parte.
    """
    if isinstance(grezzo, dict) and grezzo.get("ok") is False:
        dettaglio = grezzo.get("detail") or grezzo.get("message") or "errore ignoto"
        return None, f"ShadowBroker '{cmd}': {dettaglio}"
    if grezzo is None:
        return None, f"ShadowBroker '{cmd}': nessun risultato nel batch"
    return grezzo, None


class LayerStore:
    def __init__(self, client: Optional[ShadowBrokerClient] = None):
        self._client = client or get_client()
        self._lock = threading.RLock()
        self._dati: Dict[str, List[Dict[str, Any]]] = {}
        self._quando: Dict[str, float] = {}
        # layer -> {id: elemento intero}. Indicizzato per layer, non in un unico
        # dizionario piatto: gli identificativi portano gia' il layer come
        # prefisso (`gdelt:3d0669`), e una mappa unica con potatura in ordine di
        # arrivo cancellava gli identificativi di gdelt appena si caricava
        # `power_plants` (34.936 elementi) — il modello citava un id di un
        # briefing appena ricevuto e si sentiva rispondere "non trovato".
        #
        # Le voci sono riferimenti agli stessi dizionari gia' in `_dati`: il
        # costo e' quello di un puntatore, non dell'oggetto.
        self._per_id: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # ── lettura ──────────────────────────────────────────────────────────

    def scaduto(self, layer: str) -> bool:
        quando = self._quando.get(layer)
        if quando is None:
            return True
        return (time.time() - quando) > TTL.get(layer, TTL_PREDEFINITO)

    def carica(self, layer: str, forza: bool = False,
               limite: Optional[int] = None) -> List[Dict[str, Any]]:
        """Il layer intero, dal magazzino o da ShadowBroker.

        Nessun limite predefinito: qui si tiene tutto. Il taglio avviene piu'
        avanti, dopo aver ordinato — tagliare prima significherebbe tenere i
        primi N per ordine di arrivo invece dei piu' importanti.
        """
        with self._lock:
            if not forza and not self.scaduto(layer):
                return self._dati.get(layer, [])
        try:
            grezzo = self._client.layer(layer, limite=limite)
        except Exception as e:
            logger.warning("[shadowbroker] lettura di %s fallita: %s", layer, e)
            with self._lock:
                return self._dati.get(layer, [])
        elementi = _appiattisci(grezzo)
        for e in elementi:
            e["_id"] = _identificativo(layer, e)
            e["_layer"] = layer
        with self._lock:
            self._indicizza(layer, elementi)
        logger.info("[shadowbroker] %s: %d elementi", layer, len(elementi))
        return elementi

    def _indicizza(self, layer: str, elementi: List[Dict[str, Any]]) -> None:
        """Sostituisce i dati e l'indice di UN layer. Sempre sotto lock."""
        self._dati[layer] = elementi
        self._quando[layer] = time.time()
        self._per_id[layer] = {e["_id"]: e for e in elementi}

    def carica_molti(self, nomi: List[str], forza: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """Piu' layer, riusando quelli ancora buoni e chiedendo il resto in una
        sola richiesta."""
        da_chiedere = [n for n in nomi if forza or self.scaduto(n)]
        blocco: Dict[str, Any] = {}
        if da_chiedere:
            try:
                blocco = self._client.layers(da_chiedere)
            except Exception as e:
                logger.warning("[shadowbroker] lettura multipla fallita (%s), passo a una alla volta: %s",
                               da_chiedere, e)
                blocco = {}
        return self._assorbi(nomi, da_chiedere, blocco)

    def _assorbi(self, nomi: List[str], da_chiedere: List[str],
                 blocco: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Mette in magazzino il blocco appena letto e compone la risposta.

        Un layer che il blocco non porta (errore, layer geometrico escluso
        dalla lettura multipla) si ricarica da solo: una chiamata in piu' per
        quel layer, non un briefing monco.
        """
        fuori: Dict[str, List[Dict[str, Any]]] = {}
        for n in nomi:
            if n not in da_chiedere:
                fuori[n] = self._dati.get(n, [])
        for n in da_chiedere:
            if n in blocco:
                elementi = _appiattisci(blocco[n])
                for e in elementi:
                    e["_id"] = _identificativo(n, e)
                    e["_layer"] = n
                with self._lock:
                    self._indicizza(n, elementi)
                fuori[n] = elementi
            else:
                fuori[n] = self.carica(n, forza=True)
        return fuori

    # ── lettura in un solo giro ──────────────────────────────────────────

    def istantanea(self, nomi: List[str], extra: Optional[List[Dict[str, Any]]] = None,
                   con_riepilogo: bool = True,
                   forza: bool = False) -> Dict[str, Any]:
        """Riepilogo + layer scaduti + comandi indipendenti in UN round-trip.

        Un briefing a cache fredda faceva tre richieste HTTP in fila
        (`get_summary`, `get_layer_slice`, poi il comando del briefing): sono
        indipendenti fra loro — nessuna usa il risultato dell'altra — quindi
        viaggiano insieme su `/api/ai/channel/batch`, che lato loro le esegue
        in parallelo.

        Niente `compact` e niente playbook lato server: `get_layer_slice`
        resta quello non compatto, perche' la versione compatta butta via
        `lat`/`lng` e `link`.

        Ritorna::

            {"conteggi": {layer: n}, "layer": {nome: [elementi]},
             "extra": [(dati, errore), ...]}      # uno per comando in `extra`

        Le regole di cache non cambiano: si chiedono solo i layer scaduti, e
        quelli ancora buoni non toccano la rete. Se il batch cade, o risponde
        in una forma inattesa, si torna alle chiamate singole di prima.
        """
        extra = [dict(c) for c in (extra or [])]
        da_chiedere = [n for n in nomi if forza or self.scaduto(n)]
        # I layer geometrici non si mescolano agli altri (vedi client.layers):
        # restano fuori dal batch e si caricano da soli.
        sicuri = [n for n in da_chiedere if n not in LAYER_GEOMETRICI]

        comandi: List[Dict[str, Any]] = []
        i_riepilogo: Optional[int] = None
        i_layer: Optional[int] = None
        if con_riepilogo:
            i_riepilogo = len(comandi)
            comandi.append({"cmd": "get_summary", "args": {"compact": True}})
        if sicuri:
            i_layer = len(comandi)
            comandi.append({"cmd": "get_layer_slice", "args": {"layers": sicuri}})
        i_extra = len(comandi)
        comandi.extend(extra)

        risultati: Optional[List[Any]] = None
        if len(comandi) >= 2:
            try:
                r = self._client.batch(comandi)
                if isinstance(r, list) and len(r) == len(comandi):
                    risultati = r
                else:
                    logger.warning(
                        "[shadowbroker] batch: attesi %d risultati, ricevuto %s; "
                        "passo alle chiamate singole", len(comandi),
                        f"{len(r)} risultati" if isinstance(r, list) else type(r).__name__)
            except Exception as e:
                logger.warning("[shadowbroker] batch fallito (%s), passo alle chiamate singole", e)
        if risultati is None:
            return self._istantanea_sequenziale(nomi, extra, con_riepilogo, forza)

        conteggi: Dict[str, int] = {}
        if i_riepilogo is not None:
            dati, errore = _esito_batch("get_summary", risultati[i_riepilogo])
            if errore:
                logger.warning("[shadowbroker] riepilogo fallito: %s", errore)
            elif isinstance(dati, dict):
                grezzi = dati.get("counts") or {}
                conteggi = {k: v for k, v in grezzi.items() if isinstance(v, int)}

        blocco: Dict[str, Any] = {}
        if i_layer is not None:
            dati, errore = _esito_batch("get_layer_slice", risultati[i_layer])
            if errore:
                logger.warning("[shadowbroker] lettura multipla fallita (%s), passo a una alla volta: %s",
                               sicuri, errore)
            elif isinstance(dati, dict):
                blocco = dati.get("layers") or {}

        esiti = [_esito_batch(str(c.get("cmd") or "?"), risultati[i_extra + k])
                 for k, c in enumerate(extra)]
        return {"conteggi": conteggi, "layer": self._assorbi(nomi, da_chiedere, blocco),
                "extra": esiti}

    def _istantanea_sequenziale(self, nomi: List[str], extra: List[Dict[str, Any]],
                                con_riepilogo: bool, forza: bool) -> Dict[str, Any]:
        """Il percorso di prima: una richiesta per pezzo. Ripiego del batch."""
        conteggi = self.riepilogo() if con_riepilogo else {}
        strato = self.carica_molti(nomi, forza=forza)
        esiti: List[Tuple[Any, Optional[str]]] = []
        for c in extra:
            try:
                esiti.append((self._client.comando(str(c.get("cmd") or ""), c.get("args") or {}), None))
            except Exception as e:
                esiti.append((None, str(e)))
        return {"conteggi": conteggi, "layer": strato, "extra": esiti}

    def dettaglio(self, identificativo: str) -> Optional[Dict[str, Any]]:
        """L'elemento **intero**, senza nessuna riduzione.

        Il layer si ricava dal prefisso dell'identificativo, quindi la ricerca
        e' diretta. Se il layer non e' in memoria si tenta di caricarlo: il
        modello puo' citare un identificativo di un turno precedente.
        """
        ident = (identificativo or "").strip()
        if not ident:
            return None
        layer = ident.split(":", 1)[0] if ":" in ident else ""
        with self._lock:
            if layer and layer in self._per_id:
                trovato = self._per_id[layer].get(ident)
                if trovato is not None:
                    return trovato
            # Ripiego: identificativo senza prefisso riconoscibile.
            for mappa in self._per_id.values():
                if ident in mappa:
                    return mappa[ident]
        if layer and layer not in self._per_id:
            self.carica(layer)
            with self._lock:
                return self._per_id.get(layer, {}).get(ident)
        return None

    def registra(self, layer: str, elementi: List[Dict[str, Any]]) -> List[str]:
        """Mette in magazzino elementi che **non** vengono da ShadowBroker.

        Serve ai briefing che chiamano direttamente una fonte esterna — oggi i
        contratti federali da Finnhub. Senza questo passaggio quegli elementi
        non avrebbero un identificativo, e `osint_mappa evidenzia` risponderebbe
        "non trovato" su cose che il modello ha appena citato.

        Non ha scadenza: il layer non si ricarica da solo perche' non esiste di
        la'. Viene sostituito alla chiamata successiva del briefing.
        """
        copie = []
        for e in elementi:
            c = dict(e)
            c["_id"] = _identificativo(layer, c)
            c["_layer"] = layer
            c["_locale"] = True
            copie.append(c)
        with self._lock:
            self._indicizza(layer, copie)
            # Scadenza lontana: ricaricarlo da ShadowBroker darebbe una lista
            # vuota, cancellando gli identificativi appena consegnati al modello.
            self._quando[layer] = time.time() + 86400
        return [c["_id"] for c in copie]

    def riepilogo(self) -> Dict[str, int]:
        try:
            return self._client.riepilogo()
        except Exception as e:
            logger.warning("[shadowbroker] riepilogo fallito: %s", e)
            return {}

    def stato_cache(self) -> List[Tuple[str, int, float]]:
        with self._lock:
            return [(n, len(v), round(time.time() - self._quando.get(n, 0), 1))
                    for n, v in self._dati.items()]


_store: Optional[LayerStore] = None
_store_lock = threading.Lock()


def get_store() -> LayerStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = LayerStore()
        return _store
