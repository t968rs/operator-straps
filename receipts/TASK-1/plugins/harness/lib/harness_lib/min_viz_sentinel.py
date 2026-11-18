"""``--min-viz`` sentinel: location, arming and clearing.

Layout: ``<main checkout>/<state_dir>/pr-sum/.minviz_pending_<PR>``. Line 1 is the PR number, line 2 the
unix-int write time, line 3 the arming session id (blank when unknown), line 4 the required block count.
``pr_sum.py capture`` arms it, ``pr_sum.py build`` clears it, and the ``Stop`` / ``SubagentStop`` hook
``check_min_viz_sentinel.py`` blocks the arming session while it exists. Like the Phase 5 sentinel it is per
repository: a linked worktree resolves to its main checkout.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

SENTINEL_PREFIX = ".minviz_pending_"
SENTINEL_GLOB = f"{SENTINEL_PREFIX}*"
SENTINEL_SUBDIR = "pr-sum"


def sentinel_dir_under(project: Path, state_dir: str) -> Path:
    """``<main checkout of project>/<state_dir>/pr-sum``; usable without a loaded config."""
    from harness_lib.project import main_worktree
    return main_worktree(Path(project)) / Path(state_dir) / SENTINEL_SUBDIR


def sentinel_path(cfg: HarnessConfig, pr: Union[int, str]) -> Path:
    """Sentinel file of ``pr`` under the repository's sentinel directory."""
    return sentinel_dir_under(cfg.project_root, cfg.state_dir) / f"{SENTINEL_PREFIX}{pr}"


def arm(cfg: HarnessConfig, pr: Union[int, str], minimum: int, now: Optional[int] = None) -> Path:
    """Write the sentinel for ``pr``; the arming session id comes from ``CLAUDE_CODE_SESSION_ID``."""
    path = sentinel_path(cfg, pr)
    path.parent.mkdir(parents=True, exist_ok=True)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    stamp = int(time.time()) if now is None else now
    path.write_text(f"{pr}\n{stamp}\n{session}\n{minimum}\n", encoding="utf-8")
    return path


def clear(cfg: HarnessConfig, pr: Union[int, str]) -> bool:
    """Remove the sentinel of ``pr``; True when one existed."""
    path = sentinel_path(cfg, pr)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True
