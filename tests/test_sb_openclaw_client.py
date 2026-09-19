"""client.py: override dei layer (PUT/DELETE) e ascoltatore SSE.

L'ascoltatore non viene avviato da nessuno all'import: qui si accende a mano
con una connessione finta, e si spegne con lo stesso `stop_event` che userebbe
un compito di sfondo.
"""

import threading

import pytest

from src.shadowbroker import client as C


class _Risposta:
    """Finge la risposta di urlopen: iterabile riga per riga, context manager."""

    def __init__(self, righe):
        self._righe = list(righe)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._righe)


# ── override dei layer ───────────────────────────────────────────────────

def test_accendi_livelli_server_fa_un_put(monkeypatch):
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")
    visti = {}

    def finto_post(percorso, corpo, timeout, metodo="POST"):
        visti.update(percorso=percorso, corpo=corpo, metodo=metodo)
        return {"ok": True, "overrides": {"military": True}, "ignored": []}

    monkeypatch.setattr(c, "_post", finto_post)
    r = c.accendi_livelli_server({"military": True}, ttl_s=300)
    assert visti["metodo"] == "PUT"
    assert visti["percorso"] == "/api/ai/layer-overrides"
    assert visti["corpo"] == {"layers": {"military": True}, "ttl_seconds": 300.0}
    assert r["overrides"] == {"military": True}


def test_azzera_livelli_server_fa_una_delete_senza_corpo(monkeypatch):
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")
    visti = {}

    def finto_post(percorso, corpo, timeout, metodo="POST"):
        visti.update(percorso=percorso, corpo=corpo, metodo=metodo)
        return {"ok": True}

    monkeypatch.setattr(c, "_post", finto_post)
    c.azzera_livelli_server()
    assert visti["metodo"] == "DELETE" and visti["corpo"] is None


def test_il_comando_resta_un_post(monkeypatch):
    """La firma nuova non deve cambiare il canale agente."""
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")
    visti = {}

    def finto_post(percorso, corpo, timeout, metodo="POST"):
        visti.update(percorso=percorso, metodo=metodo)
        return {"result": {"ok": True, "data": {"x": 1}}}

    monkeypatch.setattr(c, "_post", finto_post)
    assert c.comando("get_summary", {}) == {"x": 1}
    assert visti == {"percorso": "/api/ai/channel/command", "metodo": "POST"}


# ── ascoltatore SSE ──────────────────────────────────────────────────────

def test_ascolta_eventi_spacchetta_event_e_data(monkeypatch):
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")
    righe = [
        b": keep-alive\n",
        b"event: connected\n",
        b'data: {"access_tier": "restricted"}\n',
        b"\n",
        b"event: alert\n",
        b'data: {"type": "alert", "label": "AF1"}\n',
        b"\n",
        b"\n",            # giro in piu': fa vedere lo stop al ciclo
    ]
    chiesto = {}

    def finto_urlopen(req, timeout=None):
        chiesto["url"] = req.full_url
        chiesto["accept"] = req.get_header("Accept")
        return _Risposta(righe)

    monkeypatch.setattr(C.urllib.request, "urlopen", finto_urlopen)

    stop = threading.Event()
    ricevuti = []

    def su_evento(tipo, dati):
        ricevuti.append((tipo, dati))
        if tipo == "alert":
            stop.set()

    c.ascolta_eventi(su_evento, stop)

    assert chiesto["url"].endswith("/api/ai/channel/sse")
    assert chiesto["accept"] == "text/event-stream"
    assert ricevuti[0] == ("connected", {"access_tier": "restricted"})
    assert ricevuti[1] == ("alert", {"type": "alert", "label": "AF1"})


def test_ascolta_eventi_si_riconnette_dopo_una_caduta(monkeypatch):
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")
    tentativi = []

    def finto_urlopen(req, timeout=None):
        tentativi.append(1)
        if len(tentativi) == 1:
            raise OSError("connessione rifiutata")
        return _Risposta([b"event: task\n", b'data: {"id": 1}\n', b"\n", b"\n"])

    monkeypatch.setattr(C.urllib.request, "urlopen", finto_urlopen)

    stop = threading.Event()
    ricevuti = []

    def su_evento(tipo, dati):
        ricevuti.append(tipo)
        stop.set()

    c.ascolta_eventi(su_evento, stop, timeout_lettura=1.0)
    assert len(tentativi) == 2
    assert ricevuti == ["task"]


def test_ascolta_eventi_non_parte_se_gia_fermato(monkeypatch):
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")

    def finto_urlopen(req, timeout=None):
        raise AssertionError("non doveva connettersi")

    monkeypatch.setattr(C.urllib.request, "urlopen", finto_urlopen)
    stop = threading.Event()
    stop.set()
    c.ascolta_eventi(lambda t, d: None, stop)


def test_callback_che_esplode_non_ferma_il_flusso(monkeypatch):
    c = C.ShadowBrokerClient("http://127.0.0.1:8000")
    righe = [b"event: a\n", b"data: 1\n", b"\n",
             b"event: b\n", b"data: 2\n", b"\n", b"\n"]
    monkeypatch.setattr(C.urllib.request, "urlopen",
                        lambda req, timeout=None: _Risposta(righe))
    stop = threading.Event()
    visti = []

    def su_evento(tipo, dati):
        visti.append(tipo)
        if tipo == "b":
            stop.set()
        raise ValueError("callback rotta")

    c.ascolta_eventi(su_evento, stop)
    assert visti == ["a", "b"]


def test_nessun_thread_all_import():
    """Il modulo non deve avviare niente da solo."""
    vivi = [t.name for t in threading.enumerate()]
    assert not any("shadowbroker" in n.lower() for n in vivi)
