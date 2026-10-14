#!/usr/bin/env python3
"""PreToolUse (Bash) hook: one command per Bash call.

Denies, through the documented ``permissionDecision: deny`` hook output:
  - ``&&`` chaining outside quoted strings and heredoc bodies;
  - top-level ``;`` chaining (``cd X; git ...``, ``cmd1; cmd2``).

Allowed: quoted or escaped separators, inert heredoc bodies (commit messages; a body under an unquoted
delimiter that runs ``$(...)`` or backticks stays checked), ``;`` inside balanced
``for/while/until/if ... done/fi`` and ``case ... esac`` constructs, and leading ``VAR=val;`` assignments
that prefix such a construct. Disabled when the plugin option ``bash_discipline`` is ``false``
(``CLAUDE_PLUGIN_OPTION_BASH_DISCIPLINE`` set to ``false`` or ``0``). Unparseable input never blocks.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

OPTION_ENV = "CLAUDE_PLUGIN_OPTION_BASH_DISCIPLINE"

_AND_MSG = ("Bash discipline violation: '&&' is not allowed.\n"
            "Each command must be its own Bash tool call.\nSplit this into separate Bash calls.")
_CD_MSG = ("Bash discipline violation: 'cd <path> ; <cmd>' is not allowed.\n"
           "Use 'git -C \"<absolute-path>\" <subcommand>' instead of 'cd <path> ; git ...'.\n"
           "For non-git commands, use absolute paths or separate Bash calls.")
_SEMI_MSG = ("Bash discipline violation: ';' command chaining is not allowed.\n"
             "Each command must be its own Bash tool call.\nSplit this into separate Bash calls.")

_HEREDOC_OPEN = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(['\"]?)([A-Za-z_][\w-]*)\1[^\n]*\n")
_LEADING_ASSIGNS = re.compile(r"^\s*(?:[A-Za-z_]\w*=\S*\s*;\s*)+(?=(?:for|while|until|if|case)\b)")


def enabled() -> bool:
    """False only when the plugin option is explicitly ``false`` or ``0``."""
    return os.environ.get(OPTION_ENV, "").strip().lower() not in {"false", "0"}


def check_command(cmd: str) -> Optional[str]:
    """Return the violation message for ``cmd``, else None."""
    unquoted = _strip_quoted_sections(_strip_heredoc_bodies(cmd.strip()))
    if "&&" in unquoted:
        return _AND_MSG
    cleaned = _neutralize_constructs(_LEADING_ASSIGNS.sub("", unquoted))
    if re.search(r"\bcd\s+\S.*?\s*;\s*\S", cleaned):
        return _CD_MSG
    if re.search(r"\S\s*;\s*\S", cleaned):
        return _SEMI_MSG
    return None


def _strip_heredoc_bodies(text: str) -> str:
    """Drop inert heredoc bodies and their terminator lines; the opener line stays visible.

    Only an unquoted ``<<`` / ``<<-`` opens a heredoc (``<<<`` herestrings and quoted ``<<`` do not). A body
    is inert when its delimiter is quoted, or when it holds no ``$(`` or backtick substitution; bodies that
    expand commands stay visible to the chain checks.
    """
    out, pos = [], 0
    while True:
        opener = _next_heredoc_opener(text, pos)
        if opener is None:
            break
        closer = re.compile(rf"^[ \t]*{re.escape(opener.group(2))}[ \t]*$", re.M).search(text, opener.end())
        if closer is None:
            break
        body = text[opener.end():closer.start()]
        expands = not opener.group(1) and ("$(" in body or "`" in body)
        out.append(text[pos:closer.end()] if expands else text[pos:opener.end()])
        pos = closer.end()
    out.append(text[pos:])
    return "".join(out)


def _next_heredoc_opener(text: str, pos: int) -> Optional[re.Match]:
    """First heredoc opener at or after ``pos`` whose ``<<`` lies outside quotes and escapes."""
    masked = _strip_quoted_sections(text[pos:])
    for m in _HEREDOC_OPEN.finditer(text, pos):
        if masked[m.start() - pos:m.start() - pos + 2] == "<<":
            return m
    return None


def _neutralize_constructs(text: str) -> str:
    """Replace balanced shell constructs with tokens so only top-level ``;`` separators remain.

    ``_X_`` is a whole ``case ... esac``; ``_O_ ... _C_`` is an opener/closer pair whose inner ``;``
    separators are erased. Separators *between* constructs stay visible to the chain check.
    """
    text = re.sub(r"\bcase\b.*?\besac\b", "_X_", text, flags=re.DOTALL)
    text = re.sub(r"\b(for|while|until|if)\b[^;]*;\s*(do|then)\b", "_O_", text)
    text = re.sub(r";\s*\belif\b[^;]*;\s*then\b", "_O_", text)
    text = re.sub(r";\s*\b(done|fi|else)\b", "_C_", text)
    text = re.sub(r"\b(done|fi|else)\s*;", "_C_", text)
    return re.sub(r"_O_.*?_C_", lambda m: m.group(0).replace(";", "_"), text, flags=re.DOTALL)


def _strip_quoted_sections(text: str) -> str:
    """Blank out quoted substrings and backslash-escaped characters (bash quoting rules).

    Inside double quotes a backslash escapes the next character; single quotes are literal.
    """
    result, quote, i, n = [], "", 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < n:
            result.append("  ")
            i += 2
            continue
        if quote:
            quote = "" if ch == quote else quote
            result.append(" ")
        elif ch in "'\"":
            quote = ch
            result.append(" ")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def deny(reason: str) -> str:
    """The PreToolUse hook output that denies the call with ``reason``."""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def main() -> int:
    if not enabled():
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    command = (payload.get("tool_input") or {}).get("command", "") if isinstance(payload, dict) else ""
    error = check_command(command) if isinstance(command, str) and command else None
    if error:
        print(deny(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
