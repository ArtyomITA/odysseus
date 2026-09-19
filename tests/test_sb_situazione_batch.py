"""`osint_situazione` a cache fredda: un solo giro HTTP.

Prima il briefing faceva tre richieste in fila — `get_summary`,
`get_layer_slice`, `gt_top_alerts` — che pero' non dipendono l'una dall'altra.
Adesso partono insieme su `/api/ai/channel/batch`.

Quello che questi banchi difendono:

  * a cache fredda **una** chiamata batch e **zero** comandi singoli;
  * a cache calda i layer non si richiedono (restano solo i due comandi che
    non hanno cache: riepilogo e classifica GT);
  * un sotto-comando caduto degrada solo la sua sezione, come prima;
  * batch irraggiungibile o risposta di forma inattesa -> si torna alle
    chiamate singole;
  * l'uscita dei due percorsi e' identica sugli stessi dati.
"""

import copy

import pytest

from src.shadowbroker import briefing as B
from src.shadowbroker import store as S


# ── dati finti ───────────────────────────────────────────────────────────

LAYER = {
    "gdelt": [
        {"name": "Kyiv, Ukraine", "num_articles": 120, "num_sources": 40,
         "goldstein": -7.5, "avg_tone": -6.23, "event_date": "20260918",
         "actors": ["UKR", "RUS"], "_headlines_list": [], "_urls_list": []},
        {"name": "Taipei, Taiwan", "num_articles": 30, "num_sources": 9,
         "goldstein": -2.0, "avg_tone": -1.1, "event_date": "20260918",
         "actors": ["TWN"], "_headlines_list": [], "_urls_list": []},
    ],
    "threat_level": [{"score": 63, "level": "ORANGE", "drivers": ["gdelt", "correlations"]}],
    "correlations": [
        {"type": "air_incident", "severity": "high", "score": 0.91,
         "drivers": ["volo militare", "allarme aereo"], "lat": 50.4, "lng": 30.5},
    ],
    "news": [
        {"title": "Esplosione a Odessa", "source": "Reuters", "oracle_score": 9,
         "link": "https://example.invalid/a", "published": "Fri, 18 Sep 2026 10:00:00 GMT",
         "machine_assessment": "grave"},
        {"title": "Nulla di che", "source": "X", "oracle_score": 2,
         "link": "https://example.invalid/b"},
    ],
}

CONTEGGI = {"gdelt": 2, "news": 2, "correlations": 1, "threat_level": 1,
            "prediction_markets": 0, "gps_jamming": 0, "liveuamap": 0,
            "cctv": 0, "financial": 0}

GT = {"alerts": [{"lat": 50.45, "lng": 30.52, "risk": 0.8123, "conflict": 0.51,
                  "unrest": 0.22, "contagion": 0.13, "ignition": True,
                  "region_label": "Kyiv"}],
      "engine_regions": 1641, "tracked_regions": 207}

COMANDI_ATTESI = [
    {"cmd": "get_summary", "args": {"compact": True}},
    {"cmd": "get_layer_slice",
     "args": {"layers": ["gdelt", "threat_level", "correlations", "news"]}},
    {"cmd": "gt_top_alerts", "args": {}},
]


_NORMALE = object()          # sentinella: nessuna forma anomala forzata


