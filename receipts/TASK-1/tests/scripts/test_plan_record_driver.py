"""``plan.py`` records sealed, tree-referenced item records and verifies them on demand.

Each test gets a project on branch ``feat-x`` cut from ``main`` (the layout of ``_plan_driver_helpers``). A
record names the tree that was tested and the commit when there was one; ``check`` never compares either with
HEAD, so an amend, a squash, a staged attach or a commit unreachable from HEAD leaves the plan valid.
``verify`` reruns the COMPLETE items' tests at HEAD and writes nothing. ``harness_lib.plan_record`` decides
every record rule these tests drive.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List

import pytest
from conftest import git

from harness_lib import plan_doc as pd
from harness_lib.plan_enums import OutcomeKind, RecordScheme, RecordSource
from harness_lib.plan_models import ItemRecord

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import (MUL_TEST, PLANS, SUB_TEST, Run, plan_file, read_plan, trees,  # noqa: E402
                                  write_op, write_plan)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
sealed_first_freeze = helpers.sealed_first_freeze
WALK_ROOTS = ()  # walks only a make_project repo and tmp_path/trees
LEGACY_REFS = ["a" * 40, "tree " + "b" * 40]


@pytest.fixture(autouse=True)
def _sealed_first(sealed_first_freeze: None) -> None:
    """Every test here runs with a first freeze storing the sealed scheme (D3)."""


def item_record(root: Path, index: int = 0) -> ItemRecord:
    return ItemRecord.model_validate(read_plan(root)["items"][index]["record"])


def _item(item_id: str, name: str, deps: List[str]) -> Dict[str, Any]:
    return {"id": item_id, "title": f"Add {name}", "action": f"Add {name} beside add.", "status": "PENDING",
            "evidence": "not started", "files": ["src/calc.py", f"tests/test_calc_{name}.py"],
            "dependencies": deps or None,
            "anchors": [{"at": "src/calc.py:1", "expect": "def add(a, b):"}],
            "tests": [{"node": f"tests/test_calc_{name}.py::test_{name}", "red": "ImportError"}]}


def fill(run: Run, project: Path, *, two: bool = False, chained: bool = False) -> None:
    """``new``, the planned test files and TASK-1 (sub), plus TASK-2 (mul) when ``two``; then freeze."""
    code, _, err = run("new", "Add operators", "--spec", "docs/spec.md")
    assert code == 0, err
    planned = project / PLANS / "0001" / "tests" / "tests"
    planned.mkdir(parents=True, exist_ok=True)
    (planned / "test_calc_sub.py").write_text(SUB_TEST, encoding="utf-8")
    (planned / "test_calc_mul.py").write_text(MUL_TEST, encoding="utf-8")
    plan = read_plan(project)
    plan["items"] = [_item("TASK-1", "sub", [])]
    if two:
        plan["items"].append(_item("TASK-2", "mul", ["TASK-1"] if chained else []))
    write_plan(project, plan)
    code, _, err = run("freeze", "1")
    assert code == 0, err


def commit_op(root: Path, name: str) -> str:
    write_op(root, name)
    git(root, "add", "src/calc.py", f"tests/test_calc_{name}.py")
    git(root, "commit", "-q", "-m", f"add {name}")
    return git(root, "rev-parse", "HEAD")


def hand_set_legacy(project: Path, index: int = 0) -> None:
    """Set an item to the old ``record --sha`` shape by hand: COMPLETE with pasted references, no record."""
    plan = read_plan(project)
    plan["items"][index].update(status="COMPLETE", evidence="commit aaaaaaa: 1 test node(s) passed",
                                verification_references=list(LEGACY_REFS))
    write_plan(project, plan)


def old_driver_freeze(project: Path) -> None:
    """Make the plan look frozen by the driver before the record scheme and the ledger: an in-file stamp
    with no ``records``, the old digest."""
    helpers.as_legacy(project)


def ref_names(root: Path) -> List[str]:
    """Every ref name of the repository, sorted."""
    return sorted(git(root, "for-each-ref", "--format=%(refname)").splitlines())


# --- the record -------------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_record_sha_writes_a_sealed_record_with_tree_and_commit(run: Run, project: Path) -> None:
    fill(run, project)
    assert helpers.stamp(project).records == RecordScheme.sealed
    sha = commit_op(project, "sub")
    code, out, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 0, err
    record = item_record(project)
    assert record.outcome.kind == OutcomeKind.complete
    assert record.outcome.provenance.source == RecordSource.commit
    assert record.outcome.provenance.commit == sha
    assert record.outcome.provenance.tree == git(project, "rev-parse", f"{sha}^{{tree}}")
    assert record.outcome.tests.nodes == ["tests/test_calc_sub.py::test_sub"]
    assert not read_plan(project)["items"][0].get("verification_references")
    assert out.startswith("record [done] | TASK-1 COMPLETE") and run("check", "1")[0] == 0


def test_check_flags_a_hand_set_status(run: Run, project: Path) -> None:
    fill(run, project)
    plan = read_plan(project)
    plan["items"][0]["status"] = "COMPLETE"
    write_plan(project, plan)
    code, _, err = run("check", "1")
    assert code == 1
    assert "problem: TASK-1 is COMPLETE without a sealed record; run plan.py record 0001 TASK-1" in err


def test_check_flags_a_hand_edit_of_the_evidence(run: Run, project: Path) -> None:
    fill(run, project)
    run("record", "1", "TASK-1", "--blocked", "waits on the operator module")
    plan = read_plan(project)
    plan["items"][0]["evidence"] = "no longer blocked"
    write_plan(project, plan)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: TASK-1 record does not match its seal" in err


def test_lanes_refuses_a_hand_set_status(run: Run, project: Path) -> None:
    fill(run, project, two=True, chained=True)
    plan = read_plan(project)
    plan["items"][0]["status"] = "COMPLETE"
    write_plan(project, plan)
    code, _, err = run("lanes", "1", "--target", "feat-x")
    assert code == 1 and "problem: TASK-1 is COMPLETE without a sealed record" in err


# --- history shape no longer matters ----------------------------------------------------------------------

@pytest.mark.cross_os
def test_an_amend_of_the_recorded_commit_keeps_check_green(run: Run, project: Path) -> None:
    fill(run, project)
    sha = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", sha)[0] == 0
    git(project, "commit", "-q", "--amend", "-m", "add sub, reworded")
    assert git(project, "rev-parse", "HEAD") != sha
    code, _, err = run("check", "1")
    assert code == 0, err


@pytest.mark.cross_os
def test_a_squash_of_two_recorded_commits_keeps_check_green(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    start = git(project, "rev-parse", "HEAD")
    first = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", first)[0] == 0
    second = commit_op(project, "mul")
    assert run("record", "1", "TASK-2", "--sha", second)[0] == 0
    git(project, "reset", "-q", "--soft", start)
    git(project, "commit", "-q", "-m", "add sub and mul")
    code, _, err = run("check", "1")
    assert code == 0, err


@pytest.mark.cross_os
def test_a_record_made_in_a_worktree_survives_a_staged_attach(run: Run, project: Path,
                                                              tmp_path: Path) -> None:
    fill(run, project)
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "plan 0001")
    worktree = tmp_path / "lane"
    git(project, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    lane = commit_op(worktree, "sub")
    code, _, err = run("record", "1", "TASK-1", "--sha", lane, repo=worktree)
    assert code == 0, err
    git(worktree, "commit", "-qam", "record TASK-1")
    git(project, "restore", "--source", git(worktree, "rev-parse", "HEAD"), "--staged", "--worktree", ".")
    git(project, "commit", "-q", "-m", "attach lane")
    assert git(project, "rev-parse", "HEAD") != git(worktree, "rev-parse", "HEAD")
    code, _, err = run("check", "1")
    assert code == 0, err


@pytest.mark.cross_os
def test_record_sha_accepts_a_commit_unreachable_from_head(run: Run, project: Path) -> None:
    fill(run, project)
    git(project, "checkout", "-q", "-b", "side")
    side = commit_op(project, "sub")
    git(project, "checkout", "-q", "feat-x")
    paths = ["src/calc.py", "tests/test_calc_sub.py"]
    git(project, "restore", "--source", side, "--staged", "--worktree", *paths)
    git(project, "commit", "-q", "-m", "take sub from side")
    code, _, err = run("record", "1", "TASK-1", "--sha", side)
    assert code == 0, err
    assert item_record(project).outcome.provenance.commit == side


# --- record --staged --------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_record_staged_records_the_index_and_survives_the_commit(run: Run, project: Path,
                                                                 tmp_path: Path) -> None:
    fill(run, project)
    refs = ref_names(project)
    write_op(project, "sub")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    index_tree = git(project, "write-tree")
    code, out, err = run("record", "1", "TASK-1", "--staged")
    assert code == 0, err
    provenance = item_record(project).outcome.provenance
    assert provenance.source == RecordSource.staged and provenance.tree == index_tree
    assert provenance.commit is None
    stem = pd.load_plan(plan_file(project)).ledger
    assert ref_names(project) == sorted([*refs, f"refs/tags/receipt/{stem}/TASK-1-tree"])
    assert trees(tmp_path) == []
    git(project, "commit", "-q", "-m", "add sub")
    code, _, err = run("check", "1")
    assert code == 0, err


def test_record_staged_refuses_unstaged_item_files(run: Run, project: Path) -> None:
    fill(run, project)
    write_op(project, "sub")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8") + "\n# unstaged\n", encoding="utf-8")
    code, _, err = run("record", "1", "TASK-1", "--staged")
    assert code == 1 and "problem: TASK-1 files differ from the index" in err and "src/calc.py" in err
    assert read_plan(project)["items"][0]["status"] == "PENDING"


@pytest.mark.cross_os
def test_record_staged_runs_the_tests_on_the_index(run: Run, project: Path, tmp_path: Path) -> None:
    fill(run, project)
    (project / "tests" / "test_calc_sub.py").write_text(SUB_TEST, encoding="utf-8")
    calc = project / "src" / "calc.py"
    body = "\n\ndef sub(a, b):\n    from src.helper import minus\n    return minus(a, b)\n"
    calc.write_text(calc.read_text(encoding="utf-8") + body, encoding="utf-8")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    (project / "src" / "helper.py").write_text("def minus(a, b):\n    return a - b\n", encoding="utf-8")
    code, _, err = run("record", "1", "TASK-1", "--staged")
    assert code == 1 and "problem: TASK-1 tests failed at the index" in err
    assert read_plan(project)["items"][0]["status"] == "PENDING" and trees(tmp_path) == []


def test_record_refuses_both_a_sha_and_staged(run: Run, project: Path,
                                              capsys: pytest.CaptureFixture) -> None:
    fill(run, project)
    with pytest.raises(SystemExit):
        run("record", "1", "TASK-1", "--staged", "--sha", "HEAD")
    assert "not allowed with argument" in capsys.readouterr().err


# --- recording again --------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_a_complete_item_records_again(run: Run, project: Path) -> None:
    fill(run, project)
    first = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", first)[0] == 0
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8") + "\n# tidy\n", encoding="utf-8")
    git(project, "commit", "-qam", "tidy")
    second = git(project, "rev-parse", "HEAD")
    code, _, err = run("record", "1", "TASK-1", "--sha", second)
    assert code == 0, err
    assert item_record(project).outcome.provenance.commit == second


@pytest.mark.cross_os
def test_record_runs_while_another_item_has_a_broken_seal(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    first = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", first)[0] == 0
    plan = read_plan(project)
    plan["items"][0]["evidence"] = "edited by hand"
    write_plan(project, plan)
    second = commit_op(project, "mul")
    code, _, err = run("record", "1", "TASK-2", "--sha", second)
    assert code == 0, err
    code, _, err = run("record", "1", "TASK-1", "--sha", second)
    assert code == 0, err
    code, _, err = run("check", "1")
    assert code == 0, err


def test_a_hand_set_complete_dependency_unlocks_nothing(run: Run, project: Path) -> None:
    fill(run, project, two=True, chained=True)
    hand_set_legacy(project)
    commit_op(project, "sub")
    sha = commit_op(project, "mul")
    code, _, err = run("record", "1", "TASK-2", "--sha", sha)
    assert code == 1 and "problem: TASK-2 depends on TASK-1" in err
    assert "run plan.py record 0001 TASK-1" in err


@pytest.mark.cross_os
def test_a_legacy_dependency_unlocks_its_dependent_on_a_legacy_plan(run: Run, project: Path) -> None:
    fill(run, project, two=True, chained=True)
    old_driver_freeze(project)
    hand_set_legacy(project)
    commit_op(project, "sub")
    sha = commit_op(project, "mul")
    code, _, err = run("record", "1", "TASK-2", "--sha", sha)
    assert code == 0, err


@pytest.mark.cross_os
def test_a_refreeze_that_changes_an_item_breaks_only_its_seal(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    first = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", first)[0] == 0
    second = commit_op(project, "mul")
    assert run("record", "1", "TASK-2", "--sha", second)[0] == 0
    plan = read_plan(project)
    plan["items"][0]["files"].append("docs/spec.md")
    write_plan(project, plan)
    code, out, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    assert "re-record after refreeze: TASK-1" in out and "TASK-2" not in out.split("\n", 1)[1]
    code, _, err = run("check", "1")
    assert code == 1 and "problem: TASK-1 record does not match its seal" in err and "TASK-2" not in err
    assert run("record", "1", "TASK-1", "--sha", second)[0] == 0
    code, _, err = run("check", "1")
    assert code == 0, err


def test_a_refreeze_refuses_a_status_without_a_record(run: Run, project: Path) -> None:
    fill(run, project)
    plan = read_plan(project)
    plan["items"][0]["status"] = "COMPLETE"
    write_plan(project, plan)
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 1 and "problem: TASK-1 is COMPLETE without a sealed record" in err


# --- verify -----------------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_verify_passes_and_writes_nothing(run: Run, project: Path, tmp_path: Path) -> None:
    fill(run, project)
    sha = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", sha)[0] == 0
    before = plan_file(project).read_bytes()
    code, out, err = run("verify", "1")
    assert code == 0, err
    assert out.startswith("verify [ok] | plan 0001") and "TASK-1 pass" in out
    assert plan_file(project).read_bytes() == before and trees(tmp_path) == []


@pytest.mark.cross_os
def test_verify_staged_runs_the_tests_on_the_index(run: Run, project: Path, tmp_path: Path) -> None:
    fill(run, project)
    write_op(project, "sub")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    assert run("record", "1", "TASK-1", "--staged")[0] == 0
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8").replace("a - b", "a + b"), encoding="utf-8")
    refs = git(project, "for-each-ref")
    code, out, err = run("verify", "1", "--staged")
    assert code == 0, err
    assert "at the index" in out and "TASK-1 pass" in out
    assert git(project, "for-each-ref") == refs and trees(tmp_path) == []
    code, _, err = run("verify", "1")
    assert code == 1 and "problem: TASK-1 tests fail at" in err


@pytest.mark.cross_os
def test_verify_reports_every_item_and_check_stays_green(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    first = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", first)[0] == 0
    second = commit_op(project, "mul")
    assert run("record", "1", "TASK-2", "--sha", second)[0] == 0
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8").replace("a - b", "a + b"), encoding="utf-8")
    git(project, "commit", "-qam", "break sub")
    before = plan_file(project).read_bytes()
    code, out, err = run("verify", "1")
    assert code == 1 and "TASK-2 pass" in out
    assert "problem: TASK-1 tests fail at" in err and "run plan.py record 0001 TASK-1 again" in err
    assert plan_file(project).read_bytes() == before
    assert run("check", "1")[0] == 0


# --- legacy plans -----------------------------------------------------------------------------------------

def test_a_legacy_plan_passes_check_without_git(run: Run, project: Path, driver: ModuleType,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """The record rules ``check`` applies run no git; the anchor checks at the base still may."""
    fill(run, project)
    old_driver_freeze(project)
    hand_set_legacy(project)
    rules, real_run, calls = driver.prc.record_lines, subprocess.run, []

    def no_git(argv: Any, *args: Any, **kwargs: Any) -> Any:
        assert "git" not in Path(str(argv[0])).stem, f"the record rules ran {argv}"
        return real_run(argv, *args, **kwargs)

    def guarded(plan: Any) -> List[str]:
        calls.append(plan.plan_id)
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", no_git)
            return rules(plan)

    monkeypatch.setattr(driver.prc, "record_lines", guarded)
    code, _, err = run("check", "1")
    assert code == 0, err
    assert calls == ["0001"]


def test_a_sealed_plan_refuses_a_pasted_legacy_shape(run: Run, project: Path) -> None:
    fill(run, project)
    hand_set_legacy(project)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: TASK-1 is COMPLETE without a sealed record" in err


def test_deleting_the_record_scheme_by_hand_is_a_plan_change(run: Run, project: Path) -> None:
    fill(run, project)
    helpers.drop_ledger_scheme(project)
    hand_set_legacy(project)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: plan changed after freeze" in err
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 1 and "problem: TASK-1 is COMPLETE without a sealed record" in err


def test_a_refreeze_keeps_the_scheme_the_committed_plan_stores(run: Run, project: Path) -> None:
    """Deleting the scheme in an edit that changes a digested field cannot downgrade a committed seal."""
    fill(run, project)
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "plan 0001")
    helpers.drop_ledger_scheme(project)
    plan = read_plan(project)
    plan["items"][0]["action"] = "Add sub beside add, with a changed design."
    write_plan(project, plan)
    hand_set_legacy(project)
    before = plan_file(project).read_bytes()
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 1 and "problem: TASK-1 is COMPLETE without a sealed record" in err
    assert plan_file(project).read_bytes() == before


@pytest.mark.cross_os
def test_a_refreeze_seals_the_scheme_once_no_legacy_item_remains(run: Run, project: Path) -> None:
    fill(run, project)
    old_driver_freeze(project)
    hand_set_legacy(project)
    assert run("freeze", "1", "--refreeze")[0] == 0
    assert helpers.stamp(project).records is None
    sha = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", sha)[0] == 0
    assert run("freeze", "1", "--refreeze")[0] == 0
    assert helpers.stamp(project).records == RecordScheme.sealed
