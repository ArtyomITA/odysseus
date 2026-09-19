"""Leve per modelli piccoli/obbedienti (LFM2.5-2.6B), tutte env-gated.

Tre interruttori, tutti con default = comportamento storico (il profilo Ling
non deve cambiare di un byte):

* ``ODYSSEUS_INTENT_NUDGE_MAX_CHARS`` (default 400) — soglia di lunghezza del
  nudge "intento senza azione"; oltre i 400 la promessa deve stare in coda.
* ``ODYSSEUS_EMPTY_TOOLCALL_RETRY`` (default 0) — un rilancio quando il
  modello emette una coppia di marker tool_call VUOTA.
* ``ODYSSEUS_BROWSER_AUTO_ESCALATION`` (default 0) — sblocco automatico di una
  categoria specialista dopo 2 fallimenti consecutivi di un adattatore.

Gli helper sono funzioni pure a livello di modulo proprio per essere testabili
senza modello vivo; in coda ci sono due prove di integrazione che guidano
``stream_agent_loop`` con uno ``stream_llm_with_fallback`` finto (stesso
schema di ``tests/test_agent_rounds_exhausted.py``).
"""

import asyncio
import json

import pytest

import src.agent_loop as al
from src.agent_tools.browser_tools import BROWSER_SPECIALIST_CATEGORIES


# ── Cambio 1: soglia del nudge configurabile ─────────────────────────────