class FintoClient:
    """Il minimo del client vero, con il conto di quello che viene chiesto.

    `batch` restituisce gia' i `data` spacchettati, come il `batch()` vero.
    `errori` mappa un comando al dizionario di errore che il backend
    metterebbe al suo posto dentro il batch.
    """

    def __init__(self, batch_esplode=False, batch_forma=_NORMALE, errori=None):
        self.batch_chiamate = []
        self.singoli = []
        self.batch_esplode = batch_esplode
        self.batch_forma = batch_forma
        self.errori = errori or {}

    # -- risposte per comando -------------------------------------------
    def _dati(self, cmd, args):
        if cmd in self.errori:
            return self.errori[cmd]
        if cmd == "get_summary":
            return {"counts": copy.deepcopy(CONTEGGI)}
        if cmd == "get_layer_slice":
            return {"layers": {n: copy.deepcopy(LAYER.get(n) or [])
                               for n in (args or {}).get("layers") or []}}
        if cmd == "gt_top_alerts":
            return copy.deepcopy(GT)
        raise RuntimeError(f"comando finto sconosciuto: {cmd}")

    # -- canale agente ---------------------------------------------------
    def batch(self, comandi, timeout=None):
        self.batch_chiamate.append(copy.deepcopy(comandi))
        if self.batch_esplode:
            raise RuntimeError("ShadowBroker non risponde")
        if self.batch_forma is not _NORMALE:
            return self.batch_forma
        return [self._dati(c.get("cmd"), c.get("args")) for c in comandi]

    def comando(self, cmd, args=None, timeout=None):
        self.singoli.append(("comando", cmd))
        dati = self._dati(cmd, args)
        if isinstance(dati, dict) and dati.get("ok") is False:
            raise RuntimeError(f"ShadowBroker '{cmd}': {dati.get('detail')}")
        return dati

    # -- scorciatoie che il percorso sequenziale usa ----------------------
    def riepilogo(self):
        self.singoli.append(("riepilogo", "get_summary"))
        dati = self._dati("get_summary", {})
        if isinstance(dati, dict) and dati.get("ok") is False:
            raise RuntimeError("riepilogo fallito")
        return {k: v for k, v in (dati.get("counts") or {}).items() if isinstance(v, int)}

    def layers(self, nomi, limite=None, timeout=None):
        self.singoli.append(("layers", tuple(nomi)))
        dati = self._dati("get_layer_slice", {"layers": nomi})
        if isinstance(dati, dict) and dati.get("ok") is False:
            raise RuntimeError("lettura multipla fallita")
        return dati.get("layers") or {}

    def layer(self, nome, limite=None, timeout=None):
        self.singoli.append(("layer", nome))
        return copy.deepcopy(LAYER.get(nome) or [])


@pytest.fixture
def monta(monkeypatch):
    """Monta uno store nuovo su un client finto e lo mette sotto il briefing."""

    def _monta(**kw):
        finto = FintoClient(**kw)
        magazzino = S.LayerStore(client=finto)
        monkeypatch.setattr(B, "get_store", lambda: magazzino)
        return finto, magazzino

    return _monta


# ── cache fredda: un solo giro ───────────────────────────────────────────

def test_cache_fredda_un_solo_batch_e_zero_comandi_singoli(monta):
    finto, _ = monta()
    fuori = B.situazione()

    assert len(finto.batch_chiamate) == 1
    assert finto.batch_chiamate[0] == COMANDI_ATTESI
    assert finto.singoli == []

    # e il briefing e' quello di sempre
    assert fuori["tipo"] == "situazione_globale"
    assert fuori["minaccia_globale"]["punteggio"] == 63
    assert [v["dove"] for v in fuori["piu_coperti"]] == ["Kyiv, Ukraine", "Taipei, Taiwan"]
    assert fuori["anomalie"][0]["tipo"] == "air_incident"
    assert fuori["notizie_critiche"][0]["titolo"] == "Esplosione a Odessa"
    assert fuori["regioni_a_rischio"][0]["rischio"] == 0.812
    assert "prediction_markets: " in fuori["non_osservabile"][0]


def test_get_layer_slice_resta_non_compatto(monta):
    """`compact` butta via lat/lng e link: non deve comparire negli args."""
    finto, _ = monta()
    B.situazione()
    args = finto.batch_chiamate[0][1]["args"]
    assert "compact" not in args
    assert args["layers"] == ["gdelt", "threat_level", "correlations", "news"]


# ── cache calda ──────────────────────────────────────────────────────────

def test_cache_calda_non_richiede_i_layer(monta):
    finto, _ = monta()
    B.situazione()
    finto.batch_chiamate.clear()

    fuori = B.situazione()
    comandi = finto.batch_chiamate[0]
    # Nessun get_layer_slice: i quattro layer sono ancora buoni.
    assert [c["cmd"] for c in comandi] == ["get_summary", "gt_top_alerts"]
    assert finto.singoli == []
    assert len(finto.batch_chiamate) == 1
    # i dati arrivano dal magazzino, non dalla rete
    assert len(fuori["piu_coperti"]) == 2


# ── degrado per singolo comando ──────────────────────────────────────────

