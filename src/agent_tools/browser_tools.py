"""Small, strict adapters for the built-in Playwright MCP browser.

The raw Playwright server exposes many large, overlapping schemas.  Local
models do substantially better with a stable six-tool core and an explicit
gateway for uncommon capabilities.  The raw tools are still available: a
successful ``browser_more`` call asks the agent loop to expose one specialist
category on the following round.

Element references are scoped to the chat session and refreshed from every
returned accessibility snapshot.  Action adapters accept snapshot refs only;
free-form selectors such as ``body`` or ``youtube homepage`` are deliberately
rejected because they were the main source of plausible-looking failed calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import weakref
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import urlparse

from src.browser_tooling_constants import (
    BROWSER_ADAPTER_RAW_DEPENDENCIES,
    BROWSER_CORE_ORDER,
    BROWSER_CORE_TOOL_NAMES,
    BROWSER_MCP_PREFIX,
)
from src.tool_utils import get_mcp_manager

# Categories stay intentionally narrow.  There is no "all" option: asking for
# one specialist family preserves progressive disclosure and stable prefixes.
BROWSER_SPECIALIST_CATEGORIES: Mapping[str, tuple[str, ...]] = {
    "navigation": (
        "browser_wait_for", "browser_tabs", "browser_close",
        "browser_resize", "browser_press_key",
    ),
    "forms": (
        "browser_fill_form", "browser_select_option", "browser_hover",
        "browser_drag", "browser_drop", "browser_file_upload",
        "browser_handle_dialog",
    ),
    "debug": (
        "browser_console_messages", "browser_network_requests",
        "browser_network_request",
    ),
    "visual": (
        "browser_take_screenshot", "browser_pdf_save",
        "browser_generate_locator", "browser_highlight",
        "browser_hide_highlight",
    ),
    "storage": (
        "browser_cookie_clear", "browser_cookie_delete", "browser_cookie_get",
        "browser_cookie_list", "browser_cookie_set",
        "browser_localstorage_clear", "browser_localstorage_delete",
        "browser_localstorage_get", "browser_localstorage_list",
        "browser_localstorage_set", "browser_sessionstorage_clear",
        "browser_sessionstorage_delete", "browser_sessionstorage_get",
        "browser_sessionstorage_list", "browser_sessionstorage_set",
        "browser_set_storage_state", "browser_storage_state",
    ),
    "developer": (
        "browser_evaluate", "browser_route", "browser_route_list",
        "browser_unroute", "browser_network_state_set",
    ),
    # RCE-equivalent Playwright code remains reachable, but only through an
    # unmistakable category whose schema tells the model to require user intent.
    "unsafe": ("browser_run_code_unsafe",),
}

_REF_RE = re.compile(r"\[ref=([A-Za-z]\d+(?:[A-Za-z]\d+)*)\]")
_REF_VALUE_RE = re.compile(r"^[A-Za-z]\d+(?:[A-Za-z]\d+)*$")
_MAX_RESULT_CHARS = 24_000
_MAX_TEXT_CHARS = 20_000

# Vergilius: quanto testo leggibile si mostra di una pagina. Il taglio e'
# sempre dalla TESTA (inizio dell'articolo), mai dalla coda: un articolo
# comincia dove comincia, e la coda e' quasi sempre note e collegamenti.
_MAX_PAGE_TEXT_CHARS = 9_000
_MAX_PAGE_TEXT_IN_TREE = 4_000

# Riga in inglese che accompagna ogni lettura: il modello deve rispondere SOLO
# da questo testo. Senza, con l'albero di accessibilita' troncato, il 2,6B
# riempiva i vuoti inventando (luogo di nascita di Virgilio, QA 20 set).
LEGGI_COSI = (
    "leggi_cosi: answer ONLY from the page text below. "
    "If the answer is not in it, say you did not find it on the page and, "
    "if useful, ask for another page. Never complete it from memory."
)

# Estrattore del contenuto principale. Gira nella pagina aperta ed e' una
# COSTANTE nostra: il modello non puo' influenzarla in nessun punto, quindi
# non apre la strada a Playwright arbitrario. Prende il primo contenitore
# plausibile; se non c'e', sceglie per densita' di testo contro collegamenti
# (i menu hanno tanti link e poco testo).
_PAGE_TEXT_JS = (
    "() => {\n"
    "  const t = (document.title || '').trim();\n"
    "  const sels = ['#mw-content-text', 'main', 'article', '[role=\"main\"]',"
    " '#content', '#main-content', '#main'];\n"
    "  let el = null;\n"
    "  for (const s of sels) {\n"
    "    const c = document.querySelector(s);\n"
    "    if (c && (c.innerText || '').trim().length > 200) { el = c; break; }\n"
    "  }\n"
    "  if (!el) {\n"
    "    let best = null, bs = 0;\n"
    "    document.querySelectorAll('div,section').forEach(d => {\n"
    "      const x = (d.innerText || '').trim();\n"
    "      if (x.length < 200) return;\n"
    "      const l = d.querySelectorAll('a').length;\n"
    "      const s = x.length / (1 + l * 40);\n"
    "      if (s > bs) { bs = s; best = d; }\n"
    "    });\n"
    "    el = best || document.body;\n"
    "  }\n"
    "  if (!el) return t;\n"
    "  const x = (el.innerText || '').replace(/[ \\t]+\\n/g, '\\n')"
    ".replace(/\\n{3,}/g, '\\n\\n').trim();\n"
    "  return (t ? t + '\\n\\n' : '') + x;\n"
    "}"
)

_state_lock = threading.Lock()
_refs_by_session: Dict[str, frozenset[str]] = {}
_active_session_key: Optional[str] = None
_transaction_locks: "weakref.WeakKeyDictionary[Any, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _transaction_lock() -> asyncio.Lock:
    """One Playwright transaction at a time, without binding across loops."""
    loop = asyncio.get_running_loop()
    with _state_lock:
        lock = _transaction_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _transaction_locks[loop] = lock
        return lock


def _schema(name: str, description: str, properties: Dict[str, Any], required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


BROWSER_TOOL_SCHEMAS = [
    _schema(
        "browser_open",
        "Open an http/https URL in the isolated browser and return the page accessibility tree with element refs.",
        {"url": {"type": "string", "description": "Absolute http/https URL."}},
        ("url",),
    ),
    _schema(
        "browser_read",
        "Read the open page as readable text: title plus the main article, without menus or navigation. This is how you ANSWER a question about a page. Pass refs=true only when you must click or type and need the element ids.",
        {
            "refs": {
                "type": "boolean",
                "description": "false (default) = readable text of the page. true = accessibility tree with element refs, for acting.",
            }
        },
    ),
    _schema(
        "browser_find",
        "Search the page already open for a word, label or link text ('Privacy', 'Accedi', 'Storia') and return only the matching elements with refs. Use it instead of browser_read when you look for something specific.",
        {"text": {"type": "string", "description": "Word or phrase to look for in the open page, case-insensitive. Not a URL."}},
        ("text",),
    ),
    _schema(
        "browser_click",
        "Click an element of the open page by its ref (the eNN id shown by browser_open/browser_read/browser_find).",
        {"ref": {"type": "string", "description": "Element ref like e12. It is an id from the page tree, never a URL or a label."}},
        ("ref",),
    ),
    _schema(
        "browser_type",
        "Type text into a field of the open page by its ref (the eNN id of the textbox/searchbox shown by browser_read/browser_find); optionally press Enter. Do not open a URL for this.",
        {
            "ref": {"type": "string", "description": "Field ref like e4. It is an id from the page tree, never a URL."},
            "text": {"type": "string", "description": "Text to enter."},
            "submit": {"type": "boolean", "description": "Press Enter after typing (default false)."},
        },
        ("ref", "text"),
    ),
    _schema(
        "browser_back",
        "Go back one page and return the refreshed accessibility tree.",
        {},
    ),
    _schema(
        "browser_more",
        "Expose one uncommon browser-tool category for the next round. Core browsing does not need this. Use unsafe only when the user explicitly requested arbitrary Playwright code.",
        {
            "category": {
                "type": "string",
                "enum": list(BROWSER_SPECIALIST_CATEGORIES),
                "description": "Specialist family to expose.",
            }
        },
        ("category",),
    ),
]


def browser_policy_names(tool_name: str) -> frozenset[str]:
    """Return policy-equivalent adapter/raw spellings for denylist checks."""
    if tool_name in BROWSER_CORE_TOOL_NAMES:
        names = {tool_name, "builtin_browser"}
        names.update(
            BROWSER_MCP_PREFIX + raw
            for raw in BROWSER_ADAPTER_RAW_DEPENDENCIES.get(tool_name, ())
        )
        return frozenset(names)
    if tool_name.startswith(BROWSER_MCP_PREFIX):
        raw = tool_name[len(BROWSER_MCP_PREFIX):]
        names = {tool_name, "builtin_browser"}
        names.update(
            adapter
            for adapter, dependencies in BROWSER_ADAPTER_RAW_DEPENDENCIES.items()
            if raw in dependencies
        )
        return frozenset(names)
    if tool_name == "builtin_browser":
        return frozenset({tool_name, *BROWSER_CORE_TOOL_NAMES})
    return frozenset((tool_name,))


def _session_key(ctx: Optional[dict]) -> Optional[str]:
    ctx = ctx or {}
    session_id = str(ctx.get("session_id") or "").strip()
    owner = str(ctx.get("owner") or "").strip()
    # A process-global Playwright page must never be addressable through an
    # owner-only key: two chats belonging to the same owner are still distinct
    # browser transactions and must not inherit one another's refs/page.
    if not session_id:
        return None
    return f"owner:{owner or '-'}|session:{session_id or '-'}"


def _page_access_error(ctx: Optional[dict]) -> Optional[str]:
    session_key = _session_key(ctx)
    if not session_key:
        return "Browser access requires the active chat session id; call browser_open from that chat."
    with _state_lock:
        active = _active_session_key
    if active != session_key:
        return (
            "This chat does not own the current browser page. "
            "Call browser_open with an explicit URL before reading or acting."
        )
    return None


def _decode_args(content: str, allowed: Iterable[str]) -> tuple[Optional[dict], Optional[str]]:
    try:
        args = json.loads((content or "{}").strip() or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"Invalid JSON arguments: {exc}"
    if not isinstance(args, dict):
        return None, "Arguments must be a JSON object."
    unknown = set(args) - set(allowed)
    if unknown:
        return None, f"Unknown argument(s): {', '.join(sorted(unknown))}."
    return args, None


def _browser_raw_tools(ctx: Optional[dict] = None) -> Dict[str, str]:
    mgr = get_mcp_manager()
    if not mgr:
        return {}
    disabled = set((ctx or {}).get("disabled_tools") or ())
    tools: Dict[str, str] = {}
    try:
        for item in mgr.get_all_tools():
            if item.get("server_id") != "builtin_browser" or item.get("is_disabled"):
                continue
            name = str(item.get("name") or "")
            qualified = str(item.get("qualified_name") or "")
            if disabled and not browser_policy_names(qualified).isdisjoint(disabled):
                continue
            if name and qualified:
                tools[name] = qualified
    except Exception:
        return {}
    return tools


def _compact_result(
    result: dict,
    session_key: Optional[str],
    *,
    record_refs: bool = True,
) -> dict:
    out = dict(result or {})
    raw = str(out.get("stdout") or out.get("stderr") or "")
    refs = frozenset(_REF_RE.findall(raw))
    if record_refs:
        with _state_lock:
            # Playwright owns one process-global page.  A tree obtained by any
            # chat invalidates refs held by every other chat; otherwise e12
            # from chat A could act on chat B's newly navigated page.
            _refs_by_session.clear()
            # A fresh tree with zero refs invalidates the previous page's refs
            # too. Keeping them would permit a stale click after navigation.
            if session_key:
                _refs_by_session[session_key] = refs
    if len(raw) > _MAX_RESULT_CHARS:
        head = raw[:18_000]
        tail = raw[-4_000:]
        compact = (
            head
            + f"\n\n[Snapshot compacted: {len(raw) - len(head) - len(tail)} characters omitted. "
              "Use browser_find for a specific element.]\n\n"
            + tail
        )
        if out.get("stdout"):
            out["stdout"] = compact
        else:
            out["stderr"] = compact
    out["browser_ref_count"] = len(refs)
    out["browser_raw_chars"] = len(raw)
    return out


async def _call_raw(
    raw_name: str,
    args: dict,
    ctx: Optional[dict],
    *,
    record_refs: bool = True,
) -> dict:
    mgr = get_mcp_manager()
    available = _browser_raw_tools(ctx)
    qualified = available.get(raw_name)
    if not mgr or not qualified:
        return {
            "error": f"Built-in browser tool '{raw_name}' is not connected.",
            "exit_code": 1,
        }
    result = await mgr.call_tool(qualified, args)
    return _compact_result(result, _session_key(ctx), record_refs=record_refs)


async def _reset_context_for_session_switch_unlocked(
    session_key: str,
    ctx: Optional[dict],
) -> Optional[dict]:
    """Destroy Playwright state before a different chat takes ownership.

    The built-in Playwright MCP is launched with ``--isolated``.  In that
    mode its ``browser_close`` tool disposes the complete BrowserContext; the
    next browser call creates a new context, so cookies, local/session storage,
    IndexedDB, service workers, permissions and open pages cannot cross the
    chat boundary.

    This function is called while holding the browser transaction lock.  It
    deliberately fails closed when ``browser_close`` is missing or reports an
    error: navigating in the old context would give the new chat access to the
    previous chat's authenticated state.
    """
    global _active_session_key

    with _state_lock:
        previous_key = _active_session_key
    if previous_key == session_key:
        return None

    mgr = get_mcp_manager()
    qualified = _browser_raw_tools(ctx).get("browser_close")
    if not mgr or not qualified:
        with _state_lock:
            _refs_by_session.clear()
            _active_session_key = None
        return {
            "error": (
                "Browser context isolation is unavailable, so this chat was "
                "not allowed to inherit another chat's browser state. "
                "Reconnect the built-in Browser MCP and retry browser_open."
            ),
            "exit_code": 1,
        }

    try:
        result = await mgr.call_tool(qualified, {})
    except Exception as exc:
        result = {"error": str(exc), "exit_code": 1}

    # Clear ownership even on failure.  That keeps both the previous and new
    # chat locked out until a later browser_open can prove a successful reset.
    with _state_lock:
        _refs_by_session.clear()
        _active_session_key = None

    if result.get("exit_code"):
        detail = str(
            result.get("stderr") or result.get("error") or "browser_close failed"
        ).strip()
        return {
            "error": (
                "Browser context isolation reset failed; page access remains "
                f"locked. Reconnect the built-in Browser MCP and retry. {detail}"
            )[:2000],
            "exit_code": 1,
            "browser_context_reset": False,
        }
    return None


async def _action_then_snapshot(raw_name: str, args: dict, ctx: Optional[dict]) -> dict:
    action = await _call_raw(raw_name, args, ctx)
    if action.get("exit_code"):
        return action
    snapshot = await _call_raw("browser_snapshot", {}, ctx)
    if snapshot.get("exit_code"):
        return action
    action_text = str(action.get("stdout") or "").strip()
    snapshot_text = str(snapshot.get("stdout") or "").strip()
    merged = dict(snapshot)
    merged["stdout"] = (
        (action_text + "\n\n" if action_text else "") + snapshot_text
    )
    return merged


async def _refresh_raw_browser_result_unlocked(
    raw_name: str,
    result: dict,
    ctx: Optional[dict],
) -> dict:
    """Bound a specialist result and refresh its page refs before next round.

    Specialist MCP tools bypass the core adapters.  Always taking a compact
    snapshot after a successful specialist action keeps the next core
    click/type on the same page and prevents stale references from surviving a
    tab/form/storage/developer operation.
    """
    session_key = _session_key(ctx)
    if raw_name in {"browser_snapshot", "browser_find"}:
        return _compact_result(result, session_key)
    primary = _compact_result(result, session_key, record_refs=False)
    if primary.get("exit_code"):
        return primary
    snapshot = await _call_raw("browser_snapshot", {}, ctx)
    if snapshot.get("exit_code"):
        if session_key:
            with _state_lock:
                _refs_by_session[session_key] = frozenset()
        primary["browser_refs_refreshed"] = False
        primary["browser_snapshot_error"] = str(
            snapshot.get("stderr") or snapshot.get("error") or "snapshot failed"
        )[:1000]
        return primary
    action_text = str(primary.get("stdout") or "").strip()
    snapshot_text = str(snapshot.get("stdout") or "").strip()
    merged = dict(snapshot)
    merged["stdout"] = (action_text + "\n\n" if action_text else "") + snapshot_text
    if primary.get("images"):
        merged["images"] = list(primary.get("images") or []) + list(snapshot.get("images") or [])
    merged["browser_refs_refreshed"] = True
    return merged


async def refresh_raw_browser_result(
    raw_name: str,
    result: dict,
    ctx: Optional[dict],
) -> dict:
    """Serialize a pre-executed raw result's snapshot refresh."""
    async with _transaction_lock():
        return await _refresh_raw_browser_result_unlocked(raw_name, result, ctx)


