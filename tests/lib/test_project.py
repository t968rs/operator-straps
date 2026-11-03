"""Contract tests for harness_lib.project: project root, plugin root, schema resolution."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import git
from harness_lib import config as config_module
from harness_lib import project as project_module
from harness_lib.config import load_config
from harness_lib.project import main_worktree, plugin_root, project_root, run_git, schema_path


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


def _recording_run(calls: list):
    def fake_run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 1, "", "")

    return fake_run


def test_run_git_closes_stdin_and_bounds_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """A git child must not inherit the caller's stdin nor wait forever."""
    calls: list = []
    monkeypatch.setattr(project_module.subprocess, "run", _recording_run(calls))
    run_git(["git", "status"])
    assert calls[0]["stdin"] == subprocess.DEVNULL
    assert isinstance(calls[0]["timeout"], (int, float)) and calls[0]["timeout"] > 0


def test_run_git_timeout_surfaces_as_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung git becomes an OSError subclass, the failure the hooks already report and skip."""

    def hang(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(project_module.subprocess, "run", hang)
    with pytest.raises(OSError, match="timed out"):
        run_git(["git", "status"])


@pytest.mark.parametrize("caller", [
    lambda root: project_module._git_toplevel(root),
    lambda root: project_module.main_worktree(root),
    lambda root: config_module._origin_head(root),
])
def test_every_git_lookup_goes_through_run_git(make_project, monkeypatch: pytest.MonkeyPatch, caller) -> None:
    """Project, main-worktree and origin/HEAD lookups all carry the closed stdin and the timeout."""
    root = make_project()
    calls: list = []
    monkeypatch.setattr(project_module.subprocess, "run", _recording_run(calls))
    caller(root)
    assert calls and all(c["stdin"] == subprocess.DEVNULL and c["timeout"] > 0 for c in calls)
