"""llama-swap runtime awareness.

Vergilius serves every local profile through one llama-swap instance
(127.0.0.1:8012). Picking a different profile in the model dropdown makes
llama-swap kill the running llama-server and start another one, which takes
30-60 seconds from cold. Odysseus had no idea that was happening: the first
message after a switch just hung.

llama-swap exposes exactly what we need:

    GET  /running                    -> [{"model": "...", "state": "starting"|"ready"}]
    GET  /v1/models                  -> per-model {"status": {"value": "unloaded"}}
    GET  /upstream/{model}/{path}    -> proxy to the llama-server, LOADS IT FIRST
    POST /api/models/unload/{model}  -> stop one

Hitting any /upstream path is therefore both the warm-up trigger and, once the
server is up, the way to read llama.cpp's own `/props` — which reports
`modalities.vision` truthfully instead of guessing from the model name. That
matters here: our vision profiles are called `qwenpaw-vista` / `heretic-vista`
and Odysseus' name-based `is_vision_model()` sees no "vl"/"vision" keyword, so
it would strip images from a model that has an mmproj loaded.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

# A confirmed proxy is stable, but a failed startup probe is often only a race
# with the local service.  Never poison capability/loading detection for five
# minutes because the first 1.5-second request happened too early.
_KIND_POSITIVE_TTL = 300.0
_KIND_NEGATIVE_TTL = 2.0
# Runtime state changes on its own (ttl expiry, another client swapping the
# model), so it gets a short life.
_STATE_TTL = 2.0
# `modalities` is a property of the GGUF + mmproj pair, fixed for a profile.
# Cached for the process lifetime; llama-swap is restarted when config.yaml
# changes, and so is Odysseus.
# Config is watched live by llama-swap; a day-long cache could keep an old
# n_ctx after a config reload. Capability probes are cheap and only hit a ready
# model, so one minute is enough to suppress chatter without going stale.
_PROPS_TTL = 60.0

_lock = threading.Lock()
_kind_cache: Dict[str, Tuple[bool, float]] = {}
_state_cache: Dict[str, Tuple[Dict[str, str], float]] = {}
_props_cache: Dict[Tuple[str, str], Tuple[Dict[str, Any], float]] = {}


def swap_base(endpoint_url: str) -> str:
    """Strip the OpenAI path suffix so we can reach llama-swap's own routes.

    Endpoints are stored as `http://127.0.0.1:8012/v1`; `/running` and
    `/upstream/...` live one level up.
    """
    if not endpoint_url:
        return ""
    parsed = urlparse(endpoint_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))


def _cached(cache: Dict, key, ttl: float):
    with _lock:
        hit = cache.get(key)
    if hit is not None and (time.time() - hit[1]) < ttl:
        return hit[0]
    return None


def _store(cache: Dict, key, value) -> None:
    with _lock:
        cache[key] = (value, time.time())


def is_llamaswap(endpoint_url: str) -> bool:
    """True for llama-swap; negative startup probes are cached only briefly.

    Anything that answers `GET /running` with a `running` list is one; a plain
    llama-server, Ollama or a cloud API 404s.
    """
    base = swap_base(endpoint_url)
    if not base:
        return False
    hit = _cached(_kind_cache, base, _KIND_POSITIVE_TTL)
    if hit is True:
        return True
    hit = _cached(_kind_cache, base, _KIND_NEGATIVE_TTL)
    if hit is False:
        return False
    verdict = False
    try:
        r = httpx.get(f"{base}/running", timeout=1.5)
        verdict = r.is_success and isinstance(r.json().get("running"), list)
    except Exception:
        verdict = False
    _store(_kind_cache, base, verdict)
    return verdict


def _states(base: str) -> Dict[str, str]:
    """{model_id: state} for every profile llama-swap knows about.

    `/running` only lists what is up, so `/v1/models` fills in the rest as
    `unloaded` — otherwise a model that has never been started looks unknown
    and the UI can't tell "not loaded yet" from "endpoint is down".
    """
    hit = _cached(_state_cache, base, _STATE_TTL)
    if hit is not None:
        return hit
    states: Dict[str, str] = {}
    try:
        r = httpx.get(f"{base}/v1/models", timeout=2.0)
        if r.is_success:
            for item in r.json().get("data") or []:
                mid = str(item.get("id") or "")
                if mid:
                    states[mid] = str((item.get("status") or {}).get("value") or "unloaded")
    except Exception:
        pass
    try:
        r = httpx.get(f"{base}/running", timeout=2.0)
        if r.is_success:
            for item in r.json().get("running") or []:
                mid = str(item.get("model") or "")
                if mid:
                    states[mid] = str(item.get("state") or "ready")
    except Exception:
        pass
    _store(_state_cache, base, states)
    return states


def model_state(endpoint_url: str, model: str) -> str:
    """`ready`, `starting`, `stopping`, `unloaded`, or `` when unknown."""
    base = swap_base(endpoint_url)
    if not base or not model:
        return ""
    return _states(base).get(model, "")


def start_load(endpoint_url: str, model: str, timeout: float = 2.0) -> None:
    """Ask llama-swap to bring `model` up, without waiting for it.

    Any /upstream request triggers the swap; `/health` is the cheapest one and
    costs no prompt evaluation. The short timeout is expected to expire while
    the model is still loading — llama-swap keeps going regardless, which is
    exactly what we want since the caller polls `model_state()`.
    """
    base = swap_base(endpoint_url)
    if not base or not model:
        return
    with _lock:
        _state_cache.pop(base, None)
        _props_cache.pop((base, model), None)
    try:
        model_path = quote(str(model), safe="")
        httpx.get(f"{base}/upstream/{model_path}/health", timeout=timeout)
    except Exception:
        pass


# Upper bound on how long `props(load=True)` waits for a cold profile. A Q4 9B
# needs ~50s on the 1080; past three minutes something is wrong and the caller
# is better off with "unknown" than with a hung request.
_LOAD_WAIT_SECONDS = 180.0


def props(
    endpoint_url: str,
    model: str,
    timeout: float = 5.0,
    load: bool = False,
) -> Optional[Dict[str, Any]]:
    """llama.cpp `/props` for a profile, or None when it can't be read.

    By default this does NOT trigger a load: asking for capabilities must never
    evict the model the user is currently talking to.

    `load=True` is for the one case where it is free — an image is attached, so
    this profile is about to be started by the very next request anyway. Then
    the wait is the same wait, just moved early enough to route the image
    correctly instead of stripping it.
    """
    base = swap_base(endpoint_url)
    if not base or not model:
        return None
    key = (base, model)
    hit = _cached(_props_cache, key, _PROPS_TTL)
    if hit is not None:
        return hit
    if _states(base).get(model) != "ready" and load:
        start_load(endpoint_url, model, timeout=_LOAD_WAIT_SECONDS)
    if _states(base).get(model) != "ready":
        return None
    try:
        model_path = quote(str(model), safe="")
        r = httpx.get(f"{base}/upstream/{model_path}/props", timeout=timeout)
        if not r.is_success:
            return None
        payload = r.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    modalities = payload.get("modalities") or {}
    ctx = (payload.get("default_generation_settings") or {}).get("n_ctx")
    summary = {
        "vision": bool(modalities.get("vision")),
        "audio": bool(modalities.get("audio")),
        "context_tokens": int(ctx) if isinstance(ctx, int) else None,
        "model_path": str(payload.get("model_path") or ""),
    }
    _store(_props_cache, key, summary)
    logger.info("[llama-swap] %s capabilities: %s", model, summary)
    return summary


def supports_vision(endpoint_url: str, model: str, load: bool = False) -> Optional[bool]:
    """True/False from the loaded server, None when it can't be determined.

    None means "no opinion" so callers fall back to Odysseus' name heuristic
    rather than silently deciding the model is blind. A profile that is merely
    unloaded is unknown, never blind: `qwenpaw-vista` has a projector whether
    or not its process happens to be up.
    """
    if not is_llamaswap(endpoint_url):
        return None
    info = props(endpoint_url, model, load=load)
    if info is None:
        return None
    return bool(info["vision"])


def vista_esterna(model: str) -> bool:
    """Vergilius: un profilo `*-vista` SENZA proiettore (es. `lfm-vista`) vede
    attraverso gli occhi esterni (Holo, src/vista). Diverso dalla vista nativa
    (`qwenpaw-vista`, mmproj): qui le immagini NON vanno al modello — le
    descrive Holo — quindi `vision` resta False e questo flag dice alla UI
    "ha la vista" e al warmup "avvia gli occhi"."""
    m = (model or "").lower().rsplit("/", 1)[-1]
    return m.endswith("-vista") and m.startswith("lfm")


def status(endpoint_url: str, model: str) -> Dict[str, Any]:
    """Everything the UI needs for one profile in a single call."""
    if not is_llamaswap(endpoint_url):
        return {"swap": False, "state": "", "vision": None, "context_tokens": None}
    state = model_state(endpoint_url, model)
    info = props(endpoint_url, model) if state == "ready" else None
    out = {
        "swap": True,
        "state": state,
        "vision": (info or {}).get("vision") if info else None,
        "context_tokens": (info or {}).get("context_tokens") if info else None,
    }
    if vista_esterna(model):
        out["vista_esterna"] = True
        try:
            from src.vista.client import get_vista
            out["occhi_pronti"] = get_vista().pronto()
        except Exception:
            out["occhi_pronti"] = False
    return out
