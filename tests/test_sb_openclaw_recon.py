"""osint_recon: i lookup gia' esposti piu' `tipo='espandi'` (entity_expand)."""

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
def recon(monkeypatch):
    def _fai(cliente):
        monkeypatch.setattr("src.shadowbroker.client.get_client", lambda: cliente)
        return T.ReconTool()
    return _fai


def _dati(esito):
    assert esito.get("exit_code") == 0, esito
    return json.loads(esito["output"])


def test_lookup_classico_invariato(recon):
    c = ClienteFinto()
    recon(c).run({"tipo": "bgp", "valore": "AS15169"}, {})
    assert c.chiamate[0] == ("osint_lookup", {"tool": "bgp", "query": "AS15169",
                                              "bgp": "AS15169"})


@pytest.mark.parametrize("tipo", ["ip", "dns", "whois", "certs", "bgp", "sanctions",
                                  "cve", "mac", "github", "leaks", "threats"])
def test_tutti_i_lookup_passano(recon, tipo):
    c = ClienteFinto()
    r = recon(c).run({"tipo": tipo, "valore": "x"}, {})
    assert r["exit_code"] == 0
    assert c.chiamate[0][1]["tool"] == tipo


def test_espandi_manda_entity_expand(recon):
    c = ClienteFinto()
    r = recon(c).run({"tipo": "espandi", "valore": "Rosneft"}, {})
    assert c.chiamate[0] == ("entity_expand", {"type": "company", "id": "Rosneft"})
    assert _dati(r)["entita"] == "company"


def test_espandi_indovina_un_ip(recon):
    c = ClienteFinto()
    recon(c).run({"tipo": "espandi", "valore": "8.8.8.8"}, {})
    assert c.chiamate[0][1]["type"] == "ip"


def test_espandi_con_entita_esplicita(recon):
    c = ClienteFinto()
    recon(c).run({"tipo": "espandi", "valore": "IMO9123456", "entita": "vessel"}, {})
    assert c.chiamate[0][1]["type"] == "vessel"


def test_espandi_accetta_gli_alias_italiani(recon):
    c = ClienteFinto()
    recon(c).run({"tipo": "grafo", "valore": "RA-96023", "entita": "aereo"}, {})
    assert c.chiamate[0] == ("entity_expand", {"type": "aircraft", "id": "RA-96023"})


def test_entita_sconosciuta_elenca_le_ammesse(recon):
    c = ClienteFinto()
    r = recon(c).run({"tipo": "espandi", "valore": "x", "entita": "drago"}, {})
    for nome in ("aircraft", "vessel", "company", "person", "ip", "country"):
        assert nome in r["error"]
    assert c.chiamate == []


def test_tipo_sconosciuto_elenca_gli_ammessi(recon):
    c = ClienteFinto()
    r = recon(c).run({"tipo": "telepatia", "valore": "x"}, {})
    assert "espandi" in r["error"] and "sanctions" in r["error"]
    assert c.chiamate == []


def test_schema_enum_allineato_al_codice():
    schema = next(s for s in schemi.OSINT_TOOL_SCHEMAS
                  if s["function"]["name"] == "osint_recon")
    enum = set(schema["function"]["parameters"]["properties"]["tipo"]["enum"])
    assert enum == T.ReconTool._TIPI
    ent = set(schema["function"]["parameters"]["properties"]["entita"]["enum"])
    assert ent == T.ReconTool._ENTITA


def test_output_sotto_il_tetto(recon):
    c = ClienteFinto(risposte={"entity_expand": {"nodes": [{"id": "x" * 400}] * 500}})
    r = recon(c).run({"tipo": "espandi", "valore": "x"}, {})
    assert len(r["output"]) <= T._MAX_CARATTERI + 200
    assert "TAGLIATO" in r["output"]