async def execute_raw_browser_tool(
    raw_name: str,
    args: dict,
    ctx: Optional[dict],
) -> dict:
    """Execute a raw specialist and refresh refs as one page transaction."""
    access_error = _page_access_error(ctx)
    if access_error:
        return {"error": access_error, "exit_code": 1}
    mgr = get_mcp_manager()
    qualified = _browser_raw_tools(ctx).get(raw_name)
    if not mgr or not qualified:
        return {
            "error": f"Built-in browser tool '{raw_name}' is disabled or not connected.",
            "exit_code": 1,
        }
    async with _transaction_lock():
        # Ownership can change while this coroutine waits for another browser
        # transaction. Recheck inside the lock to close the TOCTOU window.
        access_error = _page_access_error(ctx)
        if access_error:
            return {"error": access_error, "exit_code": 1}
        result = await mgr.call_tool(qualified, args)
        return await _refresh_raw_browser_result_unlocked(raw_name, result, ctx)


def _ref_error(ref: Any, ctx: Optional[dict]) -> Optional[str]:
    value = str(ref or "").strip()
    if not _REF_VALUE_RE.fullmatch(value):
        return (
            "ref must be an exact accessibility-snapshot reference such as e12; "
            "call browser_read or browser_find first."
        )
    session_key = _session_key(ctx)
    if not session_key:
        return "Browser refs require an authenticated chat/session context; call browser_read from the active chat."
    with _state_lock:
        known = _refs_by_session.get(session_key, frozenset())
    if not known:
        return "No current browser refs exist for this chat; call browser_read first."
    if value not in known:
        return f"Unknown or stale browser ref '{value}'; call browser_read or browser_find again."
    return None


