import asyncio
import json

import pytest

from src.browser_tooling_constants import BROWSER_CORE_TOOL_NAMES
from src.browser_tooling_constants import browser_adapters_disabled_by_raw
from src.agent_tools import browser_tools as bt
from src.agent_tools import ToolBlock
from src.agent_loop import _select_browser_core_tools
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tool_security import email_tool_policy_names


class _FakeBrowserMcp:
    def __init__(self):
        self.calls = []
        self.names = {
            "browser_navigate", "browser_snapshot", "browser_find",
            "browser_click", "browser_type", "browser_navigate_back",
            "browser_tabs", "browser_console_messages", "browser_close",
        }

    def get_all_tools(self):
        return [
            {
                "server_id": "builtin_browser",
                "name": name,
                "qualified_name": f"mcp__builtin_browser__{name}",
                "is_disabled": False,
            }
            for name in sorted(self.names)
        ]

    async def call_tool(self, qualified, args):
        self.calls.append((qualified, args))
        name = qualified.rsplit("__", 1)[-1]
        if name == "browser_snapshot":
            return {"stdout": "- textbox \"Search\" [ref=e12]\n- button \"Go\" [ref=e13]", "exit_code": 0}
        if name == "browser_find":
            return {"stdout": "- textbox \"Search\" [ref=e12]", "exit_code": 0}
        return {"stdout": f"{name} ok", "exit_code": 0}


@pytest.fixture(autouse=True)
def _reset_browser_page_state():
    bt._refs_by_session.clear()
    bt._active_session_key = None
    yield
    bt._refs_by_session.clear()
    bt._active_session_key = None


def test_browser_core_is_small_strict_and_stable():
    names = [schema["function"]["name"] for schema in bt.BROWSER_TOOL_SCHEMAS]
    assert names == [
        "browser_open", "browser_read", "browser_find", "browser_click",
        "browser_type", "browser_back", "browser_more",
    ]
    assert set(names) == set(BROWSER_CORE_TOOL_NAMES)
    assert all(
        schema["function"]["parameters"]["additionalProperties"] is False
        for schema in bt.BROWSER_TOOL_SCHEMAS
    )


def test_raw_browser_hit_collapses_to_adapter_core():
    selected = _select_browser_core_tools({
        "manage_memory", "mcp__builtin_browser__browser_snapshot",
        "mcp__builtin_browser__browser_click",
    })
    assert BROWSER_CORE_TOOL_NAMES <= selected
    assert "manage_memory" in selected
    assert not any(name.startswith("mcp__builtin_browser__") for name in selected)


def test_refs_are_session_scoped_and_actions_refresh_snapshot(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    bt._refs_by_session.clear()

    opened = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com"}), {"session_id": "a"}
    ))
    assert opened["browser_ref_count"] == 2

    clicked = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_click"](
        json.dumps({"ref": "e12"}), {"session_id": "a"}
    ))
    assert clicked["exit_code"] == 0
    assert [call[0].rsplit("__", 1)[-1] for call in fake.calls[-2:]] == [
        "browser_click", "browser_snapshot",
    ]

    before = len(fake.calls)
    denied = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_click"](
        json.dumps({"ref": "e12"}), {"session_id": "b"}
    ))
    assert denied["exit_code"] == 1
    assert "does not own" in denied["error"]
    assert len(fake.calls) == before


def test_ref_state_keys_owner_and_session_and_empty_tree_clears_refs(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    bt._refs_by_session.clear()
    ctx = {"owner": "alice", "session_id": "shared"}
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com"}), ctx
    ))
    assert bt._session_key(ctx) != bt._session_key({"owner": "bob", "session_id": "shared"})

    bt._compact_result({"stdout": "", "exit_code": 0}, bt._session_key(ctx))
    denied = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_click"](
        json.dumps({"ref": "e12"}), ctx
    ))
    assert denied["exit_code"] == 1
    assert "No current browser refs" in denied["error"]


def test_new_tree_in_another_chat_invalidates_old_chat_refs(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    bt._refs_by_session.clear()
    alice = {"owner": "alice", "session_id": "a"}
    bob = {"owner": "bob", "session_id": "b"}
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com/a"}), alice
    ))
    denied_read = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_read"]("{}", bob))
    assert denied_read["exit_code"] == 1
    assert "does not own" in denied_read["error"]
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com/b"}), bob
    ))
    denied_alice = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_click"](
        json.dumps({"ref": "e12"}), alice
    ))
    assert denied_alice["exit_code"] == 1
    assert "does not own" in denied_alice["error"]


