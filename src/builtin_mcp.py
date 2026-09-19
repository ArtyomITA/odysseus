"""
builtin_mcp.py

Auto-registration of built-in MCP servers on startup.
Each server runs as a stdio subprocess managed by McpManager.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys

from core.platform_compat import IS_WINDOWS, which_tool
from src.runtime_paths import get_app_root

logger = logging.getLogger(__name__)


def _find_npx() -> str:
    """Find the npx binary, checking common locations if not on PATH.

    On Windows the shim is `npx.cmd`, which `which_tool` resolves via PATHEXT.
    """
    npx = which_tool("npx")
    if npx:
        return npx
    if IS_WINDOWS:
        # Minimal-PATH fallbacks: npm's global bin lives under %APPDATA%\npm,
        # and node's installer dir carries npx.cmd alongside node.exe.
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        for candidate in (
            os.path.join(appdata, "npm", "npx.cmd"),
            r"C:\Program Files\nodejs\npx.cmd",
        ):
            if os.path.isfile(candidate):
                return candidate
        node = which_tool("node")
        if node:
            cand = os.path.join(os.path.dirname(node), "npx.cmd")
            if os.path.isfile(cand):
                return cand
        return "npx.cmd"  # fallback, will fail with a clear error
    # Common POSIX locations when PATH is minimal (e.g. systemd)
    for candidate in [
        os.path.expanduser("~/.npm-global/bin/npx"),
        os.path.expanduser("~/.local/bin/npx"),
        "/usr/local/bin/npx",
        "/usr/bin/npx",
    ]:
        if os.path.isfile(candidate):
            return candidate
    # Try to find node and use npx from same dir
    node = shutil.which("node")
    if node:
        npx_candidate = os.path.join(os.path.dirname(node), "npx")
        if os.path.isfile(npx_candidate):
            return npx_candidate
    return "npx"  # fallback, will fail with a clear error

# Server definitions: id -> (script path relative to project root, display name)
#
# bash / python / filesystem / web_search were folded into native in-process
# execution (src/tool_execution.py:_direct_fallback). Those trivial subprocess
# wrappers are gone.
#
# image_gen / memory / rag / email still run as stdio MCP servers — each
# carries hundreds of LOC of unique IMAP / HTTP / manager logic not worth
# duplicating into the native path right now.
_BUILTIN_SERVERS = {
    "image_gen":  ("mcp_servers/image_gen_server.py",  "Built-in: Image Generation"),
    "memory":     ("mcp_servers/memory_server.py",     "Built-in: Memory"),
    "rag":        ("mcp_servers/rag_server.py",        "Built-in: RAG"),
    "email":      ("mcp_servers/email_server.py",      "Built-in: Email"),
}

# NPX-based built-in servers (run via npx, not Python)
#
# Flags are tuned for a small local model with a ~48k window, where Playwright's
# defaults are ruinous (measured elsewhere at ~114k tokens for a 10-step task):
#   --caps vision      REMOVED: adds 6 coordinate-based tools, worse than the
#                      ref-based ones for a small model, and every screenshot
#                      costs thousands of tokens.
#   --snapshot-mode none   default "full" re-snapshots the page after EVERY
#                      action; the model asks for a snapshot when it needs one.
#   --output-mode file REMOVED (22 ago 2026): Playwright MCP 0.0.79 non accetta
#                      piu' il flag ("error: unknown option '--output-mode'") e
#                      il server moriva in avvio: niente browser per il modello.
#                      La versione attuale scrive comunque gli output su disco
#                      (--output-dir, default tmp); il flag era diventato
#                      ridondante. Vergilius: verificato con --help della
#                      versione scaricata da npx.
#   --image-responses omit / --isolated   no images back, ephemeral profile.
PLAYWRIGHT_MCP_PACKAGE = "@playwright/mcp@0.0.79"

_BUILTIN_NPX_SERVERS = {
    "builtin_browser": {
        "name": "Built-in: Browser",
        "command": "npx",
        "args": [
            "-y", PLAYWRIGHT_MCP_PACKAGE,
            "--headless",
            "--isolated",
            "--snapshot-mode", "none",
            "--image-responses", "omit",
        ],
    }
}

# Global flag to disable MCP if there are compatibility issues
MCP_DISABLED = os.environ.get("ODYSSEUS_DISABLE_MCP", "").lower() in ("1", "true", "yes")
BROWSER_MCP_REQUIRE_CACHE = os.environ.get("ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE", "").lower() in ("1", "true", "yes")


# Strong references to the fire-and-forget startup tasks scheduled below.
# asyncio only keeps weak references to tasks created via create_task, so
# without this the GC can collect a task mid-execution and the server
# registration silently never runs. Mirrors _spawn_bg in routes/chat_helpers.py.
_BG_TASKS: set[asyncio.Task] = set()


def _spawn_bg(coro) -> asyncio.Task:
    """Schedule a background task and hold a strong reference until it finishes."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task

