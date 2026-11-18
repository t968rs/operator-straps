"""Contract tests for harness_lib.project: project root, plugin root, schema resolution, and the bounded
git runner."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import replace
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


_STDIN_PROBE = """\
import sys
sys.path.insert(0, sys.argv[1])
from harness_lib.project import run_git
done = run_git([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"])
print(done.stdout.strip())
"""


def _run_with_open_stdin(script: str, *args: str, wait: float = 20) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in a child whose stdin is a pipe held open (never written, never closed) meanwhile."""
    proc = subprocess.Popen([sys.executable, "-c", script, *args], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        code = proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail(f"child still blocked after {wait}s: run_git passed the open stdin through")
    finally:
        proc.stdin.close()
    return subprocess.CompletedProcess(proc.args, code, proc.stdout.read(), proc.stderr.read())


def test_run_git_child_sees_eof_not_the_callers_stdin() -> None:
    """A child reading stdin gets EOF at once even when the caller's stdin is an open, silent pipe."""
    lib = Path(project_module.__file__).resolve().parents[1]
    done = _run_with_open_stdin(_STDIN_PROBE, str(lib))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "''"


def test_run_git_cuts_off_a_slow_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child that outlives the bound is killed and surfaces as ``TimeoutError``."""
    monkeypatch.setattr(project_module, "_GIT_TIMEOUT_SECONDS", 1)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        run_git([sys.executable, "-c", "import time; time.sleep(30)"])
    assert time.monotonic() - started < 15


def test_run_git_timeout_surfaces_as_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung git becomes an OSError subclass, the failure the hooks already report and skip."""

    def hang(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(project_module.subprocess, "run", hang)
    with pytest.raises(OSError, match="timed out"):
        run_git(["git", "status"])


def _hanging_git_on_path(bin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a ``git`` that never returns first on PATH and shrink the run_git bound to one second."""
    bin_dir.mkdir()
    shim = bin_dir / "git"
    shim.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(project_module, "_GIT_TIMEOUT_SECONDS", 1)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell shim stands in for git")
def test_project_main_worktree_and_origin_head_lookups_survive_a_hung_git(
        make_project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung git is cut off: main_worktree falls back to the start path, the base branch to ``main``,
    and the project-root lookup raises ``TimeoutError`` instead of stalling."""
    root = make_project()
    cfg = replace(load_config(root), base_branch=None)
    _hanging_git_on_path(tmp_path / "bin", monkeypatch)
    started = time.monotonic()
    assert main_worktree(root) == root.resolve()
    assert config_module._origin_head(root) is None
    assert cfg.resolve_base_branch() == "main"
    with pytest.raises(TimeoutError):
        project_root(root)
    assert time.monotonic() - started < 30
