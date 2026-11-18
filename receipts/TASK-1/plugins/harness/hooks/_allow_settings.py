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
    project = _project_dir(payload)
    own = [] if project is None else [project / ".claude" / name for name in _SETTINGS_NAMES]
    return own + _user_settings_files()


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


def configured_interpreters(plugin: str = "pytest-scope") -> List[str]:
    """``python`` option values of ``plugin`` from the user settings ``pluginConfigs``, any marketplace.

    The key is ``<plugin>@<marketplace>`` for an installed plugin and ``<plugin>`` or ``<plugin>@inline`` for
    a ``--plugin-dir`` one. ``pluginConfigs`` lives in user (or managed) settings only.
    """
    found: List[str] = []
    for path in _user_settings_files():
        for key, entry in _plugin_configs(path).items():
            if key != plugin and not key.startswith(f"{plugin}@"):
                continue
            options = entry.get("options") if isinstance(entry, dict) else None
            value = options.get("python") if isinstance(options, dict) else None
            if isinstance(value, str) and value.strip():
                found.append(value.strip())
    return found


def _user_settings_files() -> List[Path]:
    user = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return [user / name for name in _SETTINGS_NAMES]


def _plugin_configs(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    configs = data.get("pluginConfigs") if isinstance(data, dict) else None
    return configs if isinstance(configs, dict) else {}


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
