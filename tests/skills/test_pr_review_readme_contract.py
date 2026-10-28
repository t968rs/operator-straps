"""Guard test: the pr-review README stays aligned with the fix-wave planner it illustrates.

The README draws the wave layout of one worked example and names the planner's caps, helpers and config keys.
The test replans that example with ``review_merge.plan_waves`` and pins each name the prose shares with it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

import pytest
from harness_lib import review_merge as rmg

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL_DIR = _PLUGIN_ROOT / "skills" / "pr-review"
_README = _SKILL_DIR / "README.md"
_DEFAULTS = _PLUGIN_ROOT / "config" / "defaults.json"


def _text() -> str:
    if not _README.exists():
        pytest.fail(f"missing {_README}")
    return _README.read_text(encoding="utf-8")


def _issue(issue_id: str, file: str, **extra: object) -> Dict[str, object]:
    return {"id": issue_id, "name": f"n {issue_id}", "file": file, "reviewer": "runtime",
            "fix_kind": "mechanical", "summary": "s", "fix": ["f"], **extra}


def _example_issues() -> List[Dict[str, object]]:
    """The README's worked example: a hub over seven files, a leaf per file, a critical and a lone minor."""
    names = [f"mod_{letter}.py" for letter in "abcdefg"]
    issues = [_issue("I1", names[0], fix_kind="judgment", files=names)]
    issues += [_issue(f"M{n}", name) for n, name in enumerate(names, start=1)]
    return [*issues, _issue("C1", "cli.py", fix_kind="judgment"), _issue("M8", "docs_x.py")]


def _lane(ids: List[str]) -> str:
    return "".join(f"[{i}]" for i in ids) if len(ids) > 1 else f"[{ids[0]}"


def _lanes(waves: List[List[Dict[str, object]]]) -> List[List[List[str]]]:
    """Issue ids of every fixer, grouped by wave."""
    return [[list(map(str, fixer["issue_ids"])) for fixer in wave] for wave in waves]  # type: ignore[call-overload]


def test_worked_example_lanes_match_the_planner() -> None:
    lanes = _lanes(rmg.plan_waves(_example_issues(), held=[], done=[]))
    text = _text()
    assert len(lanes) == 2, "the README draws two waves"
    for wave in lanes:
        for ids in wave:
            assert _lane(ids) in text, f"README never draws the lane {ids}"
    longest = [max(len(ids) for ids in wave) for wave in lanes]
    assert longest == [3, 1] and f"critical path: {longest[0]} + {longest[1]} = {sum(longest)} ids" in text


def test_caps_in_the_prose_are_the_planner_constants() -> None:
    text = _text()
    assert f"{rmg.MAX_ISSUES_PER_FIXER} units" in text
    assert f"up to {rmg.FIXERS_PER_WAVE} fixers" in text
    assert f"fewer than {rmg.FIXERS_PER_WAVE} fixers" in text


def test_every_planner_helper_the_readme_names_exists() -> None:
    names = re.findall(r"\((_\w+)\)", _text())
    assert names, "README names no planner helper"
    for name in names:
        assert hasattr(rmg, name), f"README names {name}, which review_merge no longer defines"


def test_config_keys_in_the_table_exist_in_the_defaults() -> None:
    defaults = json.loads(_DEFAULTS.read_text(encoding="utf-8"))
    keys = re.findall(r"^\| `((?:review|tests)\.\w+)` \|", _text(), re.MULTILINE)
    assert keys, "README table names no config key"
    for key in keys:
        section, name = key.split(".")
        assert name in defaults.get(section, {}), f"README documents {key}, which defaults.json lacks"


def test_related_links_resolve() -> None:
    section = _text().split("## Related", 1)[1]
    links = re.findall(r"^- `([^`]+)`", section, re.MULTILINE)
    assert links, "README has no Related links"
    for link in links:
        assert (_SKILL_DIR / link).exists(), f"README links {link}, which does not exist"


def test_readme_describes_current_behavior_only() -> None:
    text = _text()
    for marker in ("BEFORE:", "AFTER:", "[new]", "[changed]"):
        assert marker not in text, f"README carries the change-review marker {marker}"
