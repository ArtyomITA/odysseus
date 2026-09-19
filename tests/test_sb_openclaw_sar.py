"""osint_sar: facciata sui comandi sar_* di OpenClaw.

Verifica il contratto (nome comando + parametri), la registrazione dello
strumento, e che il messaggio del backend quando il SAR e' spento arrivi
intero al modello.
"""

import json

import pytest

from src.agent_tools import shadowbroker_tools as T
from src.shadowbroker import schemi


class ClienteFinto:
    def __init__(self, risposte=None, errore=None):
        self.chiamate = []
        self._risposte = risposte or {}
        self._errore = errore

    def comando(self, cmd, args=None, timeout=None):
        self.chiamate.append((cmd, args or {}))
        if self._errore is not None:
            raise self._errore
        return self._risposte.get(cmd, {"ok": True})


@pytest.fixture
def sar(monkeypatch):
    def _fai(cliente):
        monkeypatch.setattr("src.shadowbroker.client.get_client", lambda: cliente)
        return T.SarTool()
    return _fai


def _dati(esito):
    assert esito.get("exit_code") == 0, esito
    return json.loads(esito["output"])


# ── registrazione ────────────────────────────────────────────────────────

def test_registrato_fra_i_gestori_e_negli_strumenti_osint():
    assert "osint_sar" in T.SHADOWBROKER_TOOL_HANDLERS
    assert "osint_sar" in T.OSINT_TOOL_NAMES
    assert "osint_sar" not in T.FINANCE_TOOL_NAMES


def test_schema_presente_e_valido():
    schema = next(s for s in schemi.OSINT_TOOL_SCHEMAS
                  if s["function"]["name"] == "osint_sar")
    p = schema["function"]["parameters"]
    assert schema["type"] == "function"
    assert schema["function"]["description"].strip()
    assert p["type"] == "object" and p["required"] == ["azione"]
    assert "azione" in p["properties"]
    for nome, campo in p["properties"].items():
        assert campo["type"] in ("string", "number", "integer", "boolean", "array"), nome
    # serializzabile: e' cio' che finisce nel prompt
    json.loads(json.dumps(schema))


def test_indice_semantico_lo_descrive():
    assert "osint_sar" in schemi.descrizioni_brevi()


def test_ogni_gestore_ha_uno_schema():
    nomi = {s["function"]["name"]
            for s in schemi.OSINT_TOOL_SCHEMAS + schemi.FINANCE_TOOL_SCHEMAS}
    assert set(T.SHADOWBROKER_TOOL_HANDLERS) - nomi == set()


# ── letture ──────────────────────────────────────────────────────────────

def test_stato(sar):
    c = ClienteFinto()
    sar(c).run({"azione": "stato"}, {})
    assert c.chiamate[0] == ("sar_status", {})


def test_anomalie_senza_luogo_usa_recent(sar):
    c = ClienteFinto()
    sar(c).run({"azione": "anomalie", "quante": 7}, {})
    assert c.chiamate[0] == ("sar_anomalies_recent", {"limit": 7})


def test_anomalie_con_punto_usa_near(sar):
    c = ClienteFinto()
    sar(c).run({"azione": "anomalie", "lat": 44.6, "lng": 33.5, "raggio_km": 120}, {})
    cmd, args = c.chiamate[0]
    assert cmd == "sar_anomalies_near"
    assert args["lat"] == 44.6 and args["lng"] == 33.5 and args["radius_km"] == 120


def test_scene_e_copertura(sar):
    c = ClienteFinto()
    sar(c).run({"azione": "scene", "area": "Sevastopol"}, {})
    assert c.chiamate[0] == ("sar_scene_search", {"aoi_id": "sevastopol", "limit": 25})
    c2 = ClienteFinto()
    sar(c2).run({"azione": "copertura", "area": "sevastopol"}, {})
    assert c2.chiamate[0] == ("sar_coverage_for_aoi", {"aoi_id": "sevastopol"})


def test_aree(sar):
    c = ClienteFinto(risposte={"sar_aoi_list": [{"id": "kerch"}]})
    r = sar(c).run({"azione": "aree"}, {})
    assert c.chiamate[0] == ("sar_aoi_list", {})
    assert _dati(r)["aree"][0]["id"] == "kerch"


# ── scritture ────────────────────────────────────────────────────────────

def test_aggiungi_area(sar):
    c = ClienteFinto()
    sar(c).run({"azione": "aggiungi_area", "lat": 45.3, "lng": 36.5,
                "nome": "Ponte di Kerch", "raggio_km": 40}, {})
    cmd, args = c.chiamate[0]
    assert cmd == "sar_aoi_add"
    assert args["center_lat"] == 45.3 and args["center_lon"] == 36.5
    assert args["radius_km"] == 40
    assert args["name"] == "Ponte di Kerch"
    assert args["id"] == "ponte_di_kerch"


def test_aggiungi_area_senza_punto(sar):
    c = ClienteFinto()
    r = sar(c).run({"azione": "aggiungi_area", "nome": "x"}, {})
    assert "lat" in r["error"] and c.chiamate == []


def test_rimuovi_sorveglia_centra(sar):
    c = ClienteFinto()
    sar(c).run({"azione": "rimuovi_area", "area": "kerch"}, {})
    assert c.chiamate[-1] == ("sar_aoi_remove", {"id": "kerch"})
    sar(c).run({"azione": "sorveglia", "area": "kerch"}, {})
    assert c.chiamate[-1] == ("sar_watch_anomaly", {"aoi_id": "kerch"})
    sar(c).run({"azione": "centra", "area": "kerch"}, {})
    assert c.chiamate[-1] == ("sar_focus_aoi", {"aoi_id": "kerch", "zoom": 8})


def test_scritture_senza_area(sar):
    c = ClienteFinto()
    for azione in ("rimuovi_area", "sorveglia", "centra"):
        r = sar(c).run({"azione": azione}, {})
        assert "area" in r["error"]
    assert c.chiamate == []


def test_tier_insufficiente_sulle_scritture(sar):
    c = ClienteFinto(errore=RuntimeError(
        "ShadowBroker 'sar_watch_anomaly': command requires full access tier"))
    r = sar(c).run({"azione": "sorveglia", "area": "kerch"}, {})
    assert "full" in r["error"] and "Non riprovo" in r["error"]


# ── SAR spento lato server ───────────────────────────────────────────────

def test_sar_spento_riporta_il_messaggio_del_backend(sar):
    c = ClienteFinto(errore=RuntimeError(
        "ShadowBroker 'sar_status': SAR OpenClaw integration disabled "
        "(MESH_SAR_OPENCLAW_ENABLED=false)"))
    r = sar(c).run({"azione": "stato"}, {})
    assert "SAR OpenClaw integration disabled" in r["error"]
    assert "MESH_SAR_OPENCLAW_ENABLED" in r["error"]


def test_azione_sconosciuta_elenca_le_ammesse(sar):
    c = ClienteFinto()
    r = sar(c).run({"azione": "radiografia"}, {})
    for nome in ("stato", "anomalie", "aree", "aggiungi_area", "centra"):
        assert nome in r["error"]
    assert c.chiamate == []


def test_output_sotto_il_tetto(sar):
    c = ClienteFinto(risposte={"sar_anomalies_recent":
                               [{"id": i, "nota": "x" * 400} for i in range(500)]})
    r = sar(c).run({"azione": "anomalie"}, {})
    assert len(r["output"]) <= T._MAX_CARATTERI + 200
    assert "TAGLIATO" in r["output"]
