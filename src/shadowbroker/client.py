"""Client HTTP verso ShadowBroker.

Su loopback il canale agente non richiede firma: verificato, risponde in chiaro.
Tutta la parte HMAC del loro protocollo riguarda un agente su un'altra macchina.

Tre difese che non sono opzionali, ognuna corrisponde a un difetto misurato:

  * **Backoff sul rate limiter.** Interrogare i layer di fila da HTTP 429 dopo
    ~20 richieste. Il loro `slowapi` non manda `Retry-After`, quindi si aspetta
    a scalare.

  * **Blocco dei comandi mostruosi.** `get_telemetry` restituisce 2.470.667
    token e `get_slow_telemetry` 2.300.977: 50 volte il nostro contesto. Non
    esiste una ragione per chiamarli, e se qualcuno ci prova deve fallire in
    modo rumoroso invece di riempire la memoria.

  * **Nome corretto del parametro raggio.** `/api/ai/news-near` accetta solo
    `radius`. Passando `radius_km` o `radius_miles` il valore viene **ignorato
    in silenzio** e si ricade su 500 miglia: chiedere "entro 50 km da Kyiv"
    restituisce Mosca. Qui si normalizza sempre, e le distanze si ricontrollano
    comunque a valle (vedi geo.py).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_API = "http://127.0.0.1:8000"

# Comandi che restituiscono l'intero magazzino. Misurati: 2,3-2,4 milioni di
# token. Bloccati a monte, sempre.
COMANDI_VIETATI = frozenset({"get_telemetry", "get_slow_telemetry", "get_report"})

# Layer che non sono liste di elementi ma un unico oggetto geometrico:
# `limit_per_layer` non li tocca. `frontlines` con limite 1 costa comunque
# 18.769 token, perche' e' il poligono intero del fronte ucraino.
LAYER_GEOMETRICI = frozenset({"frontlines"})

_TIMEOUT_NORMALE = 30.0
_TIMEOUT_LUNGO = 120.0
_TENTATIVI = 4


class ShadowBrokerNonRaggiungibile(RuntimeError):
    """ShadowBroker non risponde. Distinta da un errore di comando."""


class ShadowBrokerClient:
    def __init__(self, base: Optional[str] = None):
        self.base = (base or os.getenv("SHADOWBROKER_API_URL") or DEFAULT_API).rstrip("/")
        self._lock = threading.Lock()
        # Il rate limiter e' per processo lato loro: serializzare qui evita di
        # farci bloccare da soli con richieste concorrenti.
        self._ultima_chiamata = 0.0
        self._pausa_minima = 0.12

    # ── trasporto ────────────────────────────────────────────────────────

    def _post(self, percorso: str, corpo: Optional[Dict[str, Any]], timeout: float,
              metodo: str = "POST") -> Dict[str, Any]:
        # `metodo` serve alle API REST che non sono POST (le override dei layer
        # sono PUT/DELETE): stesso backoff, stesso rate limiting, un solo posto.
        dati = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        req = urllib.request.Request(
            f"{self.base}{percorso}",
            data=dati,
            headers={"Content-Type": "application/json"},
            method=metodo,
        )
        ultimo: Optional[Exception] = None
        for tentativo in range(_TENTATIVI):
            with self._lock:
                attesa = self._pausa_minima - (time.time() - self._ultima_chiamata)
                if attesa > 0:
                    time.sleep(attesa)
                self._ultima_chiamata = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and tentativo < _TENTATIVI - 1:
                    # Nessun Retry-After nelle loro risposte: si sale a scalare.
                    time.sleep(1.5 * (tentativo + 1))
                    ultimo = e
                    continue
                corpo_err = ""
                try:
                    corpo_err = e.read()[:200].decode("utf-8", "replace")
                except Exception:
                    pass
                raise RuntimeError(f"ShadowBroker HTTP {e.code}: {corpo_err}") from e
            except (urllib.error.URLError, OSError) as e:
                ultimo = e
                if tentativo < _TENTATIVI - 1:
                    time.sleep(1.0 * (tentativo + 1))
                    continue
                raise ShadowBrokerNonRaggiungibile(
                    f"ShadowBroker non risponde su {self.base}: {e}"
                ) from e
        raise ShadowBrokerNonRaggiungibile(f"ShadowBroker: tentativi esauriti ({ultimo})")

    def _get(self, percorso: str, parametri: Optional[Dict[str, Any]] = None,
             timeout: float = _TIMEOUT_NORMALE) -> Dict[str, Any]:
        url = f"{self.base}{percorso}"
        if parametri:
            url += "?" + urllib.parse.urlencode(parametri)
        for tentativo in range(_TENTATIVI):
            with self._lock:
                attesa = self._pausa_minima - (time.time() - self._ultima_chiamata)
                if attesa > 0:
                    time.sleep(attesa)
                self._ultima_chiamata = time.time()
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and tentativo < _TENTATIVI - 1:
                    time.sleep(1.5 * (tentativo + 1))
                    continue
                raise RuntimeError(f"ShadowBroker HTTP {e.code} su {percorso}") from e
            except (urllib.error.URLError, OSError) as e:
                if tentativo < _TENTATIVI - 1:
                    time.sleep(1.0 * (tentativo + 1))
                    continue
                raise ShadowBrokerNonRaggiungibile(f"ShadowBroker non risponde: {e}") from e
        raise ShadowBrokerNonRaggiungibile("ShadowBroker: tentativi esauriti")

    # ── canale agente ────────────────────────────────────────────────────

    def comando(self, cmd: str, args: Optional[Dict[str, Any]] = None,
                timeout: float = _TIMEOUT_NORMALE) -> Any:
        """Un comando sul canale agente. Restituisce il `data` gia' spacchettato.

        L'involucro di ShadowBroker e'
        `{ok, command_id, tier, status, result: {ok, data}}` — al chiamante non
        serve niente di tutto cio'.
        """
        if cmd in COMANDI_VIETATI:
            raise ValueError(
                f"comando '{cmd}' bloccato: restituisce milioni di token "
                f"(misurato: get_telemetry = 2.470.667). Usare get_layer_slice."
            )
        risposta = self._post("/api/ai/channel/command", {"cmd": cmd, "args": args or {}}, timeout)
        risultato = risposta.get("result") or {}
        if isinstance(risultato, dict):
            if risultato.get("ok") is False:
                dettaglio = risultato.get("detail") or risultato.get("message") or "errore ignoto"
                raise RuntimeError(f"ShadowBroker '{cmd}': {dettaglio}")
            return risultato.get("data", risultato)
        return risultato

    def avvisi_watchdog(self, timeout: float = 8.0) -> List[Dict[str, Any]]:
        """Drena gli avvisi che il watchdog di ShadowBroker ha spinto verso di noi.

        Il watchdog valuta i watch attivi (callsign, geofence, keyword news) e
        chiama `channel.push_task("alert", ...)`; `/api/ai/channel/poll` li
        consegna (lettura distruttiva). Ritorna solo le voci di tipo alert.
        """
        try:
            r = self._post("/api/ai/channel/poll", {}, timeout)
        except Exception:
            return []
        tasks = (r or {}).get("tasks") or (r or {}).get("pending") or []
        avvisi = [t for t in tasks
                  if str(t.get("type") or t.get("task_type") or "").lower() == "alert"]
        return avvisi or [t for t in tasks if isinstance(t, dict)]

    def http_get(self, percorso: str, parametri: Optional[Dict[str, Any]] = None,
                 timeout: float = _TIMEOUT_NORMALE) -> Any:
        """Un endpoint HTTP diretto di ShadowBroker (non il canale agente).

        Serve per i tool che usano le API REST della piattaforma (geocode,
        feed cyber, radio, satellite): quelle non passano da `/channel/command`.
        Su loopback l'auth e' bypassata, compreso `require_local_operator`.
        """
        return self._get(percorso, parametri, timeout)

    def http_post(self, percorso: str, corpo: Dict[str, Any],
                  timeout: float = _TIMEOUT_NORMALE) -> Any:
        """POST verso un endpoint HTTP diretto di ShadowBroker."""
        return self._post(percorso, corpo, timeout)

    # ── override dei layer lato server ───────────────────────────────────
    #
    # `set_layers` (canale agente) muove l'INTERFACCIA: il cruscotto accende
    # e spegne le sue caselle. `/api/ai/layer-overrides` invece accende la
    # SORGENTE: `effective_layers()` unisce le override allo stato
    # dell'operatore, e senza di loro un layer che lui tiene spento lato
    # server si accende vuoto nel browser. Servono entrambe, non sono
    # alternative. L'override scade da sola (TTL) e non tocca le preferenze
    # dell'operatore: niente da ripristinare se la conversazione muore.

    def accendi_livelli_server(self, livelli: Dict[str, bool],
                               ttl_s: float = 300.0) -> Dict[str, Any]:
        """Accende (o spegne) lato server dei layer per `ttl_s` secondi.

        Le chiavi sono quelle dei fetcher (`military`, non `military_flights`):
        quelle sconosciute tornano in `ignored`. Ogni PUT sostituisce la mappa
        intera e fa ripartire il TTL.
        """
        return self._post(
            "/api/ai/layer-overrides",
            {"layers": {str(k): bool(v) for k, v in livelli.items()},
             "ttl_seconds": float(ttl_s)},
            _TIMEOUT_NORMALE, metodo="PUT")

    def azzera_livelli_server(self) -> Dict[str, Any]:
        """Toglie tutte le override: torna lo stato scelto dall'operatore."""
        return self._post("/api/ai/layer-overrides", None,
                          _TIMEOUT_NORMALE, metodo="DELETE")

    # ── flusso eventi (SSE) ──────────────────────────────────────────────

    def ascolta_eventi(self, callback, stop_event,
                       timeout_lettura: float = 60.0) -> None:
        """Ascolta `/api/ai/channel/sse` e chiama `callback(evento, dati)`.

        BLOCCANTE e non collegata al ciclo dell'agente: qui c'e' solo il
        motore. Un eventuale compito di sfondo la userebbe cosi'::

            stop = threading.Event()
            def su_evento(tipo, dati):
                if tipo in ("alert", "task"):
                    coda_avvisi.put(dati)      # poi li racconta osint_situazione
            threading.Thread(target=client.ascolta_eventi,
                             args=(su_evento, stop), daemon=True).start()

        Attenzione a una cosa sola: il flusso SSE drena la STESSA coda di
        `avvisi_watchdog()` (lettura distruttiva lato loro). O si ascolta, o
        si interroga: usarli insieme significa perdere meta' degli avvisi.

        Eventi che il backend spinge: `connected`, `layer_changed`, `task`,
        `alert`, `heartbeat` (ogni 15 s, tiene viva la connessione). Alla
        caduta si riconnette a scalare (1, 2, 4… fino a 30 s); `stop_event`
        ferma sia l'attesa sia la lettura. Solo libreria standard.
        """
        attesa = 1.0
        while not stop_event.is_set():
            try:
                req = urllib.request.Request(
                    f"{self.base}/api/ai/channel/sse",
                    headers={"Accept": "text/event-stream"},
                )
                with urllib.request.urlopen(req, timeout=timeout_lettura) as r:
                    attesa = 1.0
                    evento, righe = "message", []
                    for grezza in r:
                        if stop_event.is_set():
                            return
                        riga = grezza.decode("utf-8", "replace").rstrip("\r\n")
                        if not riga:
                            if righe:
                                corpo: Any = "\n".join(righe)
                                try:
                                    corpo = json.loads(corpo)
                                except (ValueError, TypeError):
                                    pass
                                try:
                                    callback(evento, corpo)
                                except Exception:
                                    logger.exception("[shadowbroker] callback SSE fallita")
                            evento, righe = "message", []
                        elif riga.startswith(":"):
                            continue          # commento di keep-alive
                        elif riga.startswith("event:"):
                            evento = riga[6:].strip() or "message"
                        elif riga.startswith("data:"):
                            righe.append(riga[5:].lstrip())
            except Exception as e:
                logger.info("[shadowbroker] SSE caduto (%s), riprovo fra %.0f s",
                            type(e).__name__, attesa)
            if stop_event.wait(attesa):
                return
            attesa = min(attesa * 2.0, 30.0)

    def batch(self, comandi: List[Dict[str, Any]],
              timeout: float = _TIMEOUT_LUNGO) -> List[Any]:
        """Fino a 20 comandi in una richiesta, eseguiti in parallelo lato loro.

        Misurato: 4 comandi in 7,2 s contro tre round-trip sequenziali. Si usa
        ogni volta che servono due o piu' letture.
        """
        for c in comandi:
            if c.get("cmd") in COMANDI_VIETATI:
                raise ValueError(f"comando '{c.get('cmd')}' bloccato nel batch")
        if len(comandi) > 20:
            raise ValueError(f"il batch accetta al massimo 20 comandi, ricevuti {len(comandi)}")
        risposta = self._post("/api/ai/channel/batch", {"commands": comandi}, timeout)
        fuori: List[Any] = []
        for r in risposta.get("results") or []:
            if isinstance(r, dict):
                interno = r.get("result") if "result" in r else r
                if isinstance(interno, dict):
                    fuori.append(interno.get("data", interno))
                    continue
            fuori.append(r)
        return fuori

    # ── letture dei layer ────────────────────────────────────────────────

    def layer(self, nome: str, limite: Optional[int] = None,
              timeout: float = _TIMEOUT_LUNGO) -> Any:
        """Un layer intero (o limitato). Niente `compact`: quella modalita' butta
        via `lat`/`lng` e `link`, che servono per la mappa e per citare le fonti.
        La compressione la facciamo noi, tenendo cio' che conta (vedi sagome.py).
        """
        args: Dict[str, Any] = {"layers": [nome]}
        if limite is not None:
            args["limit_per_layer"] = limite
        dati = self.comando("get_layer_slice", args, timeout=timeout)
        if isinstance(dati, dict):
            return (dati.get("layers") or {}).get(nome)
        return None

    def layers(self, nomi: List[str], limite: Optional[int] = None,
               timeout: float = _TIMEOUT_LUNGO) -> Dict[str, Any]:
        """Piu' layer in una chiamata. I layer geometrici vanno chiesti da soli:
        mescolati agli altri fanno esplodere la risposta (misurato: i 4 layer di
        conflitto insieme = 47.891 token, il 97% del contesto).
        """
        sicuri = [n for n in nomi if n not in LAYER_GEOMETRICI]
        scartati = [n for n in nomi if n in LAYER_GEOMETRICI]
        if scartati:
            logger.info("[shadowbroker] layer geometrici esclusi dalla lettura multipla: %s", scartati)
        if not sicuri:
            return {}
        args: Dict[str, Any] = {"layers": sicuri}
        if limite is not None:
            args["limit_per_layer"] = limite
        dati = self.comando("get_layer_slice", args, timeout=timeout)
        if isinstance(dati, dict):
            return dati.get("layers") or {}
        return {}

    def riepilogo(self) -> Dict[str, int]:
        """Quanti elementi ha ogni layer adesso. ~968 token, la lettura piu'
        economica che dice davvero qualcosa."""
        dati = self.comando("get_summary", {"compact": True})
        conteggi = (dati or {}).get("counts") or {}
        return {k: v for k, v in conteggi.items() if isinstance(v, int)}

    def news_vicino(self, lat: float, lng: float, raggio_miglia: float = 200) -> Dict[str, Any]:
        """Cluster GDELT vicino a un punto.

        `radius` e' l'unico nome che ShadowBroker legge: `radius_km` e
        `radius_miles` vengono ignorati in silenzio e si ricade su 500 miglia.
        Anche cosi' il filtro non e' affidabile — le distanze si ricontrollano
        in geo.py.
        """
        return self._get("/api/ai/news-near",
                         {"lat": lat, "lng": lng, "radius": raggio_miglia})

    def stato(self) -> Dict[str, Any]:
        """Vivo o no, senza costo apprezzabile (~133 token)."""
        try:
            return {"vivo": True, "dati": self.comando("channel_status", {})}
        except Exception as e:
            return {"vivo": False, "errore": str(e)[:200]}


_client: Optional[ShadowBrokerClient] = None
_client_lock = threading.Lock()


def get_client() -> ShadowBrokerClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ShadowBrokerClient()
        return _client
