"""Unit tests of ``harness_lib.parallel_lanes``: plan checks, overlap, waves, probes, staging, rendering."""
from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from harness_lib import parallel_lanes as pl
from harness_lib.commit_grouping import CapturedPath


def lane(
        lane_id: str, files: Optional[List[str]] = None, kind: str = "implement", wave: Optional[int] = None,
        tools: Optional[List[str]] = None, model: str = "haiku",
) -> Dict[str, object]:
    """One raw lane dict as the plan JSON carries it."""
    raw: Dict[str, object] = {
        "id": lane_id, "kind": kind, "model": model, "tools": tools or ["Read", "Edit"],
        "files": files if files is not None else [f"src/{lane_id}.py"],
    }
    if wave is not None:
        raw["wave"] = wave
    return raw


def plan_problems(lanes: List[Dict[str, object]], **extra: object) -> List[str]:
    with pytest.raises(pl.PlanError) as caught:
        pl.plan_lanes({"lanes": lanes, **extra})
    return caught.value.problems


def waves_of(lanes: List[Dict[str, object]]) -> Dict[str, Optional[int]]:
    _, built = pl.plan_lanes({"lanes": lanes})
    return {item.id: item.wave for item in built}


# --- structure --------------------------------------------------------------------------------------------

def test_valid_plan_parses_lanes_and_target() -> None:
    lanes = [lane("task1"), lane("task2", kind="review")]
    target, built = pl.plan_lanes({"target": "feat-x", "lanes": lanes})
    assert target == "feat-x"
    assert [(item.id, item.kind, item.status) for item in built] == [
        ("task1", "implement", "planned"), ("task2", "review", "planned"),
    ]


def test_target_is_optional() -> None:
    target, _ = pl.plan_lanes({"lanes": [lane("a")]})
    assert target is None


@pytest.mark.parametrize("bad", ["Task1", "-a", "a_b", "", "a b"])
def test_lane_id_must_match_pattern(bad: str) -> None:
    assert any("id" in p for p in plan_problems([lane(bad)]))


def test_duplicate_ids_are_a_problem() -> None:
    problems = plan_problems([lane("a"), lane("a", files=["other.py"])])
    assert any("duplicate" in p and "a" in p for p in problems)


def test_unknown_kind_empty_model_and_tools_are_problems() -> None:
    raw = lane("a")
    raw.update(kind="build", model="", tools=[])
    problems = plan_problems([raw])
    assert any("kind" in p for p in problems)
    assert any("model" in p for p in problems)
    assert any("tools" in p for p in problems)


def test_implement_lane_needs_files_but_review_lane_does_not() -> None:
    assert any("files" in p for p in plan_problems([lane("a", files=[])]))
    _, built = pl.plan_lanes({"lanes": [lane("a", files=[], kind="research")]})
    assert built[0].files == []


@pytest.mark.parametrize("entry", ["/abs/a.py", "C:/abs/a.py", "src\\a.py", "../a.py", "src/../a.py"])
def test_paths_must_be_repo_relative_posix(entry: str) -> None:
    assert plan_problems([lane("a", files=[entry])])


def test_all_problems_are_reported_together() -> None:
    problems = plan_problems([lane("A"), lane("b", files=["/x"])])
    assert len(problems) >= 2


def test_empty_lane_list_is_a_problem() -> None:
    assert plan_problems([])


@pytest.mark.parametrize("bad", [0, -1, "1", 1.5, True])
def test_wave_must_be_a_positive_integer(bad: object) -> None:
    raw = lane("a")
    raw["wave"] = bad
    assert any("wave" in p for p in plan_problems([raw]))


def test_mixed_explicit_and_implicit_waves_are_a_problem() -> None:
    problems = plan_problems([lane("a", wave=1), lane("b")])
    assert any("wave" in p and "all" in p for p in problems)


