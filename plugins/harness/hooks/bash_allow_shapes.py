#!/usr/bin/env python3
"""PreToolUse (Bash) hook: approve shell-construct one-liners whose inner commands are all allowlisted.

Recognized shapes:
  for VAR in LIST; do BODY; done
  while TEST; do BODY; done / until TEST; do BODY; done
  if TEST; then BODY; [elif T; then B;] [else B;] fi
  case EXPR in PAT) BODY;; ... esac
  ( BODY )                     subshell wrapper around one command or construct
  HOST $(INNER) ...            command substitution; INNER is checked as its own sub-command
  CMD1 | CMD2 [| CMD3 ...]     top-level pipeline; every stage is checked
  CMD; rc=$? [; echo "..."]    exit-code probe trailers
  VAR=val; CMD                 leading assignments
  VAR=val CMD args             inline environment prefix (stripped before checks)
  CMD 2>&1 [...]               trailing redirects (stripped before checks)

Every sub-command must match a ``Bash(...)`` allow rule from the session project's
``.claude/settings.json`` / ``settings.local.json`` or the user settings directory (sources resolved by
``_allow_settings``), or be a read-only builtin
(``[``, ``[[``, ``test``, ``:``, ``true``, ``false``, ``pwd``) or a bare ``VAR=value`` assignment.
A rule or builtin only matches a single command (``harness_lib.shell_scan``): a sub-command that still
holds a separator, newline, background ``&`` or substitution is decomposed again or refused.
When all pass the hook emits an ``allow`` decision; otherwise it stays silent. It never blocks.

A ``"<python>" -m pytest ARGS`` command (the form the ``pytest-scope`` mod rewrites bare pytest into) counts
as allowlisted when ``<python>`` is that mod's configured ``python`` option (user settings ``pluginConfigs``)
and the bare form (``pytest ARGS``, ``py.test ARGS``, ``python -m pytest ARGS``, ``python3 -m pytest ARGS``)
matches an allow rule: the rewrite never widens what the rules already allow.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _allow_settings import configured_interpreters, load_allow_patterns, settings_files  # noqa: E402
from harness_lib.shell_scan import is_single_command  # noqa: E402

__all__ = [
    "command_subcommands", "extract_subcommands", "is_allowed", "load_allow_patterns", "settings_files",
]

SAFE_BUILTINS = {"[", "[[", "test", ":", "true", "false", "pwd"}
SUBST_PLACEHOLDER = "__SUBST__"

_INLINE_ENV_RE = re.compile(r"""^\s*[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|\$\([^)]*\)|\S*)\s+(?=\S)""")
_TRAILING_REDIR_RE = re.compile(r"\s+(?:\d?>>?\s*&\d+|\d?>>?\s*[^|;&\s)]+|<\s*[^|;&\s)]+)\s*$")
_EXIT_PROBE_TRAILER_RE = re.compile(
    r"""\s*;\s*(?:[A-Za-z_]\w*=\$\?|echo\s+(?:"[^"]*"|'[^']*'|\$\?|\S+))\s*$""")
_LEADING_ASSIGN_RE = re.compile(r"""^\s*([A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|\S*))\s*;\s*""")
_TILDE_RE = re.compile(r"""(^|(?<=["'\s]))~(?=/)""")
_ROUTED_PYTEST_RE = re.compile(r'^"([^"]+)"\s+-m\s+pytest(?=\s|$)(.*)$', re.DOTALL)
_BARE_PYTEST_FORMS = ("pytest", "py.test", "python -m pytest", "python3 -m pytest")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "") if isinstance(payload, dict) else ""
    interpreters = configured_interpreters()
    subs = command_subcommands(cmd, interpreters) if isinstance(cmd, str) and cmd else None
    if subs is None:
        return 0
    patterns = load_allow_patterns(payload, "Bash")
    if all(is_allowed(s, patterns, interpreters) for s in subs):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": (
                "shell construct; every internal command is allowlisted or a read-only builtin"
            ),
        }}))
    return 0


# --- shape extraction -------------------------------------------------------------------------------------


def command_subcommands(cmd: str, interpreters: Sequence[str]) -> Optional[List[str]]:
    """``extract_subcommands``, plus a plain routed-pytest command as its own sub-command."""
    subs = extract_subcommands(cmd)
    if subs is None and interpreters and _ROUTED_PYTEST_RE.match(cmd.strip()):
        return [cmd.strip()]
    return subs


