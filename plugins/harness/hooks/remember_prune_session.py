#!/usr/bin/env python3
"""SessionStart hook: prune stale files from the project's ``.remember`` folder.

The remember plugin retires, rotates and caps some of its files but never deletes the rest. This hook
removes the leftovers by age (file mtime):

* ``today-*.done.md``: staging files already folded into ``recent.md`` and ``archive.md``.
* ``logs/logs-*.tar.gz``: log tarballs the plugin writes after 7 days and never removes.
* ``tmp/handoff-path.*`` and ``tmp/position.*``: per-session pointers that outlive their session.

It also trims ``logs/hook-errors.log`` to its last lines. Rotated memory slices (``archive-*.md``,
``recent-*.md``), ``core-memories.md`` and the live state files in ``tmp/`` are never touched.

The project comes from the payload ``cwd``; the hook walks up to the nearest ``.remember`` folder and does
nothing without one. It prints nothing and fails open: any error exits 0 silently.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

REMEMBER_DIR_NAME = ".remember"
DAY_SECONDS = 86400

DONE_STAGING_DAYS = 14
LOG_TARBALL_DAYS = 30
SESSION_POINTER_DAYS = 14
HOOK_ERRORS_KEEP_LINES = 200

# (folder under .remember, glob, max age in days)
AGE_RULES: Tuple[Tuple[str, str, int], ...] = (
    (".", "today-*.done.md", DONE_STAGING_DAYS),
    ("logs", "logs-*.tar.gz", LOG_TARBALL_DAYS),
    ("tmp", "handoff-path.*", SESSION_POINTER_DAYS),
    ("tmp", "position.*", SESSION_POINTER_DAYS),
)


def _payload_cwd() -> Path:
    """The payload's ``cwd``, else the process working directory."""
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())


def find_remember_dir(start: Path) -> Optional[Path]:
    """The nearest ``.remember`` folder at or above ``start``, else None."""
    for folder in (start, *start.parents):
        candidate = folder / REMEMBER_DIR_NAME
        if candidate.is_dir():
            return candidate
    return None


def stale_files(remember: Path, now: float) -> List[Path]:
    """Files under ``remember`` that an age rule selects and whose mtime is past its cutoff."""
    found: List[Path] = []
    for folder, pattern, days in AGE_RULES:
        cutoff = now - days * DAY_SECONDS
        for path in (remember / folder).glob(pattern):
            if path.is_file() and path.stat().st_mtime < cutoff:
                found.append(path)
    return found


def trim_log(path: Path, keep_lines: int) -> bool:
    """Rewrite ``path`` with its last ``keep_lines`` lines; True when lines were dropped."""
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if len(lines) <= keep_lines:
        return False
    path.write_text("".join(lines[-keep_lines:]), encoding="utf-8")
    return True


def prune(remember: Path, now: Optional[float] = None) -> List[Path]:
    """Delete the stale files and trim the hook error log; return the deleted paths."""
    stamp = time.time() if now is None else now
    removed: List[Path] = []
    for path in stale_files(remember, stamp):
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    try:
        trim_log(remember / "logs" / "hook-errors.log", HOOK_ERRORS_KEEP_LINES)
    except OSError:
        pass
    return removed


def main() -> int:
    try:
        remember = find_remember_dir(_payload_cwd())
        if remember is not None:
            prune(remember)
    except Exception:  # noqa: BLE001 - a SessionStart hook never blocks or warns the session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