async def _open(content: str, ctx: Optional[dict]) -> dict:
    args, error = _decode_args(content, {"url"})
    if error:
        return {"error": error, "exit_code": 1}
    url = str(args.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return {"error": "url must be an absolute http/https URL.", "exit_code": 1}
    session_key = _session_key(ctx)
    if not session_key:
        return {
            "error": "browser_open requires the active chat session id.",
            "exit_code": 1,
        }
    reset_error = await _reset_context_for_session_switch_unlocked(session_key, ctx)
    if reset_error:
        return reset_error

    result = await _call_raw("browser_navigate", {"url": url}, ctx)
    if result.get("exit_code"):
        global _active_session_key
        with _state_lock:
            _refs_by_session.clear()
            _active_session_key = None
        return result
    # Ownership is published only after navigation succeeds.  While this
    # handler holds the transaction lock, no action from another chat can run
    # between the destructive reset and this assignment.
    with _state_lock:
        _active_session_key = session_key
    if not result.get("exit_code") and not result.get("browser_ref_count"):
        result = await _call_raw("browser_snapshot", {}, ctx)
    if result.get("exit_code"):
        return result
    # Vergilius: l'albero da solo comincia con banner e menu, e il troncamento
    # mangiava proprio l'articolo: chi apriva Wikipedia non leggeva una riga di
    # testo e inventava la risposta. Il testo leggibile va in TESTA, i ref
    # restano sotto per chi deve agire.
    testo = await _page_text(ctx, _MAX_PAGE_TEXT_IN_TREE)
    if testo:
        result = dict(result)
        result["stdout"] = (
            LEGGI_COSI
            + "\n\n--- page text ---\n"
            + testo
            + "\n\n--- elements (only for clicking or typing) ---\n"
            + str(result.get("stdout") or "")
        )
    return result


async def _page_text(ctx: Optional[dict], limit: int) -> Optional[str]:
    """Testo leggibile del contenuto principale, o None se non ottenibile.

    Usa `browser_evaluate` del server Playwright con una funzione COSTANTE
    (vedi `_PAGE_TEXT_JS`): nessun pezzo arriva dal modello, quindi non e' una
    scorciatoia verso la categoria `developer`. Se lo strumento non e'
    collegato o e' disattivato dal proprietario, si ripiega sull'albero.
    """
    if "browser_evaluate" not in _browser_raw_tools(ctx):
        return None
    try:
        # record_refs=False: la lettura del testo non e' uno snapshot e non
        # deve cancellare i ref appena raccolti dall'albero.
        result = await _call_raw(
            "browser_evaluate", {"function": _PAGE_TEXT_JS}, ctx, record_refs=False
        )
    except Exception:
        return None
    if result.get("exit_code"):
        return None
    raw = str(result.get("stdout") or "").strip()
    if not raw:
        return None
    # Playwright incornicia il valore restituito; si tiene solo la parte utile.
    if "### Result" in raw:
        raw = raw.split("### Result", 1)[1]
    raw = raw.strip().strip("`").strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) > 1:
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    raw = str(raw).strip()
    if len(raw) < 80:
        return None
    if len(raw) > limit:
        raw = raw[:limit].rstrip() + (
            f"\n\n[Page text cut after {limit} characters, from the beginning. "
            "Use browser_find for something further down.]"
        )
    return raw


