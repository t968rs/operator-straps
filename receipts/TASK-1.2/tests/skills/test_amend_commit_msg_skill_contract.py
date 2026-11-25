"""Guard test: the amend-commit-msg skill and ``branch_commit_msg.py`` agree.

The skill amends a drafted commit breakdown in the main session, the only context that holds what changed
since the draft; the script owns capture, regrouping and build. Both are named in prose, so the test parses
the skill's own command lines (placeholders filled) with the script's parser, and pins that the skill never
runs in a context-free fork.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path
from typing import Dict, List

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN_ROOT / "skills" / "amend-commit-msg" / "SKILL.md"
_ORIGINAL = _PLUGIN_ROOT / "skills" / "branch-commit-msg" / "SKILL.md"
_SCRIPT = _PLUGIN_ROOT / "scripts" / "branch_commit_msg.py"
_LAUNCHER = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py"'


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> Dict[str, str]:
    block = re.match(r"^---\n(.*?)\n---\n", _text(path), re.DOTALL)
    assert block, f"{path.name} has no frontmatter"
    pairs = (line.split(":", 1) for line in block.group(1).splitlines() if re.match(r"^[a-z-]+:", line))
    return {key.strip(): value.strip() for key, value in pairs}


def _commands(subcommand: str) -> List[str]:
    """Lines of the skill that run ``subcommand`` through the launcher or its ``SCRIPT`` stand-in."""
    pattern = rf"^(?:SCRIPT|{re.escape(_LAUNCHER)}) {subcommand}\b.*$"
    return re.findall(pattern, _text(_SKILL), re.MULTILINE)


@pytest.fixture(scope="module")
def parser():
    spec = importlib.util.spec_from_file_location("branch_commit_msg_guard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._parser()


def test_skill_runs_in_the_main_session() -> None:
    meta = _frontmatter(_SKILL)
    assert meta["name"] == "amend-commit-msg"
    for key in ("context", "agent"):
        assert key not in meta, f"{key} would amend the breakdown without the session's context"
    assert "model" not in meta, "model would hand the amendment to a different model than the session's"


def test_skill_names_no_agent_to_dispatch() -> None:
    body = _text(_SKILL)
    assert re.search(r"harness:(?!amend-commit-msg|branch-commit-msg)[a-z-]+", body) is None
    assert "subagent" not in body.lower()


def test_skill_hints_the_capture_arguments_and_the_change() -> None:
    hint = _frontmatter(_SKILL)["argument-hint"]
    for part in ("REF", "--base", "--no-fetch"):
        assert part in hint
    assert " -- " in hint, "no separator before the change description"
    assert "--fresh" not in hint and "--pending" not in hint


def test_skill_passes_the_arguments_through() -> None:
    body = _text(_SKILL)
    assert "$ARGUMENTS" in body
    assert "usage:" in body, "no usage line for a missing change description"


def test_skill_runs_every_subcommand_through_the_launcher() -> None:
    body = _text(_SKILL)
    assert _LAUNCHER in body
    for subcommand in ("capture", "diff", "move", "message", "build"):
        assert _commands(subcommand), f"skill never runs {subcommand}"


def test_capture_always_edits_and_never_replans() -> None:
    lines = _commands("capture")
    assert lines and all("--edit" in line and "--save" in line for line in lines)
    assert not any("--fresh" in line or "--pending" in line for line in lines)


_PLACEHOLDERS = {
    "<capture arguments>": "--base HEAD --no-fetch",
    "<skeleton>": "s.json",
    "<key>": "1",
    "<entry>": "a",
    "<N|new>": "new",
}


def _argv(line: str) -> List[str]:
    """Argv of a skill command line: launcher dropped, optional repeats stripped, placeholders filled."""
    text = re.sub(rf"^(?:SCRIPT|{re.escape(_LAUNCHER)}) ", "", line)
    text = re.sub(r"\s*<<'?\w+'?\s*$", "", text)
    text = re.sub(r"\s*\[[^\]]*\]", "", text)
    for placeholder, value in _PLACEHOLDERS.items():
        text = text.replace(placeholder, value)
    assert "<" not in text, f"unfilled placeholder in {line!r}"
    return shlex.split(text)


@pytest.mark.parametrize("subcommand", ["capture", "diff", "move", "message", "build"])
def test_skill_command_lines_parse(parser, subcommand) -> None:
    lines = _commands(subcommand)
    assert lines, f"skill never runs {subcommand}"
    for line in lines:
        try:
            args = parser.parse_args(_argv(line))
        except SystemExit:
            pytest.fail(f"the script's parser rejects the skill's command: {line}")
        assert args.command == subcommand


def test_hand_picked_argv_parse(parser) -> None:
    args = parser.parse_args(["capture", "--save", "--edit", "--base", "HEAD", "--no-fetch"])
    assert args.edit is True and args.save is True
    assert parser.parse_args(["diff", "s.json", "--block", "1", "--block", "2"]).block == [1, 2]
    assert parser.parse_args(["diff", "s.json", "--all"]).all is True
    moved = parser.parse_args(["move", "s.json", "--path", "a", "--path", "b", "--to", "new"])
    assert (moved.path, moved.to) == (["a", "b"], "new")
    assert parser.parse_args(["move", "s.json", "--path", "a", "--to", "2"]).to == 2
    assert parser.parse_args(["build", "s.json"]).skeleton == Path("s.json")
    message = parser.parse_args(["message", "s.json", "--block", "2"])
    assert (message.skeleton, message.block) == (Path("s.json"), 2)
    assert parser.parse_args(["message", "s.json", "--all"]).all is True


def test_skill_regroups_only_through_move() -> None:
    body = _text(_SKILL).lower()
    assert "bullet" in body, "no rule that a path's description moves with it"
    assert "never edit the path lists" in body, "no rule against hand-editing the grouping"


def test_skill_writes_messages_through_the_script_and_stays_quiet() -> None:
    body = _text(_SKILL)
    assert "never use Edit or Write on the skeleton" in body, "no rule against Edit output on the skeleton"
    assert "Quiet run" in body and "receipt is the only text" in body
    step = body[body.index("## Step 4"):body.index("## Step 5")]
    assert _commands("message")[0] in step, "the message command belongs to Step 4"


def test_a_build_problem_is_fixed_through_the_message_command() -> None:
    body = _text(_SKILL)
    step = " ".join(body[body.index("## Step 5"):body.index("## Common Mistakes")].split())
    assert "fix the json" not in step.lower(), "Step 5 sends a build problem back to Edit"
    assert "`message`" in step, "Step 5 never names the message command as the fix route"


def test_skill_reads_the_diff_and_states_facts() -> None:
    body = _text(_SKILL).lower()
    assert "concrete facts" in body, "no rule that conversation references become facts"
    assert "commit_format.md" in body, "format reference not required"


def test_skill_reports_a_missing_draft_and_points_to_the_drafter() -> None:
    body = _text(_SKILL)
    assert "no TXT to amend" in body
    assert "harness:branch-commit-msg" in body, "no pointer to the skill that makes the first draft"


def test_original_skill_points_to_the_amend_skill() -> None:
    assert "harness:amend-commit-msg" in _text(_ORIGINAL)
