# core/models.py
"""
Pure data models — no database logic, no side effects.

These are simple datacontainers. All persistence is handled by SessionManager.
"""

import copy
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, TYPE_CHECKING

from src.tool_approval_scopes import (
    CHAT_SESSION_APPROVAL_CONTEXT_MARKER,
    CHAT_SESSION_APPROVAL_DECISION,
    CHAT_SESSION_APPROVAL_SIGNATURE_FIELD,
    verify_chat_session_grant,
)

if TYPE_CHECKING:
    from .session_manager import SessionManager

# Module-level session manager singleton (single source of truth)
_SESSION_MANAGER_INSTANCE: Optional["SessionManager"] = None


def set_session_manager_instance(manager: "SessionManager"):
    """Set the global SessionManager singleton."""
    global _SESSION_MANAGER_INSTANCE
    _SESSION_MANAGER_INSTANCE = manager


def get_session_manager_instance() -> Optional["SessionManager"]:
    """Get the global SessionManager singleton."""
    return _SESSION_MANAGER_INSTANCE


# Keep legacy name for backward compatibility
set_session_manager = set_session_manager_instance
get_session_manager = get_session_manager_instance


def _history_grants_chat_session_approval(
    history: List["ChatMessage"],
    session_id: str,
) -> bool:
    """Return whether this exact chat has a resolved session-scope grant."""

    expected_session = str(session_id or "")
    if not expected_session:
        return False
    for message in reversed(history or []):
        metadata = getattr(message, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        tool_events = metadata.get("tool_events")
        if not isinstance(tool_events, list):
            continue
        for event in reversed(tool_events):
            ask_user = event.get("ask_user") if isinstance(event, dict) else None
            if not isinstance(ask_user, dict):
                continue
            if (
                ask_user.get("kind") == "tool_approval"
                and ask_user.get("resolved") == CHAT_SESSION_APPROVAL_DECISION
                and str(ask_user.get("session_id") or "") == expected_session
                # Shape proves nothing here: routes that accept a
                # caller-supplied metadata blob write into this same history.
                and verify_chat_session_grant(
                    ask_user.get(CHAT_SESSION_APPROVAL_SIGNATURE_FIELD),
                    expected_session,
                    ask_user.get("approval_id"),
                    CHAT_SESSION_APPROVAL_DECISION,
                )
            ):
                return True
    return False


@dataclass
class ChatMessage:
    """A single chat message."""
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API responses."""
        result = {"role": self.role, "content": self.content}
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def get(self, key: str, default=None):
        """Dict-like access for compatibility."""
        return getattr(self, key, default)


@dataclass
class Session:
    """A chat session — pure data container.

    ``.history`` is the authoritative mutable message list. Callers may
    read, append, pop, or reassign it directly — these changes take
    effect immediately. ``_history`` remains a compatibility alias that
    always resolves to the authoritative ``history`` list.

    Each session gets its own unique history list at construction time
    (the dataclass default is never shared between instances).
    """

    id: str
    name: str
    endpoint_url: str
    model: str
    rag: bool = False
    archived: bool = False
    headers: Optional[Dict[str, str]] = None
    history: List[ChatMessage] = None
    owner: Optional[str] = None
    is_important: bool = False
    message_count: int = 0

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}
        # Ensure each session gets its OWN list (not the shared dataclass default)
        if self.history is None:
            self.history = []

    @property
    def _history(self) -> List[ChatMessage]:
        """Compatibility alias for callers that still reference ``_history``."""
        return self.history

    @_history.setter
    def _history(self, messages: List[ChatMessage]):
        self.history = messages

    def add_message(self, message: ChatMessage):
        """
        Add a message to this session.

        Appends to the authoritative history list and increments
        message_count. Delegates to SessionManager for persistence
        if available.
        """
        self.history.append(message)
        self.message_count = len(self.history)

        # Delegate to session manager for persistence
        if _SESSION_MANAGER_INSTANCE:
            _SESSION_MANAGER_INSTANCE._persist_message(self.id, message)

    def get_context_messages(self) -> List[Dict[str, Any]]:
        """Get messages in format for LLM API.

        Slash-command / setup replies are persisted to history so they render
        in the transcript, but they are UI chatter (e.g. ``/setup ...`` and its
        status lines) the user never meant as conversation. They carry
        ``metadata.source == "slash"``; exclude them here so they never reach
        the model. Display/history-load paths use the raw ``history`` and are
        unaffected.
        """
        messages = [
            msg.to_dict()
            for msg in self.history
            if (msg.metadata or {}).get("source") != "slash"
        ]
        if not _history_grants_chat_session_approval(self.history, self.id):
            return messages

        # Keep the grant close to the latest user request so route-neutral
        # compaction/trimming preserves it. Copy the metadata instead of
        # mutating the durable transcript object.
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") != "user":
                continue
            message = dict(messages[index])
            metadata = dict(message.get("metadata") or {})
            metadata[CHAT_SESSION_APPROVAL_CONTEXT_MARKER] = True
            message["metadata"] = metadata
            messages[index] = message
            break
        return messages

    def get_llm_messages(
        self,
        tool_output_chars: int = 1500,
        tool_output_chars_old: int = 300,
        recenti: int = 2,
    ) -> List[Dict[str, Any]]:
        """History for the chat completion, *including* the tool calls the
        assistant actually made in earlier turns.

        ``get_context_messages`` returns prose only — ``ChatMessage`` has no
        ``tool_calls`` field, so a turn where the model called a tool replays
        as if it had answered out of its own knowledge. Over a few turns that
        is few-shot priming to *not* call tools. Measured on the previous model,
        same conversation and same final question, 8 repetitions each:
        prose history 0/8 calls and 5 fabricated answers; this one 6/8 calls
        and 1 fabrication.

        Every production harness keeps this in history (Claude Code, Codex,
        OpenHands, Qwen-Agent — see ricerche/harness-agentici-ciclo-multistep.md).
        The data is already persisted in ``metadata["tool_events"]`` (tool
        name, arguments, output), so this rebuilds the spec-correct
        assistant ``tool_calls`` + ``role:"tool"`` pair from it — no schema
        change, and the other ``get_context_messages`` callers (memory and
        skill extraction, compaction, bg_monitor, session_tools) are untouched.

        Older tool outputs are truncated harder than recent ones: what the
        model imitates is the *shape* of the exchange, not the payload.
        ``_sanitize_llm_messages`` repairs any adjacency the context trim breaks.
        """
        visible = [
            msg for msg in self.history
            if (msg.metadata or {}).get("source") != "slash"
        ]
        used_tools = [
            i for i, msg in enumerate(visible)
            if msg.role == "assistant" and (msg.metadata or {}).get("tool_events")
        ]
        fresh = set(used_tools[-recenti:]) if recenti > 0 else set()

        # Onda 4 / E08c "replay fedele" (27 ago 2026): con ODYSSEUS_HISTORY_REPLAY=1
        # ogni turno viene ripetuto BYTE-IDENTICO a come fu inviato: il messaggio di
        # contesto data/ora che precedeva l'utente (metadata["datetime_ctx"]) e la coda
        # dei messaggi del turno (metadata["llm_tail"]: assistant+tool_calls, tool,
        # nudge, risposta) salvata da agent_loop. Misurato senza: cache_n fisso a 8429
        # (solo system+tools) e riprocesso di 7-14k token a ogni turno, perche' il
        # contesto data/ora "si sposta" davanti all'ultimo messaggio utente e la storia
        # ricostruita non coincide con quella in cache.
        replay = os.getenv("ODYSSEUS_HISTORY_REPLAY", "0") == "1"
        out: List[Dict[str, Any]] = []
        for i, msg in enumerate(visible):
            meta = msg.metadata or {}
            if replay and msg.role == "user":
                nxt = visible[i + 1] if i + 1 < len(visible) else None
                nmeta = (nxt.metadata or {}) if (nxt is not None and nxt.role == "assistant") else {}
                pre = nmeta.get("llm_pre")
                if isinstance(pre, list) and pre:
                    out.extend(copy.deepcopy(m) for m in pre if isinstance(m, dict) and m.get("role"))
                elif isinstance(nmeta.get("datetime_ctx"), str) and nmeta.get("datetime_ctx"):
                    out.append({"role": "user", "content": nmeta["datetime_ctx"]})
                um = msg.to_dict()
                if isinstance(nmeta.get("llm_user_sent"), str) and nmeta.get("llm_user_sent"):
                    um["content"] = nmeta["llm_user_sent"]   # testo come fu inviato (note in coda incluse)
                out.append(um)
                continue
            if replay and msg.role == "assistant" and isinstance(meta.get("llm_tail"), list) and meta.get("llm_tail"):
                tail = copy.deepcopy(meta["llm_tail"])
                out.extend(m for m in tail if isinstance(m, dict) and m.get("role"))
                last = tail[-1] if isinstance(tail[-1], dict) else {}
                gia = (last.get("role") == "assistant" and not last.get("tool_calls")
                       and str(last.get("content") or "").strip())
                if not gia:
                    out.append({"role": "assistant", "content": msg.content})
                continue
            events = meta.get("tool_events") or []
            if msg.role == "assistant" and isinstance(events, list):
                limit = tool_output_chars if i in fresh else tool_output_chars_old
                for j, ev in enumerate(events):
                    if not isinstance(ev, dict):
                        continue
                    name = ev.get("tool")
                    if not name:
                        continue
                    args = ev.get("command")
                    if not isinstance(args, str):
                        try:
                            args = json.dumps(args or {}, ensure_ascii=False)
                        except Exception:
                            args = "{}"
                    call_id = f"call_{i}_{j}"
                    out.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": call_id,
                            "type": "function",
                            "function": {"name": str(name), "arguments": args},
                        }],
                    })
                    output = ev.get("output")
                    if not isinstance(output, str):
                        try:
                            output = json.dumps(output, ensure_ascii=False)
                        except Exception:
                            output = str(output)
                    if len(output) > limit:
                        output = output[:limit] + "\n…[output troncato]"
                    out.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": output,
                    })
            out.append(msg.to_dict())
        return out

    def get(self, key: str, default=None):
        """Dict-like access for compatibility."""
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        """Allow session['field'] syntax."""
        return getattr(self, key)
