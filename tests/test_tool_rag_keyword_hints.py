"""Regression for issue #1707 — the agent tool-RAG force-included the entire
email toolset on any "tell me ..." query, crowding out the relevant tools so the
model believed it only had email tools and refused web/other tasks.

Root cause: `_KEYWORD_HINTS` in src/tool_index.py listed "tell" under the email
intent, and `get_tools_for_query` force-includes a hint's tools whenever any of
its keywords appears (word-boundary match). "tell" appears in a huge fraction of
requests (the reporter's was "visit <url> and tell me the title"), so email tools
were force-included for non-email queries.

These hints are deterministic string matching — no embeddings — so we can test
`get_tools_for_query` directly with retrieval stubbed out (no ChromaDB needed).
"""

from src.tool_index import ToolIndex, ALWAYS_AVAILABLE

_EMAIL_TOOLS = {
    "list_emails", "read_email", "send_email", "reply_to_email",
    "bulk_email", "delete_email", "archive_email", "mark_email_read",
}


def _index_without_embeddings():
    """A ToolIndex whose retrieval returns nothing, so get_tools_for_query
    exercises only the deterministic base + keyword-hint logic."""
    ti = ToolIndex.__new__(ToolIndex)        # skip __init__ (no ChromaDB/fastembed)
    ti.retrieve = lambda query, k=8: []
    return ti


def test_tell_in_web_query_does_not_force_email_tools():
    """The #1707 repro: a web request that merely contains the word 'tell' must
    NOT drag in the email toolset."""
    ti = _index_without_embeddings()
    q = "visit https://www.youtube.com/user/example and tell me the title of the latest video"
    tools = ti.get_tools_for_query(q)
    leaked = _EMAIL_TOOLS & tools
    assert not leaked, f"'tell me' must not force-include email tools, got {sorted(leaked)}"
    # web_search / web_fetch are always-available and must remain present.
    assert "web_search" in tools and "web_fetch" in tools


def test_explicit_web_search_query_gets_web_tools_without_retrieval():
    """Explicit web-search phrasing must surface web tools even if embeddings
    return nothing."""
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("use web search and find a recipe for chocolate chip cookies")
    assert "web_search" in tools and "web_fetch" in tools


def test_genuine_email_query_still_gets_email_tools():
    """Removing 'tell' must not break real email intent — the actual email
    keywords still force-include the toolset."""
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("reply to the unread email in my inbox")
    assert {"reply_to_email", "send_email", "read_email"} <= tools


def test_plain_tell_request_stays_minimal():
    """A bare 'tell me a joke' must not pull in email tools either."""
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("tell me a joke")
    assert not (_EMAIL_TOOLS & tools)
    # Always-available baseline is still there.
    assert set(ALWAYS_AVAILABLE) <= tools


def test_italian_browser_query_gets_compact_browser_adapter_set():
    ti = ToolIndex.__new__(ToolIndex)
    ti._lanes = []
    ti._lexical_docs = {
        name: f"Tool: {name}\n{description}"
        for name, description in __import__(
            "src.tool_index", fromlist=["BUILTIN_TOOL_DESCRIPTIONS"]
        ).BUILTIN_TOOL_DESCRIPTIONS.items()
    }
    tools = ti.get_tools_for_query("Apri YouTube nel browser e leggi la pagina")
    assert {"browser_open", "browser_read", "browser_find"} <= tools
    assert not any(name.startswith("mcp__builtin_browser__") for name in tools)


def test_italian_web_and_email_hints_work_without_embeddings():
    ti = _index_without_embeddings()
    web_tools = ti.get_tools_for_query("Cerca su internet le ultime notizie")
    mail_tools = ti.get_tools_for_query("Controlla la posta non letta")
    assert {"web_search", "web_fetch"} <= web_tools
    assert {"list_emails", "read_email"} <= mail_tools


def test_semantic_query_does_not_expand_disattiva_as_attiva():
    expanded = ToolIndex._semantic_query("Disattiva il browser")
    assert "disable turn off" in expanded
    assert "enable turn on" not in expanded


def test_mcp_reindexes_when_disabled_map_changes_without_generation_change():
    class FakeMcp:
        _generation = 7

        def __init__(self):
            self.calls = 0

        def get_all_tools(self, disabled_map):
            self.calls += 1
            return []

    ti = ToolIndex.__new__(ToolIndex)
    ti._lanes = []
    ti._mcp_generation = -1
    ti._mcp_disabled_signature = ()
    ti._lexical_docs = {}
    mcp = FakeMcp()

    ti.index_mcp_tools(mcp, {"srv": {"alpha"}})
    assert mcp.calls == 1
    ti.index_mcp_tools(mcp, {"srv": {"alpha"}})
    assert mcp.calls == 1
    ti.index_mcp_tools(mcp, {"srv": {"beta"}})
    assert mcp.calls == 2
