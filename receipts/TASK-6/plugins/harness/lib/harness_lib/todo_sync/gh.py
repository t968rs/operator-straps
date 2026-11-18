"""The ``gh`` subprocess seam of TODO sync: one place that runs ``gh``, so tests replace ``run_gh``.

Callers reach every function through the module (``gh.run_gh(...)``) so a patched ``run_gh`` applies to them.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from harness_lib.todo_sync import TodoSyncError

GH_TIMEOUT_SECONDS = 120.0
"""The longest one ``gh`` call may run. ``add --spec --file-issue`` files issues under the catalog write lock,
so a hung ``gh`` (a stalled network, an auth prompt) would otherwise hold every other writer off."""


def _label(args: Sequence[str]) -> str:
    """The call as an error names it: ``api <path>`` or the first two arguments."""
    return f"api {args[-1]}" if args and args[0] == "api" else " ".join(args[:2])


def run_gh(cwd: Path, args: Sequence[str], stdin: Optional[str] = None) -> str:
    """Stdout of ``gh <args>`` run in ``cwd`` with ``stdin`` as input; a missing ``gh``, a failure or a call
    past ``GH_TIMEOUT_SECONDS`` raises.

    Long text (an issue body) travels on ``stdin`` so the command line stays under the Windows length limit.
    """
    try:
        done = subprocess.run(["gh", *args], cwd=cwd, input=stdin, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=GH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise TodoSyncError(f"gh {_label(args)} timed out after {GH_TIMEOUT_SECONDS:.0f}s") from exc
    except OSError as exc:
        raise TodoSyncError(f"gh could not run ({exc}); install gh or check PATH") from exc
    if done.returncode != 0:
        raise TodoSyncError(f"gh {_label(args)} failed: {done.stderr.strip()}")
    return done.stdout


def api_object(cwd: Path, path: str) -> Dict[str, Any]:
    """The JSON object ``gh api <path>`` returns."""
    value = json.loads(run_gh(cwd, ["api", path]))
    if not isinstance(value, dict):
        raise TodoSyncError(f"gh api {path} returned no object")
    return value


def api_list(cwd: Path, path: str) -> List[Dict[str, Any]]:
    """Every object of a paginated array endpoint, one per output line of ``--jq .[]``."""
    text = run_gh(cwd, ["api", "--paginate", "--jq", ".[]", path])
    return [row for row in (json.loads(line) for line in text.splitlines() if line.strip())
            if isinstance(row, dict)]