# --- overlap ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("a, b, shared", [
    ("src/util.py", "src/util.py", "src/util.py"),
    ("src/", "src/util.py", "src/util.py"),
    ("src/util.py", "src/", "src/util.py"),
    ("src/", "src/pkg/", "src/pkg/"),
    ("src/*.py", "src/util.py", "src/util.py"),
    ("src/util.py", "src/*.py", "src/util.py"),
    ("src/*.py", "src/u*.py", "src/u*.py"),
    ("src/", "src/*.py", "src/*.py"),
])
def test_entries_overlap(a: str, b: str, shared: str) -> None:
    assert pl.entry_overlap(a, b) == shared


@pytest.mark.parametrize("a, b", [
    ("src/a.py", "src/b.py"),
    ("src/", "tests/a.py"),
    ("src/", "srcother/a.py"),
    ("src/*.py", "tests/*.py"),
    ("src/*.py", "src/a.txt"),
    ("src/", "tests/*.py"),
])
def test_entries_do_not_overlap(a: str, b: str) -> None:
    assert pl.entry_overlap(a, b) is None


def test_explicit_wave_overlap_is_a_problem_with_exact_text() -> None:
    problems = plan_problems([
        lane("task1", files=["src/util.py", "a.py"], wave=1), lane("task2", files=["src/util.py"], wave=1),
    ])
    assert problems == ["overlap: wave 1 lanes task1, task2 share src/util.py"]


def test_overlap_across_waves_is_allowed() -> None:
    _, built = pl.plan_lanes({"lanes": [
        lane("a", files=["x.py"], wave=1), lane("b", files=["x.py"], wave=2),
    ]})
    assert [item.wave for item in built] == [1, 2]


def test_read_only_lanes_never_overlap() -> None:
    _, built = pl.plan_lanes({"lanes": [
        lane("a", files=["x.py"], wave=1), lane("b", files=["x.py"], kind="review", wave=1),
    ]})
    assert [item.wave for item in built] == [1, 1]


# --- wave packing -----------------------------------------------------------------------------------------

def test_disjoint_lanes_pack_into_wave_one() -> None:
    assert waves_of([lane("a"), lane("b")]) == {"a": 1, "b": 1}


def test_overlapping_lanes_pack_first_fit() -> None:
    packed = waves_of([
        lane("a", files=["x.py"]), lane("b", files=["x.py"]), lane("c", files=["y.py"]),
        lane("d", files=["x.py", "y.py"]),
    ])
    assert packed == {"a": 1, "b": 2, "c": 1, "d": 3}


def test_read_only_lanes_pack_into_wave_one() -> None:
    packed = waves_of([lane("a", files=["x.py"]), lane("b", files=["x.py"]), lane("r", kind="review")])
    assert packed == {"a": 1, "b": 2, "r": 1}


# --- profiles and summary ---------------------------------------------------------------------------------

def _built(lanes: List[Dict[str, object]]) -> List[pl.Lane]:
    return pl.plan_lanes({"target": "feat-x", "lanes": lanes})[1]


def test_probe_profiles_group_by_sorted_deduplicated_tools() -> None:
    built = _built([
        lane("task1", tools=["Read", "Edit", "Bash(pytest *)"]),
        lane("task2", tools=["Edit", "Read", "Bash(pytest *)", "Read"], files=["b.py"]),
        lane("task3", tools=["Read"], files=["c.py"]),
        lane("task4", tools=["Read"], files=["d.py"], kind="review", model="opus"),
    ])
    profiles = pl.probe_profiles(built)
    assert [(p.name, p.tools, p.lane_ids) for p in profiles] == [
        ("P1", ("Bash(pytest *)", "Edit", "Read"), ("task1", "task2")),
        ("P2", ("Read",), ("task3",)),
    ]
    assert profiles[0].model == "haiku"


