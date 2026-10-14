#!/usr/bin/env python3
"""PreToolUse (Bash) hook: auto-approve ``python -c`` / ``python3 -c`` one-liners, opt-in per project.

Inline scripts with a newline followed by ``#`` inside a quoted argument trip the permission prompt
"Newline followed by # inside a quoted argument can hide arguments from path validation". Projects whose
``.claude/harness.json`` sets ``auto_approve_python_c: true`` get those calls approved; every other project
(and every unreadable payload or config) gets no decision, so the normal permission flow runs.

Only a single command is approved: an unquoted newline, operator, redirect, subshell, command
substitution or ANSI-C ``$'...'`` string anywhere in the payload withholds the decision, because the
approval would otherwise cover whatever follows the ``python -c`` call.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

_PYTHON_C = re.compile(r"(python|python3)\s+-c\s+")


def is_python_c(command: str) -> bool:
    """True when ``command`` is one ``python -c`` / ``python3 -c`` call and nothing else."""
    from harness_lib.shell_scan import is_single_command
    return _PYTHON_C.match(command) is not None and is_single_command(command)


def project_opted_in(payload: Dict[str, Any]) -> bool:
    """True when the payload's project sets ``auto_approve_python_c``; False on any config error."""
    from harness_lib.config import ConfigError, load_config
    from harness_lib.project import project_root
    try:
        return load_config(project_root(Path(payload.get("cwd") or os.getcwd()))).auto_approve_python_c
    except (ConfigError, OSError):
        return False


def allow(reason: str) -> str:
    """The PreToolUse hook output that approves the call with ``reason``."""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": reason}})


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    if isinstance(command, str) and is_python_c(command) and project_opted_in(payload):
        print(allow("python -c auto-approved (harness.json auto_approve_python_c)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
