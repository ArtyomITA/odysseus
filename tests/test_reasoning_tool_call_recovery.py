import json

from src import agent_loop as al
from src.tool_parsing import parse_reasoning_tool_blocks, parse_tool_blocks


LING_CALL = (
    "<tool_call>browser_open\n"
    "<arg_key>url</arg_key>\n"
    "<arg_value>https://example.com</arg_value>\n"
    "</tool_call>"
)


def test_ling_arg_key_format_parses_complete_call():
    blocks = parse_tool_blocks(LING_CALL, skip_fenced=True)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "browser_open"
    assert json.loads(blocks[0].content) == {"url": "https://example.com"}


def test_ling_parser_rejects_partial_and_duplicate_args():
    partial = LING_CALL.removesuffix("</tool_call>")
    duplicate = (
        "<tool_call>browser_open"
        "<arg_key>url</arg_key><arg_value>https://a.test</arg_value>"
        "<arg_key>url</arg_key><arg_value>https://b.test</arg_value>"
        "</tool_call>"
    )
    assert parse_tool_blocks(partial, skip_fenced=True) == []
    assert parse_tool_blocks(duplicate, skip_fenced=True) == []


def test_complete_advertised_call_is_recovered_from_reasoning():
    blocks, used_native, converted = al._resolve_tool_blocks(
        "", [], 1, is_api_model=True,
        round_reasoning=LING_CALL,
        allowed_tool_names={"browser_open"},
    )
    assert [block.tool_type for block in blocks] == ["browser_open"]
    assert used_native is True
    assert len(converted) == 1
    assert converted[0]["name"] == "browser_open"
    assert json.loads(converted[0]["arguments"]) == {"url": "https://example.com"}


def test_recovered_call_threads_result_as_native_tool_observation():
    blocks, used_native, converted = al._resolve_tool_blocks(
        "", [], 2, is_api_model=True,
        round_reasoning=LING_CALL,
        allowed_tool_names={"browser_open"},
    )
    messages = []
    al._append_tool_results(
        messages,
        "",
        converted,
        [{"output": "opened"}],
        ["opened"],
        used_native,
        2,
        round_reasoning="",
        model_name="ling",
    )
    assert blocks[0].tool_type == "browser_open"
    assert messages[0]["role"] == "assistant"
    assert messages[0]["tool_calls"][0]["function"]["name"] == "browser_open"
    assert messages[1] == {
        "role": "tool",
        "tool_call_id": converted[0]["id"],
        "content": "opened",
    }


def test_reasoning_recovery_rejects_hidden_or_zero_schema_tool():
    hidden = LING_CALL.replace("browser_open", "mcp__builtin_browser__browser_snapshot")
    for allowed in ({"browser_open"}, set()):
        blocks, _, _ = al._resolve_tool_blocks(
            "", [], 1, is_api_model=True,
            round_reasoning=hidden,
            allowed_tool_names=allowed,
        )
        assert blocks == []


def test_reasoning_recovery_rejects_plain_prose_and_unwrapped_json():
    unsafe_candidates = (
        "I might use ui_control open_panel settings after checking.",
        '{"function":{"name":"browser_open","arguments":"{\\"url\\":\\"https://example.com\\"}"},"type":"function"}',
        "<tool_call>browser_open<arg_key>url</arg_key><arg_value>https://example.com</arg_value>",
    )
    for reasoning in unsafe_candidates:
        assert parse_reasoning_tool_blocks(reasoning) == []
        blocks, used_native, converted = al._resolve_tool_blocks(
            "", [], 1, is_api_model=True,
            round_reasoning=reasoning,
            allowed_tool_names={"browser_open", "ui_control"},
        )
        assert blocks == []
        assert used_native is False
        assert converted == []


def test_native_structured_call_wins_over_reasoning_call():
    native = [{"name": "browser_read", "arguments": "{}"}]
    blocks, used_native, _ = al._resolve_tool_blocks(
        "", native, 1, is_api_model=True,
        round_reasoning=LING_CALL,
        allowed_tool_names={"browser_read", "browser_open"},
    )
    assert used_native is True
    assert [block.tool_type for block in blocks] == ["browser_read"]


def test_low_signal_fast_path_keeps_preset_persona_and_language():
    messages = [
        {"role": "system", "content": "Your name is Mao. Rispondi in italiano."},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old reply"},
    ]
    compact = al._minimal_persona_messages(messages, "ciao")
    assert compact == [
        {"role": "system", "content": "Your name is Mao. Rispondi in italiano."},
        {"role": "user", "content": "ciao"},
    ]


def test_recovery_history_keeps_original_json_for_text_internal_tools():
    cases = (
        ("web_search", {"query": "CUDA oggi", "time_filter": "day"}),
        ("bash", {"command": "git status --short"}),
        ("read_file", {"path": "README.md"}),
    )
    for tool, arguments in cases:
        tags = "".join(
            f"<arg_key>{key}</arg_key><arg_value>{json.dumps(value)}</arg_value>"
            for key, value in arguments.items()
        )
        reasoning = f"<tool_call>{tool}{tags}</tool_call>"
        blocks, used_native, converted = al._resolve_tool_blocks(
            "", [], 3, is_api_model=True,
            round_reasoning=reasoning,
            allowed_tool_names={tool},
        )
        assert used_native is True
        assert len(blocks) == len(converted) == 1
        assert json.loads(converted[0]["arguments"]) == arguments
        messages = []
        al._append_tool_results(
            messages, "", converted, [{"output": "ok"}], ["ok"], True, 3,
            model_name="ling",
        )
        assert json.loads(
            messages[0]["tool_calls"][0]["function"]["arguments"]
        ) == arguments
