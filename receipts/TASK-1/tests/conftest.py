"""Shared fixtures: plugin and repo roots, and ``make_project`` for throwaway consuming projects."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional, Union

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "harness"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with a fixed identity; return stripped stdout."""
    env = {**os.environ, **GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def _fresh_harness_config() -> Iterator[None]:
    """No test inherits another test's activated harness configuration."""
    from harness_lib.config import deactivate
    deactivate()
    yield
    deactivate()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The operator-straps checkout."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def plugin_root() -> Path:
    """The ``harness`` plugin directory."""
    return PLUGIN_ROOT


ProjectFactory = Callable[..., Path]


@pytest.fixture()
def make_project(tmp_path: Path) -> ProjectFactory:
    """Build a committed git repo under ``tmp_path`` standing in for a consuming project.

    ``config`` becomes ``.claude/harness.json`` (omitted when None). ``files`` maps repo-relative POSIX
    paths to text or JSON-able data.
    """
    return project_factory(tmp_path)


def _free_dir(parent: Path, name: str) -> Path:
    """``parent/name``, or ``parent/name-2``, ``-3``, ... when taken."""
    root, n = parent / name, 2
    while root.exists():
        root, n = parent / f"{name}-{n}", n + 1
    return root


def copy_project(template: Path, parent: Path, name: Optional[str] = None) -> Path:
    """A copy of a module-scoped ``template`` repo under ``parent`` (``.git`` included), named like
    ``make_project`` names its repos. A copy plus one git call costs about half of a three-call build.

    Copied files keep their mtimes but not their ctimes, so the index is refreshed: without it,
    non-refreshing plumbing (``git diff-files``) reports every tracked file as modified.
    """
    root = Path(shutil.copytree(template, _free_dir(parent, name or template.name)))
    git(root, "update-index", "-q", "--refresh")
    return root


def project_factory(parent: Path) -> ProjectFactory:
    """``make_project``'s factory over any ``parent``, for module-scoped templates built once."""
    def _make(config: Optional[dict] = None, files: Optional[Dict[str, Union[str, dict, list]]] = None,
              name: str = "project") -> Path:
        root = _free_dir(parent, name)
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        written = dict(files or {})
        if config is not None:
            written[".claude/harness.json"] = config
        written.setdefault("README.md", "project\n")
        for rel, body in written.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            text = body if isinstance(body, str) else json.dumps(body, indent=2)
            target.write_text(text, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
        return root

    return _make
