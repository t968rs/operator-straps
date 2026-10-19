#!/usr/bin/env python3
"""SessionStart hook: write the todo_sync runner pointer (``<state_dir>/todo-sync/runner.json``).

The todo-watch mod reads the pointer to run ``scripts/todo_sync.py check`` with this session's interpreter.
The project comes from the payload ``cwd``. With ``todo.catalog`` null the hook writes nothing. It never
runs a check, prints nothing and fails open: any error (unreadable payload or config, unwritable state
directory) exits 0 silently.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _payload_cwd() -> Path:
    """The payload's ``cwd``, else the process working directory."""
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())


def _write_pointer(start: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    from harness_lib.todo_sync import write_runner

    cfg = activate(load_config(project_root(start)))
    if cfg.todo.enabled:
        write_runner(cfg)


def main() -> int:
    try:
        _write_pointer(_payload_cwd())
    except Exception:  # noqa: BLE001 - a SessionStart hook never blocks or warns the session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
