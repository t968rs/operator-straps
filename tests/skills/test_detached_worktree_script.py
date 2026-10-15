"""Behavioral tests for the harness d-w skill command ``commands/new_worktree.py``.

Every test runs against a throwaway origin/clone pair under ``tmp_path``. The clone is the consuming project:
its ``.claude/harness.json`` names ``dev`` and ``main`` as integration branches unless a test says otherwise.
The clone's local ``dev`` is deliberately stale against the origin, so a ``dev`` base proves the script
fetched before cutting.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from conftest import copy_project

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


def _commit(repo: Path, label: str) -> str:
    (repo / f"{label}.txt").write_text(label, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", label)
    return _git(repo, "rev-parse", "HEAD")


def _configure(repo: Path, config: Optional[dict]) -> None:
    """Write (or remove) the project's untracked ``.claude/harness.json``."""
    target = repo / ".claude" / "harness.json"
    if config is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config), encoding="utf-8")


@pytest.fixture(scope="module")
def script_path(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "d-w" / "commands" / "new_worktree.py"


@pytest.fixture(scope="module")
def module(script_path: Path):
    spec = importlib.util.spec_from_file_location("new_worktree", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_repos(parent: Path) -> dict:
    """``origin.git`` and its clone ``work`` under ``parent`` as ``repos`` describes; the three SHAs."""
    origin = parent / "origin.git"
    seed = parent / "seed"
    work = parent / "work"
    _git(parent, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(parent, "init", "-q", "-b", "main", str(seed))
    main_sha = _commit(seed, "a")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main", "main:dev")
    _git(parent, "clone", "-q", str(origin), str(work))
    _git(work, "branch", "-q", "dev", "origin/dev")
    _git(seed, "checkout", "-q", "-b", "dev")
    dev_sha = _commit(seed, "b")
    _git(seed, "push", "-q", "origin", "dev")
    _git(work, "checkout", "-q", "-b", "feature")
    head_sha = _commit(work, "c")
    _configure(work, {"integration_branches": ["dev", "main"]})
    return {"main": main_sha, "dev": dev_sha, "head": head_sha}


@pytest.fixture(scope="module")
def repos_template(tmp_path_factory: pytest.TempPathFactory) -> tuple:
    """The origin and clone built once per module; ``repos`` copies them and never writes here."""
    parent = tmp_path_factory.mktemp("repos_template")
    return parent, _build_repos(parent)


@pytest.fixture()
def repos(repos_template: tuple, tmp_path: Path) -> dict:
    """Origin + clone; origin ``dev`` is one commit ahead of the clone's ``dev``; clone HEAD is a feature.

    Both are copies of the template, with the clone's ``origin`` re-pointed at the copied bare repo.
    """
    template, shas = repos_template
    origin = Path(shutil.copytree(template / "origin.git", tmp_path / "origin.git"))
    work = copy_project(template / "work", tmp_path)
    _git(work, "remote", "set-url", "origin", str(origin))
    return {"work": work, "root": tmp_path / "wts", **shas}


def _run(script_path: Path, repos: dict, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script_path), *args,
           "--repo", str(repos["work"]), "--root", str(repos["root"])]
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **_GIT_ENV})


def _wt_head(path: str) -> tuple:
    wt = Path(path)
    return _git(wt, "rev-parse", "HEAD"), _git(wt, "rev-parse", "--abbrev-ref", "HEAD")


def test_default_base_is_current_head_detached(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 1, "stdout carries the worktree path and nothing else"
    assert Path(lines[0]).is_dir()
    assert _wt_head(lines[0]) == (repos["head"], "HEAD")


def test_dev_base_fetches_origin_before_cutting(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "dev")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["dev"]


def test_main_base(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "main")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["main"]


def test_no_fetch_uses_stale_local_ref(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "dev", "--no-fetch")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["main"]


def test_no_fetch_prefers_local_branch_over_remote_tracking_ref(script_path: Path, repos: dict) -> None:
    work = repos["work"]
    _git(work, "checkout", "-q", "dev")
    (work / "local-only.txt").write_text("local-only", encoding="utf-8")
    _git(work, "add", "local-only.txt")
    _git(work, "commit", "-q", "-m", "local-only")
    local_sha = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "feature")
    assert (work / ".claude" / "harness.json").is_file(), "dev must stay an integration branch"
    done = _run(script_path, repos, "dev", "--no-fetch")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == local_sha


