"""Pure unit tests for the guarded Ling behaviour harness."""

import json

from scripts import prova_ling_behavior as harness


def test_extracts_native_tool_call_and_original_argument_types():
    calls, channel = harness._extract_calls({
        "tool_calls": [{
            "id": "call_1",
            "function": {
                "name": "browser_type",
                "arguments": json.dumps({"ref": "e4", "text": "ciao", "submit": True}),
            },
        }]
    })
    assert channel == "native"
    assert calls == [{
        "id": "call_1", "name": "browser_type",
        "args": {"ref": "e4", "text": "ciao", "submit": True},
        "valid_json": True,
    }]


def test_extracts_complete_bailing_wrapper_from_reasoning_only():
    message = {
        "reasoning_content": (
            "Need browse. <tool_call>browser_open"
            "<arg_key>url</arg_key><arg_value>https://example.com</arg_value>"
            "</tool_call>"
        )
    }
    calls, channel = harness._extract_calls(message)
    assert channel == "reasoning_wrapper"
    assert calls[0]["name"] == "browser_open"
    assert calls[0]["args"] == {"url": "https://example.com"}


def test_does_not_recover_partial_reasoning_wrapper():
    calls, channel = harness._extract_calls({
        "reasoning_content": "<tool_call>browser_open<arg_key>url</arg_key>"
    })
    assert calls == []
    assert channel == "none"


def test_schema_validation_catches_extra_and_wrong_type():
    offered = harness.schemas(("browser_type",))
    errors = harness._schema_errors(
        "browser_type",
        {"ref": "e4", "text": "ciao", "submit": "yes", "selector": "#x"},
        offered,
    )
    assert "type:submit" in errors
    assert "extra:selector" in errors


def test_payload_uses_ling_recommended_sampling_controls_and_prefix_cache():
    payload = harness.make_payload(
        "ling", "production_fragment", "it", "Apri example.com",
        harness.schemas(("browser_open",)), seed=17,
    )
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 20
    assert payload["cache_prompt"] is True
    assert payload["parallel_tool_calls"] is False


def test_full_single_repeat_matrix_has_expected_request_budget():
    factories = (
        harness.matrix_baseline, harness.matrix_pressure,
        harness.matrix_thinking, harness.matrix_schema,
        harness.matrix_order, harness.matrix_communication,
        harness.matrix_choice, harness.matrix_temperature,
    )
    assert sum(len(factory(1)) for factory in factories) + 3 == 263


def test_pressure_matrix_places_target_at_head_middle_and_tail():
    jobs = [
        job for job in harness.matrix_pressure(1)
        if job["case"].case_id == "browser_open"
        and job["variant"].startswith("pressure:16:")
    ]
    positions = {}
    for job in jobs:
        names = [(item.get("function") or {}).get("name") for item in job["offered"]]
        positions[job["variant"].rsplit(":", 1)[-1]] = names.index("browser_open")
    assert positions == {"head": 0, "middle": 7, "tail": 15}
