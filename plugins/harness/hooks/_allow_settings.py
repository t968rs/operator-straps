"""Settings sources shared by the allow-shape hooks: which ``permissions.allow`` rules apply to a call.

The project half mirrors what Claude Code enforces: the session project (``CLAUDE_PROJECT_DIR``) when set,
so a linked-worktree ``cwd`` still sees the main checkout's ``settings.local.json`` and a ``cwd`` inside an
unrelated repo never contributes rules. Without ``CLAUDE_PROJECT_DIR`` the git top level of the payload
``cwd`` stands in; when git cannot run, only the user settings apply. The user half is
``CLAUDE_CONFIG_DIR``, else the default user settings directory.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_SETTINGS_NAMES = ("settings.json", "settings.local.json")


def settings_files(payload: Dict[str, Any]) -> List[Path]:
    """Project then user settings files whose ``permissions.allow`` rules apply to this call."""
    user = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    project = _project_dir(payload)
    dirs = [user] if project is None else [project / ".claude", user]
    return [d / name for d in dirs for name in _SETTINGS_NAMES]


def load_allow_patterns(payload: Dict[str, Any], tool: str) -> List[str]:
    """Bodies of every ``<tool>(...)`` allow rule, deduplicated in first-seen order."""
    rule = re.compile(rf"^{re.escape(tool)}\((.*)\)\s*$")
    patterns: Dict[str, None] = {}
    for path in settings_files(payload):
        for entry in _allow_entries(path):
            m = rule.match(entry) if isinstance(entry, str) else None
            if m:
                patterns.setdefault(m.group(1))
    return list(patterns)


def _project_dir(payload: Dict[str, Any]) -> Optional[Path]:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    from harness_lib.project import project_root
    try:
        return project_root(Path(payload.get("cwd") or os.getcwd()))
    except OSError:
        return None


def _allow_entries(path: Path) -> List[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    allow = ((data.get("permissions") or {}).get("allow") or []) if isinstance(data, dict) else []
    return allow if isinstance(allow, list) else []