def _find_browser_executable() -> str:
    """Find a browser binary for the built-in Playwright MCP server.

    Docker images ship Debian's `chromium`; desktop installs may already have
    Chrome/Chromium in a conventional location. If nothing is found, return an
    empty string and let Playwright MCP use its own default browser/channel.
    """
    configured = os.environ.get("ODYSSEUS_BROWSER_EXECUTABLE", "").strip()
    if configured:
        return configured
    for name in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    if IS_WINDOWS:
        roots = (
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        )
        relative_candidates = (
            os.path.join("Google", "Chrome", "Application", "chrome.exe"),
            os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join("Chromium", "Application", "chrome.exe"),
        )
        for root in roots:
            for relative in relative_candidates:
                candidate = os.path.join(root, relative) if root else ""
                if candidate and os.path.isfile(candidate):
                    return candidate
    for candidate in (
        "/opt/google/chrome/chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ):
        if os.path.isfile(candidate):
            return candidate
    return ""


# Vergilius (23 ago 2026): consenso cookie risolto A MONTE, non dal modello.
# Un profilo `--isolated` e' vergine ad ogni avvio: Google/YouTube mostrano
# SEMPRE "Prima di continuare" e il backdrop del dialog intercetta i click
# (misurato: 4 click falliti su "Home", 2 turni da 500 e 400 s senza mai
# leggere la pagina). Due livelli:
#   1. `--storage-state`: cookie `SOCS=CAI` su .youtube.com/.google.*: e' lo
#      stesso che imposta yt-dlp ("accept all"); il dialog non compare proprio.
#   2. `--init-script`: per tutti gli altri CMP (OneTrust, Didomi, ...) un
#      MutationObserver clicca UNA volta il bottone "Rifiuta tutto"/"Reject
#      all" (preferito) o "Accetta tutto"/"Accept all", poi si spegne.
# Spegnibile con ODYSSEUS_BROWSER_CONSENT=0. I file vivono in DATA_DIR/local
# e vengono rigenerati se mancano (il contenuto e' versionato qui sotto).
_CONSENT_COOKIE_DOMAINS = (".youtube.com", ".google.com", ".google.it")
_CONSENT_INIT_SCRIPT = r"""(() => {
  if (window.__vergiliusConsentDone) return;
  const REJECT = [/^rifiuta tutto$/i, /^reject all$/i, /^rifiuta$/i, /^reject$/i,
    /^decline all$/i, /^rifiuta tutti$/i, /^solo (i )?necessari/i, /^only necessary/i,
    /^continua senza accettare/i, /^continue without accepting/i, /^alle ablehnen$/i,
    /^tout refuser$/i, /^rechazar todo$/i];
  const ACCEPT = [/^accetta tutto$/i, /^accept all$/i, /^accetta tutti$/i, /^accetta$/i,
    /^accept$/i, /^i agree$/i, /^agree$/i, /^consenti$/i, /^ok,? capito$/i, /^got it$/i,
    /^alle akzeptieren$/i, /^tout accepter$/i, /^aceptar todo$/i];
  const label = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const find = (pats) => {
    const nodes = document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], a');
    for (const el of nodes) {
      const t = el.tagName === 'INPUT' ? (el.value || '') : label(el);
      if (t && t.length < 40 && visible(el) && pats.some((p) => p.test(t))) return el;
    }
    return null;
  };
  let tries = 0;
  const attempt = () => {
    if (window.__vergiliusConsentDone) return true;
    const el = find(REJECT) || find(ACCEPT);
    if (el) { window.__vergiliusConsentDone = true; try { el.click(); } catch (e) {} return true; }
    return false;
  };
  const obs = new MutationObserver(() => { if (attempt() || ++tries > 400) obs.disconnect(); });
  const start = () => {
    if (attempt()) return;
    obs.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(() => obs.disconnect(), 15000);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();"""


def _browser_consent_files(base_dir: str | None = None) -> tuple[str, str] | None:
    """Create (once) and return the consent storage-state + init-script paths."""
    try:
        import json as _json
        import time as _time
        from src.constants import DATA_DIR
        root = os.path.join(base_dir or os.environ.get("ODYSSEUS_DATA_DIR") or DATA_DIR, "local")
        os.makedirs(root, exist_ok=True)
        state_path = os.path.join(root, "browser-consent-state.json")
        script_path = os.path.join(root, "browser-consent-init.js")
        if not os.path.exists(state_path):
            expires = int(_time.time()) + 390 * 24 * 3600  # ~13 mesi, come Google
            cookies = [
                {
                    "name": "SOCS", "value": "CAI", "domain": d, "path": "/",
                    "expires": expires, "httpOnly": False, "secure": True, "sameSite": "Lax",
                }
                for d in _CONSENT_COOKIE_DOMAINS
            ]
            with open(state_path, "w", encoding="utf-8") as fh:
                _json.dump({"cookies": cookies, "origins": []}, fh, indent=1)
        if not os.path.exists(script_path) or open(script_path, encoding="utf-8").read() != _CONSENT_INIT_SCRIPT:
            with open(script_path, "w", encoding="utf-8") as fh:
                fh.write(_CONSENT_INIT_SCRIPT)
        return state_path, script_path
    except Exception as exc:  # mai bloccare l'avvio del browser per il consenso
        logger.warning("browser consent files unavailable: %s", exc)
        return None


def _browser_mcp_args(args: list[str]) -> list[str]:
    """Return Playwright MCP args with a concrete browser executable when found."""
    out = list(args or [])
    if "--executable-path" not in out:
        browser = _find_browser_executable()
        if browser:
            out.extend(["--executable-path", browser])
    if os.environ.get("ODYSSEUS_BROWSER_ISOLATED", "1").lower() not in ("0", "false", "no"):
        if "--isolated" not in out and "--user-data-dir" not in out:
            out.append("--isolated")
    if os.environ.get("ODYSSEUS_BROWSER_NO_SANDBOX", "1").lower() not in ("0", "false", "no"):
        if "--no-sandbox" not in out and "--sandbox" not in out:
            out.append("--no-sandbox")
    if os.environ.get("ODYSSEUS_BROWSER_CONSENT", "1").lower() not in ("0", "false", "no"):
        files = _browser_consent_files()
        if files:
            state_path, script_path = files
            # `--storage-state` vale solo per i contesti isolati; con un profilo
            # persistente i cookie restano da soli.
            if "--storage-state" not in out and "--isolated" in out:
                out.extend(["--storage-state", state_path])
            if "--init-script" not in out:
                out.extend(["--init-script", script_path])
    return out


def builtin_python_env(base_dir: str) -> dict[str, str]:
    """Environment for built-in Python MCP subprocesses.

    The app root must be importable so mcp_servers can import local modules, but
    replacing PYTHONPATH entirely hides site-packages in container/dev launches
    that rely on PYTHONPATH for their active environment.
    """
    existing = os.environ.get("PYTHONPATH", "")
    parts = [base_dir]
    for item in existing.split(os.pathsep):
        if item and item not in parts:
            parts.append(item)
    return {"PYTHONPATH": os.pathsep.join(parts)}


async def register_builtin_servers(mcp_manager):
    """Connect all built-in MCP servers to the manager."""
    if MCP_DISABLED:
        logger.info("Built-in MCP servers disabled via ODYSSEUS_DISABLE_MCP")
        return

    base_dir = get_app_root()
    python = sys.executable

    async def _connect_python_server(server_id: str, script_path: str, name: str):
        try:
            ok = await mcp_manager.connect_server(
                server_id=server_id,
                name=name,
                transport="stdio",
                command=python,
                args=[script_path],
                env=builtin_python_env(base_dir),
            )
            if ok:
                logger.info(f"Built-in MCP server registered: {name}")
            else:
                logger.warning(f"Built-in MCP server failed to connect: {name}")
        except asyncio.CancelledError:
            logger.warning(f"Built-in MCP server {name} cancelled")
            raise
        except BaseException as e:
            logger.warning(f"Built-in MCP server {name} error: {type(e).__name__}: {e}")

    for server_id, (script, name) in _BUILTIN_SERVERS.items():
        script_path = os.path.join(base_dir, script)
        if not os.path.exists(script_path):
            logger.warning(f"Built-in MCP server script not found: {script_path}")
            continue
        _spawn_bg(_connect_python_server(server_id, script_path, name))

    # Register NPX-based servers in the background (they take longer to start)
    npx_path = _find_npx()
    logger.info(f"NPX binary resolved to: {npx_path}")

    async def _start_npx_servers():
        await asyncio.sleep(3)  # let Python servers finish first
        for server_id, cfg in _BUILTIN_NPX_SERVERS.items():
            # Browser automation is a shipped built-in, so the default path
            # lets `npx -y` install @playwright/mcp on first start. Locked-down
            # installs can opt back into the old no-network startup behavior
            # with ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE=1.
            args = _browser_mcp_args(cfg["args"]) if server_id == "builtin_browser" else list(cfg["args"])
            pkg_spec = _npx_package_from_args(args)
            if BROWSER_MCP_REQUIRE_CACHE and pkg_spec and not await _is_npx_package_cached(npx_path, pkg_spec):
                logger.warning(
                    f"{cfg['name']} is not available.\n"
                    f"  Reason: npm package {pkg_spec!r} is not installed in the npx cache.\n"
                    f"  Impact: tools provided by this MCP server will be unavailable.\n"
                    f"  Fix:    {os.path.basename(npx_path)} -y {pkg_spec} --version\n"
                    f"          (run once, then restart Odysseus)\n"
                    f"  Notes:  ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE=1 is set, "
                    f"so Odysseus will not install browser automation on startup."
                )
                continue

            logger.info(f"Starting NPX server: {cfg['name']} ({npx_path} {' '.join(args)})")
            try:
                env = None
                if server_id == "builtin_browser":
                    cache_home = os.environ.get(
                        "ODYSSEUS_BROWSER_MCP_CACHE",
                        os.path.join(base_dir, "data", "local", "playwright-mcp-cache"),
                    )
                    os.makedirs(cache_home, exist_ok=True)
                    env = {"XDG_CACHE_HOME": cache_home}
                    # Do not force Playwright into a private empty browser
                    # directory.  A user may opt into a managed cache, while
                    # the default either uses the detected Chrome/Edge
                    # executable or Playwright's normal platform cache.
                    browsers_path = os.environ.get(
                        "ODYSSEUS_PLAYWRIGHT_BROWSERS_PATH", ""
                    ).strip()
                    if browsers_path:
                        env["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
                ok = await mcp_manager.connect_server(
                    server_id=server_id,
                    name=cfg["name"],
                    transport="stdio",
                    command=npx_path,
                    args=args,
                    env=env,
                )
                if ok:
                    logger.info(f"Built-in NPX server registered: {cfg['name']}")
                else:
                    logger.warning(f"Built-in NPX server failed to connect: {cfg['name']}")
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                logger.warning(f"Built-in NPX server {cfg['name']} error: {type(e).__name__}: {e}")

    _spawn_bg(_start_npx_servers())


def _npx_package_from_args(args):
    """Pick the package spec out of an npx args list shaped like
    ['-y', '<package@version>', ...flags]. Returns None if the
    convention doesn't match (we then skip the cache check and just
    try the connect)."""
    if not args:
        return None
    if "-y" in args:
        idx = args.index("-y") + 1
        if idx < len(args) and not args[idx].startswith("-"):
            return args[idx]
    # No -y prefix: first non-flag arg is the package
    for a in args:
        if not a.startswith("-"):
            return a
    return None


async def _is_npx_package_cached(npx_path, package_spec, timeout_s=5):
    """Probe whether an npx package is already in the local cache.

    First checks the local `_npx` cache for an installed package. If the
    package is not found there, falls back to `npx --no-install <pkg>
    --version` so older npm layouts still work without downloading.
    """
    if _is_package_in_npx_cache(package_spec):
        return True

    try:
        proc = await asyncio.create_subprocess_exec(
            npx_path, "--no-install", package_spec, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except NotImplementedError:
        try:
            result = subprocess.run(
                [npx_path, "--no-install", package_spec, "--version"],
                capture_output=True,
                timeout=timeout_s,
            )
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return False
        return result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, ValueError):
        return False
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return False
    except asyncio.CancelledError:
        # The probe was cancelled (e.g. app shutdown). Reap the child so it
        # isn't orphaned, then propagate the cancellation.
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise
    return proc.returncode == 0 and bool(stdout.strip())


def _is_package_in_npx_cache(package_spec):
    """Return True when npm's `_npx` cache already contains package_spec."""
    package_name, package_version = _npx_package_identity(package_spec)
    if not package_name:
        return False

    for cache_root in _npm_cache_roots():
        npx_root = os.path.join(cache_root, "_npx")
        if _npx_cache_contains_package(npx_root, package_name, package_version):
            return True
    return False


def _npx_package_name(package_spec):
    """Strip a version/range suffix from an npm package spec."""
    return _npx_package_identity(package_spec)[0]


def _npx_package_identity(package_spec):
    """Return ``(name, exact_version)`` for an npm package spec.

    Tags/ranges such as ``latest`` intentionally accept any cached version;
    an exact pin must match the package.json version as well as its name.
    """
    if not package_spec:
        return "", ""
    spec = str(package_spec).strip()
    if spec.startswith("@"):
        split_at = spec.rfind("@")
        if split_at > 0:
            name, requested = spec[:split_at], spec[split_at + 1:]
        else:
            name, requested = spec, ""
    else:
        name, sep, requested = spec.partition("@")
        if not sep:
            requested = ""
    exact = requested if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", requested) else ""
    return name, exact


def _npm_cache_roots():
    roots = []
    configured = os.environ.get("npm_config_cache")
    if configured:
        roots.append(os.path.expanduser(configured))
    roots.append(os.path.join(os.path.expanduser("~"), ".npm"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(os.path.join(local_app_data, "npm-cache"))
    return list(dict.fromkeys(roots))


def _npx_cache_contains_package(npx_root, package_name, package_version=""):
    if not os.path.isdir(npx_root):
        return False
    package_path = os.path.join("node_modules", *package_name.split("/"), "package.json")
    try:
        entries = list(os.scandir(npx_root))
    except OSError:
        return False
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        cached_name, cached_version = _cached_package_identity(
            os.path.join(entry.path, package_path)
        )
        if (
            is_dir
            and cached_name == package_name
            and (not package_version or cached_version == package_version)
        ):
            return True
    return False


def _cached_package_name(package_json_path):
    return _cached_package_identity(package_json_path)[0]


def _cached_package_identity(package_json_path):
    try:
        with open(package_json_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "", ""
    return (
        str(data.get("name", "")).strip(),
        str(data.get("version", "")).strip(),
    )
