"""Plan documents: file names, plan ids, schema validation and the freeze digest of ``plan_doc``."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import pytest
from harness_lib import plan_doc as pd
from harness_lib.config import activate, load_config


def sample_plan() -> Dict[str, Any]:
    return {
        "plan_id": "0003", "plan_created": "2026-10-28", "execution_model": "serial",
        "base_commit": "a" * 40,
        "decisions": [{"id": "D1", "question": "Split or keep?", "chosen": "split",
                       "options": [{"id": "split", "summary": "two modules"},
                                   {"id": "keep", "summary": "one module"}]}],
        "items": [{"id": "TASK-1", "title": "Split the module", "action": "Move the readers.",
                   "status": "PENDING", "evidence": "not started", "files": ["src/a.py"],
                   "anchors": [{"at": "src/a.py:1-2", "expect": "def read"}],
                   "commands": [{"run": "python -m pytest tests/test_a.py -q", "expect": "1 passed"}],
                   "tests": [{"node": "tests/test_a.py::test_read", "red": "ImportError"}]}],
    }


def test_title_slug_keeps_words_and_joins_them_with_underscores() -> None:
    assert pd.title_slug("Split schema I/O: readers + writers") == "Split_schema_I_O_readers_writers"


def test_title_slug_refuses_a_title_without_letters_or_digits() -> None:
    with pytest.raises(pd.PlanError):
        pd.title_slug(" -- ")


def test_next_plan_id_counts_up_from_the_highest_prefix(tmp_path: Path) -> None:
    (tmp_path / "0002_a_ActionPlan.json").write_text("{}", encoding="utf-8")
    (tmp_path / "0009_b_PIP.md").write_text("", encoding="utf-8")
    (tmp_path / "notes.md").write_text("", encoding="utf-8")
    assert pd.next_plan_id(tmp_path) == "0010"


def test_next_plan_id_starts_at_one_in_a_missing_folder(tmp_path: Path) -> None:
    assert pd.next_plan_id(tmp_path / "absent") == "0001"


def test_find_plan_accepts_an_id_with_or_without_padding(tmp_path: Path) -> None:
    path = tmp_path / "0003_Split_ActionPlan.json"
    path.write_text("{}", encoding="utf-8")
    assert pd.find_plan(tmp_path, "3") == path
    assert pd.find_plan(tmp_path, "0003") == path


def test_find_plan_names_a_missing_id(tmp_path: Path) -> None:
    with pytest.raises(pd.PlanError, match="no plan 0004"):
        pd.find_plan(tmp_path, "4")


def test_pip_path_sits_beside_the_plan(tmp_path: Path) -> None:
    assert pd.pip_path(tmp_path / "0003_Split_ActionPlan.json") == tmp_path / "0003_Split_PIP.md"


def test_planned_tests_live_under_the_plan_id(tmp_path: Path) -> None:
    assert pd.planned_tests_dir(tmp_path, "0003") == tmp_path / "0003" / "tests"


def test_a_v2_plan_validates(make_project) -> None:
    cfg = activate(load_config(make_project({})))
    assert pd.schema_problems(sample_plan(), cfg) == []


def test_a_malformed_anchor_is_a_schema_problem(make_project) -> None:
    cfg = activate(load_config(make_project({})))
    plan = sample_plan()
    plan["items"][0]["anchors"][0]["at"] = "src/a.py"
    problems = pd.schema_problems(plan, cfg)
    assert len(problems) == 1 and problems[0].startswith("schema: items/0/anchors/0/at:")


def test_digest_ignores_status_and_evidence() -> None:
    plan = sample_plan()
    moved = copy.deepcopy(plan)
    moved["items"][0].update(status="COMPLETE", evidence="done", verification_references=["b" * 40])
    moved["completed"] = "2026-10-29"
    assert pd.frozen_digest(plan) == pd.frozen_digest(moved)


def test_digest_changes_when_a_fixed_field_changes() -> None:
    plan = sample_plan()
    edited = copy.deepcopy(plan)
    edited["items"][0]["anchors"][0]["expect"] = "def write"
    assert pd.frozen_digest(plan) != pd.frozen_digest(edited)


def test_dump_round_trips_and_ends_with_a_newline() -> None:
    text = pd.dump_plan(sample_plan())
    assert text.endswith("}\n")
    assert pd.parse_plan(text, "x.json") == sample_plan()


def test_item_lookup_names_an_unknown_item() -> None:
    with pytest.raises(pd.PlanError, match="no item TASK-9"):
        pd.item_by_id(sample_plan(), "TASK-9")
