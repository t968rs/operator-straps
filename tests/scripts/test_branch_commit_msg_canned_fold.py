"""``build`` folds canned-set paths that appear or vanish after capture (``harness_lib.canned_fold``).

A canned set's files carry a fixed message, so a regenerated file of one (a TODO catalog, a review artifact,
a project set) must not fail ``build`` with ``is in no commit`` or ``matches nothing``. ``fold_canned`` is
tested alone, then through ``run_build``, the caller that runs it before the coverage check.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Sequence, Tuple

import pytest

from conftest import git
from harness_lib.canned_fold import fold_canned
from harness_lib.canned_messages import get_canned_message
from harness_lib.config import activate, load_config

WALK_ROOTS = ()  # walks nothing; the clone lives under tmp_path
TODO = "docs/TODO/RepoToDo.json"
SNAPSHOT = "docs/TODO/Snapshots/TODO_Snapshot_2026_1110.md"
CANNED_TODO = "Chore(todo): refresh TODO catalog, research stubs and snapshot"
REPORT = "offlineTestReport.json"
CANNED_REPORT = "Chore(tests): refresh the offline test report"
DRAFT = "Chore: commit {key}\n\nWhy.\n  - x: y"
Commits = Dict[int, Tuple[List[str], str]]


def _canned(paths: Sequence[str]) -> Optional[str]:
    return get_canned_message(paths)


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> ModuleType:
    """Import branch_commit_msg.py by absolute path."""
    path = plugin_root / "scripts" / "branch_commit_msg.py"
    spec = importlib.util.spec_from_file_location("branch_commit_msg_canned_fold", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clone(make_project, tmp_path: Path, config: Optional[dict] = None) -> Path:
    """Branch ``9999-demo`` of a clone of a project with ``config``, one commit ahead of ``main``."""
    upstream = make_project(config, files={"src/pkg/a.py": "x\n"}, name="upstream")
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(upstream), str(work))
    git(work, "checkout", "-q", "-b", "9999-demo")
    _write(work, "src/pkg/a.py", "changed\n")
    git(work, "commit", "-qam", "wip")
    activate(load_config(work))
    return work


@pytest.fixture()
def clone(make_project, tmp_path: Path) -> Path:
    """Branch ``9999-demo`` of a clone, one commit ahead of ``main`` (``src/pkg/a.py`` changed)."""
    return _clone(make_project, tmp_path)


@pytest.fixture()
def project_clone(make_project, tmp_path: Path) -> Path:
    """As ``clone``, on a project whose ``canned_messages`` key holds the offline test report set."""
    config = {"canned_messages": [{"patterns": [REPORT], "message": CANNED_REPORT}]}
    return _clone(make_project, tmp_path, config)


def _fill(payload: Dict[str, object]) -> Dict[str, object]:
    """Draft every empty message; a canned or carried one stays."""
    blocks = payload["commits"].items()
    commits = {key: [paths, message or DRAFT.format(key=key)] for key, (paths, message) in blocks}
    return {**payload, "commits": commits}


class TestFoldCanned:
    def test_an_appeared_canned_path_gets_a_new_block(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a")}
        folded = fold_canned(commits, {"src/pkg/a.py", TODO}, _canned, pending=False)
        assert folded == {1: (["src/pkg/a.py"], "Feature: a"), 2: ([TODO], CANNED_TODO)}

    def test_an_appeared_canned_path_joins_its_canned_block(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a"), 2: ([TODO], CANNED_TODO)}
        folded = fold_canned(commits, {"src/pkg/a.py", TODO, SNAPSHOT}, _canned, pending=False)
        assert folded[2] == ([TODO, SNAPSHOT], CANNED_TODO)
        assert sorted(folded) == [1, 2]

    def test_two_appeared_paths_of_one_set_share_one_new_block(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a")}
        folded = fold_canned(commits, {"src/pkg/a.py", TODO, SNAPSHOT}, _canned, pending=False)
        assert folded[2] == ([TODO, SNAPSHOT], CANNED_TODO)
        assert sorted(folded) == [1, 2]

    def test_a_vanished_canned_path_drops_and_its_empty_block_goes(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a"), 2: ([TODO], CANNED_TODO)}
        folded = fold_canned(commits, {"src/pkg/a.py"}, _canned, pending=False)
        assert folded == {1: (["src/pkg/a.py"], "Feature: a")}

    def test_a_non_canned_path_is_left_to_the_coverage_check(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py", "src/pkg/gone.py"], "Feature: a")}
        folded = fold_canned(commits, {"src/pkg/a.py", "src/pkg/b.py"}, _canned, pending=False)
        assert folded == commits

    def test_a_pending_document_folds_into_its_one_block(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a")}
        folded = fold_canned(commits, {"src/pkg/a.py", TODO}, _canned, pending=True)
        assert folded == {1: (["src/pkg/a.py", TODO], "Feature: a")}

    def test_it_joins_a_canned_block_whose_message_has_trailing_space(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a"), 2: ([TODO], CANNED_TODO + "\n")}
        folded = fold_canned(commits, {"src/pkg/a.py", TODO, SNAPSHOT}, _canned, pending=False)
        assert folded[2] == ([TODO, SNAPSHOT], CANNED_TODO + "\n")
        assert sorted(folded) == [1, 2]

    def test_a_path_a_glob_entry_stands_for_stays_put(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a"), 2: (["docs/TODO/*.json"], CANNED_TODO)}
        folded = fold_canned(commits, {"src/pkg/a.py", TODO}, _canned, pending=False)
        assert folded == commits

    def test_a_block_with_no_files_survives(self) -> None:
        commits: Commits = {1: ([], "Feature: x"), 2: (["src/pkg/a.py"], "Feature: a")}
        folded = fold_canned(commits, {"src/pkg/a.py"}, _canned, pending=False)
        assert folded == commits

    def test_the_input_is_not_changed(self) -> None:
        commits: Commits = {1: (["src/pkg/a.py"], "Feature: a"), 2: ([TODO], CANNED_TODO)}
        fold_canned(commits, {"src/pkg/a.py", SNAPSHOT}, _canned, pending=False)
        assert commits == {1: (["src/pkg/a.py"], "Feature: a"), 2: ([TODO], CANNED_TODO)}


class TestBuildFolds:
    def test_a_canned_file_written_after_capture_builds(self, script: ModuleType, clone: Path) -> None:
        payload = _fill(script.run_capture(clone, fetch=False))
        _write(clone, TODO)
        _, document = script.run_build(clone, payload)
        assert document.commits[2].files == [TODO]
        assert document.commits[2].header == CANNED_TODO

    def test_it_joins_the_canned_block_capture_made(self, script: ModuleType, clone: Path) -> None:
        _write(clone, TODO)
        payload = _fill(script.run_capture(clone, fetch=False))
        _write(clone, SNAPSHOT)
        _, document = script.run_build(clone, payload)
        assert len(document.commits) == 2
        assert sorted(document.commits[2].files) == sorted([TODO, SNAPSHOT])

    def test_a_canned_file_deleted_after_capture_builds(self, script: ModuleType, clone: Path) -> None:
        _write(clone, TODO)
        payload = _fill(script.run_capture(clone, fetch=False))
        (clone / TODO).unlink()
        _, document = script.run_build(clone, payload)
        assert [entry.files for entry in document.commits.values()] == [["src/pkg/a.py"]]

    def test_a_project_set_file_written_after_capture_builds(
            self, script: ModuleType, project_clone: Path,
    ) -> None:
        payload = _fill(script.run_capture(project_clone, fetch=False))
        _write(project_clone, REPORT)
        _, document = script.run_build(project_clone, payload)
        assert document.commits[2].files == [REPORT]
        assert document.commits[2].header == CANNED_REPORT

    def test_another_file_written_after_capture_still_fails(self, script: ModuleType, clone: Path) -> None:
        payload = _fill(script.run_capture(clone, fetch=False))
        _write(clone, "src/pkg/b.py")
        with pytest.raises(script.BuildError, match="is in no commit"):
            script.run_build(clone, payload)

    def test_a_pending_build_takes_the_canned_file_into_its_block(
            self, script: ModuleType, clone: Path,
    ) -> None:
        _write(clone, "src/pkg/c.py")
        payload = _fill(script.run_capture_pending(clone))
        _write(clone, TODO)
        _, document = script.run_build(clone, payload)
        assert sorted(document.commits) == [1]
        assert sorted(document.commits[1].files) == sorted(["src/pkg/c.py", TODO])