def test_no_fetch_without_local_branch_uses_remote_tracking_ref(script_path: Path, repos: dict) -> None:
    _git(repos["work"], "branch", "-q", "-D", "dev")
    done = _run(script_path, repos, "dev", "--no-fetch")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["main"]


def test_failed_fetch_is_an_error(script_path: Path, repos: dict, tmp_path: Path) -> None:
    _git(repos["work"], "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    done = _run(script_path, repos, "dev")
    assert done.returncode != 0
    assert "fetch" in done.stderr and "--no-fetch" in done.stderr
    assert not repos["root"].exists() or not any(repos["root"].iterdir())


def test_base_without_remote_falls_back_to_local_branch(script_path: Path, repos: dict) -> None:
    _git(repos["work"], "remote", "remove", "origin")
    done = _run(script_path, repos, "dev")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["main"]


def test_name_collision_gets_numeric_suffix(script_path: Path, repos: dict) -> None:
    first = _run(script_path, repos, "--name", "probe")
    second = _run(script_path, repos, "--name", "probe")
    assert first.returncode == 0 and second.returncode == 0, second.stderr
    assert Path(first.stdout.strip()).name == "probe"
    assert Path(second.stdout.strip()).name == "probe-2"


def test_default_name_carries_base_and_short_sha(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "dev")
    assert Path(done.stdout.strip()).name == f"dev-{repos['dev'][:9]}"


def test_unknown_ref_fails_without_creating_anything(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "no-such-ref")
    assert done.returncode != 0
    assert done.stdout == ""
    assert "no-such-ref" in done.stderr
    assert not repos["root"].exists() or not any(repos["root"].iterdir())


def test_base_branch_config_makes_it_an_integration_branch(script_path: Path, repos: dict) -> None:
    _configure(repos["work"], {"base_branch": "dev"})
    done = _run(script_path, repos, "dev")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["dev"]


def test_without_config_only_origin_head_and_main_are_integration(script_path: Path, repos: dict) -> None:
    _configure(repos["work"], None)
    done = _run(script_path, repos, "dev")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["main"], "dev is cut as a plain (stale) local ref"
    assert "(dev)" in done.stderr


def test_configured_integration_branches_replace_the_fallback(script_path: Path, repos: dict) -> None:
    _configure(repos["work"], {"integration_branches": ["main"]})
    done = _run(script_path, repos, "dev")
    assert done.returncode == 0, done.stderr
    assert _wt_head(done.stdout.strip())[0] == repos["main"]


def test_invalid_config_fails_without_creating_anything(script_path: Path, repos: dict) -> None:
    (repos["work"] / ".claude" / "harness.json").write_text("{not json", encoding="utf-8")
    done = _run(script_path, repos, "dev")
    assert done.returncode == 1
    assert done.stdout == ""
    assert "harness.json" in done.stderr
    assert not repos["root"].exists() or not any(repos["root"].iterdir())


def test_configured_worktree_root_applies_without_root_flag(script_path: Path, repos: dict,
                                                            tmp_path: Path) -> None:
    trees = tmp_path / "trees"
    _configure(repos["work"], {"worktree_root": (trees / "{repo}").as_posix()})
    cmd = [sys.executable, str(script_path), "--name", "cfg", "--repo", str(repos["work"])]
    done = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **_GIT_ENV})
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()) == (trees / "work" / "cfg").resolve()


def test_root_from_a_linked_worktree_names_the_main_checkout(script_path: Path, repos: dict,
                                                              tmp_path: Path) -> None:
    trees = tmp_path / "trees"
    _configure(repos["work"], {"worktree_root": (trees / "{repo}").as_posix()})
    _git(repos["work"], "add", "-f", ".claude/harness.json")
    _git(repos["work"], "commit", "-q", "-m", "config")
    inner = _run(script_path, repos, "--name", "inner").stdout.strip()
    cmd = [sys.executable, str(script_path), "--name", "nested", "--repo", inner]
    done = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **_GIT_ENV})
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()).parent == (trees / "work").resolve()
