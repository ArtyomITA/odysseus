from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def test_llamaswap_context_uses_ready_upstream_props(monkeypatch):
    from src import model_context
    from src import llamaswap

    calls = []
    monkeypatch.setattr(model_context, "is_local_endpoint", lambda _url: True)
    monkeypatch.setattr(llamaswap, "is_llamaswap", lambda _url: True)

    def fake_props(endpoint, model, load=False):
        calls.append((endpoint, model, load))
        return {"context_tokens": 49152}

    monkeypatch.setattr(llamaswap, "props", fake_props)
    monkeypatch.setattr(
        model_context.httpx,
        "get",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("direct /slots must be skipped")),
    )
    assert model_context._query_context_length(
        "http://127.0.0.1:8012/v1", "ling-vista"
    ) == (49152, True)
    assert calls == [("http://127.0.0.1:8012/v1", "ling-vista", False)]


def test_production_runtime_flags_preserve_live_prefix_cache():
    config = (ROOT.parent / "llama-swap" / "config.yaml").read_text(encoding="utf-8")
    assert "--cache-ram 0" in config
    assert "--load-mode mmap" in config
    assert "--no-mmap" not in config
    assert "--mlock" not in config
    assert "--batch-size 2048 --ubatch-size 1024" in config
    assert "--no-cache-prompt" not in config


def test_holo_warmup_is_post_ling_and_deduplicated():
    routes = (ROOT / "routes" / "model_routes.py").read_text(encoding="utf-8")
    client = (ROOT / "src" / "vista" / "client.py").read_text(encoding="utf-8")
    assert 'llamaswap.model_state(base, model) == "ready"' in routes
    assert "_v.avvia_in_background(" in routes
    assert "target=_v.avvia" not in routes
    assert "self._warmup_thread.is_alive()" in client
    assert "with self._inference_lock" in client
    assert "expected_generation" in client
    assert "kwargs={\"expected_generation\": _stop_generation}" in routes
    status_body = routes.split('def model_runtime_status', 1)[1].split(
        '@router.post("/model-runtime/warmup")', 1
    )[0]
    assert "imposta_attiva" not in status_body
    assert "avvia_in_background" not in status_body


def test_verified_playwright_version_is_pinned():
    source = (ROOT / "src" / "builtin_mcp.py").read_text(encoding="utf-8")
    assert 'PLAYWRIGHT_MCP_PACKAGE = "@playwright/mcp@0.0.79"' in source
    assert '"@playwright/mcp@latest"' not in source
    assert '"PLAYWRIGHT_BROWSERS_PATH": os.path.join' not in source


def test_llamaswap_negative_probe_expires_quickly(monkeypatch):
    from src import llamaswap

    now = [100.0]
    calls = []

    class _Response:
        is_success = True

        @staticmethod
        def json():
            return {"running": []}

    def fake_get(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise OSError("startup race")
        return _Response()

    llamaswap._kind_cache.clear()
    monkeypatch.setattr(llamaswap.time, "time", lambda: now[0])
    monkeypatch.setattr(llamaswap.httpx, "get", fake_get)
    endpoint = "http://127.0.0.1:8012/v1"
    assert llamaswap.is_llamaswap(endpoint) is False
    now[0] += 1.0
    assert llamaswap.is_llamaswap(endpoint) is False
    assert len(calls) == 1
    now[0] += 2.0
    assert llamaswap.is_llamaswap(endpoint) is True
    assert len(calls) == 2
    llamaswap._kind_cache.clear()


def test_holo_stale_start_and_stop_generations_are_cancelled(monkeypatch):
    from src.vista import client as vista

    v = vista.VistaClient()
    start_generation = v.imposta_attiva(True)
    stop_generation = v.imposta_attiva(False)
    monkeypatch.setattr(vista.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        vista.subprocess,
        "Popen",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("stale start spawned")),
    )
    with pytest.raises(vista.VistaNonDisponibile, match="annullato"):
        v.avvia(attendi=False, expected_generation=start_generation)

    class _Proc:
        def __init__(self):
            self.kills = 0

        def poll(self):
            return None

        def kill(self):
            self.kills += 1

        def wait(self, timeout=None):
            return 0

    proc = _Proc()
    v._proc = proc
    v.imposta_attiva(True)
    v.ferma(expected_generation=stop_generation)
    assert proc.kills == 0


def test_vista_handler_fails_closed_when_profile_is_inactive(monkeypatch):
    from src.agent_tools import vista_tools
    from src.vista import client as vista

    fake = vista.VistaClient()
    monkeypatch.setattr(vista, "get_vista", lambda: fake)
    with pytest.raises(vista.VistaNonDisponibile, match="non sono attivi"):
        vista_tools._vista_pronta()


def test_model_warmup_rejects_unknown_and_deduplicates_vista_watchers():
    routes = (ROOT / "routes" / "model_routes.py").read_text(encoding="utf-8")
    assert 'raise HTTPException(404, "Unknown llama-swap model profile")' in routes
    assert "_vista_watcher_keys" in routes
    assert "_vista_watcher_lock" in routes