def test_session_switch_destroys_context_storage_but_same_session_keeps_it(monkeypatch):
    class _StorageBrowserMcp(_FakeBrowserMcp):
        def __init__(self):
            super().__init__()
            self.storage = {}
            self.context_generation = 0
            self.navigate_observed_storage = []

        async def call_tool(self, qualified, args):
            self.calls.append((qualified, args))
            name = qualified.rsplit("__", 1)[-1]
            if name == "browser_close":
                self.storage.clear()
                self.context_generation += 1
                return {"stdout": "browser closed", "exit_code": 0}
            if name == "browser_navigate":
                self.navigate_observed_storage.append(dict(self.storage))
                return {
                    "stdout": f"generation={self.context_generation} [ref=e12]",
                    "exit_code": 0,
                }
            return await super().call_tool(qualified, args)

    fake = _StorageBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    alice = {"owner": "alice", "session_id": "a"}
    bob = {"owner": "bob", "session_id": "b"}

    first = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com/a"}), alice
    ))
    assert first["exit_code"] == 0
    assert fake.context_generation == 1
    fake.storage["secret"] = "alice-token"

    same_chat = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com/a2"}), alice
    ))
    assert same_chat["exit_code"] == 0
    assert fake.navigate_observed_storage[-1] == {"secret": "alice-token"}
    assert fake.context_generation == 1

    switched = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com/b"}), bob
    ))
    assert switched["exit_code"] == 0
    assert fake.navigate_observed_storage[-1] == {}
    assert fake.context_generation == 2
    assert [name.rsplit("__", 1)[-1] for name, _args in fake.calls[-2:]] == [
        "browser_close", "browser_navigate",
    ]


def test_session_switch_fails_closed_when_context_reset_fails(monkeypatch):
    class _FailingCloseMcp(_FakeBrowserMcp):
        async def call_tool(self, qualified, args):
            self.calls.append((qualified, args))
            name = qualified.rsplit("__", 1)[-1]
            if name == "browser_close":
                return {"stderr": "close failed", "exit_code": 1}
            return {"stdout": f"{name} ok", "exit_code": 0}

    fake = _FailingCloseMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    with bt._state_lock:
        bt._active_session_key = bt._session_key(
            {"owner": "alice", "session_id": "a"}
        )
        bt._refs_by_session[bt._active_session_key] = frozenset({"e12"})

    denied = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com/b"}),
        {"owner": "bob", "session_id": "b"},
    ))
    assert denied["exit_code"] == 1
    assert denied["browser_context_reset"] is False
    assert "isolation reset failed" in denied["error"]
    assert bt._active_session_key is None
    assert bt._refs_by_session == {}
    assert not any(name.endswith("browser_navigate") for name, _args in fake.calls)


def test_concurrent_session_switch_is_one_atomic_close_navigate_transaction(monkeypatch):
    class _BlockingBrowserMcp(_FakeBrowserMcp):
        def __init__(self):
            super().__init__()
            self.navigate_started = asyncio.Event()
            self.release_navigate = asyncio.Event()

        async def call_tool(self, qualified, args):
            self.calls.append((qualified, args))
            name = qualified.rsplit("__", 1)[-1]
            if name == "browser_navigate" and args["url"].endswith("/b"):
                self.navigate_started.set()
                await self.release_navigate.wait()
            if name == "browser_navigate":
                return {"stdout": "- page [ref=e12]", "exit_code": 0}
            if name == "browser_snapshot":
                return {"stdout": "- button [ref=e12]", "exit_code": 0}
            return {"stdout": f"{name} ok", "exit_code": 0}

    async def _race():
        fake = _BlockingBrowserMcp()
        monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
        alice = {"owner": "alice", "session_id": "a"}
        bob = {"owner": "bob", "session_id": "b"}
        await bt.BROWSER_TOOL_HANDLERS["browser_open"](
            json.dumps({"url": "https://example.com/a"}), alice
        )
        bob_open = asyncio.create_task(bt.BROWSER_TOOL_HANDLERS["browser_open"](
            json.dumps({"url": "https://example.com/b"}), bob
        ))
        await fake.navigate_started.wait()
        stale_alice_read = asyncio.create_task(
            bt.BROWSER_TOOL_HANDLERS["browser_read"]("{}", alice)
        )
        await asyncio.sleep(0)
        assert not stale_alice_read.done()
        fake.release_navigate.set()
        opened, denied = await asyncio.gather(bob_open, stale_alice_read)
        return fake, opened, denied

    fake, opened, denied = asyncio.run(_race())
    assert opened["exit_code"] == 0
    assert denied["exit_code"] == 1
    assert "does not own" in denied["error"]
    names = [name.rsplit("__", 1)[-1] for name, _args in fake.calls]
    assert names == [
        "browser_close", "browser_navigate",
        "browser_close", "browser_navigate",
    ]


