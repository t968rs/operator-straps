"""Shared fixtures: plugin and repo roots, and ``make_project`` for throwaway consuming projects."""
from __future__ import annotations

import json
import os
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
    def _make(config: Optional[dict] = None, files: Optional[Dict[str, Union[str, dict, list]]] = None,
              name: str = "project") -> Path:
        root, n = tmp_path / name, 2
        while root.exists():
            root, n = tmp_path / f"{name}-{n}", n + 1
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