def test_gt_caduto_degrada_solo_la_sua_sezione(monta):
    finto, _ = monta(errori={"gt_top_alerts": {"ok": False, "detail": "engine offline"}})
    fuori = B.situazione()

    assert len(finto.batch_chiamate) == 1
    assert "regioni_a_rischio" not in fuori
    assert fuori["gt_non_disponibile"] == "ShadowBroker 'gt_top_alerts': engine offline"
    # tutto il resto c'e'
    assert fuori["minaccia_globale"]["livello"] == "ORANGE"
    assert len(fuori["piu_coperti"]) == 2


def test_riepilogo_caduto_non_uccide_il_briefing(monta):
    finto, _ = monta(errori={"get_summary": {"ok": False, "detail": "no"}})
    fuori = B.situazione()
    assert len(finto.batch_chiamate) == 1
    assert finto.singoli == []
    # senza conteggi ogni layer interessante risulta un buco: dichiarato, non
    # spacciato per "tutto tranquillo".
    assert len(fuori["non_osservabile"]) == 5
    assert len(fuori["piu_coperti"]) == 2


def test_layer_slice_caduto_ricade_sui_singoli_layer(monta):
    finto, _ = monta(errori={"get_layer_slice": {"ok": False, "detail": "layer store busy"}})
    fuori = B.situazione()

    assert len(finto.batch_chiamate) == 1
    # quattro letture singole di ripiego, una per layer
    assert [n for tipo, n in finto.singoli if tipo == "layer"] == [
        "gdelt", "threat_level", "correlations", "news"]
    assert len(fuori["piu_coperti"]) == 2
    assert fuori["regioni_a_rischio"][0]["conflitto"] == 0.51


# ── ripiego sequenziale ──────────────────────────────────────────────────

def test_batch_irraggiungibile_ripiega_sul_sequenziale(monta):
    finto, _ = monta(batch_esplode=True)
    fuori = B.situazione()

    assert len(finto.batch_chiamate) == 1
    assert finto.singoli == [
        ("riepilogo", "get_summary"),
        ("layers", ("gdelt", "threat_level", "correlations", "news")),
        ("comando", "gt_top_alerts"),
    ]
    assert fuori["minaccia_globale"]["punteggio"] == 63
    assert fuori["regioni_a_rischio"][0]["rischio"] == 0.812


@pytest.mark.parametrize("forma", [[], {"results": []}, None, ["solo", "due"]])
def test_forma_inattesa_ripiega_sul_sequenziale(monta, forma):
    finto, _ = monta(batch_forma=forma)
    fuori = B.situazione()
    assert len(finto.batch_chiamate) == 1
    assert [t for t, _ in finto.singoli] == ["riepilogo", "layers", "comando"]
    assert len(fuori["piu_coperti"]) == 2


# ── i due percorsi danno la stessa cosa ──────────────────────────────────

def _senza_ora(d):
    d = dict(d)
    d.pop("ora_utc", None)
    return d


def test_batch_e_sequenziale_danno_la_stessa_uscita(monta):
    finto_b, _ = monta()
    da_batch = _senza_ora(B.situazione())
    assert len(finto_b.batch_chiamate) == 1

    finto_s, _ = monta(batch_esplode=True)
    da_sequenziale = _senza_ora(B.situazione())
    assert finto_s.singoli

    assert da_batch == da_sequenziale


# ── lo store da solo ─────────────────────────────────────────────────────

def test_istantanea_senza_extra_e_senza_riepilogo_non_usa_il_batch():
    """Un comando solo non e' un batch: resta la chiamata singola."""
    finto = FintoClient()
    magazzino = S.LayerStore(client=finto)
    r = magazzino.istantanea(["gdelt"], con_riepilogo=False)
    assert finto.batch_chiamate == []
    assert finto.singoli == [("layers", ("gdelt",))]
    assert r["conteggi"] == {} and r["extra"] == []
    assert len(r["layer"]["gdelt"]) == 2


def test_esito_batch_traduce_l_errore_come_comando():
    assert S._esito_batch("gt_top_alerts", {"ok": False, "detail": "boom"}) == (
        None, "ShadowBroker 'gt_top_alerts': boom")
    assert S._esito_batch("gt_top_alerts", None)[1].endswith("nessun risultato nel batch")
    assert S._esito_batch("x", {"alerts": []}) == ({"alerts": []}, None)