def test_raw_specialist_result_refreshes_snapshot_refs(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    bt._refs_by_session.clear()
    ctx = {"owner": "alice", "session_id": "a"}
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com"}), ctx
    ))
    result = asyncio.run(bt.refresh_raw_browser_result(
        "browser_tabs", {"stdout": "selected tab", "exit_code": 0}, ctx
    ))
    assert result["browser_refs_refreshed"] is True
    assert result["browser_ref_count"] == 2
    assert "selected tab" in result["stdout"]
    assert fake.calls[-1][0].endswith("browser_snapshot")


def test_browser_more_unlocks_only_one_connected_category(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com"}), {"session_id": "a"}
    ))
    result = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_more"](
        json.dumps({"category": "navigation"}), {"session_id": "a"}
    ))
    assert result["unlock_tools"] == [
        "mcp__builtin_browser__browser_tabs",
        "mcp__builtin_browser__browser_close",
    ]
    assert all(name.startswith("mcp__builtin_browser__") for name in result["unlock_tools"])


def test_browser_more_filters_per_server_disabled_specialists(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com"}), {"session_id": "a"}
    ))
    result = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_more"](
        json.dumps({"category": "navigation"}),
        {
            "session_id": "a",
            "disabled_tools": {"mcp__builtin_browser__browser_tabs"},
        },
    ))
    assert result["exit_code"] == 0
    assert result["unlock_tools"] == ["mcp__builtin_browser__browser_close"]


def test_raw_disable_maps_to_every_compact_dependency():
    assert browser_adapters_disabled_by_raw({"browser_navigate"}) == {"browser_open"}
    assert browser_adapters_disabled_by_raw({"browser_close"}) == {"browser_open"}
    assert browser_adapters_disabled_by_raw({"browser_snapshot"}) == {
        "browser_open", "browser_read", "browser_click", "browser_type", "browser_back",
    }


def test_unsafe_gateway_and_runtime_require_explicit_user_intent(monkeypatch):
    fake = _FakeBrowserMcp()
    fake.names.add("browser_run_code_unsafe")
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)
    asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_open"](
        json.dumps({"url": "https://example.com"}), {"session_id": "a"}
    ))
    denied_gateway = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_more"](
        json.dumps({"category": "unsafe"}), {"session_id": "a"}
    ))
    assert denied_gateway["exit_code"] == 1
    allowed_gateway = asyncio.run(bt.BROWSER_TOOL_HANDLERS["browser_more"](
        json.dumps({"category": "unsafe"}),
        {"session_id": "a", "allow_browser_unsafe": True},
    ))
    assert allowed_gateway["exit_code"] == 0

    _desc, denied_runtime = asyncio.run(execute_tool_block(
        ToolBlock("mcp__builtin_browser__browser_run_code_unsafe", "{}"),
        owner="admin",
        security_context=NO_TOOL_SECURITY_CONTEXT,
    ))
    assert denied_runtime["exit_code"] == 1
    assert "explicit user request" in denied_runtime["error"]


def test_raw_specialist_rechecks_page_owner_after_waiting_for_lock(monkeypatch):
    fake = _FakeBrowserMcp()
    monkeypatch.setattr(bt, "get_mcp_manager", lambda: fake)

    async def _race():
        alice = {"owner": "alice", "session_id": "a"}
        await bt.BROWSER_TOOL_HANDLERS["browser_open"](
            json.dumps({"url": "https://example.com/a"}), alice
        )
        lock = bt._transaction_lock()
        await lock.acquire()
        task = asyncio.create_task(
            bt.execute_raw_browser_tool("browser_tabs", {}, alice)
        )
        await asyncio.sleep(0)
        with bt._state_lock:
            bt._active_session_key = bt._session_key(
                {"owner": "bob", "session_id": "b"}
            )
        lock.release()
        return await task

    before = len(fake.calls)
    denied = asyncio.run(_race())
    assert denied["exit_code"] == 1
    assert "does not own" in denied["error"]
    assert len(fake.calls) == before + 3


def test_browser_adapter_and_raw_names_share_policy_gate():
    aliases = email_tool_policy_names("browser_click")
    assert "builtin_browser" in aliases
    assert "mcp__builtin_browser__browser_click" in aliases
    snapshot_aliases = email_tool_policy_names("mcp__builtin_browser__browser_snapshot")
    assert {"browser_read", "browser_open", "browser_click"} <= set(snapshot_aliases)