def test_plan_summary_matches_the_documented_shape() -> None:
    built = _built([
        lane("task1", tools=["Read", "Edit", "Bash(pytest *)"], files=["a.py"]),
        lane("task2", tools=["Edit", "Read", "Bash(pytest *)"], files=["a.py"], model="sonnet"),
        lane("task3", kind="review", model="opus"),
    ])
    assert pl.render_plan_summary("feat-x", built).splitlines() == [
        "target: feat-x",
        "wave 1: task1 (implement, haiku), task3 (review, opus)",
        "wave 2: task2 (implement, sonnet)",
        "prong 1: worktrees for task1, task2",
        "prong 2: probe P1 [Bash(pytest *), Edit, Read]: task1, task2",
        "prong 2: optional probe for read-only lanes: task3",
        "next: setup --wave 1",
    ]


def test_plan_summary_without_implement_lanes() -> None:
    built = _built([lane("r1", kind="research", model="opus")])
    lines = pl.render_plan_summary("feat-x", built).splitlines()
    assert "prong 1: skip (no implement lanes)" in lines
    assert not any("probe P" in line for line in lines)
    assert "prong 2: optional probe for read-only lanes: r1" in lines


# --- slug, state ------------------------------------------------------------------------------------------

def test_target_slug_replaces_foreign_characters() -> None:
    assert pl.target_slug("feat/x y@1.2_z") == "feat-x-y-1.2_z"


def test_state_round_trips() -> None:
    built = _built([lane("a"), lane("b", kind="review")])
    built[0].status, built[0].branch, built[0].staged = "dispatched", "p2/a", ["src/a.py"]
    target, loaded = pl.load_state(pl.dump_state("feat-x", built))
    assert target == "feat-x"
    assert loaded == built


def test_load_state_rejects_garbage() -> None:
    with pytest.raises(pl.PlanError):
        pl.load_state("{not json")
    with pytest.raises(pl.PlanError):
        pl.load_state('{"target": "t"}')


def test_unfinished_state_blocks_replanning() -> None:
    built = _built([lane("a")])
    assert pl.unfinished(built) == ["a"]
    built[0].status = "cleaned"
    assert pl.unfinished(built) == []


def test_state_is_removable_only_without_live_worktrees_or_planned_lanes() -> None:
    built = _built([lane("a"), lane("b"), lane("r", kind="review")])
    a, b, r = built
    a.status, a.worktree = "cleaned", "/w/a"
    b.status, b.worktree = "dispatched", "/w/b"
    r.status = "dispatched"
    assert not pl.state_is_spent(built)
    b.status = "cleaned"
    assert pl.state_is_spent(built)
    b.status, b.worktree = "planned", None
    assert not pl.state_is_spent(built)


# --- staging ----------------------------------------------------------------------------------------------

def test_path_matching_against_entries() -> None:
    entries = ["src/a.py", "tests/", "docs/*.md"]
    assert pl.matches_entries("src/a.py", entries)
    assert pl.matches_entries("tests/sub/test_a.py", entries)
    assert pl.matches_entries("docs/x.md", entries)
    assert not pl.matches_entries("src/b.py", entries)
    assert not pl.matches_entries("testsx/a.py", entries)


def test_undeclared_paths_include_both_sides_of_a_rename() -> None:
    changes = [CapturedPath("M", "src/a.py"), CapturedPath("R", "src/new.py", "lib/old.py")]
    assert pl.undeclared_paths(changes, ["src/"]) == ["lib/old.py"]


def test_staging_report_lists_each_change_and_every_touched_path() -> None:
    changes = [
        CapturedPath("A", "a.py"), CapturedPath("M", "m.py"), CapturedPath("T", "t.py"),
        CapturedPath("D", "d.py"), CapturedPath("R", "new.py", "old.py"),
    ]
    report = pl.staging_report(changes)
    assert report.lines == ["A a.py", "M m.py", "T t.py", "D d.py", "R old.py -> new.py"]
    assert report.touched == ["a.py", "m.py", "t.py", "d.py", "old.py", "new.py"]


