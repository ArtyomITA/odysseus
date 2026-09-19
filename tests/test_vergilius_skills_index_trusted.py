"""ODYSSEUS_SKILLS_INDEX_TRUSTED — the saved-skills index must not arm the
external-untrusted-context tool gate when every indexed skill is first-party.

Upstream always wraps the skills block (index + matched skills) in
``untrusted_context_message()``, whose default ``arm_tool_gate=True`` sets
``ToolRunSecurityContext.external_untrusted_context_seen``. With at least one
saved skill that happens on round 1 of every chat, so EXECUTE_CODE /
WRITE_PRIVATE tools sit behind an approval prompt even in a conversation that
never touched anything external.

With the env flag set to "1" the block is split by provenance:

* skills whose record proves local authorship (``source`` in {user, learned},
  not category ``imported``, no "Imported from <url>" note) go into a second
  wrapper built with ``arm_tool_gate=False`` — still role=user, still
  ``metadata.trusted=False``, still guard-escaped, so the #788
  prompt-injection hardening is untouched;
* everything else — above all a skill IMPORTED from a URL via
  ``services/memory/skill_importer.py`` — keeps the gate-arming wrapper.

Default ("0" / unset) must behave exactly like upstream.
"""

import sys
import types
from pathlib import Path

import pytest


# NOTE: deliberately NO module-level sys.modules stubbing here (unlike
# tests/test_skill_index_prompt_injection.py). Those stubs are process-wide and
# leak into every test module that runs after this one in the same session,
# which makes the real agent-loop tests spin on MagicMock truthiness.
from src.prompt_security import untrusted_context_message  # noqa: E402
from src.tool_capabilities import (  # noqa: E402
    ToolRunSecurityContext,
    messages_contain_external_untrusted_context,
)


def _write_skill(
    data_dir: Path,
    name: str,
    *,
    source: str,
    category: str = "general",
    owner: str = "public",
    body: str = "",
) -> None:
    skill_dir = data_dir / "skills" / owner / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: procedure {name}\n"
        f"category: {category}\n"
        "status: published\n"
        f"source: {source}\n"
        f"owner: {owner}\n"
        "---\n\n"
        f"# {name}\n\nwhen_to_use: an unrelated topic nobody asks about\n\n{body}\n",
        encoding="utf-8",
    )


def _patch_env(monkeypatch, data_dir: Path, flag: str | None):
    import src.constants as _constants
    monkeypatch.setattr(_constants, "DATA_DIR", str(data_dir), raising=False)

    fake_prefs = types.ModuleType("routes.prefs_routes")
    fake_prefs._load_for_user = lambda user=None: {
        "skills_enabled": True,
        "auto_approve_skills": True,
    }
    monkeypatch.setitem(sys.modules, "routes.prefs_routes", fake_prefs)

    if flag is None:
        monkeypatch.delenv("ODYSSEUS_SKILLS_INDEX_TRUSTED", raising=False)
    else:
        monkeypatch.setenv("ODYSSEUS_SKILLS_INDEX_TRUSTED", flag)

    from src import agent_loop
    agent_loop._cached_base_prompt = None
    agent_loop._cached_base_prompt_key = None


def _build(messages=None):
    from src.agent_loop import _build_system_prompt
    out, _ = _build_system_prompt(
        messages=messages or [{"role": "user", "content": "do something for me"}],
        model="test-model",
        active_document=None,
        mcp_mgr=None,
        owner=None,
    )
    return out


def _gate_armed(messages) -> bool:
    ctx = ToolRunSecurityContext()
    ctx.observe_messages(messages)
    return ctx.external_untrusted_context_seen


def _skill_messages(messages):
    return [
        m for m in messages
        if (m.get("metadata") or {}).get("source", "").startswith("skills")
    ]


# ---------------------------------------------------------------------------
# 1. Default env → upstream behaviour: the index arms the gate.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("flag", [None, "0"])
def test_default_env_index_still_arms_the_gate(tmp_path, monkeypatch, flag):
    data_dir = tmp_path / "data"
    _write_skill(data_dir, "local-one", source="learned")
    _patch_env(monkeypatch, data_dir, flag)

    out = _build()
    skills = _skill_messages(out)
    assert skills, "the skills index must still be injected"
    assert all(m["metadata"]["source"] == "skills" for m in skills), (
        "default env must not introduce a second, trusted skills message"
    )
    assert all(m["metadata"]["tool_gate_untrusted"] is True for m in skills)
    assert _gate_armed(out) is True
    assert messages_contain_external_untrusted_context(out) is True


