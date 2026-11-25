#!/usr/bin/env python3
"""PreToolUse hook (composed): deny writes to Locked plan and strap files and to the freeze ledger.

Decided inside ``write_pretool.py`` (Write|Edit), ``bash_pretool.py`` (Bash) and ``powershell_pretool.py``
(PowerShell), always before the other hooks there, so a deny here outranks any allow they would give.

Covered: only paths under the plans folder (``artifacts.plans``) and its ``freezes/``. Every file under
``<plans>/freezes/`` is denied. Otherwise a path is denied when a subject ledger
(``<plans>/freezes/plan/<no>-<slug>/`` or ``<plans>/freezes/skill/<name>/``) is Locked or armed and its last
lock entry lists the path (``freeze_ledger.locked_files``). A plan whose lock carries the ``sealed`` scheme
or no scheme keeps its plan JSON writable, since ``record`` still writes it there.

Targets: ``tool_input.file_path`` for Write and Edit; for Bash and PowerShell a best-effort read of
``tool_input.command``. Writes: Bash ``>``/``>>``, ``tee``, ``sed -i`` and the ``cp``/``mv`` destination,
PowerShell redirects, ``Set-Content``, ``Add-Content``, ``Out-File`` and the ``Copy-Item``/``Move-Item``
destination. Removals and moves, which undo a lock as surely as a write: Bash ``rm``/``unlink`` operands, the
``mv`` sources, ``git rm`` (not ``--cached``) and both sides of ``git mv``; PowerShell ``Remove-Item`` and its
aliases (``ri``, ``rm``, ``del``, ``erase``, ``rd``, ``rmdir``) and the ``Move-Item`` source. The
``freezes/`` folder itself counts as a ledger path; a removal of a folder above it (the plans folder or its
parents) is not caught. Each target becomes a repo-relative POSIX path under the project
``load_config(project_root(cwd))`` gives; on Windows a Git Bash or Cygwin drive path (``/e/...``,
``/cygdrive/e/...``) is read as ``e:/...`` first, and every prefix and lookup compares in the OS's case rule.
Anything outside the plans folder returns at once, before any ledger read. A command with no write, removal
or move shape returns before the config load. Unusable payloads, an unusable config and unreadable ledgers
never block.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

_FILE_TOOLS = ("Write", "Edit")
_PUNCTUATION = "();<>|&\n"
_SEPARATOR_CHARS = set("();|&\n")
_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
_SHELL_PREFIXES = {"sudo", "command", "env", "builtin", "exec", "nohup", "time"}
_GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_MSYS_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?=/)")
_PATH_PARAMS = ("-path", "-literalpath")
# Per cmdlet: each (named parameters, positional index) slot that names a path the command writes,
# removes or moves away.
_PS_WRITERS: Dict[str, Tuple[Tuple[Tuple[str, ...], int], ...]] = {
    "set-content": ((_PATH_PARAMS, 0),),
    "add-content": ((_PATH_PARAMS, 0),),
    "ac": ((_PATH_PARAMS, 0),),
    "out-file": ((("-filepath", "-literalpath", "-path"), 0),),
    "copy-item": ((("-destination",), 1),),
    "move-item": ((("-destination",), 1), (_PATH_PARAMS, 0)),
    "remove-item": ((_PATH_PARAMS, 0),),
}
for _alias, _cmdlet in (("copy", "copy-item"), ("cpi", "copy-item"), ("cp", "copy-item"),
                        ("move", "move-item"), ("mi", "move-item"), ("mv", "move-item"),
                        ("ri", "remove-item"), ("rm", "remove-item"), ("del", "remove-item"),
                        ("erase", "remove-item"), ("rd", "remove-item"), ("rmdir", "remove-item")):
    _PS_WRITERS[_alias] = _PS_WRITERS[_cmdlet]
_PS_SWITCHES = {"-force", "-nonewline", "-append", "-passthru", "-recurse", "-r", "-whatif", "-confirm",
                "-noclobber", "-asbytestream", "-container"}
_WAY_IN = ("Ways in run through the drivers (scripts/plan.py and scripts/strap.py under the harness plugin "
           "root): a Locked plan changes after plan.py unlock <id> --arm REASON, run only on the "
           "developer's explicit OK, then plan.py unlock <id> when the change is needed; a Locked strap "
           "spec changes after strap.py reopen <name>. Ledger files under freezes/ are written by the "
           "drivers alone. A Locked plan JSON that fails to load is repaired by the developer's own hand "
           "edit, never the session's.")


def deny(reason: str) -> str:
    """The PreToolUse hook output that denies the call with ``reason``."""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def _reason(rel: str, subject: str) -> str:
    return (f"{rel} is locked by {subject}; hand edits, shell writes, removals and moves of it are denied. "
            f"{_WAY_IN}")


def _tokens(command: str, escape: str) -> List[str]:
    """Shell-like tokens of ``command``; runs of ``();<>|&`` and newlines come out as their own tokens."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    lex.escape = escape
    try:
        return list(lex)
    except ValueError:
        return command.split()


