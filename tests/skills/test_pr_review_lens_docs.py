"""Contract tests: the pr-review docs state the roast sub-lens exception and the any-``skills/`` trigger.

The planner drops the plugin's linear pass for the roast slot and finds per-skill-package skills in any
``skills/<name>/`` folder holding a ``SKILL.md``; the skill text, the lens catalog and the ``skills_dir``
key description say the same, so a reader of any of them gets the rule the code applies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_SKILL = Path("skills") / "pr-review" / "SKILL.md"
_CATALOG = Path("schemas") / "catalogs" / "CrossCuttingLensCatalog.json"
_CONFIG_SCHEMA = Path("config") / "harness.schema.json"
_LINEAR = "linear docstring-vs-code pass"


def _normalized(text: str) -> str:
    """``text`` with whitespace runs collapsed to one space."""
    return re.sub(r"\s+", " ", text).strip()


def _catalog(plugin_root: Path) -> dict:
    """The plugin lens catalog."""
    return json.loads((plugin_root / _CATALOG).read_text(encoding="utf-8"))


def test_skill_states_the_roast_exception(plugin_root: Path) -> None:
    text = _normalized((plugin_root / _SKILL).read_text(encoding="utf-8"))
    assert "Every reviewer slot except roast runs a linear docstring-vs-code pass" in text
    assert "Every reviewer, in every slot, runs" not in text


def test_skill_trigger_row_names_any_skills_folder(plugin_root: Path) -> None:
    lines = (plugin_root / _SKILL).read_text(encoding="utf-8").splitlines()
    row = next(line for line in lines if line.startswith("| per-skill-package |"))
    assert "`<skills_dir>" not in row
    assert "any `skills/<name>/` folder holding a `SKILL.md` at the PR head" in row


def test_catalog_linear_pass_names_its_skip(plugin_root: Path) -> None:
    row = next(sub for sub in _catalog(plugin_root)["default_sub_lenses"] if sub["name"] == _LINEAR)
    assert row.get("skip_lenses") == ["roast"]
    assert "except the roast slot" in row["trigger"]["description"]


def test_catalog_policy_names_the_pr_review_skill_trigger(plugin_root: Path) -> None:
    policy = _normalized(_catalog(plugin_root)["policy"]["mechanical_triggers"])
    assert "per-skill-package matches any skills/<name>/ folder holding a SKILL.md at the PR head" in policy


def test_skills_dir_no_longer_claims_pr_review_detection(plugin_root: Path) -> None:
    schema = json.loads((plugin_root / _CONFIG_SCHEMA).read_text(encoding="utf-8"))
    description = schema["properties"]["skills_dir"]["description"]
    assert "pr-team" in description and "(review lens detection)" not in description