async def _read(content: str, ctx: Optional[dict]) -> dict:
    args, error = _decode_args(content, {"refs"})
    if error:
        return {"error": error, "exit_code": 1}
    if access_error := _page_access_error(ctx):
        return {"error": access_error, "exit_code": 1}
    refs = args.get("refs", False)
    if isinstance(refs, str):
        refs = refs.strip().lower() in {"1", "true", "yes", "on"}
    if refs:
        return await _call_raw("browser_snapshot", {}, ctx)
    testo = await _page_text(ctx, _MAX_PAGE_TEXT_CHARS)
    if testo is None:
        # Ripiego onesto: l'albero, ma detto chiaramente che non e' prosa.
        result = await _call_raw("browser_snapshot", {}, ctx)
        if not result.get("exit_code"):
            result["stdout"] = (
                "[Readable page text is not available here; this is the element "
                "tree, menus included.]\n\n" + str(result.get("stdout") or "")
            )
        return result
    # Solo le chiavi che il formattatore dei risultati conosce: una chiave in
    # piu' finirebbe in coda come JSON grezzo sotto gli occhi del modello.
    return {
        "stdout": LEGGI_COSI + "\n\n" + testo,
        "stderr": "",
        "exit_code": 0,
    }


async def _find(content: str, ctx: Optional[dict]) -> dict:
    args, error = _decode_args(content, {"text"})
    if error:
        return {"error": error, "exit_code": 1}
    query = str(args.get("text") or "").strip()
    if not query or len(query) > 500:
        return {"error": "text must contain 1-500 characters.", "exit_code": 1}
    if access_error := _page_access_error(ctx):
        return {"error": access_error, "exit_code": 1}
    if "browser_find" in _browser_raw_tools(ctx):
        return await _call_raw("browser_find", {"text": query}, ctx)

    # Compatibility fallback for older pinned servers: take one snapshot and
    # return matching lines plus local context, without asking the model to
    # invent optional snapshot arguments.
    result = await _call_raw("browser_snapshot", {}, ctx)
    raw = str(result.get("stdout") or result.get("stderr") or "")
    if result.get("exit_code") or not raw:
        return result
    lines = raw.splitlines()
    hits = [i for i, line in enumerate(lines) if query.casefold() in line.casefold()]
    selected = set()
    for idx in hits[:40]:
        selected.update(range(max(0, idx - 2), min(len(lines), idx + 3)))
    snippet = "\n".join(lines[i] for i in sorted(selected))
    result["stdout"] = snippet or f"No snapshot match for: {query}"
    return result