def _segments(tokens: List[str]) -> Tuple[List[List[str]], List[str]]:
    """Simple commands split on separators, and the targets of file redirects."""
    segments: List[List[str]] = [[]]
    redirected: List[str] = []
    skip = False
    for i, tok in enumerate(tokens):
        if skip:
            skip = False
        elif tok in _REDIRECTS:
            if i + 1 < len(tokens):
                redirected.append(tokens[i + 1])
            skip = True
        elif tok and set(tok) <= _SEPARATOR_CHARS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return [s for s in segments if s], redirected


def _operands(args: List[str]) -> List[str]:
    return [a for a in args if not a.startswith("-")]


def _copy_split(args: List[str]) -> Tuple[Optional[str], List[str]]:
    """``cp``/``mv`` destination (``-t DIR`` or the last operand) and sources; no destination when absent."""
    target, operands, i = None, [], 0
    while i < len(args):
        arg = args[i]
        if arg in ("-t", "--target-directory") and i + 1 < len(args):
            target, i = args[i + 1], i + 1
        elif arg.startswith("--target-directory="):
            target = arg.split("=", 1)[1]
        elif not arg.startswith("-"):
            operands.append(arg)
        i += 1
    if target is None:
        if len(operands) < 2:
            return None, []
        target, operands = operands[-1], operands[:-1]
    return target, operands


def _copy_targets(args: List[str], moves: bool = False) -> List[str]:
    """``cp``/``mv`` destinations, each joined with every source name; a move adds its sources."""
    target, sources = _copy_split(args)
    if target is None:
        return []
    names = [posixpath.basename(s.replace("\\", "/").rstrip("/")) for s in sources]
    found = [target] + [posixpath.join(target.replace("\\", "/"), n) for n in names if n]
    return found + sources if moves else found


def _git_targets(args: List[str]) -> List[str]:
    """Paths ``git rm`` removes (none under ``--cached``) and both sides of ``git mv``."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in _GIT_VALUE_OPTIONS else 1
    sub, rest = (args[i], args[i + 1:]) if i < len(args) else ("", [])
    if sub == "rm":
        return [] if "--cached" in rest else _operands(rest)
    return _copy_targets(rest, moves=True) if sub == "mv" else []


def _sed_in_place(args: List[str]) -> bool:
    return any(a.startswith("--in-place") or (a[:1] == "-" and a[1:2] != "-" and "i" in a[1:]) for a in args)


def _bash_segment(words: List[str]) -> List[str]:
    while words and ("=" in words[0].split("/")[0] or words[0] in _SHELL_PREFIXES):
        words = words[1:]
    if not words:
        return []
    name, args = posixpath.basename(words[0]), words[1:]
    if name == "tee":
        return _operands(args)
    if name == "sed":
        return _operands(args) if _sed_in_place(args) else []
    if name in ("rm", "unlink"):
        return _operands(args)
    if name in ("cp", "mv"):
        return _copy_targets(args, moves=name == "mv")
    return _git_targets(args) if name == "git" else []


def bash_targets(command: str) -> List[str]:
    """Best-effort paths a Bash command writes, removes or moves away."""
    segments, found = _segments(_tokens(command, "\\"))
    for words in segments:
        found += _bash_segment(words)
    return found


def _ps_args(args: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """Named parameter values (lower-case names) and positional arguments of one PowerShell command."""
    named: Dict[str, str] = {}
    positional: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if len(arg) > 1 and arg[0] == "-" and arg[1].isalpha():
            name, sep, value = arg.partition(":")
            if sep:
                named[name.lower()] = value
            elif name.lower() not in _PS_SWITCHES and i + 1 < len(args):
                named[name.lower()], i = args[i + 1], i + 1
        else:
            positional.append(arg)
        i += 1
    return named, positional


def _ps_segment(words: List[str]) -> List[str]:
    if words and words[0] == "&":
        words = words[1:]
    slots = _PS_WRITERS.get(words[0].lower()) if words else None
    if slots is None:
        return []
    named, positional = _ps_args(words[1:])
    found: List[str] = []
    for params, index in slots:
        value = next((named[p] for p in params if p in named), None)
        if value is None and len(positional) > index:
            value = positional[index]
        found += [v for v in (value or "").split(",") if v.strip()]
    return found


def powershell_targets(command: str) -> List[str]:
    """Best-effort paths a PowerShell command writes, removes or moves away."""
    segments, found = _segments(_tokens(command, "`"))
    for words in segments:
        found += _ps_segment(words)
    return found


def _targets(payload: Dict[str, Any]) -> List[str]:
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    if tool in _FILE_TOOLS:
        raw = tool_input.get("file_path")
        return [raw] if isinstance(raw, str) and raw else []
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return []
    if tool == "Bash":
        return bash_targets(command)
    return powershell_targets(command) if tool == "PowerShell" else []


def _under(target: Path, base: Path) -> Optional[str]:
    """``target`` relative to ``base`` as POSIX, compared in the OS's case rule; None when outside."""
    t, b = os.path.normpath(str(target)), os.path.normpath(str(base))
    if not os.path.normcase(t).startswith(os.path.normcase(b).rstrip(os.sep) + os.sep):
        return None
    return t[len(b.rstrip(os.sep)) + 1:].replace(os.sep, "/")


