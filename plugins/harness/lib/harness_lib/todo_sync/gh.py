"""The ``gh`` subprocess seam of TODO sync: one place that runs ``gh``, so tests replace ``run_gh``.

Callers reach every function through the module (``gh.run_gh(...)``) so a patched ``run_gh`` applies to them.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence

from harness_lib.todo_sync import TodoSyncError


def run_gh(cwd: Path, args: Sequence[str]) -> str:
    """Stdout of ``gh <args>`` run in ``cwd``; a missing ``gh`` or a non-zero exit raises."""
    try:
        done = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except OSError as exc:
        raise TodoSyncError(f"gh could not run ({exc}); install gh or check PATH") from exc
    if done.returncode != 0:
        label = f"api {args[-1]}" if args and args[0] == "api" else " ".join(args[:2])
        raise TodoSyncError(f"gh {label} failed: {done.stderr.strip()}")
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
