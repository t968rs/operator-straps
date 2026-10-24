#!/usr/bin/env python3
"""PreToolUse (Write|Edit) hook: commit-message TXT files are ``branch_commit_msg.py build`` output.

Denies, through the documented ``permissionDecision: deny`` hook output, an ``Edit`` or ``Write`` of a
``.txt`` file at any depth under the project's ``artifacts.commit_messages`` directory. A drafted message
changes only on the developer's ask, through the skills ``CHANGE_ROUTE`` names, so a hand edit of the TXT
drifts from its skeleton or rewrites a message the developer never asked to change.

Allowed: ``PR<NNN>_merge.txt`` (``harness:merge-commit-msg`` writes that file with the Write tool), the
skeleton ``.json`` and the ``.txt.bak`` backup. The project is the one holding the target file (its nearest
existing directory), else the payload ``cwd``. Unparseable input, a payload without a file path and an
unusable harness config never block.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.commit_txt import CHANGE_ROUTE  # noqa: E402
from harness_lib.config import ConfigError, HarnessConfig, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

# Every route the reason names sits behind the developer's ask; a bare "edit the skeleton and rebuild" route
# would hand the session the same unasked rewrite one hop later, over a skeleton that may predate TXT edits.
REASON = f"Commit-message TXT files are build output and final as saved. {CHANGE_ROUTE}"

_MERGE_TXT = re.compile(r"^PR\d+_merge\.txt$", re.IGNORECASE)


def guarded(file_path: Path, cfg: HarnessConfig) -> bool:
    """True when ``file_path`` is a build-owned ``.txt`` under the project's commit_messages directory."""
    if not file_path.name.lower().endswith(".txt") or _MERGE_TXT.match(file_path.name):
        return False
    folder = cfg.path(cfg.artifacts.commit_messages).resolve()
    try:
        file_path.resolve().relative_to(folder)
    except ValueError:
        return False
    return True


def _existing_dir(path: Path) -> Optional[Path]:
    """``path``'s nearest existing ancestor directory, else None."""
    return next((p for p in path.parents if p.is_dir()), None)


def _config_for(file_path: Path, payload: Dict[str, Any]) -> Optional[HarnessConfig]:
    """The activated config of the project holding ``file_path`` (else the payload ``cwd``), or None."""
    cwd = payload.get("cwd")
    start = _existing_dir(file_path) or (Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd()))
    try:
        return activate(load_config(project_root(start)))
    except (ConfigError, OSError):  # OSError: git missing from PATH during the project lookup
        return None


def _file_path(payload: Any) -> Optional[Path]:
    """The absolute ``tool_input.file_path`` of the payload, else None."""
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    raw = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else None


def deny(reason: str) -> str:
    """The PreToolUse hook output that denies the call with ``reason``."""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    file_path = _file_path(payload)
    cfg = _config_for(file_path, payload) if file_path is not None else None
    if cfg is not None and guarded(file_path, cfg):
        print(deny(REASON))
    return 0


if __name__ == "__main__":
    sys.exit(main())