async def _click(content: str, ctx: Optional[dict]) -> dict:
    args, error = _decode_args(content, {"ref"})
    if error:
        return {"error": error, "exit_code": 1}
    ref = str(args.get("ref") or "").strip()
    if access_error := _page_access_error(ctx):
        return {"error": access_error, "exit_code": 1}
    error = _ref_error(ref, ctx)
    if error:
        return {"error": error, "exit_code": 1}
    return await _action_then_snapshot("browser_click", {"target": ref}, ctx)


async def _type(content: str, ctx: Optional[dict]) -> dict:
    args, error = _decode_args(content, {"ref", "text", "submit"})
    if error:
        return {"error": error, "exit_code": 1}
    ref = str(args.get("ref") or "").strip()
    if access_error := _page_access_error(ctx):
        return {"error": access_error, "exit_code": 1}
    error = _ref_error(ref, ctx)
    if error:
        return {"error": error, "exit_code": 1}
    value = args.get("text")
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT_CHARS:
        return {"error": f"text must contain 1-{_MAX_TEXT_CHARS} characters.", "exit_code": 1}
    submit = args.get("submit", False)
    if isinstance(submit, str):
        submit = submit.strip().lower() in {"1", "true", "yes", "on"}
    if not isinstance(submit, bool):
        return {"error": "submit must be a boolean.", "exit_code": 1}
    return await _action_then_snapshot(
        "browser_type", {"target": ref, "text": value, "submit": submit}, ctx
    )


