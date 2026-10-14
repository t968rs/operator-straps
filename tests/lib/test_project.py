"""Contract tests for harness_lib.project: project root, plugin root, schema resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import git
from harness_lib.config import load_config
from harness_lib.project import main_worktree, plugin_root, project_root, schema_path


def test_project_root_from_subdirectory(make_project) -> None:
    root = make_project(files={"a/b/c.txt": "x"})
    assert project_root(root / "a" / "b") == root.resolve()


def test_project_root_inside_linked_worktree(make_project, tmp_path: Path) -> None:
    root = make_project()
    wt = tmp_path / "wt"
    git(root, "worktree", "add", "-q", "--detach", str(wt))
    assert project_root(wt) == wt.resolve()


def test_main_worktree_of_main_checkout_is_itself(make_project) -> None:
    root = make_project(files={"a/x.txt": "x"})
    assert main_worktree(root / "a") == root.resolve()


def test_main_worktree_from_linked_worktree(make_project, tmp_path: Path) -> None:
    root = make_project()
    wt = tmp_path / "wt"
    git(root, "worktree", "add", "-q", "--detach", str(wt))
    assert main_worktree(wt) == root.resolve()


def test_main_worktree_outside_git_is_start(tmp_path: Path) -> None:
    assert main_worktree(tmp_path) == tmp_path.resolve()


def test_project_root_defaults_to_cwd(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_project(files={"sub/x.txt": "x"})
    monkeypatch.chdir(root / "sub")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert project_root() == root.resolve()


def test_project_root_outside_git_uses_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loose = tmp_path / "loose"
    proj = tmp_path / "proj"
    loose.mkdir()
    proj.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    assert project_root(loose) == proj.resolve()


def test_plugin_root_is_the_harness_plugin() -> None:
    assert (plugin_root() / ".claude-plugin" / "plugin.json").is_file()


def test_schema_path_prefers_project_pinned_copy(make_project) -> None:
    root = make_project(files={".claude/agent-schemas/PR_REVIEW.schema.json": "{}"})
    cfg = load_config(root)
    pinned = root / ".claude" / "agent-schemas" / "PR_REVIEW.schema.json"
    assert schema_path("PR_REVIEW.schema.json", cfg) == pinned


def test_schema_path_falls_back_to_plugin(make_project) -> None:
    cfg = load_config(make_project())
    assert schema_path("PR_REVIEW.schema.json", cfg) == plugin_root() / "schemas" / "PR_REVIEW.schema.json"
