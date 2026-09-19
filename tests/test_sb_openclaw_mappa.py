"""osint_mappa: note sulla mappa e override dei layer lato server (OpenClaw).

Nessun backend: il client e' finto e registra i comandi che riceve. Quello
che si verifica e' il CONTRATTO verso ShadowBroker — nome esatto del comando
e parametri — piu' i messaggi d'errore che il modello si rilegge.
"""

import json

import pytest

from src.agent_tools import shadowbroker_tools as T


class ClienteFinto:
    def __init__(self, risposte=None, errore=None, errore_override=None):
        self.chiamate = []
        self.override = []
        self.azzerati = 0
        self._risposte = risposte or {}
        self._errore = errore
        self._errore_override = errore_override

    def comando(self, cmd, args=None, timeout=None):
        self.chiamate.append((cmd, args or {}))
        if self._errore is not None:
            raise self._errore
        return self._risposte.get(cmd, {"ok": True})

    def accendi_livelli_server(self, livelli, ttl_s=300.0):
        if self._errore_override is not None:
            raise self._errore_override
        self.override.append((dict(livelli), ttl_s))
        return {"ok": True, "overrides": dict(livelli), "ignored": []}

    def azzera_livelli_server(self):
        self.azzerati += 1
        return {"ok": True}


@pytest.fixture
def mappa(monkeypatch):
    def _fai(cliente):
        monkeypatch.setattr("src.shadowbroker.client.get_client", lambda: cliente)
        return T.MappaTool()
    return _fai


def _dati(esito):
    assert esito.get("exit_code") == 0, esito
    return json.loads(esito["output"])


# ── note sulla mappa (analysis zones) ────────────────────────────────────

def test_nota_manda_place_analysis_zone(mappa):
    c = ClienteFinto()
    r = mappa(c).run({"azione": "nota", "lat": 50.45, "lng": 30.52,
                      "testo": "batteria antiaerea spostata"}, {})
    cmd, args = c.chiamate[0]
    assert cmd == "place_analysis_zone"
    assert args["lat"] == 50.45 and args["lng"] == 30.52
    assert args["body"] == "batteria antiaerea spostata"
    assert args["title"] == "batteria antiaerea spostata"
    assert args["category"] == "analysis"
    assert _dati(r)["azione"] == "nota"


def test_nota_colore_diventa_categoria(mappa):
    c = ClienteFinto()
    mappa(c).run({"azione": "nota", "lat": 1, "lng": 2, "testo": "x", "colore": "rosso"}, {})
    assert c.chiamate[0][1]["category"] == "warning"


def test_nota_colore_sconosciuto_ripiega_su_analysis(mappa):
    c = ClienteFinto()
    mappa(c).run({"azione": "nota", "lat": 1, "lng": 2, "testo": "x", "colore": "fucsia"}, {})
    assert c.chiamate[0][1]["category"] == "analysis"


def test_nota_senza_testo_e_senza_punto(mappa):
    c = ClienteFinto()
    assert "testo" in mappa(c).run({"azione": "nota", "lat": 1, "lng": 2}, {})["error"]
    assert "lat" in mappa(c).run({"azione": "nota", "testo": "x"}, {})["error"]
    assert c.chiamate == []


def test_elenco_note(mappa):
    c = ClienteFinto(risposte={"list_analysis_zones": {"zones": [{"id": "ab12"}]}})
    r = mappa(c).run({"azione": "note"}, {})
    assert c.chiamate[0][0] == "list_analysis_zones"
    assert _dati(r)["note"]["zones"][0]["id"] == "ab12"


def test_cancella_nota(mappa):
    c = ClienteFinto()
    mappa(c).run({"azione": "cancella_nota", "id": "ab12"}, {})
    assert c.chiamate[0] == ("delete_analysis_zone", {"zone_id": "ab12"})


def test_cancella_nota_senza_id(mappa):
    c = ClienteFinto()
    r = mappa(c).run({"azione": "cancella_nota"}, {})
    assert "id" in r["error"] and c.chiamate == []