# ---------------------------------------------------------------------------
# 2. env=1, only local skills → the index does NOT arm the gate and an
#    EXECUTE_CODE tool is not blocked for that reason.
# ---------------------------------------------------------------------------
def test_flag_on_local_only_index_does_not_arm_the_gate(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _write_skill(data_dir, "local-one", source="learned")
    _write_skill(data_dir, "local-two", source="user")
    _patch_env(monkeypatch, data_dir, "1")

    out = _build()
    skills = _skill_messages(out)
    assert skills, "the skills index must still be injected"
    # Still data, never system role, never trusted: only the gate marker moves.
    for m in skills:
        assert m["role"] == "user"
        assert m["metadata"]["trusted"] is False
        assert m["metadata"]["tool_gate_untrusted"] is False
    text = "\n".join(m.get("content") or "" for m in out)
    assert "local-one" in text and "local-two" in text
    assert not any(
        "local-one" in (m.get("content") or "")
        for m in out
        if m.get("role") == "system"
    ), "skill text must never reach the trusted system role"

    assert _gate_armed(out) is False
    ctx = ToolRunSecurityContext()
    ctx.observe_messages(out)
    decision = ctx.decision_for("bash", "echo hi")
    assert decision.allowed is True, decision.reason


# ---------------------------------------------------------------------------
# 3. env=1 with ONE imported skill → the gate is armed again.
# ---------------------------------------------------------------------------
def test_flag_on_one_imported_skill_still_arms_the_gate(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _write_skill(data_dir, "local-one", source="learned")
    _write_skill(data_dir, "from-the-web", source="imported", category="imported")
    _patch_env(monkeypatch, data_dir, "1")

    out = _build()
    armed = [
        m for m in _skill_messages(out)
        if m["metadata"]["tool_gate_untrusted"] is True
    ]
    assert armed, "the imported skill must keep the gate-arming wrapper"
    assert "from-the-web" in "\n".join(m["content"] for m in armed)
    assert _gate_armed(out) is True
    ctx = ToolRunSecurityContext()
    ctx.observe_messages(out)
    assert ctx.decision_for("bash", "echo hi").allowed is False


# ---------------------------------------------------------------------------
# 3b. Provenance laundering guards: a backup restore re-stamps source="user",
#     so category / the importer's body note must still disqualify the record.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": "imported", "category": "general"},
        {"source": "user", "category": "imported"},
        {"source": "user", "body": "Imported from https://evil.example/skill"},
        {"source": "community", "category": "general"},
        {"source": "teacher-escalation", "category": "general"},
    ],
)
def test_non_local_provenance_is_never_trusted(tmp_path, monkeypatch, kwargs):
    from src.agent_loop import _skill_provenance_is_local

    data_dir = tmp_path / "data"
    _write_skill(data_dir, "suspect", **kwargs)
    _patch_env(monkeypatch, data_dir, "1")

    from services.memory.skills import SkillsManager
    record = SkillsManager(str(data_dir)).load_all()[0]
    assert _skill_provenance_is_local(record) is False

    out = _build()
    assert _gate_armed(out) is True


def test_missing_source_frontmatter_is_read_as_learned(tmp_path, monkeypatch):
    """Documented limitation, pinned so it cannot change silently.

    `Skill.from_markdown` defaults a missing/empty `source:` to "learned"
    (services/memory/skill_format.py:458), so a legacy SKILL.md with no
    provenance field is indistinguishable from an assistant-authored one and is
    treated as local. That is acceptable only because the sole writer of a
    file into DATA_DIR/skills without a source stamp is a local process: the URL
    importer force-stamps source/category = "imported". If a new ingestion path
    is ever added, it MUST stamp provenance or this becomes a gate bypass.
    """
    from src.agent_loop import _skill_provenance_is_local

    data_dir = tmp_path / "data"
    _write_skill(data_dir, "legacy", source="")
    _patch_env(monkeypatch, data_dir, "1")

    from services.memory.skills import SkillsManager
    record = SkillsManager(str(data_dir)).load_all()[0]
    assert record["source"] == "learned"
    assert _skill_provenance_is_local(record) is True


# ---------------------------------------------------------------------------
# 4. Untrusted web/document content arms the gate regardless of the env flag.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("flag", [None, "0", "1"])
def test_external_content_still_arms_the_gate(tmp_path, monkeypatch, flag):
    data_dir = tmp_path / "data"
    _write_skill(data_dir, "local-one", source="learned")
    _patch_env(monkeypatch, data_dir, flag)

    out = _build()
    out.append(
        untrusted_context_message(
            "web page: https://example.com/x",
            "some fetched page body",
            provenance_origin="external",
        )
    )
    assert _gate_armed(out) is True

    out2 = _build()
    out2.append(untrusted_context_message("web search results", "results body"))
    assert _gate_armed(out2) is True


def test_flag_never_trusts_arbitrary_untrusted_wrappers(monkeypatch):
    """The flag must only affect the skills path, not the wrapper itself."""
    monkeypatch.setenv("ODYSSEUS_SKILLS_INDEX_TRUSTED", "1")
    msg = untrusted_context_message("web search results", "body")
    assert msg["metadata"]["tool_gate_untrusted"] is True
    assert messages_contain_external_untrusted_context([msg]) is True