async def _back(content: str, ctx: Optional[dict]) -> dict:
    _args, error = _decode_args(content, set())
    if error:
        return {"error": error, "exit_code": 1}
    if access_error := _page_access_error(ctx):
        return {"error": access_error, "exit_code": 1}
    return await _action_then_snapshot("browser_navigate_back", {}, ctx)


async def _more(content: str, ctx: Optional[dict]) -> dict:
    args, error = _decode_args(content, {"category"})
    if error:
        return {"error": error, "exit_code": 1}
    if access_error := _page_access_error(ctx):
        return {"error": access_error, "exit_code": 1}
    category = str(args.get("category") or "").strip().lower()
    wanted = BROWSER_SPECIALIST_CATEGORIES.get(category)
    if not wanted:
        return {
            "error": "Unknown browser category. Choose navigation, forms, debug, visual, storage, developer, or unsafe.",
            "exit_code": 1,
        }
    if category == "unsafe" and not bool((ctx or {}).get("allow_browser_unsafe")):
        return {
            "error": (
                "The unsafe Playwright-code capability requires an explicit "
                "request from the user in this turn."
            ),
            "exit_code": 1,
        }
    available = _browser_raw_tools(ctx)
    unlocked = [available[name] for name in wanted if name in available]
    if not unlocked:
        return {
            "error": f"No connected browser tools are available in category '{category}'.",
            "exit_code": 1,
        }
    return {
        "stdout": (
            f"Browser category '{category}' is available next round: "
            + ", ".join(unlocked)
        ),
        "unlock_tools": unlocked,
        "browser_category": category,
        "exit_code": 0,
    }


def _serialized(handler):
    async def _run(content: str, ctx: Optional[dict]) -> dict:
        async with _transaction_lock():
            return await handler(content, ctx)
    return _run


BROWSER_TOOL_HANDLERS = {
    "browser_open": _serialized(_open),
    "browser_read": _serialized(_read),
    "browser_find": _serialized(_find),
    "browser_click": _serialized(_click),
    "browser_type": _serialized(_type),
    "browser_back": _serialized(_back),
    "browser_more": _serialized(_more),
}
