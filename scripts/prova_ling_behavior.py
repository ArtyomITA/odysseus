"""Characterise Ling-3.0-tiny's natural chat and tool-call behaviour.

This is a read-only model harness: it calls llama-swap directly and never
executes a tool.  It compares prompt language/style, schema pressure/order,
thinking, and multi-turn reasoning preservation.  Every request is sequential
and guarded by host-RAM/GPU checks for the GTX 1080 workstation.

Examples (from the Odysseus directory):
  venv\\Scripts\\python.exe scripts\\prova_ling_behavior.py --suite baseline
  venv\\Scripts\\python.exe scripts\\prova_ling_behavior.py --suite all --repeats 2
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import queue
import random
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Import through the compatibility facade: importing tool_schemas first has a
# legacy circular dependency in this repository.
from src.agent_tools import FUNCTION_TOOL_SCHEMAS  # noqa: E402
from src.agent_loop import _API_AGENT_RULES  # noqa: E402
from src.tool_parsing import parse_reasoning_tool_calls, strip_tool_blocks  # noqa: E402


DEFAULT_ENDPOINT = "http://127.0.0.1:8012/v1/chat/completions"
DEFAULT_MODEL = "ling"
MIN_FREE_RAM_GB = 1.0   # dopo il trim del working set (vedi _trim_llama_gpu_ws) e' una soglia vera
MIN_FREE_VRAM_MIB = 300
MAX_GPU_TEMP_C = 90        # abort; la GTX 1080 throttla da sola a ~83, limite hw 94
COOL_GPU_TEMP_C = 84       # sopra: pausa di raffreddamento, non abort (23 ago)
COOL_RESUME_TEMP_C = 76
_ALLOW_UNKNOWN_GUARDS = False
_REQUEST_TIMEOUT = 180
# Onda 4 (27 ago 2026): campi extra da fondere in OGNI payload (es. reasoning_budget_tokens)
EXTRA_PAYLOAD: dict = {}


class GuardAbort(RuntimeError):
    pass


class TransportAbort(RuntimeError):
    pass


PROMPTS = {
    "en_controlled": (
        "You are Vergilius, a capable and friendly personal assistant. "
        "Answer in the user's language. Use an available tool when it is "
        "needed to perform or verify the request. Never invent a tool result."
    ),
    "production_fragment": (
        "You are Vergilius. Always answer the user in their language.\n" +
        _API_AGENT_RULES
    ),
    "it_controlled": (
        "Sei Vergilius, un assistente personale capace e cordiale. "
        "Rispondi nella lingua dell'utente. Usa uno strumento disponibile "
        "quando serve per eseguire o verificare la richiesta. Non inventare "
        "mai il risultato di uno strumento."
    ),
    "caveman_lite": (
        "You are Vergilius. Reply in the user's language. Need action or fresh "
        "facts: use the matching available tool with exact arguments. Never "
        "invent results or browser refs. Otherwise answer directly. "
        "These compressed operational notes are not the response style; "
        "answer naturally in complete sentences."
    ),
    "caveman_max": (
        "You Vergilius. Reply user language. Need action/fresh data -> tool. "
        "Exact tool + exact args. No fake result. No selector invention. "
        "Tool succeeds -> brief confirm. Tool fails -> fix or state block. "
        "No needed tool -> answer direct. Finish task, no narration. "
        "Compressed notes not response style. Natural complete sentences."
    ),
}


@dataclass(frozen=True)
class Case:
    case_id: str
    it: str
    en: str
    expected: tuple[str, ...]
    args: tuple[tuple[str, Any], ...] = ()
    should_call: bool = True
    args_en: tuple[tuple[str, Any], ...] = ()   # attese per il prompt inglese, se diverse (23 ago)


CASES = (
    Case(
        "browser_open",
        "Apri https://example.com nel browser.",
        "Open https://example.com in the browser.",
        ("browser_open",),
        (("url", "https://example.com"),),
    ),
    Case(
        "browser_read",
        "Leggi la pagina attualmente aperta nel browser.",
        "Read the page currently open in the browser.",
        ("browser_read",),
    ),
    Case(
        "browser_find",
        "Trova la parola Privacy nella pagina aperta.",
        "Find the word Privacy on the open page.",
        ("browser_find",),
        (("text", "privacy"),),
    ),
    Case(
        "browser_click",
        "Clicca l'elemento del browser con ref e12.",
        "Click the browser element with ref e12.",
        ("browser_click",),
        (("ref", "e12"),),
    ),
    Case(
        "browser_type",
        "Nel campo del browser con ref e4 scrivi ciao mondo e premi Invio.",
        "In browser field ref e4 type hello world and press Enter.",
        ("browser_type",),
        (("ref", "e4"), ("text", "ciao mondo"), ("submit", True)),
        args_en=(("ref", "e4"), ("text", "hello world"), ("submit", True)),
    ),
    Case(
        "web_search",
        "Cerca sul web le notizie CUDA di oggi.",
        "Search the web for today's CUDA news.",
        ("web_search",),
        (("query", "cuda"), ("time_filter", "day")),
    ),
    Case(
        "read_file",
        r"Leggi il file D:\assistenteeee\PROMTREALE.MD.",
        r"Read the file D:\assistenteeee\PROMTREALE.MD.",
        ("read_file",),
        (("path", "promtreale.md"),),
    ),
    Case(
        "email_unread",
        "Mostrami le email non lette nella posta in arrivo.",
        "Show me the unread emails in the inbox.",
        ("list_emails",),
        (("unread_only", True),),
    ),
    Case(
        "calendar_list",
        "Controlla cosa ho in calendario domani.",
        "Check what is on my calendar tomorrow.",
        ("manage_calendar",),
        (("action", "list_events"),),
    ),
    Case(
        "no_tool_concept",
        "Spiegami in due frasi che cos'è una cache KV.",
        "Explain what a KV cache is in two sentences.",
        (),
        should_call=False,
    ),
    Case(
        "no_tool_unknown",
        "Qual è il numero di serie del mio tostapane? Non inventarlo.",
        "What is my toaster's serial number? Do not make it up.",
        (),
        should_call=False,
    ),
)


COMMUNICATION_CASES = (
    Case(
        "comm_analogy",
        "Spiegami la cache KV come a un amico curioso, in massimo tre frasi.",
        "Explain KV cache to a curious friend in at most three sentences.",
        (), should_call=False,
    ),
    Case(
        "comm_constraint",
        "Quanto fa 17 per 23? Rispondi soltanto con il numero.",
        "What is 17 times 23? Answer with only the number.",
        (), should_call=False,
    ),
    Case(
        "comm_correction",
        "La GTX 1080 ha Tensor Core, vero? Correggimi se la premessa è falsa.",
        "The GTX 1080 has Tensor Cores, right? Correct me if that premise is false.",
        (), should_call=False,
    ),
    Case(
        "comm_uncertainty",
        "Dimmi il colore della tazza che ho ora sulla scrivania. Non puoi vederla.",
        "Tell me the color of the mug currently on my desk. You cannot see it.",
        (), should_call=False,
    ),
    Case(
        "comm_tone",
        "In poche righe, dimmi con sincerità perché un modello piccolo può usare male troppi tool.",
        "Briefly and candidly explain why a small model may misuse too many tools.",
        (), should_call=False,
    ),
)


BROWSER_NAMES = (
    "browser_open", "browser_read", "browser_find", "browser_click",
    "browser_type", "browser_back", "browser_more",
)
MIXED_NAMES = BROWSER_NAMES + (
    "web_search", "web_fetch", "read_file", "ls", "manage_calendar",
    "list_emails", "read_email", "ui_control", "manage_memory",
)
PRESSURE_NAMES = MIXED_NAMES + (
    "bash", "python", "grep", "glob", "create_document", "edit_document",
    "manage_settings", "trigger_research",
)


def _schema_map() -> dict[str, dict[str, Any]]:
    result = {}
    for schema in FUNCTION_TOOL_SCHEMAS:
        name = str((schema.get("function") or {}).get("name") or "")
        if name and name not in result:
            result[name] = copy.deepcopy(schema)
    return result


SCHEMA_BY_NAME = _schema_map()


_SCHEMA_IT = {
    "browser_open": "Apri un URL http/https nel browser.",
    "browser_read": "Leggi l'albero accessibile della pagina corrente.",
    "browser_find": "Trova testo nella pagina corrente.",
    "browser_click": "Clicca una ref esatta dell'ultimo albero browser.",
    "browser_type": "Scrivi in una ref esatta e, se richiesto, premi Invio.",
    "browser_back": "Torna alla pagina browser precedente.",
    "browser_more": "Espone una famiglia di strumenti browser specialistici.",
    "web_search": "Cerca informazioni aggiornate sul web.",
    "web_fetch": "Leggi il contenuto di un URL.",
    "read_file": "Leggi un file locale autorizzato.",
    "ls": "Elenca file e cartelle.",
    "manage_calendar": "Leggi o gestisci il calendario.",
    "list_emails": "Elenca le email della casella richiesta.",
    "read_email": "Leggi una email tramite il suo UID.",
    "ui_control": "Controlla un pannello o una modalità dell'interfaccia.",
    "manage_memory": "Leggi o gestisci la memoria persistente.",
}
_PARAM_IT = {
    "url": "URL assoluto.", "query": "Testo da cercare.",
    "time_filter": "Filtro temporale.", "ref": "Ref esatta dell'albero.",
    "text": "Testo richiesto.", "submit": "Premi Invio dopo la scrittura.",
    "path": "Percorso del file.", "action": "Azione da eseguire.",
}


def schemas(
    names: tuple[str, ...],
    *,
    short: bool = False,
    language: str = "en",
) -> list[dict[str, Any]]:
    out = [copy.deepcopy(SCHEMA_BY_NAME[name]) for name in names if name in SCHEMA_BY_NAME]
    if not short and language == "en":
        return out
    for schema in out:
        fn = schema["function"]
        if language == "it":
            fn["description"] = _SCHEMA_IT.get(
                fn.get("name"), f"Esegui lo strumento {fn.get('name')}."
            )
        else:
            description = str(fn.get("description") or "")
            fn["description"] = re.split(r"(?<=[.!?])\s+", description, maxsplit=1)[0][:180]
        for key, prop in (fn.get("parameters") or {}).get("properties", {}).items():
            if isinstance(prop, dict):
                if language == "it":
                    prop["description"] = _PARAM_IT.get(key, "Valore richiesto.")
                elif short:
                    prop.pop("description", None)
    return out


def _free_ram_gb() -> float:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return -1.0
    return status.ullAvailPhys / (1024 ** 3)


def _gpu_state() -> dict[str, float]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=memory.free,memory.used,temperature.gpu,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        values = [float(part.strip()) for part in raw.stdout.splitlines()[0].split(",")]
        return {"free_mib": values[0], "used_mib": values[1], "temp_c": values[2], "util": values[3]}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {}


def _trim_llama_gpu_ws() -> None:
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='llama-server.exe'", "get", "processid,commandline", "/format:csv"],
            capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout
    except Exception:
        return
    for riga in out.splitlines():
        if "llama-server" not in riga or ("--n-gpu-layers 999" not in riga and "-ngl 999" not in riga):
            continue
        try:
            pid = int(riga.strip().split(",")[-1])
        except ValueError:
            continue
        h = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0400, False, pid)
        if h:
            ctypes.windll.kernel32.SetProcessWorkingSetSize(h, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
            ctypes.windll.kernel32.CloseHandle(h)


def guard() -> dict[str, Any]:
    state = {"free_ram_gb": round(_free_ram_gb(), 3), "gpu": _gpu_state()}
    if state["free_ram_gb"] < 0 and not _ALLOW_UNKNOWN_GUARDS:
        raise GuardAbort("RAM guard unavailable")
    if 0 <= state["free_ram_gb"] < MIN_FREE_RAM_GB:
        # Prima di abortire: svuota il working set dei llama-server tutti-in-GPU
        # (la mappa mmap del GGUF non serve piu' dopo l'upload: +5 GB liberi,
        # velocita' invariata; misurato 23 ago). Stessa logica del boot.
        _trim_llama_gpu_ws()
        state["free_ram_gb"] = round(_free_ram_gb(), 3)
    if 0 <= state["free_ram_gb"] < MIN_FREE_RAM_GB:
        raise GuardAbort(f"RAM guard: only {state['free_ram_gb']:.2f} GiB free")
    if not state["gpu"] and not _ALLOW_UNKNOWN_GUARDS:
        raise GuardAbort("GPU guard unavailable (nvidia-smi failed)")
    free_vram = state["gpu"].get("free_mib")
    if free_vram is not None and free_vram < MIN_FREE_VRAM_MIB:
        raise GuardAbort(f"VRAM guard: only {free_vram:.0f} MiB free")
    temp = state["gpu"].get("temp_c")
    if temp is not None and temp >= MAX_GPU_TEMP_C:
        raise GuardAbort(f"GPU temperature guard: {temp:.0f} C")
    if temp is not None and temp >= COOL_GPU_TEMP_C:
        # Raffreddamento: la 1080 a 84 C sta solo throttlando; aspettare
        # qualche decina di secondi e' meglio che buttare via il banco.
        waited = 0
        while waited < 240:
            time.sleep(10)
            waited += 10
            t2 = (_gpu_state() or {}).get("temp_c")
            if t2 is None or t2 <= COOL_RESUME_TEMP_C:
                break
        state["cooled_s"] = waited
        state["gpu"] = _gpu_state() or state["gpu"]
    return state


def _post_json_once(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise TransportAbort(f"request failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(result, dict):
        raise TransportAbort("server returned a non-object JSON response")
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise TransportAbort(f"response has no valid choices[0]: {str(result)[:500]}")
    if not isinstance(choices[0].get("message"), dict):
        raise TransportAbort(f"response has no valid message: {str(result)[:500]}")
    return result


def post_json(url: str, payload: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
    """Request with a concurrent RAM/VRAM/temperature watchdog.

    The shared llama-server is never killed automatically. If a guard trips,
    the current request is allowed to unwind, then the whole suite aborts so a
    second generation is never started on top of it.
    """
    stop = threading.Event()
    violations: "queue.SimpleQueue[BaseException]" = queue.SimpleQueue()

    def _watch() -> None:
        while not stop.wait(1.0):
            try:
                guard()
            except BaseException as exc:
                violations.put(exc)
                return

    watcher = threading.Thread(target=_watch, name="ling-benchmark-guard", daemon=True)
    watcher.start()
    try:
        result = _post_json_once(url, payload, int(timeout or _REQUEST_TIMEOUT))
    finally:
        stop.set()
        watcher.join(timeout=2.0)
    if not violations.empty():
        raise violations.get()
    return result


def _swap_base(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    path = parsed.path
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if path.rstrip("/").endswith(suffix):
            path = path.rstrip("/")[:-len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))


def _get_json(url: str, timeout: int = 8) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise GuardAbort(f"preflight failed for {url}: {type(exc).__name__}: {exc}") from exc


def preflight(endpoint: str, model: str, *, allow_swap: bool, allow_holo: bool) -> dict[str, Any]:
    base = _swap_base(endpoint)
    running_payload = _get_json(f"{base}/running")
    running = list((running_payload or {}).get("running") or [])
    active = [str(item.get("model") or "") for item in running]
    states = [str(item.get("state") or "") for item in running]
    requested = str(model).lower().rsplit("/", 1)[-1]
    matching = [name for name in active if name.lower() == requested]
    if any(state != "ready" for state in states):
        raise GuardAbort(f"llama-swap is not steady: {running}")
    if not matching and not allow_swap:
        raise GuardAbort(
            f"model {model!r} is not already loaded (running={active}); "
            "use --allow-swap only when intentionally changing the active model"
        )
    if active and not matching and allow_swap is False:
        raise GuardAbort(f"another profile is active: {active}")

    holo = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8095/health", timeout=1.0) as response:
            holo = response.status == 200
    except Exception:
        holo = False
    if holo and not allow_holo:
        raise GuardAbort("Holo is active and would contaminate CPU timings; stop it or use --allow-holo")

    props = None
    if matching:
        try:
            props = _get_json(
                f"{base}/upstream/{quote(str(model), safe='')}/props",
                timeout=8,
            )
        except GuardAbort:
            props = None
    config_path = ROOT.parent / "llama-swap" / "config.yaml"
    config_hash = (
        hashlib.sha256(config_path.read_bytes()).hexdigest()
        if config_path.exists() else ""
    )
    return {
        "guard": guard(), "swap_base": base, "running": running,
        "holo_active": holo, "props": props, "config_sha256": config_hash,
    }


def wait_server_idle(endpoint: str, model: str, timeout: int = 180) -> bool:
    """After a transport timeout, never overlap the next request."""
    url = f"{_swap_base(endpoint)}/upstream/{quote(str(model), safe='')}/slots"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            slots = _get_json(url, timeout=5)
            if isinstance(slots, list) and not any(
                bool(slot.get("is_processing")) for slot in slots if isinstance(slot, dict)
            ):
                return True
        except GuardAbort:
            pass
        time.sleep(1.0)
    return False


class BenchmarkLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            self.handle.close()
            self.handle = None
            raise GuardAbort("another Ling benchmark harness is already running") from exc

    def release(self) -> None:
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def _json_args(raw: Any) -> tuple[dict[str, Any], bool]:
    if isinstance(raw, dict):
        return raw, True
    try:
        value = json.loads(raw or "{}")
        return (value, isinstance(value, dict))
    except (TypeError, ValueError):
        return {}, False


def _extract_calls(message: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    native = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        args, valid = _json_args(fn.get("arguments"))
        native.append({"id": call.get("id"), "name": fn.get("name"), "args": args, "valid_json": valid})
    if native:
        return native, "native"
    reasoning = str(message.get("reasoning_content") or message.get("reasoning") or message.get("thinking") or "")
    for source, text in (("reasoning_wrapper", reasoning), ("content_wrapper", str(message.get("content") or ""))):
        recovered = parse_reasoning_tool_calls(text)
        if recovered:
            parsed = []
            for index, (block, original_arguments) in enumerate(recovered):
                args, valid = _json_args(original_arguments)
                parsed.append({"id": f"parsed_{index}", "name": block.tool_type, "args": args, "valid_json": valid})
            return parsed, source
    return [], "none"


def _arg_score(case: Case, args: dict[str, Any], language: str = "it") -> bool:
    attese = case.args_en if (language == "en" and case.args_en) else case.args
    for key, expected in attese:
        if key not in args:
            return False
        actual = args[key]
        if isinstance(expected, bool):
            if actual is not expected:
                return False
        elif key in {"query", "text", "path"}:
            if str(expected).casefold() not in str(actual).casefold():
                return False
        elif str(actual).casefold() != str(expected).casefold():
            return False
    return True


def _schema_errors(name: str, args: dict[str, Any], offered: list[dict[str, Any]]) -> list[str]:
    schema = next(
        ((item.get("function") or {}) for item in offered
         if (item.get("function") or {}).get("name") == name),
        None,
    )
    if not schema:
        return ["tool_not_offered"]
    params = schema.get("parameters") or {}
    properties = params.get("properties") or {}
    errors = []
    for required in params.get("required") or []:
        if required not in args:
            errors.append(f"missing:{required}")
    if params.get("additionalProperties") is False:
        errors.extend(f"extra:{key}" for key in args if key not in properties)
    expected_types = {
        "string": str, "boolean": bool, "object": dict,
        "array": list, "integer": int, "number": (int, float),
    }
    for key, value in args.items():
        prop = properties.get(key) or {}
        expected_type = expected_types.get(prop.get("type"))
        if expected_type and not isinstance(value, expected_type):
            errors.append(f"type:{key}")
        if prop.get("enum") and value not in prop["enum"]:
            errors.append(f"enum:{key}")
    return errors


def _language_score(text: str, language: str) -> bool | None:
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if len(words) < 3:
        return None
    italian = sum(word in {"il", "la", "che", "di", "è", "e", "non", "una", "per", "con", "puoi"} for word in words)
    english = sum(word in {"the", "that", "of", "is", "and", "not", "a", "for", "with", "you"} for word in words)
    if italian == english == 0:
        return None
    return italian > english if language == "it" else english > italian


def _communication_checks(case_id: str, content: str) -> dict[str, Any]:
    clean = content.strip()
    lowered = clean.lower()
    checks: dict[str, Any] = {}
    if case_id == "comm_constraint":
        checks["only_391"] = clean == "391"
    elif case_id == "comm_correction":
        checks["rejects_false_premise"] = any(term in lowered for term in ("non ha", "does not", "doesn't", "senza tensor"))
    elif case_id == "comm_uncertainty" or case_id == "no_tool_unknown":
        checks["admits_unknown"] = any(term in lowered for term in ("non posso", "non ho", "non vedo", "non conosco", "can't", "cannot", "don't know"))
    elif case_id == "comm_analogy" or case_id == "no_tool_concept":
        sentences = [part for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
        checks["sentence_count"] = len(sentences)
        checks["within_sentence_limit"] = len(sentences) <= (3 if case_id == "comm_analogy" else 2)
    return checks


def make_payload(
    model: str,
    prompt_style: str,
    language: str,
    user_text: str,
    offered: list[dict[str, Any]],
    *,
    seed: int,
    tool_choice: str = "auto",
    thinking: bool | None = None,
    messages: list[dict[str, Any]] | None = None,
    max_tokens: int = 384,
    temperature: float = 0.25,
    session_id: str = "ling-behaviour",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages or [
            {"role": "system", "content": PROMPTS[prompt_style]},
            {"role": "user", "content": user_text},
        ],
        "temperature": temperature,
        "top_p": 0.95,
        "top_k": 20,
        "seed": seed,
        "max_tokens": max_tokens,
        "stream": False,
        "cache_prompt": True,
        "session_id": session_id,
    }
    if offered:
        payload["tools"] = offered
        payload["tool_choice"] = tool_choice
        payload["parallel_tool_calls"] = False
    if thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": thinking}
    if EXTRA_PAYLOAD:
        payload.update(EXTRA_PAYLOAD)
    return payload


def run_case(
    endpoint: str,
    model: str,
    case: Case,
    language: str,
    prompt_style: str,
    offered: list[dict[str, Any]],
    *,
    repeat: int,
    variant: str,
    tool_choice: str = "auto",
    thinking: bool | None = None,
    temperature: float = 0.25,
) -> dict[str, Any]:
    before = guard()
    text = case.it if language == "it" else case.en
    payload = make_payload(
        model, prompt_style, language, text, offered,
        seed=42420 + repeat, tool_choice=tool_choice, thinking=thinking,
        temperature=temperature,
        session_id=(
            "lingbench-" + re.sub(r"[^a-z0-9]+", "-", variant.lower()).strip("-")
            + f"-{case.case_id}-{language}"
        )[:120],
    )
    started = time.perf_counter()
    response = post_json(endpoint, payload)
    elapsed = time.perf_counter() - started
    after = guard()
    message = (response.get("choices") or [{}])[0].get("message") or {}
    calls, channel = _extract_calls(message)
    first = calls[0] if calls else {}
    name_ok = (first.get("name") in case.expected) if case.should_call else not calls
    args_ok = _arg_score(case, first.get("args") or {}, language) if case.should_call and calls else not case.should_call
    exact_count = len(calls) == (1 if case.should_call else 0)
    valid_json = all(bool(call.get("valid_json")) for call in calls)
    schema_errors = [
        error
        for call in calls
        for error in _schema_errors(
            str(call.get("name") or ""), call.get("args") or {}, offered
        )
    ]
    content = str(message.get("content") or "")
    reasoning = str(message.get("reasoning_content") or message.get("reasoning") or message.get("thinking") or "")
    usage = response.get("usage") or {}
    communication_checks = _communication_checks(case.case_id, content)
    communication_ok = all(
        value for value in communication_checks.values() if isinstance(value, bool)
    )
    correct = bool(
        name_ok and args_ok and exact_count and valid_json
        and not schema_errors and communication_ok
    )
    return {
        "suite": variant.split(":", 1)[0],
        "variant": variant,
        "case": case.case_id,
        "language": language,
        "prompt_style": prompt_style,
        "repeat": repeat,
        "tool_choice": tool_choice,
        "thinking": thinking,
        "temperature": temperature,
        "offered_count": len(offered),
        "offered_order": [(s.get("function") or {}).get("name") for s in offered],
        "schema_chars": len(json.dumps(offered, ensure_ascii=False)),
        "system_chars": len(PROMPTS[prompt_style]),
        "channel": channel,
        "calls": calls,
        "correct": correct,
        "name_ok": bool(name_ok),
        "args_ok": bool(args_ok),
        "exact_call_count": bool(exact_count),
        "valid_json": valid_json,
        "schema_errors": schema_errors,
        "content": content,
        "content_chars": len(content),
        "reasoning": reasoning,
        "reasoning_chars": len(reasoning),
        "italian_or_expected_language": _language_score(content, language),
        "communication_checks": communication_checks,
        "marker_leaks": sorted({
            marker for marker in ("<think>", "<tool_call>", "<arg_key>", "<role>")
            if marker in content
        }),
        "finish_reason": (response.get("choices") or [{}])[0].get("finish_reason"),
        "usage": usage,
        "timings": response.get("timings") or {},
        "elapsed_s": round(elapsed, 4),
        "guard_before": before,
        "guard_after": after,
    }


def _case(case_id: str) -> Case:
    return next(case for case in CASES + COMMUNICATION_CASES if case.case_id == case_id)


def matrix_baseline(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = CASES
    offered = schemas(MIXED_NAMES)
    for prompt_style in PROMPTS:
        for language in ("it", "en"):
            for case in selected:
                for repeat in range(repeats):
                    jobs.append({"case": case, "language": language, "prompt_style": prompt_style,
                                 "offered": offered, "repeat": repeat, "variant": f"baseline:{prompt_style}:{language}"})
    return jobs


def matrix_pressure(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = tuple(_case(name) for name in ("browser_open", "browser_find", "browser_click", "browser_type"))
    for count in (1, 7, 16, 24):
        for case in selected:
            target = case.expected[0]
            decoys = [name for name in PRESSURE_NAMES if name != target]
            positions = ("head",) if count == 1 else ("head", "middle", "tail")
            for position in positions:
                names = decoys[:max(count - 1, 0)]
                index = {"head": 0, "middle": len(names) // 2, "tail": len(names)}[position]
                names.insert(index, target)
                offered = schemas(tuple(names[:count]))
                for repeat in range(repeats):
                    jobs.append({"case": case, "language": "it", "prompt_style": "production_fragment",
                                 "offered": offered, "repeat": repeat,
                                 "variant": f"pressure:{count}:{position}"})
    return jobs


def matrix_thinking(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = tuple(_case(name) for name in ("browser_open", "browser_find", "web_search", "calendar_list", "no_tool_concept"))
    for thinking in (None, False, True):
        for case in selected:
            for repeat in range(repeats):
                jobs.append({"case": case, "language": "it", "prompt_style": "production_fragment",
                             "offered": schemas(MIXED_NAMES), "repeat": repeat,
                             "thinking": thinking,
                             "variant": f"thinking:{'default' if thinking is None else str(thinking).lower()}"})
    return jobs


def matrix_schema(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = tuple(_case(name) for name in ("browser_open", "browser_find", "web_search", "email_unread", "calendar_list"))
    modes = (
        ("exact_en", {"short": False, "language": "en"}),
        ("short_en", {"short": True, "language": "en"}),
        ("short_it", {"short": True, "language": "it"}),
    )
    for label, schema_kwargs in modes:
        for case in selected:
            for repeat in range(repeats):
                jobs.append({"case": case, "language": "it", "prompt_style": "production_fragment",
                             "offered": schemas(MIXED_NAMES, **schema_kwargs), "repeat": repeat,
                             "variant": f"schema:{label}"})
    return jobs


def matrix_order(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = tuple(_case(name) for name in ("browser_open", "browser_find", "web_search", "email_unread"))
    base = schemas(MIXED_NAMES)
    orders = {
        "canonical": base,
        "reverse": list(reversed(base)),
        "seeded_shuffle": random.Random(731).sample(base, len(base)),
    }
    for order_name, offered in orders.items():
        for case in selected:
            for repeat in range(repeats):
                jobs.append({"case": case, "language": "it", "prompt_style": "production_fragment",
                             "offered": offered, "repeat": repeat, "variant": f"order:{order_name}"})
    return jobs


def matrix_communication(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    for prompt_style in PROMPTS:
        for language in ("it", "en"):
            for case in COMMUNICATION_CASES:
                for repeat in range(repeats):
                    jobs.append({"case": case, "language": language, "prompt_style": prompt_style,
                                 "offered": [], "repeat": repeat, "temperature": 0.8,
                                 "variant": f"communication:{prompt_style}:{language}"})
    return jobs


def matrix_choice(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = tuple(_case(name) for name in (
        "browser_open", "browser_find", "browser_type", "web_search", "calendar_list"
    ))
    for tool_choice in ("auto", "required"):
        for case in selected:
            for repeat in range(repeats):
                jobs.append({
                    "case": case, "language": "it",
                    "prompt_style": "production_fragment",
                    "offered": schemas(MIXED_NAMES), "repeat": repeat,
                    "tool_choice": tool_choice,
                    "variant": f"choice:{tool_choice}",
                })
    return jobs


def matrix_temperature(repeats: int) -> list[dict[str, Any]]:
    jobs = []
    selected = tuple(_case(name) for name in (
        "browser_open", "browser_type", "web_search", "no_tool_concept"
    ))
    for temperature, label in ((0.25, "production_tool"), (1.0, "ling_official")):
        for case in selected:
            for repeat in range(repeats):
                jobs.append({
                    "case": case, "language": "it",
                    "prompt_style": "production_fragment",
                    "offered": schemas(MIXED_NAMES), "repeat": repeat,
                    "temperature": temperature,
                    "variant": f"temperature:{label}",
                })
    return jobs


def run_history(
    endpoint: str,
    model: str,
    repeats: int,
    max_calls: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    results = []
    calls_used = 0
    offered = schemas(BROWSER_NAMES)
    for repeat in range(repeats):
        if max_calls and calls_used >= max_calls:
            break
        guard_before = guard()
        base_messages = [
            {"role": "system", "content": PROMPTS["production_fragment"]},
            {"role": "user", "content": "Trova il link Privacy nella pagina e cliccalo."},
        ]
        first_payload = make_payload(
            model, "production_fragment", "it", "", offered,
            seed=53000 + repeat, messages=base_messages, temperature=0.25,
            session_id=f"lingbench-history-first-{repeat}",
        )
        started = time.perf_counter()
        first_response = post_json(endpoint, first_payload)
        calls_used += 1
        first_message = (first_response.get("choices") or [{}])[0].get("message") or {}
        calls, first_channel = _extract_calls(first_message)
        first = calls[0] if calls else {}
        first_correct = (
            len(calls) == 1
            and first.get("name") in {"browser_find", "browser_read"}
            and bool(first.get("valid_json"))
        )
        if not first_correct:
            for preserve in (False, True):
                results.append({
                    "suite": "history", "variant": f"history:preserve={preserve}",
                    "repeat": repeat, "first_channel": first_channel,
                    "first_calls": calls, "first_correct": False,
                    "second_correct": False, "error": "first turn emitted no call",
                    "elapsed_s": round(time.perf_counter() - started, 4), "guard_before": guard_before,
                })
            continue

        reasoning = str(first_message.get("reasoning_content") or "")
        cleaned_reasoning = strip_tool_blocks(reasoning, skip_fenced=True).strip()
        for preserve in (False, True):
            if max_calls and calls_used >= max_calls:
                break
            assistant = {
                "role": "assistant",
                "content": first_message.get("content") or None,
                "tool_calls": [{
                    "id": first.get("id") or f"history_{repeat}",
                    "type": "function",
                    "function": {"name": first["name"], "arguments": json.dumps(first["args"], ensure_ascii=False)},
                }],
            }
            if preserve and cleaned_reasoning:
                assistant["reasoning_content"] = cleaned_reasoning
            messages = list(base_messages)
            messages.extend([
                assistant,
                {"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"],
                 "content": "- link 'Privacy' [ref=e12]\n- link 'Terms' [ref=e13]"},
            ])
            second_payload = make_payload(
                model, "production_fragment", "it", "", offered,
                seed=63000 + repeat, messages=messages, temperature=0.25,
                session_id=f"lingbench-history-{repeat}-preserve-{int(preserve)}",
            )
            second_response = post_json(endpoint, second_payload)
            calls_used += 1
            second_message = (second_response.get("choices") or [{}])[0].get("message") or {}
            second_calls, second_channel = _extract_calls(second_message)
            second = second_calls[0] if second_calls else {}
            second_ok = second.get("name") == "browser_click" and "e12" in json.dumps(second.get("args") or {}).lower()
            results.append({
                "suite": "history", "variant": f"history:preserve={preserve}", "repeat": repeat,
                "first_channel": first_channel, "first_call": first,
                "first_correct": first.get("name") in {"browser_find", "browser_read"},
                "preserved_reasoning_chars": len(cleaned_reasoning) if preserve else 0,
                "second_channel": second_channel, "second_calls": second_calls,
                "second_correct": second_ok,
                "second_content": str(second_message.get("content") or ""),
                "second_reasoning_chars": len(str(second_message.get("reasoning_content") or "")),
                "elapsed_s": round(time.perf_counter() - started, 4), "guard_before": guard_before,
                "guard_after": guard(),
            })
    return results, calls_used


def summarise(rows: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("variant") or row.get("suite")), []).append(row)
    lines = ["# Ling behavioural benchmark", "", f"Generated: {datetime.now().isoformat(timespec='seconds')}", ""]
    lines.append("| Variant | Pass | Calls | Native | Reasoning XML | Median s | Median reasoning chars |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for variant in sorted(grouped):
        items = grouped[variant]
        correct = sum(bool(item.get("correct", item.get("second_correct", False))) for item in items)
        native = sum(item.get("channel", item.get("second_channel")) == "native" for item in items)
        reasoning_xml = sum(
            item.get("channel", item.get("second_channel")) == "reasoning_wrapper"
            for item in items
        )
        elapsed = [float(item.get("elapsed_s") or 0) for item in items]
        reasoning_chars = [int(item.get("reasoning_chars") or item.get("second_reasoning_chars") or 0) for item in items]
        lines.append(
            f"| {variant} | {correct}/{len(items)} | {len(items)} | {native} | {reasoning_xml} | "
            f"{statistics.median(elapsed):.2f} | {statistics.median(reasoning_chars):.0f} |"
        )
    channels: dict[str, int] = {}
    for row in rows:
        channel = str(row.get("channel", row.get("second_channel", "none")))
        channels[channel] = channels.get(channel, 0) + 1
    lines.extend(["", "Channels: " + ", ".join(f"{key}={value}" for key, value in sorted(channels.items())), ""])
    return "\n".join(lines)


def main() -> int:
    global _ALLOW_UNKNOWN_GUARDS, _REQUEST_TIMEOUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=(
        "baseline", "pressure", "thinking", "schema", "order",
        "communication", "choice", "temperature", "history", "all",
    ), default="baseline")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-calls", type=int, default=0, help="Debug cap; zero means all jobs")
    parser.add_argument("--request-timeout", type=int, default=180)
    parser.add_argument("--allow-unknown-guards", action="store_true")
    parser.add_argument("--allow-swap", action="store_true")
    parser.add_argument("--allow-holo", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extra-payload", default="", help="JSON fuso in ogni payload (onda 4: reasoning_budget_tokens)")
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 10:
        parser.error("--repeats must be between 1 and 10")

    if args.request_timeout < 30 or args.request_timeout > 900:
        parser.error("--request-timeout must be between 30 and 900 seconds")
    _ALLOW_UNKNOWN_GUARDS = bool(args.allow_unknown_guards)
    _REQUEST_TIMEOUT = args.request_timeout
    if args.extra_payload:
        EXTRA_PAYLOAD.update(json.loads(args.extra_payload))

    selected = (
        "baseline", "pressure", "thinking", "schema", "order",
        "communication", "choice", "temperature", "history",
    ) if args.suite == "all" else (args.suite,)
    output = args.output or (ROOT.parent / "ricerche" / f"ling-behavior-{args.suite}-{datetime.now():%Y%m%d-%H%M%S}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    factories: dict[str, Callable[[int], list[dict[str, Any]]]] = {
        "baseline": matrix_baseline,
        "pressure": matrix_pressure,
        "thinking": matrix_thinking,
        "schema": matrix_schema,
        "order": matrix_order,
        "communication": matrix_communication,
        "choice": matrix_choice,
        "temperature": matrix_temperature,
    }

    print(f"Ling behaviour | suites={','.join(selected)} | repeats={args.repeats} | output={output}")
    planned = sum(
        (args.repeats * 3 if suite == "history" else len(factories[suite](args.repeats)))
        for suite in selected
    )
    if args.max_calls:
        planned = min(planned, args.max_calls)
    print(f"Planned requests: {planned}")
    if args.dry_run:
        return 0

    lock = BenchmarkLock(output.parent / ".ling-behaviour.lock")
    lock.acquire()
    try:
        manifest = preflight(
            args.endpoint, args.model,
            allow_swap=args.allow_swap,
            allow_holo=args.allow_holo,
        )
    except GuardAbort as exc:
        lock.release()
        print(f"ABORTED SAFELY: {exc}")
        return 2
    print(f"Preflight: {manifest}")
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total_done = 0
    try:
        for suite in selected:
            if suite == "history":
                remaining = max(args.max_calls - total_done, 0) if args.max_calls else 0
                batch, used = run_history(
                    args.endpoint, args.model, args.repeats, max_calls=remaining
                )
                rows.extend(batch)
                total_done += used
            else:
                jobs = factories[suite](args.repeats)
                for job in jobs:
                    if args.max_calls and total_done >= args.max_calls:
                        break
                    try:
                        row = run_case(args.endpoint, args.model, **job)
                    except (GuardAbort, TransportAbort) as exc:
                        row = {
                            "suite": suite, "variant": job["variant"], "case": job["case"].case_id,
                            "repeat": job["repeat"], "error": f"{type(exc).__name__}: {exc}",
                            "correct": False,
                        }
                        rows.append(row)
                        output.write_text(
                            json.dumps(rows, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        if isinstance(exc, TransportAbort):
                            wait_server_idle(args.endpoint, args.model)
                        raise
                    rows.append(row)
                    total_done += 1
                    symbol = "✓" if row.get("correct") else "✗"
                    call_names = [call.get("name") for call in row.get("calls", [])]
                    print(f"{total_done:03d} {symbol} {row.get('variant')} {row.get('case')} {row.get('channel')} {call_names} {row.get('elapsed_s', 0):.2f}s", flush=True)
                    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.max_calls and total_done >= args.max_calls:
                    break
            output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except KeyboardInterrupt:
        print("Interrupted; partial results retained.")
    except (GuardAbort, TransportAbort) as exc:
        print(f"ABORTED SAFELY: {exc}")
        return_code = 2
    else:
        return_code = 0
    finally:
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path = output.with_suffix(".md")
        summary_path.write_text(summarise(rows), encoding="utf-8")
        print(summarise(rows))
        print(f"Raw: {output}\nSummary: {summary_path}\nManifest: {manifest_path}")
        lock.release()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
