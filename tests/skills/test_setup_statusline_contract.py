"""Guard test: the setup-statusline skill, its ccstatusline defaults and the git-status mod agree.

The skill pins a ccstatusline version and writes a ``statusLine`` command; the defaults file must be the
config schema that version reads; the git-status mod (``plugins/git-status/hooks/status.ts``) clears its own
line only when that command names ccstatusline. The defaults' ``custom-command`` widget prints the line the
working-refs mod writes (plan 2025), so its command names that file. All of it is prose or data, so the test
pins the shared names.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PLUGIN = _REPO / "plugins" / "banner-status"
_SKILL_DIR = _PLUGIN / "skills" / "setup-statusline"
_SKILL = _SKILL_DIR / "SKILL.md"
_DEFAULTS = _SKILL_DIR / "ccstatusline.defaults.json"
_README = _PLUGIN / "README.md"
_STATUS_TS = _REPO / "plugins" / "git-status" / "hooks" / "status.ts"
_HARNESS_DEFAULTS = _REPO / "plugins" / "harness" / "config" / "defaults.json"

# ccstatusline 2.2.32 reads config schema version 4 (src/types/Settings.ts CURRENT_VERSION)
_PINNED = "2.2.32"
# the install command pins a patch range, ~2.2.32 (>=2.2.32 <2.3.0), so a new minor never changes the schema
_RANGE = f"~{_PINNED}"
_SCHEMA_VERSION = 4
_WIDGETS = {
    "separator", "git-branch", "git-ahead-behind", "git-clean-status", "git-conflicts", "git-sha", "model",
    "thinking-effort", "context-length", "context-percentage", "custom-command",
}


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> Dict[str, str]:
    block = re.match(r"^---\n(.*?)\n---\n", _text(path), re.DOTALL)
    assert block, f"{path.name} has no frontmatter"
    pairs = (line.split(":", 1) for line in block.group(1).splitlines() if re.match(r"^[a-z-]+:", line))
    return {key.strip(): value.strip() for key, value in pairs}


def _items() -> List[Dict[str, Any]]:
    data = json.loads(_text(_DEFAULTS))
    return [item for line in data["lines"] for item in line]


def _custom_commands() -> List[Dict[str, Any]]:
    return [item for item in _items() if item["type"] == "custom-command"]


def test_skill_name_matches_its_folder() -> None:
    assert _frontmatter(_SKILL)["name"] == _SKILL_DIR.name


def test_skill_reads_the_defaults_from_its_own_folder() -> None:
    assert "${CLAUDE_SKILL_DIR}/ccstatusline.defaults.json" in _text(_SKILL)


def test_skill_and_readme_pin_one_version() -> None:
    install = f"npm install -g ccstatusline@{_RANGE}"
    assert install in _text(_SKILL)
    assert install in _text(_README)
    found = set(re.findall(r"ccstatusline@~?(\d+\.\d+\.\d+)", _text(_SKILL) + _text(_README)))
    assert found == {_PINNED}


def test_every_doc_that_sells_ccstatusline_names_the_install_command() -> None:
    install = f"npm install -g ccstatusline@{_RANGE}"
    for doc in (_REPO / "README.md", _PLUGIN / "README.md", _REPO / "plugins" / "git-status" / "README.md"):
        assert install in _text(doc), doc.relative_to(_REPO).as_posix()


def test_skill_offers_the_install_and_checks_npm_first() -> None:
    skill = _text(_SKILL)
    assert "AskUserQuestion" in skill
    assert "npm --version" in skill
    assert "never this skill" not in skill


def test_defaults_are_the_pinned_schema() -> None:
    data = json.loads(_text(_DEFAULTS))
    assert data["version"] == _SCHEMA_VERSION
    assert 1 <= len(data["lines"]) <= 3


def test_defaults_use_known_widgets_with_unique_ids() -> None:
    items = _items()
    assert {item["type"] for item in items} <= _WIDGETS
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))


def test_readme_lists_every_widget_the_defaults_use() -> None:
    readme = _text(_README)
    for kind in {item["type"] for item in _items()} - {"separator"}:
        assert f"`{kind}`" in readme, kind


def test_statusline_command_starts_with_the_executable_the_mod_looks_for() -> None:
    command = re.search(r'"command": "([^"]+)"', _text(_SKILL))
    assert command, "SKILL.md shows no statusLine command"
    assert command.group(1).split()[0] == "ccstatusline"
    assert "ccstatusline" in _text(_STATUS_TS)


def test_defaults_print_the_working_refs_line_on_a_line_of_its_own() -> None:
    widgets = _custom_commands()
    assert len(widgets) == 1, "the defaults hold no single custom-command widget"
    from harness_lib.working_refs import LINE_REL
    widget = widgets[0]
    state_dir = json.loads(_text(_HARNESS_DEFAULTS))["state_dir"]
    assert f"{state_dir}/{LINE_REL}" in widget["commandPath"]
    # the path resolves against the session's project folder from the status payload on stdin, not the
    # command's own working folder
    assert "project_dir" in widget["commandPath"]
    assert widget["preserveColors"] is True
    line = next(line for line in json.loads(_text(_DEFAULTS))["lines"] if widget in line)
    assert [item["type"] for item in line] == ["custom-command"]


def test_skill_resolves_state_dir_and_offers_the_widget_for_an_existing_config() -> None:
    skill = _text(_SKILL)
    assert "custom-command" in skill
    assert "state_dir" in skill
    assert "working-refs" in skill
