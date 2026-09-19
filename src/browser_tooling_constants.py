"""Dependency-light constants shared by browser routing and adapters."""

import re
from types import MappingProxyType

BROWSER_MCP_PREFIX = "mcp__builtin_browser__"
BROWSER_CORE_ORDER = (
    "browser_open",
    "browser_read",
    "browser_find",
    "browser_click",
    "browser_type",
    "browser_back",
    "browser_more",
)
BROWSER_CORE_TOOL_NAMES = frozenset(BROWSER_CORE_ORDER)

# Raw Playwright operations used by each compact adapter.  This is also the
# policy-equivalence map: disabling a raw MCP operation must disable every
# adapter that would invoke it internally, otherwise the adapter becomes a
# bypass for the per-server MCP settings.
BROWSER_ADAPTER_RAW_DEPENDENCIES = MappingProxyType({
    # browser_close is a security dependency: browser_open uses it to destroy
    # the previous chat's isolated BrowserContext before ownership changes.
    "browser_open": frozenset({
        "browser_close", "browser_navigate", "browser_snapshot",
    }),
    "browser_read": frozenset({"browser_snapshot"}),
    "browser_find": frozenset({"browser_find"}),
    "browser_click": frozenset({"browser_click", "browser_snapshot"}),
    "browser_type": frozenset({"browser_type", "browser_snapshot"}),
    "browser_back": frozenset({"browser_navigate_back", "browser_snapshot"}),
    "browser_more": frozenset(),
})


def browser_adapters_disabled_by_raw(raw_names):
    """Compact adapters made unavailable by a raw MCP denylist."""
    disabled = {str(name) for name in (raw_names or ())}
    return {
        adapter
        for adapter, dependencies in BROWSER_ADAPTER_RAW_DEPENDENCIES.items()
        if not dependencies.isdisjoint(disabled)
    }


def explicit_browser_unsafe_request(text: str) -> bool:
    """Recognise only an unmistakable raw user request for Playwright code."""
    return bool(re.search(
        r"\bbrowser_run_code_unsafe\b|"
        r"\b(?:run|execute|use)\b.{0,80}\barbitrary\s+playwright\s+code\b|"
        r"\b(?:esegui|eseguire|usa|usare)\b.{0,80}\bcodice\s+playwright\b",
        text or "",
        re.IGNORECASE,
    ))