def _native(text: str) -> str:
    """On Windows a Git Bash or Cygwin drive path (``/e/x``, ``/cygdrive/e/x``) as ``e:/x``; else ``text``."""
    if os.name != "nt":
        return text
    return _MSYS_DRIVE.sub(lambda m: f"{m.group(1)}:", text, count=1)


def repo_rel(raw: str, root: Path, cwd: Path) -> Optional[str]:
    """``raw`` (absolute or relative to ``cwd``, either slash) as a path relative to ``root``, else None."""
    text = _native(raw.strip().replace("\\", "/"))
    if not text:
        return None
    path = Path(text)
    path = path if path.is_absolute() else cwd / path
    rel = _under(path, root)
    if rel is not None:
        return rel
    try:
        return _under(path.resolve(), root.resolve())
    except OSError:
        return None


def _key(rel: str) -> str:
    return rel.lower() if os.name == "nt" else rel


def _subject_locked(ledger: Any, folder: Path, kind: str, plans_rel: str) -> List[str]:
    """The paths one subject's ledger locks; a plan JSON stays out unless the lock uses receipts."""
    try:
        entries = ledger.load_entries(folder)
    except ledger.LedgerError:
        return []
    paths = ledger.locked_files(entries, plans_rel)
    locks = [e for e in entries if e.kind == ledger.EntryKind.lock]
    if kind == "plan" and paths and max(locks, key=lambda e: (e.round, e.seq)).records != "receipts":
        paths = [p for p in paths if posixpath.dirname(p) != plans_rel]
    return paths


def locked_paths(plans_dir: Path, plans_rel: str) -> Dict[str, str]:
    """Every Locked path under ``plans_rel`` (by ``_key``) mapped to its subject stem."""
    from harness_lib import freeze_ledger

    found: Dict[str, str] = {}
    for kind in ("plan", "skill"):
        base = plans_dir / freeze_ledger.FREEZES_DIR / kind
        folders = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        for folder in folders:
            for path in _subject_locked(freeze_ledger, folder, kind, plans_rel):
                found.setdefault(_key(path), f"{kind}/{folder.name}")
    return found


def _verdict(rels: List[str], plans_dir: Path, plans_rel: str) -> Optional[str]:
    from harness_lib.freeze_ledger import FREEZES_DIR

    freezes = _key(f"{plans_rel}/{FREEZES_DIR}/")
    for rel in rels:
        if _key(rel + "/").startswith(freezes):
            return deny(_reason(rel, "the freeze ledger (driver-written only)"))
    locked = locked_paths(plans_dir, plans_rel)
    for rel in rels:
        stem = locked.get(_key(rel))
        if stem is not None:
            return deny(_reason(rel, f"the {stem} lock"))
    return None


def _config(cwd: Path) -> Any:
    """The activated config of the project ``cwd`` resolves to, or None when it cannot load."""
    from harness_lib.config import ConfigError, activate, load_config
    from harness_lib.project import project_root

    try:
        return activate(load_config(project_root(cwd)))
    except (ConfigError, OSError):
        return None


def decide(payload: Any) -> Optional[str]:
    """A deny JSON when the call writes a Locked or ledger path under the plans folder, else None."""
    if not isinstance(payload, dict):
        return None
    raw = _targets(payload)
    if not raw:
        return None
    start = payload.get("cwd")
    cwd = Path(start) if isinstance(start, str) and start else Path(os.getcwd())
    cfg = _config(cwd)
    if cfg is None:
        return None
    plans_rel = cfg.artifacts.plans.replace("\\", "/").strip("/")
    prefix = _key(plans_rel + "/")
    rels = [r for r in (repo_rel(t, cfg.project_root, cwd) for t in raw)
            if r is not None and _key(r).startswith(prefix)]
    return _verdict(rels, cfg.path(plans_rel), plans_rel) if rels else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    output = decide(payload)
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
