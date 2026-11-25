"""Guard test: the todo-edit skill and the todo-editor agent agree on `--delete-retired`, the reply block and
stable ids.

The skill parses the flag and passes it as a prompt line; the agent owns the deletion gate and the report.
Both files are prose, so the test pins the names the two sides must share, and pins that neither side ties
an id to its rank: ids are stable ``todo-xxxx`` codes, and only ``todo_sync.py migrate-ids`` (run by the
developer) turns a catalog of rank-tied ``TODO-NNN`` ids into one.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN_ROOT / "skills" / "todo-edit" / "SKILL.md"
_AGENT = _PLUGIN_ROOT / "agents" / "todo-editor.md"

_REPLY_FIELDS = ("Operation", "Result", "Retired ids", "Prose fixed", "Added", "Stubs", "Resolved", "Close",
                 "Open", "Check")


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _fenced_after(text: str, heading: str) -> List[str]:
    """Lines of the first fenced block that follows ``heading``."""
    tail = text.split(heading, 1)[1]
    match = re.search(r"```\n(.*?)\n```", tail, re.DOTALL)
    assert match, f"no fenced block after {heading!r}"
    return match.group(1).splitlines()


def _section(text: str, heading: str) -> str:
    """The body of ``heading`` up to the next heading of the same level."""
    assert heading in text, f"no {heading!r} section"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_argument_hint_lists_the_flag() -> None:
    hint = re.search(r"^argument-hint:\s*(.+)$", _text(_SKILL), re.MULTILINE)
    assert hint, "SKILL.md has no argument-hint"
    assert "--delete-retired" in hint.group(1)


def test_skill_limits_the_flag_to_retire() -> None:
    body = _text(_SKILL)
    assert re.search(r"--delete-retired[^\n]*--retire|--retire[^\n]*--delete-retired", body)
    assert "print the `argument-hint`" in body, "an unusable flag combination must stop at the hint"


def test_dispatch_prompt_carries_the_flag_line() -> None:
    skill_lines = _fenced_after(_text(_SKILL), "The prompt is this block")
    assert any(line.startswith("Delete retired:") for line in skill_lines)
    assert "Delete retired:" in _text(_AGENT)


def test_agent_reply_block_has_every_field() -> None:
    lines = _fenced_after(_text(_AGENT), "## Reply")
    names = [line.split(":", 1)[0] for line in lines if ":" in line]
    assert names == list(_REPLY_FIELDS)


def test_agent_gates_stub_deletion_on_run_evidence() -> None:
    body = _text(_AGENT)
    section = _section(body, "## delete-retired")
    for needle in ("FULLY_IMPLEMENTED", "stub_path", "null", "kept", "ran", "log --oneline"):
        assert needle in section, f"delete-retired section never mentions {needle!r}"


def test_skill_passes_stable_ids_as_typed() -> None:
    body = _text(_SKILL)
    step = _section(body, "## Step 1")
    assert "todo-k7qf" in step and "k7qf" in step.replace("todo-k7qf", "")
    assert "as typed" in step
    assert "normalize each to `TODO-NNN`" not in body
    description = re.search(r"^description:\s*(.+)$", body, re.MULTILINE)
    assert description and "retire todo-" in description.group(1)
    prompt = _fenced_after(body, "The prompt is this block")
    assert any(line.startswith("Ids: <") and "TODO-NNN" not in line for line in prompt)


def test_no_prose_ties_ids_to_rank() -> None:
    for path in (_SKILL, _AGENT):
        body = _text(path)
        assert not re.search(r"[Rr]enumber", body), path.name
        assert "equal their rank" not in body, path.name
        assert not re.search(r"TODO-\d{3}", body), f"{path.name}: examples use stable todo-xxxx ids"
        assert not re.search(r"TODO-NNN(?! ids)", body), f"{path.name}: TODO-NNN names only the old ids"


def test_agent_never_hand_edits_retired_or_legacy_ids() -> None:
    rules = _section(_text(_AGENT), "## Rules")
    never = next(line for line in rules.splitlines() if "Never hand-edit" in line)
    paragraph = rules[rules.index(never):].split("\n- ", 1)[0]
    for field in ("`id`", "`rank`", "`retired_ids`", "`legacy_ids`", "`split_ids`"):
        assert field in paragraph, field


def test_agent_stops_on_a_migrate_ids_refusal() -> None:
    stops = _section(_text(_AGENT), "## Stop conditions")
    assert "migrate-ids" in stops
    assert re.search(r"never run[s]? `?(TS )?migrate-ids", stops), "the agent must not run the switch-over"
    command = '"${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" migrate-ids --dry-run'
    assert command in stops, "the relayed refusal spells out the full launcher command"


def test_agent_rewords_split_flags_with_real_run_ids() -> None:
    split = _section(_text(_AGENT), "## split")
    assert "names split" in split and "(parts" in split, "the split step works the script's flag lines"
    assert "real run" in split, "part ids come from the real run's report"
    assert "provisional" in split, "the dry run's part ids are named as provisional"
