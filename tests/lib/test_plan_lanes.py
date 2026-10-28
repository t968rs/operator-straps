"""Tests of ``harness_lib.plan_lanes``: an action plan's open items as a parallel2 dispatch plan."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from harness_lib import parallel_lanes as pl
from harness_lib import plan_lanes as pln


def item(ident: str, files: List[str], deps: Optional[List[str]] = None, status: str = "PENDING",
         **extra: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "id": ident, "title": f"do {ident}", "status": status, "files": files, "dependencies": deps,
    }
    raw.update(extra)
    return raw


def plan(*items: Dict[str, Any]) -> Dict[str, Any]:
    return {"plan_id": "0007", "base_commit": "0" * 40, "items": list(items)}


def waves(result: Dict[str, Any]) -> Dict[str, int]:
    return {lane["id"]: lane["wave"] for lane in result["lanes"]}


def problems_of(data: Dict[str, Any]) -> List[str]:
    with pytest.raises(pln.LanesError) as caught:
        pln.lanes_plan(data, "feat-x")
    return caught.value.problems


# --- lane fields ------------------------------------------------------------------------------------------

def test_lane_fields_come_from_the_item() -> None:
    tests = [{"node": "tests/test_p.py::test_a", "red": "ImportError"},
             {"node": "tests/test_p.py::test_b", "red": "AssertionError"},
             {"node": "tests/test_q.py::TestQ::test_c", "red": "TypeError"}]
    data = plan(item("TASK-1", ["src/p.py", "tests/test_p.py"], tests=tests, model="haiku"))
    result = pln.lanes_plan(data, "feat-x")
    assert result["target"] == "feat-x"
    assert result["lanes"] == [{
        "id": "task-1", "kind": "implement", "model": "haiku", "task": "do TASK-1",
        "files": ["src/p.py", "tests/test_p.py", "tests/test_q.py"],
        "tools": list(pln.IMPLEMENT_TOOLS), "wave": 1,
    }]


def test_model_defaults_to_sonnet() -> None:
    result = pln.lanes_plan(plan(item("A", ["a.py"]), item("B", ["b.py"], model=None)), "t")
    assert [lane["model"] for lane in result["lanes"]] == ["sonnet", "sonnet"]


def test_implement_tools_cover_edits_commits_and_pytest() -> None:
    tools = pln.IMPLEMENT_TOOLS
    for needed in ("Read", "Edit", "Write", "Bash(git add *)", "Bash(git commit *)"):
        assert needed in tools
    assert any(tool.startswith("Bash(") and "pytest" in tool for tool in tools)


def test_only_open_items_become_lanes() -> None:
    data = plan(
        item("A", ["a.py"], status="COMPLETE"), item("B", ["b.py"], status="CLOSED_NO_ACTION"),
        item("C", ["c.py"], status="PENDING"), item("D", ["d.py"], status="IN_PROGRESS"),
        item("E", ["e.py"], status="BLOCKED"),
    )
    assert [lane["id"] for lane in pln.lanes_plan(data, "t")["lanes"]] == ["c", "d", "e"]


def test_test_files_alone_give_a_lane_files() -> None:
    data = plan(item("A", [], tests=[{"node": "tests/test_a.py::test_x", "red": "ImportError"}]))
    assert pln.lanes_plan(data, "t")["lanes"][0]["files"] == ["tests/test_a.py"]


# --- waves ------------------------------------------------------------------------------------------------

def test_wave_follows_the_longest_dependency_chain() -> None:
    data = plan(item("A", ["a.py"]), item("B", ["b.py"], ["A"]), item("C", ["c.py"], ["B", "A"]),
                item("D", ["d.py"]))
    assert waves(pln.lanes_plan(data, "t")) == {"a": 1, "b": 2, "c": 3, "d": 1}


def test_dependencies_on_finished_items_are_satisfied() -> None:
    data = plan(item("A", ["a.py"], status="COMPLETE"), item("X", ["x.py"], status="CLOSED_NO_ACTION"),
                item("B", ["b.py"], ["A", "X"]))
    assert waves(pln.lanes_plan(data, "t")) == {"b": 1}


def test_overlapping_lanes_of_one_wave_move_to_the_next_wave() -> None:
    data = plan(item("A", ["src/a.py"]), item("B", ["src/"]), item("C", ["src/c.py"]))
    assert waves(pln.lanes_plan(data, "t")) == {"a": 1, "b": 2, "c": 1}


def test_a_moved_lane_cascades_to_its_dependents() -> None:
    data = plan(item("A", ["shared.py"]), item("B", ["shared.py", "b.py"]), item("C", ["c.py"], ["B"]),
                item("D", ["d.py"], ["C"]))
    assert waves(pln.lanes_plan(data, "t")) == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_a_test_file_shared_by_two_items_separates_them() -> None:
    node = {"node": "tests/test_s.py::test_one", "red": "AssertionError"}
    data = plan(item("A", ["a.py"], tests=[node]), item("B", ["b.py"], tests=[node]))
    assert waves(pln.lanes_plan(data, "t")) == {"a": 1, "b": 2}


def test_output_passes_parallel2_plan_validation_unchanged() -> None:
    data = plan(
        item("TASK-1", ["src/a.py"], tests=[{"node": "tests/test_a.py::test_a", "red": "ImportError"}]),
        item("TASK-2", ["src/"], ["TASK-1"]), item("TASK-3", ["src/b.py", "docs/*.md"]),
        item("TASK-4", ["docs/guide.md"], ["TASK-3"], model="opus"),
        item("TASK-5", ["x.py"], status="COMPLETE"),
    )
    result = pln.lanes_plan(data, "feat-x")
    target, lanes = pl.plan_lanes(result)
    assert target == "feat-x"
    assert {lane.id: lane.wave for lane in lanes} == waves(result)


# --- problems ---------------------------------------------------------------------------------------------

def test_unknown_dependency_is_a_problem() -> None:
    assert problems_of(plan(item("A", ["a.py"], ["GHOST"]))) == ["item A: unknown dependency GHOST"]


def test_cycle_is_a_problem_naming_the_ids() -> None:
    data = plan(item("A", ["a.py"], ["C"]), item("B", ["b.py"], ["A"]), item("C", ["c.py"], ["B"]),
                item("D", ["d.py"]))
    found = problems_of(data)
    assert len(found) == 1 and found[0].startswith("dependency cycle: ")
    assert all(ident in found[0] for ident in ("A", "B", "C")) and "D" not in found[0]


def test_self_dependency_is_a_cycle() -> None:
    assert problems_of(plan(item("A", ["a.py"], ["A"]))) == ["dependency cycle: A -> A"]


def test_item_without_files_is_a_problem() -> None:
    assert problems_of(plan(item("A", []), item("B", ["b.py"]))) == ["item A: no files"]


def test_every_problem_is_reported_at_once() -> None:
    found = problems_of(plan(item("A", [], ["GHOST"]), item("B", ["b.py"], ["B"])))
    assert sorted(found) == [
        "dependency cycle: B -> B", "item A: no files", "item A: unknown dependency GHOST",
    ]


def test_item_id_that_is_no_lane_id_is_a_problem() -> None:
    assert problems_of(plan(item("TASK_1", ["a.py"]))) == ["item TASK_1: id does not form a lane id"]


def test_duplicate_item_ids_are_a_problem() -> None:
    assert problems_of(plan(item("A", ["a.py"]), item("A", ["b.py"]))) == ["duplicate item id A"]


def test_plan_without_open_items_is_a_problem() -> None:
    assert problems_of(plan(item("A", ["a.py"], status="COMPLETE"))) == ["plan has no open items"]


def test_lanes_error_has_the_plan_error_shape() -> None:
    error = pln.LanesError(["one", "two"])
    assert isinstance(error, pl.PlanError) and error.problems == ["one", "two"] and str(error) == "one\ntwo"
