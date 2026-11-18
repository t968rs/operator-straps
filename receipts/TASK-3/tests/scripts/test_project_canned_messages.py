"""Project canned sets (the ``canned_messages`` key) beside the plugin's built-in ``LOOKUP``.

``get_canned_message`` takes the project's sets as ``extra`` and tries them first; ``project_canned_message``
reads them from the active configuration. The callers are tested too: ``branch_commit_msg.py`` capture
prefills a project set's block, and ``merge_commit_msg.py`` prefills its prose.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from harness_lib.canned_messages import get_canned_message, project_canned_message
from harness_lib.config import CannedSet, activate, load_config

WALK_ROOTS = ()  # walks nothing; projects live under tmp_path
REPORT = CannedSet(("offlineTestReport.json",), "Chore(tests): refresh the offline test report")
CONFIG = {"canned_messages": [{"patterns": list(REPORT.patterns), "message": REPORT.message}]}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def branch_script(plugin_root: Path) -> ModuleType:
    return _load(plugin_root / "scripts" / "branch_commit_msg.py", "branch_commit_msg_project_canned")


@pytest.fixture(scope="module")
def merge_script(plugin_root: Path) -> ModuleType:
    path = plugin_root / "skills" / "merge-commit-msg" / "commands" / "merge_commit_msg.py"
    return _load(path, "merge_commit_msg_project_canned")


def test_an_extra_set_gives_its_message() -> None:
    assert get_canned_message(["out/offlineTestReport.json"], extra=[REPORT]) == REPORT.message


def test_without_extra_the_file_has_no_message() -> None:
    assert get_canned_message(["out/offlineTestReport.json"]) is None


def test_an_extra_set_wins_over_the_built_in_one() -> None:
    todo = CannedSet(("RepoToDo.json",), "Chore(todo): refresh the ranked catalog")
    assert get_canned_message(["docs/TODO/RepoToDo.json"], extra=[todo]) == todo.message


def test_a_mix_across_two_sets_has_no_message() -> None:
    assert get_canned_message(["offlineTestReport.json", "docs/TODO/RepoToDo.json"], extra=[REPORT]) is None


def test_the_built_in_sets_still_answer_beside_an_extra() -> None:
    message = get_canned_message(["docs/TODO/RepoToDo.json"], extra=[REPORT])
    assert (message or "").startswith("Chore(todo): ")


def test_the_project_lookup_reads_the_active_config(make_project) -> None:
    activate(load_config(make_project(CONFIG)))
    assert project_canned_message(["out/offlineTestReport.json"]) == REPORT.message


def test_capture_prefills_a_project_set_block(branch_script: ModuleType, make_project) -> None:
    root = make_project(CONFIG)
    activate(load_config(root))
    (root / "offlineTestReport.json").write_text("{}\n", encoding="utf-8")
    payload = branch_script.run_capture_pending(root)
    assert payload["commits"] == {"1": [["offlineTestReport.json"], REPORT.message]}


def test_merge_capture_prefills_a_project_set_prose(merge_script: ModuleType, make_project) -> None:
    activate(load_config(make_project(CONFIG)))
    view = {"title": "Refresh report", "baseRefName": "main", "headRefName": "7-report", "body": "",
            "additions": 1, "deletions": 1, "changedFiles": 1}
    out = merge_script.render(7, view, ["out/offlineTestReport.json"], [], [])
    assert "- Canned message: yes" in out
    assert REPORT.message in out
