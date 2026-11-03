"""Root resolution: the consuming project (data, state) versus the plugin (code, assets).

Nothing is ever written under ``plugin_root()``: in an installed plugin it is a versioned cache directory.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]

_GIT_TIMEOUT_SECONDS = 30


def run_git(argv: List[str]) -> subprocess.CompletedProcess[str]:
    """Run a git lookup with stdin closed and a bounded wait.

    A child that inherits the caller's stdin, or never returns, would stall a hook for as long as the host
    lets it run. A timeout raises ``TimeoutError`` (an ``OSError``). Callers that catch ``OSError``
    (``main_worktree``, ``config._origin_head``, the hooks' project lookup) treat it as "git unusable";
    ``project_root`` lets it propagate.
    """
    try:
        return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=_GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"git timed out after {_GIT_TIMEOUT_SECONDS}s: {' '.join(argv)}") from exc


def project_root(start: Optional[Path] = None) -> Path:
    """Git top level of ``start`` (default: cwd), else ``CLAUDE_PROJECT_DIR``, else ``start`` itself.

    The working directory wins over ``CLAUDE_PROJECT_DIR`` so a session working in a linked worktree
    resolves that worktree, not the main checkout the session was opened in.
    """
    base = Path(start) if start is not None else Path.cwd()
    top = _git_toplevel(base)
    if top is not None:
        return top
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env and Path(env).is_dir() else base.resolve()


def main_worktree(start: Path) -> Path:
    """Main checkout of the repository holding ``start``; ``start`` itself outside git or in a bare repo.

    Per-repository state (Phase 5 sentinels) anchors here so every linked worktree shares it.
    """
    base = Path(start)
    cwd = base if base.is_dir() else base.parent
    argv = ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"]
    try:
        done = run_git(argv)
    except OSError:
        return base.resolve()
    common = Path(done.stdout.strip()) if done.returncode == 0 else None
    if common is None or common.name != ".git":
        return base.resolve()
    return common.parent.resolve()


def plugin_root() -> Path:
    """The installed ``harness`` plugin directory (holds ``.claude-plugin/plugin.json``)."""
    return _PLUGIN_ROOT


def schema_path(name: str, cfg: HarnessConfig) -> Path:
    """Project pinned copy of schema ``name`` when present, else the plugin's canonical copy."""
    pinned = cfg.path(cfg.schemas_dir) / name
    return pinned if pinned.is_file() else _PLUGIN_ROOT / "schemas" / name


def _git_toplevel(base: Path) -> Optional[Path]:
    cwd = base if base.is_dir() else base.parent
    argv = ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]
    done = run_git(argv)
    return Path(done.stdout.strip()).resolve() if done.returncode == 0 else None