def extract_subcommands(cmd: str) -> Optional[List[str]]:
    """Sub-commands to verify, or None when ``cmd`` is not a recognized shape."""
    leading, rest = _peel_leading_assigns(cmd.strip())
    probes, rest = _peel_exit_code_probes(rest)
    unquoted = _strip_quoted(rest)
    if "||" in unquoted or "&&" in unquoted:
        return None
    subs = _extract_substitutions(rest)
    shaped = _strip_substitutions(rest) if subs else rest
    core = _core_subcommands(shaped, rest, bool(subs), bool(leading or probes))
    return None if core is None else leading + core + subs + probes


def _core_subcommands(s: str, rest: str, has_subs: bool, peeled: bool) -> Optional[List[str]]:
    constructs = _match_constructs(s)
    if constructs is not None:
        return constructs
    subshell = re.match(r"^\((.*)\)\s*$", s, re.DOTALL)
    if subshell:
        inner = subshell.group(1).strip()
        nested = _match_constructs(inner)
        if nested is not None:
            return nested
        return [inner] if inner else None
    stages = [p.strip() for p in _split_on(s, "|") if p.strip()]
    if len(stages) > 1:
        return stages
    if has_subs:
        return [s.strip()]
    if rest.strip() and (peeled or _strip_inline_env(rest) != rest):
        return [p.strip() for p in _split_on(rest, ";") if p.strip()]
    return None


def _peel_leading_assigns(cmd: str) -> Tuple[List[str], str]:
    """Split leading ``VAR=val;`` assignments off ``cmd``."""
    assigns = []
    while True:
        m = _LEADING_ASSIGN_RE.match(cmd)
        if not m:
            return assigns, cmd
        assigns.append(m.group(1))
        cmd = cmd[m.end():]


def _peel_exit_code_probes(cmd: str) -> Tuple[List[str], str]:
    """Split trailing ``; rc=$?`` / ``; echo "..."`` probes off ``cmd``, in order."""
    probes: List[str] = []
    while True:
        m = _EXIT_PROBE_TRAILER_RE.search(cmd)
        if not m:
            return probes, cmd
        probes.insert(0, cmd[m.start():].lstrip().lstrip(";").strip())
        cmd = cmd[:m.start()].rstrip()


def _match_constructs(s: str) -> Optional[List[str]]:
    """Body sub-commands of a ``for`` / ``while`` / ``until`` / ``if`` / ``case`` construct, else None.

    Anchors on ``; do`` / ``; then`` / ``; done`` / ``; fi`` so reserved words inside a for-list are data.
    """
    s = s.strip()
    m = re.match(r"^for\b(.*?);\s*do\b(.*);\s*done\b\s*$", s, re.DOTALL)
    if m:
        return _split_or_recurse(m.group(2))
    m = re.match(r"^(while|until)\b(.*?);\s*do\b(.*);\s*done\b\s*$", s, re.DOTALL)
    if m:
        return _with_test(m.group(2), m.group(3))
    m = re.match(r"^if\b(.*?);\s*then\b(.*);\s*fi\b\s*$", s, re.DOTALL)
    if m:
        body = re.sub(
            r"\belif\b(.*?);\s*then\b", lambda x: ";" + x.group(1) + ";", m.group(2), flags=re.DOTALL
        )
        return _with_test(m.group(1), re.sub(r"\belse\b", ";", body))
    m = re.match(r"^case\b(.*?)\bin\b(.*?)\besac\b\s*$", s, re.DOTALL)
    if m:
        return _case_arms(m.group(2))
    return None


def _with_test(test: str, body: str) -> List[str]:
    head = [test.strip()] if test.strip() else []
    return head + _split_or_recurse(body)


def _case_arms(body: str) -> List[str]:
    cmds: List[str] = []
    for arm in (a.strip() for a in body.split(";;")):
        paren = arm.find(")")
        if arm and paren >= 0:
            cmds.extend(_split_or_recurse(arm[paren + 1:]))
    return cmds


def _split_or_recurse(body: str) -> List[str]:
    """Sub-commands of a nested shape in ``body``, else ``body`` split on top-level ``;`` and ``|``."""
    body = body.strip()
    if not body:
        return []
    nested = extract_subcommands(body)
    if nested is not None:
        return nested
    return [p.strip() for p in _split_on(body, ";|") if p.strip()]


# --- quote-aware scanning ---------------------------------------------------------------------------------


def _quote_mask(text: str) -> List[bool]:
    """Per character: True when quoted, a quote delimiter, or part of a backslash escape (bash rules)."""
    mask, quote, i, n = [False] * len(text), "", 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < n:
            mask[i] = mask[i + 1] = True
            i += 2
            continue
        if quote:
            mask[i] = True
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            mask[i], quote = True, ch
        i += 1
    return mask


