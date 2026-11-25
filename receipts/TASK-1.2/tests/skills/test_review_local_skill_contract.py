"""Contract test for the ``review-local`` skill: its SKILL.md frontmatter, the driver commands it names and
the key model it relies on.

The skill drives the shared ``pr_review.py``; its own modules (``review_local_models``, ``review_local_api``)
hold the local-target seam. Literals are imported from those modules, never copied.
"""
from __future__ import annotations

import re

import pytest

from harness_lib import review_local_api, review_local_models
from harness_lib.project import plugin_root
from harness_lib.skill_parts import skill_parts

NAME = "review-local"
SKILL = plugin_root() / "skills" / NAME / "SKILL.md"
DRIVER = '"${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py"'
PHASE4 = '"${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/phase4_branch_safety.py"'


def _body() -> str:
    return skill_parts(SKILL)[1]


def test_frontmatter_names_the_skill_folder() -> None:
    keys = skill_parts(SKILL)[0]
    assert keys["name"].strip("\"'") == NAME


def test_description_is_filled() -> None:
    description = skill_parts(SKILL)[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description


def test_body_names_the_range_capture_and_the_local_key() -> None:
    body = _body()
    assert DRIVER in body and PHASE4 in body
    assert re.search(r"capture --range\b", body)
    assert f"--pr {review_local_models.LOCAL_PREFIX}<label>" in body
    assert f"{review_local_models.REVIEW_PREFIX}<label>_<slug>.json" in body


def test_body_never_reads_pr_metadata_from_gh() -> None:
    assert "gh pr view" not in _body()


def test_api_exports_existing_names() -> None:
    missing = [name for name in review_local_api.__all__ if not hasattr(review_local_api, name)]
    assert not missing, missing


def test_models_round_trip_a_local_key() -> None:
    label = review_local_models.branch_label("1110-bubbles", "0" * 40)
    key = review_local_models.LOCAL_PREFIX + label
    assert review_local_models.parse_key(key) == key
    with pytest.raises(ValueError):
        review_local_models.parse_key(review_local_models.LOCAL_PREFIX + label.upper())