def test_holo_off_on_during_stale_warmup_starts_latest_generation(monkeypatch):
    import threading

    from src.vista import client as vista

    v = vista.VistaClient()
    old_entered = threading.Event()
    release_old = threading.Event()
    latest_started = threading.Event()
    calls = []

    def fake_avvia(*, attendi=True, expected_generation=None):
        calls.append(expected_generation)
        if expected_generation == first_generation:
            old_entered.set()
            release_old.wait(timeout=2)
        else:
            latest_started.set()
        return {}

    monkeypatch.setattr(v, "avvia", fake_avvia)
    first_generation = v.imposta_attiva(True)
    v.avvia_in_background(expected_generation=first_generation)
    old_thread = v._warmup_thread
    assert old_entered.wait(timeout=1)

    v.imposta_attiva(False)
    latest_generation = v.imposta_attiva(True)
    v.avvia_in_background(expected_generation=latest_generation)
    latest_thread = v._warmup_thread

    try:
        assert latest_generation != first_generation
        assert latest_started.wait(timeout=1)
        assert calls == [first_generation, latest_generation]
    finally:
        release_old.set()
        if old_thread is not None:
            old_thread.join(timeout=2)
        if latest_thread is not None:
            latest_thread.join(timeout=2)


def test_holo_same_generation_background_warmup_is_deduplicated(monkeypatch):
    import threading

    from src.vista import client as vista

    v = vista.VistaClient()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_avvia(*, attendi=True, expected_generation=None):
        calls.append(expected_generation)
        entered.set()
        release.wait(timeout=2)
        return {}

    monkeypatch.setattr(v, "avvia", fake_avvia)
    generation = v.imposta_attiva(True)
    v.avvia_in_background(expected_generation=generation)
    worker = v._warmup_thread
    assert entered.wait(timeout=1)
    v.avvia_in_background(expected_generation=generation)
    assert calls == [generation]
    release.set()
    if worker is not None:
        worker.join(timeout=2)


def test_holo_ready_but_cold_is_warmed_for_current_generation(monkeypatch):
    from src.vista import client as vista

    v = vista.VistaClient()
    generation = v.imposta_attiva(True)
    warmed = []
    monkeypatch.setattr(v, "pronto", lambda: True)
    monkeypatch.setattr(
        v,
        "_scalda",
        lambda expected_generation=None: warmed.append(expected_generation),
    )

    v.avvia(attendi=True, expected_generation=generation)
    assert warmed == [generation]


def test_holo_parent_log_handle_is_closed_after_spawn(monkeypatch):
    from src.vista import client as vista

    class _Log:
        closed = False

        def close(self):
            self.closed = True

    class _Proc:
        pid = 123

        @staticmethod
        def poll():
            return None

    v = vista.VistaClient()
    generation = v.imposta_attiva(True)
    log = _Log()
    popen_stdout = []
    monkeypatch.setattr(v, "pronto", lambda: False)
    monkeypatch.setattr(vista.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(vista.os, "makedirs", lambda *_a, **_k: None)
    monkeypatch.setattr(vista, "open", lambda *_a, **_k: log, raising=False)

    def fake_popen(*_args, **kwargs):
        popen_stdout.append(kwargs["stdout"])
        return _Proc()

    monkeypatch.setattr(vista.subprocess, "Popen", fake_popen)
    v.avvia(attendi=False, expected_generation=generation)

    assert popen_stdout == [log]
    assert log.closed is True


def test_model_warmup_route_deduplicates_same_generation_watcher(monkeypatch):
    import threading
    from types import SimpleNamespace

    from routes import model_routes
    from src import llamaswap
    from src.vista import client as vista

    endpoint_url = "http://127.0.0.1:8012/v1"

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        @staticmethod
        def all():
            return [SimpleNamespace(base_url=endpoint_url)]

    class _Db:
        @staticmethod
        def query(*_args, **_kwargs):
            return _Query()

        @staticmethod
        def close():
            return None

    class _Vista:
        @staticmethod
        def imposta_attiva(_value):
            return 7

        @staticmethod
        def pronto():
            return False

        @staticmethod
        def generazione_attiva(_generation):
            return True

        @staticmethod
        def avvia_in_background(*, expected_generation=None):
            raise AssertionError("watcher must wait for Ling")

    started = []

    class _Thread:
        def __init__(self, *, target, name=None, daemon=None, **_kwargs):
            self.target = target
            self.name = name

        def start(self):
            started.append(self)

    monkeypatch.setattr(model_routes, "SessionLocal", _Db)
    monkeypatch.setattr(model_routes, "effective_user", lambda _request: "")
    monkeypatch.setattr(model_routes, "_auth_disabled", lambda: True)
    monkeypatch.setattr(llamaswap, "is_llamaswap", lambda _base: True)
    monkeypatch.setattr(llamaswap, "model_state", lambda _base, _model: "starting")
    monkeypatch.setattr(llamaswap, "vista_esterna", lambda _model: True)
    monkeypatch.setattr(vista, "get_vista", lambda: _Vista())
    monkeypatch.setattr(threading, "Thread", _Thread)

    router = model_routes.setup_model_routes(None)
    warmup = next(
        route.endpoint
        for route in router.routes
        if getattr(route, "path", "") == "/api/model-runtime/warmup"
    )
    request = SimpleNamespace(
        state=SimpleNamespace(),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)),
    )
    payload = {"endpoint_url": endpoint_url, "model": "ling-vista"}

    assert warmup(request, payload) == {"swap": True, "state": "starting"}
    assert warmup(request, payload) == {"swap": True, "state": "starting"}
    assert [thread.name for thread in started] == ["vista-after-ling"]
