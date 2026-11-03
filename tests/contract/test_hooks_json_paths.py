"""Contract: every harness hooks.json command is the ``sh hpy`` shell form naming an existing hook script."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

WALK_ROOTS = ("plugins/harness/hooks/",)
HOOKS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks"
HOOKS_JSON = HOOKS_DIR / "hooks.json"
SHELL_FORM = re.compile(
    r'^sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hpy" '
    r'"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/(?P<name>[A-Za-z0-9_]+\.py)"$')

EXPECTED: Dict[Tuple[str, str], List[str]] = {
    ("SessionStart", ""): ["session_rules.py", "todo_sync_session.py"],
    ("PreToolUse", "Bash"): ["bash_pretool.py"],
    ("PreToolUse", "PowerShell"): ["powershell_allow_shapes.py"],
    ("PreToolUse", "Write|Edit"): ["guard_commit_txt.py"],
    ("PostToolUse", "Write|Edit|Bash"): ["validate_pr_json_schema.py"],
    ("Stop", ""): ["check_phase5_sentinel.py", "check_min_viz_sentinel.py"],
    ("SubagentStop", ""): ["check_min_viz_sentinel.py"],
}

# Public hook scripts that stay runnable on their own but are decided inside a registered dispatcher
# (one interpreter launch for all of them), so hooks.json does not name them.
COMPOSED: Dict[str, List[str]] = {
    "bash_pretool.py": ["bash_discipline.py", "approve_python_c.py", "bash_allow_shapes.py"],
}


def _entries() -> List[Tuple[str, str, dict]]:
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return [(event, group.get("matcher", ""), hook)
            for event, groups in data["hooks"].items() for group in groups for hook in group["hooks"]]


def test_every_command_is_the_hpy_shell_form() -> None:
    entries = _entries()
    assert entries
    for event, matcher, hook in entries:
        assert hook["type"] == "command", (event, matcher)
        assert SHELL_FORM.match(hook["command"]), hook["command"]


def test_every_command_names_an_existing_hook_file() -> None:
    for _, _, hook in _entries():
        name = SHELL_FORM.match(hook["command"]).group("name")
        assert (HOOKS_DIR / name).is_file(), name


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_registration(key: Tuple[str, str]) -> None:
    names = [SHELL_FORM.match(h["command"]).group("name") for e, m, h in _entries() if (e, m) == key]
    assert names == EXPECTED[key]


def test_no_unexpected_registrations() -> None:
    assert {(e, m) for e, m, _ in _entries()} == set(EXPECTED)


def test_every_public_hook_script_is_registered_or_composed() -> None:
    """A ``*.py`` under hooks/ without a leading underscore is a hook entry point: wired in hooks.json, or
    decided inside a registered dispatcher that names it in ``COMPOSED``."""
    registered = {SHELL_FORM.match(h["command"]).group("name") for _, _, h in _entries()}
    composed = {name for names in COMPOSED.values() for name in names}
    assert {p.name for p in HOOKS_DIR.glob("*.py") if not p.name.startswith("_")} == registered | composed


@pytest.mark.parametrize("dispatcher", sorted(COMPOSED))
def test_a_dispatcher_runs_exactly_its_composed_hooks(dispatcher: str) -> None:
    """The dispatcher is registered and imports each composed hook, and only those, so a hook added to
    one side without the other fails here."""
    registered = {SHELL_FORM.match(h["command"]).group("name") for _, _, h in _entries()}
    assert dispatcher in registered
    source = (HOOKS_DIR / dispatcher).read_text(encoding="utf-8")
    imported = set(re.findall(r"^[ \t]+import (\w+)$", source, re.M))  # indented: the lazy imports in decide
    assert imported == {name[: -len(".py")] for name in COMPOSED[dispatcher]}
