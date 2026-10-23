"""Behavioral tests of the plugin's ``scripts/parallel2.py`` against real throwaway git repositories.

Each test gets a project on branch ``feat-x`` whose ``worktree_root`` points under ``tmp_path``. The driver
runs in-process through ``main`` with ``--repo``; git state is read back with plain git.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from typing import Callable, Dict, List, Optional, Tuple

import pytest
from conftest import git

pytestmark = pytest.mark.cross_os

Result = Tuple[int, str, str]
BASE_FILES = {
    "src/a.py": "a = 1\n", "src/b.py": "b = 1\n", "src/old.py": "old = 1\n",
    "tests/test_a.py": "def test_a(): pass\n", "docs/guide.md": "guide\n",
}


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    """Import parallel2.py by absolute path."""
    path = plugin_root / "scripts" / "parallel2.py"
    spec = importlib.util.spec_from_file_location("parallel2_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    """A project on branch ``feat-x``; new worktrees land in ``tmp_path/trees``."""
    config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()}
    root = make_project(config, files=BASE_FILES)
    git(root, "checkout", "-q", "-b", "feat-x")
    return root


@pytest.fixture()
def run(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture) -> Callable[..., Result]:
    """``run(*args)`` -> (exit code, stdout, stderr) of ``parallel2.py --repo <project> *args``."""
    def _run(*args: str, repo: Optional[Path] = None) -> Result:
        code = driver.main(["--repo", str(repo or project), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


def lane(lane_id: str, files: List[str], kind: str = "implement", **extra: object) -> Dict[str, object]:
    raw: Dict[str, object] = {
        "id": lane_id, "kind": kind, "model": "haiku", "tools": ["Read", "Edit", "Bash(pytest *)"],
        "files": files,
    }
    raw.update(extra)
    return raw


@pytest.fixture()
def plan(run: Callable[..., Result], tmp_path: Path) -> Callable[..., Result]:
    """``plan(lanes, *flags, **top)`` writes {target: feat-x, lanes, **top} as the plan JSON.

    It then runs ``plan`` on that file.
    """
    def _plan(lanes: List[Dict[str, object]], *flags: str, **top: object) -> Result:
        body = {"target": "feat-x", "lanes": lanes, **top}
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return run("plan", str(path), *flags)
    return _plan


def state(project: Path, target: str = "feat-x") -> Dict[str, object]:
    path = project / ".claude" / "state" / "harness" / "parallel2" / f"{target}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lane_state(project: Path, lane_id: str) -> Dict[str, object]:
    return next(item for item in state(project)["lanes"] if item["id"] == lane_id)


def commit_in(tree: Path, files: Dict[str, Optional[str]], message: str = "work") -> None:
    """Write (or delete, for None) files in ``tree`` and commit them."""
    for rel, body in files.items():
        target = tree / rel
        if body is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", message)


@pytest.fixture()
def two_lanes(plan: Callable[..., Result], run: Callable[..., Result], project: Path) -> Path:
    """Planned and set up: task1 owns src/a.py + tests/, task2 owns src/b.py + src/old.py."""
    plan([lane("task1", ["src/a.py", "tests/"]), lane("task2", ["src/b.py", "src/old.py"])])
    code, _, err = run("setup")
    assert code == 0, err
    return project


# --- plan -------------------------------------------------------------------------------------------------

def test_plan_writes_state_in_the_project_and_prints_the_summary(plan, project: Path) -> None:
    code, out, err = plan([lane("task1", ["src/a.py"]), lane("task3", [], kind="review", model="opus")])
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "target: feat-x",
        "wave 1: task1 (implement, haiku), task3 (review, opus)",
        "prong 1: worktrees for task1",
        "prong 2: probe P1 [Bash(pytest *), Edit, Read]: task1",
        "prong 2: optional probe for read-only lanes: task3",
        "next: setup --wave 1",
    ]
    saved = state(project)
    assert saved["target"] == "feat-x"
    assert [(i["id"], i["wave"], i["status"]) for i in saved["lanes"]] == [("task1", 1, "planned"),
                                                                           ("task3", 1, "planned")]


def test_plan_reads_stdin_for_a_dash(run, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"target": "feat-x", "lanes": [lane("a", ["src/a.py"])]})
    monkeypatch.setattr("sys.stdin", io.StringIO(body))
    code, out, err = run("plan", "-")
    assert (code, err) == (0, "")
    assert out.splitlines()[1] == "wave 1: a (implement, haiku)"


def test_plan_defaults_the_target_to_the_current_branch(run, tmp_path: Path, project: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"lanes": [lane("a", ["src/a.py"])]}), encoding="utf-8")
    code, out, _ = run("plan", str(path))
    assert code == 0
    assert out.startswith("target: feat-x\n")


def test_plan_without_target_on_a_detached_head_is_a_problem(run, tmp_path: Path, project: Path) -> None:
    git(project, "checkout", "-q", "--detach")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"lanes": [lane("a", ["src/a.py"])]}), encoding="utf-8")
    code, out, err = run("plan", str(path))
    assert code == 1 and out == ""
    assert err.startswith("problem: ") and "detached" in err


def test_plan_overlap_is_one_problem_line_and_writes_nothing(plan, project: Path) -> None:
    code, out, err = plan([lane("task1", ["src/a.py"], wave=1), lane("task2", ["src/"], wave=1)])
    assert code == 1 and out == ""
    assert err == "problem: overlap: wave 1 lanes task1, task2 share src/a.py\n"
    assert not (project / ".claude" / "state" / "harness" / "parallel2").exists()


def test_plan_packs_overlapping_lanes_into_later_waves(plan, project: Path) -> None:
    code, out, _ = plan([lane("task1", ["src/a.py"]), lane("task2", ["src/a.py"])])
    assert code == 0
    assert "wave 2: task2 (implement, haiku)" in out


def test_plan_rejects_unreadable_json(run, tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text("{nope", encoding="utf-8")
    code, _, err = run("plan", str(path))
    assert code == 1 and err.startswith("problem: ")


def test_plan_refuses_an_unfinished_run_unless_replaced(plan, project: Path) -> None:
    plan([lane("task1", ["src/a.py"])])
    code, out, err = plan([lane("task2", ["src/b.py"])])
    assert code == 1 and out == "" and "task1" in err and "--replace" in err
    code, _, err = plan([lane("task2", ["src/b.py"])], "--replace")
    assert (code, err) == (0, "")
    assert [i["id"] for i in state(project)["lanes"]] == ["task2"]


def test_plan_replace_is_refused_while_a_lane_has_a_worktree(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/a.py"])])
    run("setup")
    code, out, err = plan([lane("task2", ["src/b.py"])], "--replace")
    assert code == 1 and out == "" and "task1" in err and "cleanup --all" in err
    assert [i["id"] for i in state(project)["lanes"]] == ["task1"]
    assert run("cleanup", "--all")[0] == 0
    code, _, err = plan([lane("task2", ["src/b.py"])], "--replace")
    assert (code, err) == (0, "")


# --- setup ------------------------------------------------------------------------------------------------

def test_setup_creates_a_worktree_per_implement_lane_at_head(plan, run, project, tmp_path: Path) -> None:
    plan([lane("task1", ["src/a.py"]), lane("task2", ["src/b.py"]), lane("rev", [], kind="review")])
    head = git(project, "rev-parse", "HEAD")
    code, out, err = run("setup")
    assert (code, err) == (0, "")
    trees = tmp_path / "trees"
    for lane_id in ("task1", "task2"):
        tree = trees / f"p2-{lane_id}"
        assert git(tree, "rev-parse", "HEAD") == head
        assert git(tree, "branch", "--show-current") == f"p2/{lane_id}"
        item = lane_state(project, lane_id)
        assert (item["status"], item["branch"], item["base_sha"]) == ("dispatched", f"p2/{lane_id}", head)
        assert Path(item["worktree"]).resolve() == tree.resolve()
    rows = [line for line in out.splitlines() if line.startswith("lane=")]
    assert [row.split(" ")[0] for row in rows] == ["lane=task1", "lane=task2", "lane=rev"]
    assert rows[0].startswith("lane=task1 model=haiku kind=implement worktree=")
    assert rows[2] == "lane=rev model=haiku kind=review worktree=-"
    assert out.count("Brief: ") == 3
    assert lane_state(project, "rev")["worktree"] is None


def test_setup_writes_a_brief_per_lane(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/a.py", "tests/"], task="fix a"), lane("rev", [], kind="review")])
    run("setup")
    briefs = project / ".claude" / "state" / "harness" / "parallel2" / "feat-x"
    text = (briefs / "task1.md").read_text(encoding="utf-8")
    assert text.startswith("## Pre-Authorized Tools\n- Read\n- Edit\n- Bash(pytest *)\n")
    assert "Working directory: " in text and "p2-task1" in text
    assert "- tests/" in text and "Commit in the worktree branch p2/task1." in text
    assert "Task: fix a" in text
    review = (briefs / "rev.md").read_text(encoding="utf-8")
    assert f"Working directory: {project.as_posix()}" in review
    assert "read-only lane: no edits, no commits" in review


def test_setup_defaults_to_the_lowest_planned_wave(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/a.py"]), lane("task2", ["src/a.py"])])
    run("setup")
    assert lane_state(project, "task1")["status"] == "dispatched"
    assert lane_state(project, "task2")["status"] == "planned"
    code, out, _ = run("setup")
    assert code == 0 and "lane=task2" in out
    assert lane_state(project, "task2")["status"] == "dispatched"


def test_setup_picks_the_first_free_worktree_path(plan, run, project: Path, tmp_path: Path) -> None:
    (tmp_path / "trees" / "p2-task1").mkdir(parents=True)
    plan([lane("task1", ["src/a.py"])])
    code, _, err = run("setup")
    assert code == 0, err
    assert Path(lane_state(project, "task1")["worktree"]).name == "p2-task1-2"


def test_setup_existing_branch_creates_nothing_for_any_lane(plan, run, project: Path, tmp_path: Path) -> None:
    git(project, "branch", "p2/task2")
    plan([lane("task1", ["src/a.py"]), lane("task2", ["src/b.py"])])
    code, out, err = run("setup")
    assert code == 1 and out == ""
    assert "p2/task2" in err and err.count("problem:") == 1
    assert not (tmp_path / "trees").exists()
    assert lane_state(project, "task1")["status"] == "planned"


def test_setup_pending_overlap_is_a_problem_and_creates_nothing(plan, run, project, tmp_path: Path) -> None:
    (project / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
    (project / "tests").mkdir(exist_ok=True)
    (project / "tests" / "new_test.py").write_text("x\n", encoding="utf-8")
    plan([lane("task1", ["src/a.py", "tests/"])])
    code, out, err = run("setup")
    assert code == 1 and out == ""
    assert "src/a.py" in err and "tests/new_test.py" in err
    assert not (tmp_path / "trees").exists()


def test_setup_notes_pending_paths_outside_the_lanes(plan, run, project: Path) -> None:
    (project / "docs" / "guide.md").write_text("changed\n", encoding="utf-8")
    plan([lane("task1", ["src/a.py"])])
    code, out, _ = run("setup")
    assert code == 0
    assert ("note: 1 pending paths in the checkout are not in the lanes' base; "
            "commit them first if a lane reads them") in out.splitlines()


def test_setup_does_not_count_its_own_state_files_as_pending(plan, run) -> None:
    plan([lane("task1", ["src/a.py"])])
    _, out, _ = run("setup")
    assert "note:" not in out


def test_setup_needs_the_target_checked_out(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/a.py"])])
    git(project, "checkout", "-q", "main")
    code, _, err = run("--target", "feat-x", "setup")
    assert code == 1 and "feat-x" in err and "main" in err
    code, _, err = run("setup")
    assert code == 1 and "no parallel2 run for main" in err


# --- probe ------------------------------------------------------------------------------------------------

def test_probe_prints_a_prompt_per_profile_inside_the_first_lane_worktree(plan, run, project: Path) -> None:
    plan([
        lane("task1", ["tests/*.py", "src/a.py"]),
        lane("task2", ["src/b.py"], tools=["Read"], model="sonnet"),
    ])
    run("setup")
    code, out, err = run("probe")
    assert (code, err) == (0, "")
    assert "probe=P1 model=haiku" in out and "probe=P2 model=sonnet" in out
    tree = Path(lane_state(project, "task1")["worktree"]).as_posix()
    assert f"Working directory: {tree}" in out
    assert "Read the first 5 lines of src/a.py" in out
    assert "pytest --version" in out
    assert out.count("For each action report SUCCESS or BLOCKED") == 2


def test_probe_falls_back_to_the_readme(plan, run) -> None:
    plan([lane("task1", ["src/new_file.py"], tools=["Read"])])
    run("setup")
    _, out, _ = run("probe")
    assert "Read the first 5 lines of README.md" in out


def test_probe_before_setup_is_a_problem(plan, run) -> None:
    plan([lane("task1", ["src/a.py"])])
    code, out, err = run("probe")
    assert code == 1 and out == "" and "setup" in err


# --- stage ------------------------------------------------------------------------------------------------

def lane_tree(project: Path, lane_id: str) -> Path:
    return Path(lane_state(project, lane_id)["worktree"])


def test_stage_applies_modify_and_rename_to_the_index(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/"])])
    run("setup")
    head = git(project, "rev-parse", "HEAD")
    tree = lane_tree(project, "task1")
    git(tree, "mv", "src/old.py", "src/renamed.py")
    commit_in(tree, {"src/b.py": "b = 2\n"})
    code, out, err = run("stage", "task1")
    assert (code, err) == (0, "")
    assert git(project, "rev-parse", "HEAD") == head
    staged = git(project, "diff", "--cached", "--name-status", "-M").splitlines()
    assert sorted(staged) == ["M\tsrc/b.py", "R100\tsrc/old.py\tsrc/renamed.py"]
    assert out.splitlines() == [
        "M src/b.py", "R src/old.py -> src/renamed.py", "next: git diff --cached", "still dispatched: none",
    ]
    item = lane_state(project, "task1")
    assert item["status"] == "staged"
    assert sorted(item["staged"]) == ["src/b.py", "src/old.py", "src/renamed.py"]
    assert (project / "src" / "renamed.py").read_text(encoding="utf-8") == "old = 1\n"
    assert not (project / "src" / "old.py").exists()


def test_stage_lists_other_dispatched_lanes(two_lanes, run) -> None:
    commit_in(lane_tree(two_lanes, "task2"), {"src/b.py": "b = 2\n"})
    code, out, _ = run("stage", "task2")
    assert code == 0
    assert out.splitlines()[-2:] == ["next: git diff --cached", "still dispatched: task1"]


def test_stage_refuses_undeclared_paths_unless_included(two_lanes, run) -> None:
    project = two_lanes
    commit_in(lane_tree(project, "task2"), {"src/b.py": "b = 2\n", "docs/extra.md": "x\n"})
    code, out, err = run("stage", "task2")
    assert (code, out) == (1, "")
    assert err == "problem: lane task2 changed paths outside its files: docs/extra.md\n"
    assert git(project, "diff", "--cached", "--name-only") == ""
    code, _, err = run("stage", "task2", "--include-undeclared")
    assert (code, err) == (0, "")
    staged = git(project, "diff", "--cached", "--name-only").splitlines()
    assert sorted(staged) == ["docs/extra.md", "src/b.py"]


def test_stage_applies_adds_and_deletes(two_lanes, run) -> None:
    project = two_lanes
    tree = lane_tree(project, "task1")
    commit_in(tree, {"tests/test_new.py": "x\n", "tests/test_a.py": None, "src/a.py": "a = 9\n"})
    code, out, err = run("stage", "task1")
    assert (code, err) == (0, "")
    staged = git(project, "diff", "--cached", "--name-status").splitlines()
    assert sorted(staged) == ["A\ttests/test_new.py", "D\ttests/test_a.py", "M\tsrc/a.py"]
    assert not (project / "tests" / "test_a.py").exists()
    assert (project / "tests" / "test_new.py").is_file()


def test_stage_keeps_target_commits_made_after_setup(two_lanes, run) -> None:
    project = two_lanes
    old = git(project, "rev-parse", "HEAD")
    commit_in(lane_tree(project, "task1"), {"src/a.py": "a = 2\n"})
    commit_in(project, {"docs/guide.md": "moved\n"}, "move target")
    new = git(project, "rev-parse", "HEAD")
    code, out, err = run("stage", "task1")
    assert (code, err) == (0, "")
    note = f"note: target moved from {old[:7]} to {new[:7]} since setup; merged three-way"
    assert out.splitlines()[0] == note
    assert git(project, "diff", "--cached", "--name-only") == "src/a.py"
    assert (project / "docs" / "guide.md").read_text(encoding="utf-8") == "moved\n"


def test_stage_merges_a_file_both_sides_changed(plan, run, project: Path) -> None:
    lines = [f"line {n}\n" for n in range(1, 8)]
    commit_in(project, {"src/m.py": "".join(lines)}, "base m")
    plan([lane("task1", ["src/"])])
    run("setup")
    commit_in(lane_tree(project, "task1"), {"src/m.py": "".join(["lane 1\n", *lines[1:]])})
    commit_in(project, {"src/m.py": "".join([*lines[:-1], "target 7\n"])}, "target edit")
    code, _, err = run("stage", "task1")
    assert (code, err) == (0, "")
    staged = git(project, "show", ":src/m.py")
    assert staged.splitlines()[0] == "lane 1" and staged.splitlines()[-1] == "target 7"


def test_stage_reports_conflicts_and_records_the_lane_staged(two_lanes, run) -> None:
    project = two_lanes
    commit_in(lane_tree(project, "task1"), {"src/a.py": "a = 2\n"})
    commit_in(project, {"src/a.py": "a = 3\n"}, "conflicting target edit")
    code, _, err = run("stage", "task1")
    assert code == 1
    assert err == ("problem: three-way merge left conflicts in src/a.py; "
                   "resolve the markers and git add them\n")
    assert "<<<<<<<" in (project / "src" / "a.py").read_text(encoding="utf-8")
    assert lane_state(project, "task1")["status"] == "staged"


def test_stage_ignores_a_leftover_probe_file(two_lanes, run) -> None:
    project = two_lanes
    tree = lane_tree(project, "task1")
    commit_in(tree, {"src/a.py": "a = 2\n"})
    (tree / ".p2_probe").write_text("probe-edited", encoding="utf-8")
    code, _, err = run("stage", "task1")
    assert (code, err) == (0, "")
    assert git(project, "diff", "--cached", "--name-only") == "src/a.py"
    assert not (tree / ".p2_probe").exists()


def test_cleanup_removes_a_lane_with_a_leftover_probe_file(two_lanes, run, tmp_path: Path) -> None:
    project = two_lanes
    tree = lane_tree(project, "task1")
    commit_in(tree, {"src/a.py": "a = 2\n"})
    assert run("stage", "task1")[0] == 0
    (tree / ".p2_probe").write_text("probe-edited", encoding="utf-8")
    code, out, err = run("cleanup")
    assert (code, err) == (0, "")
    assert out.splitlines() == ["removed task1 (p2/task1)"]
    assert not (tmp_path / "trees" / "p2-task1").exists()


def test_stage_refuses_a_dirty_lane_worktree(two_lanes, run) -> None:
    project = two_lanes
    tree = lane_tree(project, "task1")
    commit_in(tree, {"src/a.py": "a = 2\n"})
    (tree / "src" / "a.py").write_text("a = 3\n", encoding="utf-8")
    code, _, err = run("stage", "task1")
    assert code == 1 and "task1" in err and "commit" in err
    assert git(project, "diff", "--cached", "--name-only") == ""
    assert lane_state(project, "task1")["status"] == "dispatched"


def test_stage_refuses_a_lane_without_commits(two_lanes, run) -> None:
    code, _, err = run("stage", "task1")
    assert (code, err) == (1, "problem: lane task1 has no commits\n")


def test_stage_refuses_pending_edits_to_changed_paths(two_lanes, run) -> None:
    project = two_lanes
    commit_in(lane_tree(project, "task1"), {"src/a.py": "a = 2\n", "tests/test_x.py": "x\n"})
    (project / "src" / "a.py").write_text("mine\n", encoding="utf-8")
    (project / "tests" / "test_x.py").write_text("untracked mine\n", encoding="utf-8")
    code, _, err = run("stage", "task1")
    assert code == 1 and "src/a.py" in err and "tests/test_x.py" in err
    assert (project / "src" / "a.py").read_text(encoding="utf-8") == "mine\n"


def test_stage_accepts_only_dispatched_implement_lanes(plan, run) -> None:
    plan([lane("task1", ["src/a.py"]), lane("rev", [], kind="review")])
    code, _, err = run("stage", "task1")
    assert code == 1 and "dispatched" in err
    run("setup")
    code, _, err = run("stage", "rev")
    assert code == 1 and "implement" in err
    code, _, err = run("stage", "ghost")
    assert code == 1 and "ghost" in err


def test_stage_keeps_paths_with_glob_characters_literal(two_lanes, run) -> None:
    project = two_lanes
    commit_in(lane_tree(project, "task1"), {"tests/test_[1].py": "x\n", "tests/test_2.py": "y\n"})
    code, _, err = run("stage", "task1")
    assert (code, err) == (0, "")
    staged = git(project, "diff", "--cached", "--name-only").splitlines()
    assert sorted(staged) == ["tests/test_2.py", "tests/test_[1].py"]


# --- status -----------------------------------------------------------------------------------------------

def test_status_lists_each_lane(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/a.py"]), lane("rev", [], kind="review")])
    code, out, _ = run("status")
    assert code == 0
    assert out.splitlines() == ["task1 1 implement planned - - -", "rev 1 review planned - - -"]
    run("setup")
    _, out, _ = run("status")
    first = out.splitlines()[0].split(" ")
    assert first[:5] == ["task1", "1", "implement", "dispatched", "p2/task1"]
    assert Path(first[5]).name == "p2-task1"


def test_status_without_a_run(run) -> None:
    assert run("status") == (0, "no parallel2 run for feat-x\n", "")


# --- cleanup ----------------------------------------------------------------------------------------------

def branches(project: Path) -> List[str]:
    return git(project, "branch", "--format=%(refname:short)").splitlines()


def test_cleanup_removes_staged_lanes_only_and_keeps_the_rest(two_lanes, run, tmp_path: Path) -> None:
    project = two_lanes
    commit_in(lane_tree(project, "task1"), {"src/a.py": "a = 2\n"})
    run("stage", "task1")
    code, out, err = run("cleanup")
    assert (code, err) == (0, "")
    assert out.splitlines() == ["removed task1 (p2/task1)"]
    assert not (tmp_path / "trees" / "p2-task1").exists()
    assert (tmp_path / "trees" / "p2-task2").is_dir()
    assert "p2/task1" not in branches(project) and "p2/task2" in branches(project)
    assert lane_state(project, "task1")["status"] == "cleaned"
    assert lane_state(project, "task2")["status"] == "dispatched"


def test_cleanup_all_deletes_state_and_briefs(two_lanes, run, tmp_path: Path) -> None:
    project = two_lanes
    code, out, err = run("cleanup", "--all")
    assert (code, err) == (0, "")
    assert out.splitlines() == ["removed task1 (p2/task1)", "removed task2 (p2/task2)"]
    folder = project / ".claude" / "state" / "harness" / "parallel2"
    assert not (folder / "feat-x.json").exists()
    assert not (folder / "feat-x").exists()
    assert [b for b in branches(project) if b.startswith("p2/")] == []


def test_cleanup_lane_selects_by_id(two_lanes, run, tmp_path: Path) -> None:
    project = two_lanes
    code, out, _ = run("cleanup", "--lane", "task2")
    assert code == 0 and out.splitlines() == ["removed task2 (p2/task2)"]
    assert lane_state(project, "task1")["status"] == "dispatched"
    code, _, err = run("cleanup", "--lane", "ghost")
    assert code == 1 and "ghost" in err


def test_cleanup_failure_stays_recorded_and_others_continue(two_lanes, run, tmp_path: Path) -> None:
    project = two_lanes
    (lane_tree(project, "task1") / "src" / "a.py").write_text("dirty\n", encoding="utf-8")
    code, out, err = run("cleanup", "--all")
    assert code == 1
    assert out.splitlines() == ["removed task2 (p2/task2)"]
    assert err.startswith("problem: ") and "task1" in err
    assert lane_state(project, "task1")["status"] == "dispatched"
    assert "p2/task1" in branches(project)
    assert (tmp_path / "trees" / "p2-task1").is_dir()


def test_cleanup_keeps_the_state_while_a_later_wave_is_planned(plan, run, project: Path) -> None:
    plan([lane("task1", ["src/a.py"]), lane("task2", ["src/a.py"])])
    run("setup")
    code, out, _ = run("cleanup", "--all")
    assert code == 0
    assert out.splitlines() == ["removed task1 (p2/task1)"]
    assert lane_state(project, "task1")["status"] == "cleaned"
    assert lane_state(project, "task2")["status"] == "planned"


def test_cleanup_without_a_run_or_staged_lane(run, plan, project: Path) -> None:
    assert run("cleanup") == (0, "no parallel2 run for feat-x\n", "")
    plan([lane("task1", ["src/a.py"])])
    assert run("cleanup") == (0, "nothing to clean up\n", "")


def test_cleanup_deletes_the_state_of_a_read_only_run(plan, run, project: Path) -> None:
    plan([lane("rev", [], kind="review")])
    run("setup")
    assert run("cleanup") == (0, "nothing to clean up\n", "")
    folder = project / ".claude" / "state" / "harness" / "parallel2"
    assert not (folder / "feat-x.json").exists()
    assert not (folder / "feat-x").exists()
    code, _, err = plan([lane("task1", ["src/a.py"])])
    assert (code, err) == (0, "")
