"""Deterministic tests for the external Wave-4 preparation harnesses."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_e2e_sse_parser_keeps_usage_tools_text_and_thinking_separate():
    module = _load("pre4_e2e", ROOT / "scripts" / "prova_e2e_onda4.py")
    state = module._new_stream_state()

    assert module.parse_sse_line(
        'data: {"type":"tool_start","tool":"browser_navigate"}', state
    ) is False
    module.parse_sse_line(
        'data: {"type":"usage","data":{"input_tokens":20,"cached_tokens":15}}',
        state,
    )
    module.parse_sse_line('data: {"delta":"hidden","thinking":true}', state)
    module.parse_sse_line('data: {"delta":"visible"}', state)

    assert state["tools"] == ["browser_navigate"]
    assert state["usage"] == [{"input_tokens": 20, "cached_tokens": 15}]
    assert state["thinking_chars"] == 6
    assert state["text_parts"] == ["visible"]
    assert module.parse_sse_line("data: [DONE]", state) is True


def test_e2e_endpoint_selection_honors_explicit_model():
    module = _load("pre4_e2e_endpoint", ROOT / "scripts" / "prova_e2e_onda4.py")
    endpoint, model = module.select_endpoint(
        {"items": [{"id": "a", "default": True, "model": "old"}]},
        "ling-vista",
    )
    assert endpoint["id"] == "a"
    assert model == "ling-vista"


def test_slot_probe_classification_requires_large_isolation_delta():
    module = _load("pre4_slot", ROOT / "scripts" / "preflight_onda4.py")
    good = module.classify_slot_result(
        {"cache_n": 950, "prompt_n": 10},
        {"cache_n": 0, "prompt_n": 960},
    )
    weak = module.classify_slot_result(
        {"cache_n": 700, "prompt_n": 300},
        {"cache_n": 300, "prompt_n": 700},
    )
    assert good["passed"] is True
    assert weak["passed"] is False


def test_financial_harness_remains_separate():
    path = ROOT / "scripts" / "prova_e2e_agente.py"
    text = path.read_text(encoding="utf-8")
    assert "financial_mode" in text
    assert "prova_e2e_onda4" not in text
    assert len(json.loads(json.dumps(text))) == len(text)