# ── tier: scrittura rifiutata ────────────────────────────────────────────

def test_nota_tier_insufficiente_messaggio_chiaro_e_nessun_ritentativo(mappa):
    c = ClienteFinto(errore=RuntimeError(
        "ShadowBroker HTTP 403: {\"detail\":\"command 'place_analysis_zone' "
        "requires full access tier\"}"))
    r = mappa(c).run({"azione": "nota", "lat": 1, "lng": 2, "testo": "x"}, {})
    assert r["exit_code"] == 1
    assert "full" in r["error"]
    assert "pannello AI" in r["error"]
    assert len(c.chiamate) == 1          # niente ritentativi


def test_cancella_nota_tier_insufficiente(mappa):
    c = ClienteFinto(errore=RuntimeError("ShadowBroker 'delete_analysis_zone': "
                                         "command requires full access tier"))
    r = mappa(c).run({"azione": "cancella_nota", "id": "z"}, {})
    assert "OPENCLAW_ACCESS_TIER=full" in r["error"]


# ── override dei layer lato server ───────────────────────────────────────

def test_livelli_manda_set_layers_e_accende_le_sorgenti(mappa):
    c = ClienteFinto()
    r = mappa(c).run({"azione": "livelli", "accendi": ["military_flights", "gdelt"]}, {})
    cmd, args = c.chiamate[0]
    assert cmd == "set_layers"
    assert args["on"] == ["military_flights", "gdelt"] and args["solo"] is True
    chiavi, ttl = c.override[0]
    assert chiavi == {"military": True, "global_incidents": True}
    assert ttl == 300.0
    assert _dati(r)["sorgenti_server"]["scadenza_s"] == 300


def test_livelli_sconosciuti_non_generano_override(mappa):
    c = ClienteFinto()
    mappa(c).run({"azione": "livelli", "accendi": ["layer_inventato"]}, {})
    assert c.chiamate[0][0] == "set_layers"
    assert c.override == []


def test_override_rotta_non_fa_fallire_la_vista(mappa):
    """set_layers resta la via maestra: l'override e' un di piu'."""
    c = ClienteFinto(errore_override=RuntimeError("HTTP 500"))
    r = mappa(c).run({"azione": "livelli", "accendi": ["ships"]}, {})
    d = _dati(r)
    assert d["azione"] == "livelli"
    assert d["sorgenti_server"]["applicate"] is False


def test_preset_accende_le_sorgenti_del_preset(mappa):
    c = ClienteFinto()
    mappa(c).run({"azione": "preset", "preset": "infrastruttura"}, {})
    assert c.chiamate[0][0] == "set_layers"
    chiavi, _ = c.override[0]
    assert chiavi["power_plants"] is True and chiavi["datacenters"] is True


def test_preset_sconosciuto_elenca_gli_ammessi(mappa):
    c = ClienteFinto()
    r = mappa(c).run({"azione": "preset", "preset": "pippo"}, {})
    for nome in ("financial", "conflitto", "infrastruttura"):
        assert nome in r["error"]


def test_ripristina_toglie_anche_le_override(mappa):
    c = ClienteFinto()
    mappa(c).run({"azione": "ripristina"}, {})
    assert c.chiamate[0] == ("set_layers", {"reset": True})
    assert c.azzerati == 1


def test_azione_sconosciuta_elenca_le_ammesse(mappa):
    c = ClienteFinto()
    r = mappa(c).run({"azione": "teletrasporto"}, {})
    for nome in ("centra", "livelli", "nota", "cancella_nota"):
        assert nome in r["error"]


def test_output_sotto_il_tetto(mappa):
    c = ClienteFinto(risposte={"list_analysis_zones": {
        "zones": [{"id": str(i), "body": "x" * 500} for i in range(400)]}})
    r = mappa(c).run({"azione": "note"}, {})
    assert len(r["output"]) <= T._MAX_CARATTERI + 200
    assert "TAGLIATO" in r["output"]
