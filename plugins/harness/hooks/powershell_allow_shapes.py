#!/usr/bin/env python3
"""PreToolUse (PowerShell) hook: approve top-level pipelines whose every stage is allowlisted.

Recognized shape: ``cmd1 | cmd2 [| cmd3 ...]``. A stage may carry a leading ``& `` call operator, stripped
before matching. Pipes inside single- or double-quoted strings, or backtick-escaped, are not stage boundaries.
A second statement (``;``, newline, ``&&``, ``||``) or a subexpression anywhere makes the hook stay silent.

A stage passes when it matches a ``PowerShell(...)`` allow rule from the session project's
``.claude/settings.json`` / ``settings.local.json`` or the user settings directory (sources resolved by
``_allow_settings``), or is a pure-output cmdlet in ``SAFE_CMDLETS``. When every stage passes the hook
emits ``allow``; otherwise it stays silent. Single-stage commands always defer to the platform
allowlist. It never blocks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _allow_settings import load_allow_patterns, settings_files  # noqa: E402

__all__ = ["load_allow_patterns", "settings_files"]

SAFE_CMDLETS = {
    "Out-Null", "Out-Default", "Out-Host", "Out-String",
    "Format-Table", "Format-List", "Format-Wide",
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "PowerShell":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    stages = _split_pipeline(cmd) if isinstance(cmd, str) else []
    if len(stages) <= 1:
        return 0
    patterns = load_allow_patterns(payload, "PowerShell")
    if all(_stage_allowed(s, patterns) for s in stages):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": (
                "PowerShell pipeline; every stage is allowlisted or a pure-output cmdlet"
            ),
        }}))
    return 0


def _stage_allowed(stage: str, patterns: List[str]) -> bool:
    s = stage.strip()
    if not s:
        return True
    if s.startswith("&") and len(s) > 1 and s[1].isspace():
        s = s[1:].lstrip()
    head = _head_token(s)
    if head and head in SAFE_CMDLETS:
        return True
    return any(_glob_match(s, p) for p in patterns)


def _head_token(cmd: str) -> Optional[str]:
    if not cmd:
        return None
    if cmd[0] in "'\"":
        end = cmd.find(cmd[0], 1)
        return cmd[1:end] if end > 0 else None
    m = re.match(r"\S+", cmd)
    return m.group(0) if m else None


def _glob_match(text: str, pattern: str) -> bool:
    rx = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(rx, text.strip(), re.DOTALL) is not None


def _split_pipeline(text: str) -> List[str]:
    """Quote-aware split on top-level ``|`` (PowerShell rules); ``[]`` when ``text`` is not one pipeline.

    Single quotes are literal; a backtick escapes the next character outside single quotes. An unquoted
    ``;``, newline, ``&&``, ``||`` or ``(`` (grouping or subexpression), a ``$(`` inside double quotes, or
    an unterminated quote refuses the split, so no extra statement rides along with an allowlisted stage.
    """
    parts, buf, quote, i, n = [], [], "", 0, len(text)
    while i < n:
        ch = text[i]
        step = 2 if ch == "`" and quote != "'" and i + 1 < n else 1
        if step == 1 and _refused_at(text, i, quote):
            return []
        if step == 1 and quote:
            quote = "" if ch == quote else quote
        elif step == 1 and ch in "'\"":
            quote = ch
        elif step == 1 and ch == "|":
            parts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(text[i:i + step])
        i += step
    if quote:
        return []
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _refused_at(text: str, i: int, quote: str) -> bool:
    """True when position ``i`` starts a statement separator, chain operator or subexpression."""
    if quote == '"':
        return text.startswith("$(", i)
    if quote:
        return False
    return text[i] in ";\n\r(" or text.startswith(("&&", "||"), i)


if __name__ == "__main__":
    sys.exit(main())
