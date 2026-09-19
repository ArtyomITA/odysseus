import json
import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import types


ROOT = Path(__file__).resolve().parent.parent


def _load_builtin_mcp(monkeypatch):
    core = types.ModuleType("core")
    core.__path__ = []
    platform_compat = types.ModuleType("core.platform_compat")
    platform_compat.IS_WINDOWS = False
    platform_compat.which_tool = lambda name: None
    monkeypatch.setitem(sys.modules, "core", core)
    monkeypatch.setitem(sys.modules, "core.platform_compat", platform_compat)

    spec = importlib.util.spec_from_file_location(
        "builtin_mcp_under_test",
        ROOT / "src" / "builtin_mcp.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_npx_package_from_args_prefers_package_after_y_flag(monkeypatch):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp._npx_package_from_args(
        ["-y", "@playwright/mcp@latest", "--headless"]
    ) == "@playwright/mcp@latest"


def test_builtin_browser_uses_verified_playwright_pin(monkeypatch):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._BUILTIN_NPX_SERVERS["builtin_browser"]["args"]
    assert builtin_mcp.PLAYWRIGHT_MCP_PACKAGE == "@playwright/mcp@0.0.79"
    assert args[:2] == ["-y", "@playwright/mcp@0.0.79"]
    assert "@playwright/mcp@latest" not in args


def test_browser_mcp_cache_requirement_is_opt_in(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE", raising=False)
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is False


def test_browser_mcp_cache_requirement_can_be_enabled(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE", "1")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is True


def test_browser_mcp_args_use_configured_browser_executable(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "/usr/bin/chromium" in args
    assert "--isolated" in args
    assert "--no-sandbox" in args


def test_windows_browser_discovery_finds_installed_chrome(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    chrome = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"")
    monkeypatch.setattr(builtin_mcp, "IS_WINDOWS", True)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", "")
    monkeypatch.setenv("LOCALAPPDATA", "")

    assert builtin_mcp._find_browser_executable() == str(chrome)


def test_browser_mcp_args_can_use_persistent_profile_when_requested(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("ODYSSEUS_BROWSER_ISOLATED", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "--isolated" not in args


def test_browser_mcp_args_respect_explicit_user_data_dir(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args([
        "-y", "@playwright/mcp@latest", "--headless", "--user-data-dir", "/tmp/profile",
    ])

    assert "--user-data-dir" in args
    assert "--isolated" not in args


def test_browser_mcp_args_can_keep_sandbox(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("ODYSSEUS_BROWSER_NO_SANDBOX", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "--no-sandbox" not in args


def test_npx_cache_check_detects_scoped_package_in_npx_cache(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    package_json = (
        tmp_path
        / ".npm"
        / "_npx"
        / "9833c18b2d85bc59"
        / "node_modules"
        / "@playwright"
        / "mcp"
        / "package.json"
    )
    package_json.parent.mkdir(parents=True)
    package_json.write_text('{"name":"@playwright/mcp","version":"0.0.76"}', encoding="utf-8")

    async def unexpected_exec(*args, **kwargs):
        raise AssertionError("cache hit should not shell out to npx")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("npm_config_cache", str(tmp_path / ".npm"))
    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unexpected_exec)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is True


def test_npx_cache_check_falls_back_when_async_subprocess_is_unsupported(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    async def unsupported_exec(*args, **kwargs):
        raise NotImplementedError("subprocess transport unavailable")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout=b"1.2.3\n", stderr=b"")

    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unsupported_exec)
    monkeypatch.setattr(builtin_mcp.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("npm_config_cache", str(tmp_path / ".npm"))

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx.cmd",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is True
    assert captured["args"] == [
        "npx.cmd",
        "--no-install",
        "@playwright/mcp@latest",
        "--version",
    ]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["timeout"] == 2


def test_npx_cache_check_fallback_treats_timeout_as_cache_miss(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    async def unsupported_exec(*args, **kwargs):
        raise NotImplementedError("subprocess transport unavailable")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unsupported_exec)
    monkeypatch.setattr(builtin_mcp.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("npm_config_cache", str(tmp_path / ".npm"))

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx.cmd",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is False


def test_exact_npx_pin_rejects_different_cached_version(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    package_json = (
        tmp_path / ".npm" / "_npx" / "old" / "node_modules"
        / "@playwright" / "mcp" / "package.json"
    )
    package_json.parent.mkdir(parents=True)
    package_json.write_text(
        '{"name":"@playwright/mcp","version":"0.0.76"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("npm_config_cache", str(tmp_path / ".npm"))

    assert builtin_mcp._is_package_in_npx_cache("@playwright/mcp@0.0.79") is False
    assert builtin_mcp._is_package_in_npx_cache("@playwright/mcp@latest") is True


def test_browser_mcp_args_add_consent_state_and_init_script(monkeypatch, tmp_path):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("ODYSSEUS_DATA_DIR", str(tmp_path))
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@0.0.79", "--headless"])

    assert "--storage-state" in args and "--init-script" in args
    state = json.loads((tmp_path / "local" / "browser-consent-state.json").read_text(encoding="utf-8"))
    assert {c["name"] for c in state["cookies"]} == {"SOCS"}
    assert ".youtube.com" in {c["domain"] for c in state["cookies"]}
    script = (tmp_path / "local" / "browser-consent-init.js").read_text(encoding="utf-8")
    assert "rifiuta tutto" in script.lower() and "reject all" in script.lower()


def test_browser_mcp_args_consent_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("ODYSSEUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ODYSSEUS_BROWSER_CONSENT", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@0.0.79", "--headless"])

    assert "--storage-state" not in args and "--init-script" not in args