def test_nudge_max_chars_default_e_storico(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_INTENT_NUDGE_MAX_CHARS", raising=False)
    assert al._nudge_max_chars() == 400


def test_nudge_max_chars_legge_env(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_INTENT_NUDGE_MAX_CHARS", "900")
    assert al._nudge_max_chars() == 900


def test_nudge_max_chars_valore_rotto_torna_al_default(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_INTENT_NUDGE_MAX_CHARS", "non-un-numero")
    assert al._nudge_max_chars() == 400


def test_promessa_corta_resta_nudgiata_come_prima():
    # < 400 caratteri: regola storica, la posizione del match non conta.
    testo = "Ora devo cercare i mercati." + " coda." * 10
    assert len(testo) < 400
    assert al._promessa_in_coda(testo, 0, 400) is True
    assert al._promessa_in_coda(testo, 0, 900) is True


def test_promessa_lunga_non_nudgiata_col_default():
    testo = "x" * 664
    assert al._promessa_in_coda(testo, 620, 400) is False


def test_promessa_lunga_in_coda_nudgiata_con_soglia_alzata():
    # Il caso misurato: 664 caratteri chiusi da "Chiamero' fin_mercati ...".
    testo = "x" * 664
    assert al._promessa_in_coda(testo, 620, 900) is True


def test_promessa_lunga_a_meta_testo_non_nudgiata():
    # Risposta FINALE lunga che cita un intento a meta': mai nudgiare.
    testo = "x" * 664
    assert al._promessa_in_coda(testo, 100, 900) is False


def test_promessa_lunga_confine_ultimi_300_caratteri():
    testo = "x" * 700
    assert al._promessa_in_coda(testo, 400, 900) is True     # esattamente 700-300
    assert al._promessa_in_coda(testo, 399, 900) is False


def test_promessa_senza_match_o_senza_testo():
    assert al._promessa_in_coda("", 0, 900) is False
    assert al._promessa_in_coda("qualcosa", None, 900) is False


def test_promessa_accetta_un_match_regex_vero():
    testo = "Tutto pronto. Ora devo cercare i prezzi."
    match = al.re.compile(r"Ora devo cercare").search(testo)
    assert al._promessa_in_coda(testo, match, 400) is True


# ── Cambio 2: tool call vuota ────────────────────────────────────────────

def test_toolcall_vuota_marker_adiacenti():
    trovata, pulito = al._toolcall_vuota("<|tool_call_start|><|tool_call_end|>", [])
    assert trovata is True
    assert pulito == ""


def test_toolcall_vuota_con_spazi_o_lista_vuota():
    for corpo in ("", " ", "\n  \n", "[]", " [ ] "):
        testo = f"<|tool_call_start|>{corpo}<|tool_call_end|>"
        trovata, pulito = al._toolcall_vuota(testo, [])
        assert trovata is True, corpo
        assert pulito == "", corpo


def test_toolcall_vuota_lascia_il_testo_intorno():
    trovata, pulito = al._toolcall_vuota(
        "Ecco il riassunto.<|tool_call_start|><|tool_call_end|>", []
    )
    assert trovata is True
    assert pulito == "Ecco il riassunto."


def test_toolcall_piena_non_e_vuota():
    testo = '<|tool_call_start|>{"name": "web_search"}<|tool_call_end|>'
    trovata, pulito = al._toolcall_vuota(testo, [])
    assert trovata is False
    assert pulito == testo


def test_toolcall_vuota_forma_nativa_senza_nome():
    for calls in ([{"name": ""}], [{"name": "   "}], [{"arguments": "{}"}]):
        trovata, pulito = al._toolcall_vuota("", calls)
        assert trovata is True, calls
        assert pulito == ""


def test_toolcall_nativa_con_nome_non_scatta():
    trovata, _ = al._toolcall_vuota("testo", [{"name": "web_search"}])
    assert trovata is False


def test_toolcall_vuota_testo_vuoto_e_nessuna_chiamata():
    assert al._toolcall_vuota("", None) == (False, "")


def test_messaggio_tool_call_vuota_filtrato_da_last_user_text():
    # Il filtro harness di _last_user_text salta i messaggi "[ERROR]": il
    # rilancio non deve mai diventare "l'ultima domanda dell'utente".
    messaggio = (
        "[ERROR] Your tool call was empty. Emit the complete function call "
        "with its name and arguments, or write the final answer. (Automated "
        "message: do not respond conversationally.)"
    )
    messages = [
        {"role": "user", "content": "che tempo fa a Roma?"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": messaggio},
    ]
    assert al._last_user_text(messages) == "che tempo fa a Roma?"


# ── Cambio 3: escalation browser ─────────────────────────────────────────

def test_categorie_escalation_esistono_davvero():
    for categoria in set(al._BROWSER_ESCALATION_CATEGORIE.values()):
        assert categoria in BROWSER_SPECIALIST_CATEGORIES, categoria


def test_mappa_escalation_per_tool():
    assert al._categoria_escalation("browser_type") == "forms"
    assert al._categoria_escalation("browser_open") == "navigation"
    assert al._categoria_escalation("browser_back") == "navigation"
    assert al._categoria_escalation("browser_click") == "debug"
    assert al._categoria_escalation("browser_find") == "debug"
    assert al._categoria_escalation("browser_read") == "debug"


def test_escalation_non_copre_browser_more_ne_ignoti():
    assert al._categoria_escalation("browser_more") is None
    assert al._categoria_escalation("web_search") is None
    assert al._categoria_escalation("") is None
    assert al._categoria_escalation(None) is None


def test_escalation_non_raggiunge_mai_unsafe():
    assert "unsafe" not in set(al._BROWSER_ESCALATION_CATEGORIE.values())


# ── Integrazione: il loop vero con uno stream finto ──────────────────────

def _collect(gen):
    async def _run():
        return [c async for c in gen]
    return asyncio.run(_run())


def _types(chunks):
    out = []
    for c in chunks:
        if c.startswith("data: ") and not c.startswith("data: [DONE]"):
            try:
                out.append(json.loads(c[6:]))
            except Exception:
                pass
    return out


def _patch_common(monkeypatch):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)

    async def _fake_exec(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})
    monkeypatch.setattr(al, "execute_tool_block", _fake_exec, raising=False)


def _run_loop(monkeypatch, testi, max_rounds=6):
    """`testi` = testo unico oppure lista, un elemento per giro."""
    sequenza = [testi] if isinstance(testi, str) else list(testi)
    stato = {"i": 0, "messaggi": []}

    async def _fake_stream(_candidates, messages, **kwargs):
        idx = min(stato["i"], len(sequenza) - 1)
        stato["i"] += 1
        # Fotografia dei messaggi visti a inizio giro: e' li' che finiscono
        # i rilanci automatici (unico punto osservabile senza modello vivo).
        stato["messaggi"].append([
            str(m.get("content") or "") for m in messages if isinstance(m, dict)
        ])
        yield f'data: {json.dumps({"delta": sequenza[idx]})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)
    gen = al.stream_agent_loop(
        "http://x/v1", "m",
        [{"role": "user", "content": "dammi i mercati di oggi"}],
        max_rounds=max_rounds,
        relevant_tools={"bash"},
    )
    return _types(_collect(gen)), stato


# 664 caratteri, promessa solo in coda (il caso LFM misurato).
_RIEMPITIVO = "Il report contiene dati aggregati e gia' verificati dalla fonte. "
_PROMESSA_FINALE = "Chiamero' fin_mercati con il titolo Apple."
_RISPOSTA_LUNGA = (
    _RIEMPITIVO * ((664 - len(_PROMESSA_FINALE)) // len(_RIEMPITIVO) + 1)
)[: 664 - len(_PROMESSA_FINALE)] + _PROMESSA_FINALE


def test_risposta_lunga_non_nudgiata_col_default(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.delenv("ODYSSEUS_INTENT_NUDGE_MAX_CHARS", raising=False)
    assert len(_RISPOSTA_LUNGA) > 400
    events, stato = _run_loop(monkeypatch, _RISPOSTA_LUNGA)
    assert not any(e.get("type") == "intent_nudge_exhausted" for e in events)
    assert stato["i"] == 1, "col default il turno deve chiudersi al primo giro"


def test_risposta_lunga_con_promessa_in_coda_nudgiata_con_env(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_INTENT_NUDGE_MAX_CHARS", "900")
    events, stato = _run_loop(monkeypatch, _RISPOSTA_LUNGA)
    assert stato["i"] > 1, "il nudge deve far ripartire almeno un giro"
    assert any(e.get("type") == "intent_nudge_exhausted" for e in events), events


_VUOTA = "<|tool_call_start|><|tool_call_end|>"


def test_toolcall_vuota_ignorata_col_default(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.delenv("ODYSSEUS_EMPTY_TOOLCALL_RETRY", raising=False)
    events, stato = _run_loop(monkeypatch, [_VUOTA, "Ecco la risposta finale."])
    assert stato["i"] == 1, "senza env il turno finisce subito, come oggi"


def test_toolcall_vuota_rilanciata_una_volta(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_EMPTY_TOOLCALL_RETRY", "1")
    events, stato = _run_loop(monkeypatch, [_VUOTA, "Ecco la risposta finale."])
    assert stato["i"] == 2, "un solo rilancio, poi la risposta"
    # Il rilancio e' un messaggio role=user "[ERROR] Your tool call was empty."
    secondo_giro = stato["messaggi"][1]
    assert any(c.startswith("[ERROR] Your tool call was empty.") for c in secondo_giro), secondo_giro
    # ...e fa scattare l'agent_step, come il nudge.
    assert any(e.get("type") == "agent_step" for e in events), events


def test_toolcall_vuota_rilancio_una_volta_sola(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_EMPTY_TOOLCALL_RETRY", "1")
    # Marker vuoti a ogni giro: il contatore deve fermarsi dopo UN rilancio.
    events, stato = _run_loop(monkeypatch, _VUOTA, max_rounds=8)
    assert stato["i"] == 2, "il contatore per-turno deve chiudere il turno"


def test_toolcall_vuota_con_testo_consegna_il_testo_senza_marker(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_EMPTY_TOOLCALL_RETRY", "1")
    events, stato = _run_loop(monkeypatch, ["Risposta completa." + _VUOTA])
    assert stato["i"] == 1, "col testo presente non si rilancia"
    # I marker restano nello stream gia' emesso token per token (non
    # riscrivibile a posteriori), ma vengono tolti dal testo conservato:
    # la ripulitura in se' e' coperta da _toolcall_vuota.
    assert al._toolcall_vuota("Risposta completa." + _VUOTA, [])[1] == "Risposta completa."


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
