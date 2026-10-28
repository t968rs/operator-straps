"""Guard test: the pr-review README stays aligned with the fix-wave planner it illustrates.

The README draws the wave layout of one worked example and names the planner's caps, helpers and config keys.
The test replans that example with ``review_waves.plan_waves`` and pins each name the prose shares with it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

import pytest
from harness_lib import review_waves as rwv

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


def _example_issues(criticals: bool) -> List[Dict[str, object]]:
    """The README's worked examples: a hub over seven files, a leaf per file and a lone minor; the second adds
    two judgment criticals sharing ``cli.py``."""
    names = [f"mod_{letter}.py" for letter in "abcdefg"]
    issues = [_issue("I1", names[0], fix_kind="judgment", files=names)]
    issues += [_issue(f"M{n}", name) for n, name in enumerate(names, start=1)]
    issues.append(_issue("M8", "docs_x.py"))
    if criticals:
        issues += [_issue(c, "cli.py", fix_kind="judgment") for c in ("C1", "C2")]
    return issues


def _lane(ids: List[str]) -> str:
    return "".join(f"[{i}]" for i in ids) if len(ids) > 1 else f"[{ids[0]}"


def _lanes(waves: List[List[Dict[str, object]]]) -> List[List[List[str]]]:
    """Issue ids of every fixer, grouped by wave."""
    return [[list(map(str, fixer["issue_ids"])) for fixer in wave] for wave in waves]  # type: ignore[call-overload]


def _seconds(fixer: Dict[str, object], by_id: Dict[str, Dict[str, object]]) -> int:
    """The README's fixer estimate, recomputed from the fixer row and the public cost constants."""
    ids = list(map(str, fixer["issue_ids"]))  # type: ignore[call-overload]
    if fixer["model"] == "haiku":
        base, per_unit = rwv.HAIKU_SECONDS
        return base + per_unit * len(ids)
    opus = rwv.OPUS_SECONDS
    kinds = ["mechanical" if by_id[i]["fix_kind"] == "mechanical" else "judgment" if i[0] == "M" else "heavy"
             for i in ids]
    return opus["base"] + sum(opus[kind] for kind in kinds)


@pytest.mark.parametrize("criticals", [False, True])
def test_worked_example_lanes_match_the_planner(criticals: bool) -> None:
    issues = _example_issues(criticals)
    waves = rwv.plan_waves(issues, held=[], done=[])
    text = _text()
    assert len(waves) == 2, "the README draws two waves per example"
    for wave in _lanes(waves):
        for ids in wave:
            assert _lane(ids) in text, f"README never draws the lane {ids}"
    by_id = {str(i["id"]): i for i in issues}
    walls = [max(_seconds(fixer, by_id) for fixer in wave) for wave in waves]
    assert f"estimated wall: {walls[0]} + {walls[1]} = {sum(walls)} s" in text


def test_caps_in_the_prose_are_the_planner_constants() -> None:
    text = _text()
    assert f"{rwv.MAX_ISSUES_PER_FIXER} units" in text
    assert f"up to {rwv.FIXERS_PER_WAVE} fixers" in text
    assert f"fewer than {rwv.FIXERS_PER_WAVE} fixers" in text
    assert f"group of exactly {rwv.MAX_ISSUES_PER_FIXER + 1} units" in text


def test_cost_figures_in_the_prose_are_the_planner_constants() -> None:
    text = _text()
    base, per_unit = rwv.HAIKU_SECONDS
    opus = rwv.OPUS_SECONDS
    assert f"haiku fixer    {base} s + {per_unit} s per unit" in text
    line = (f"opus fixer     {opus['base']} s + {opus['heavy']} s per heavy unit + "
            f"{opus['judgment']} s per minor judgment unit + {opus['mechanical']} s per mechanical part")
    assert line in text


def test_every_planner_helper_the_readme_names_exists() -> None:
    names = re.findall(r"\((_\w+)\)", _text())
    assert names, "README names no planner helper"
    for name in names:
        assert hasattr(rwv, name), f"README names {name}, which review_waves no longer defines"


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