def _strip_quoted(text: str) -> str:
    return "".join(" " if q else ch for ch, q in zip(text, _quote_mask(text)))


def _split_on(text: str, seps: str) -> List[str]:
    """Split on unquoted single separators; a doubled separator (``||``, ``;;``) stays in the part."""
    mask, parts, start, i, n = _quote_mask(text), [], 0, 0, len(text)
    while i < n:
        if mask[i] or text[i] not in seps:
            i += 1
        elif i + 1 < n and text[i + 1] == text[i]:
            i += 2
        else:
            parts.append(text[start:i])
            start = i = i + 1
    parts.append(text[start:])
    return parts


def _substitution_spans(s: str) -> List[Tuple[int, int]]:
    """``(start, end)`` of every unquoted, balanced ``$( ... )``, outermost only."""
    mask, spans, i, n = _quote_mask(s), [], 0, len(s)
    while i < n:
        if not mask[i] and s.startswith("$(", i):
            depth, j = 1, i + 2
            while j < n and depth > 0:
                depth += {"(": 1, ")": -1}.get(s[j], 0)
                j += 1
            if depth == 0:
                spans.append((i, j))
                i = j
                continue
        i += 1
    return spans


def _extract_substitutions(s: str) -> List[str]:
    inner = (s[a + 2:b - 1].strip() for a, b in _substitution_spans(s))
    return [x for x in inner if x]


def _strip_substitutions(s: str) -> str:
    out, last = [], 0
    for a, b in _substitution_spans(s):
        out.extend((s[last:a], SUBST_PLACEHOLDER))
        last = b
    out.append(s[last:])
    return "".join(out)


# --- allowlist matching -----------------------------------------------------------------------------------


def is_allowed(subcmd: str, patterns: List[str], interpreters: Sequence[str] = ()) -> bool:
    """True when ``subcmd`` is a safe builtin, an assignment, allowlisted, or a shape of allowed parts."""
    s = subcmd.strip()
    if not s:
        return True
    s = _strip_trailing_redirects(_strip_inline_env(s))
    while s.startswith("!"):
        s = s[1:].lstrip()
    head = _head_token(s)
    if head is None:
        return False
    if is_single_command(s, allow_redirects=True):
        if head in SAFE_BUILTINS or re.match(r"^[A-Za-z_]\w*=\S*\s*$", s):
            return True
        if any(_glob_match(s, p) for p in patterns) or _routed_pytest_allowed(s, patterns, interpreters):
            return True
    nested = extract_subcommands(s)
    return nested is not None and all(is_allowed(x, patterns, interpreters) for x in nested)


def _routed_pytest_allowed(cmd: str, patterns: List[str], interpreters: Sequence[str]) -> bool:
    """True for ``"<python>" -m pytest ARGS`` with a configured ``<python>`` whose bare form is allowed."""
    m = _ROUTED_PYTEST_RE.match(cmd)
    if m is None or _interpreter_key(m.group(1)) not in {_interpreter_key(i) for i in interpreters}:
        return False
    bare = [f"{form}{m.group(2)}" for form in _BARE_PYTEST_FORMS]
    return any(_glob_match(b, p) for b in bare for p in patterns)


def _interpreter_key(path: str) -> str:
    """Comparison key of an interpreter path: forward slashes, case-folded."""
    return path.strip().replace("\\", "/").casefold()


def _strip_inline_env(cmd: str) -> str:
    while True:
        m = _INLINE_ENV_RE.match(cmd)
        if not m:
            return cmd
        cmd = cmd[m.end():]


def _strip_trailing_redirects(cmd: str) -> str:
    while True:
        m = _TRAILING_REDIR_RE.search(cmd)
        if not m:
            return cmd
        cmd = cmd[:m.start()].rstrip()


def _head_token(cmd: str) -> Optional[str]:
    if not cmd:
        return None
    if cmd[0] in "'\"":
        end = cmd.find(cmd[0], 1)
        return cmd[: end + 1] if end > 0 else None
    m = re.match(r"\S+", cmd)
    return m.group(0) if m else None


def _glob_match(text: str, pattern: str) -> bool:
    """Claude Code style glob: ``*`` matches anything (newlines included); a leading ``~/`` is the
    home dir."""
    home = os.path.expanduser("~").replace("\\", "/")
    rx = re.escape(_TILDE_RE.sub(lambda m: m.group(1) + home, pattern)).replace(r"\*", ".*")
    return re.fullmatch(rx, text.strip(), re.DOTALL) is not None



if __name__ == "__main__":
    sys.exit(main())