def test_plain_files_skip_directories_and_globs() -> None:
    assert pl.plain_files(["src/*.py", "src/", "a.py", "b/c.py"]) == ["a.py", "b/c.py"]


def test_pending_overlap_lists_changed_paths_only() -> None:
    assert pl.pending_overlap(["a.py", "b.py"], ["b.py", "c.py"]) == ["b.py"]


def test_pending_entries_overlapping_lane_file_sets() -> None:
    pending = ["src/x.py", "docs/z.md", "tests/t.py"]
    assert pl.pending_in_entries(pending, ["src/", "tests/t.py"]) == ["src/x.py", "tests/t.py"]


# --- rendering --------------------------------------------------------------------------------------------

def test_brief_for_an_implement_lane() -> None:
    built = _built([lane("task1", files=["src/a.py", "src/pkg/"], tools=["Read", "Bash(pytest *)"])])
    built[0].task = "do the thing"
    text = pl.render_brief(built[0], "C:/wt/p2-task1")
    assert text.startswith("## Pre-Authorized Tools\n- Read\n- Bash(pytest *)\n")
    order = [
        "If a tool NOT listed here is needed: stop and report it back to the caller instead of prompting.",
        "Working directory: C:/wt/p2-task1",
        "Files (edit only these paths):",
        "- src/a.py",
        "- src/pkg/",
        "Commit in the worktree branch p2/task1. No push, no merge, no rebase.",
        "Task: do the thing",
    ]
    positions = [text.index(item) for item in order]
    assert positions == sorted(positions)


def test_brief_for_a_read_only_lane_has_no_commit_line_or_task() -> None:
    built = _built([lane("r", kind="review", files=[])])
    text = pl.render_brief(built[0], "C:/repo")
    assert "Working directory: C:/repo" in text
    assert "read-only lane: no edits, no commits" in text
    assert "Commit in the worktree" not in text
    assert "Task:" not in text


def test_dispatch_row() -> None:
    built = _built([lane("task1"), lane("r", kind="review", model="opus")])
    assert pl.render_dispatch_row(built[0], "C:/w/p2-task1", "C:/b/task1.md") == (
        "lane=task1 model=haiku kind=implement worktree=C:/w/p2-task1\nBrief: C:/b/task1.md"
    )
    assert pl.render_dispatch_row(built[1], None, "C:/b/r.md").splitlines()[0] == (
        "lane=r model=opus kind=review worktree=-"
    )


def test_status_line_uses_dashes_for_absent_fields() -> None:
    built = _built([lane("a"), lane("r", kind="review")])
    built[0].branch, built[0].worktree, built[0].status = "p2/a", "C:/w/p2-a", "dispatched"
    built[0].base_sha = "0123456789abcdef0123"
    assert pl.render_status_line(built[0]) == "a 1 implement dispatched p2/a C:/w/p2-a 0123456789ab"
    assert pl.render_status_line(built[1]) == "r 1 review planned - - -"


def test_probe_prompt_exercises_one_call_per_tool() -> None:
    tools = ("Bash(git status:*)", "Bash(pytest *)", "Edit", "Glob", "Read", "Write")
    text = pl.render_probe_prompt(tools, "C:/wt/p2-a", "src/a.py")
    assert "Read the first 5 lines of src/a.py" in text
    assert "C:/wt/p2-a/.p2_probe" in text
    assert 'git -C "C:/wt/p2-a" status --short' in text
    assert "pytest --version" in text
    assert "exercise Glob once with a harmless call" in text
    assert "delete" in text.lower()
    ending = "For each action report SUCCESS or BLOCKED (describe what appeared). Do nothing else."
    assert text.rstrip().endswith(ending)


def test_probe_prompt_without_read_target_and_without_write_tools() -> None:
    text = pl.render_probe_prompt(("Read",), "C:/wt/p2-a", None)
    assert "Read any one file" in text
    assert ".p2_probe" not in text
