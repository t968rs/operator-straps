"""Regroup a branch-commit-msg skeleton: move paths, with their message bullets, between blocks.

A skeleton block is ``[[paths], message]`` and a message lists one ``  - file: change`` bullet per path.
``move_paths`` keeps the two together so an amended grouping stays consistent; ``bullet_problems`` reports
any bullet whose file is not in its own block, which is what a hand edit of the skeleton leaves behind.
Both functions are pure: no configuration, no file access.
"""
from __future__ import annotations

import copy
import fnmatch
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from harness_lib.branch_capture import CaptureError

Block = List[Any]
Blocks = Dict[str, Block]

# A bullet opens with a hyphen at an indent under four columns; deeper lines continue the bullet above.
_BULLET = re.compile(r"^ {0,3}-\s*(.+?):\s*(.*)$")
_CONTINUATION = re.compile(r"^ {4,}\S")


def _base(path: str) -> str:
    """Last path segment of ``path``."""
    return path.rsplit("/", 1)[-1]


def _names_entry(name: str, entry: str) -> bool:
    """True when a bullet's file ``name`` (basename or path) refers to block ``entry`` (a glob allowed)."""
    return fnmatch.fnmatchcase(name, entry) or fnmatch.fnmatchcase(_base(name), _base(entry))


def _bullet_spans(lines: Sequence[str]) -> List[Tuple[str, int, int]]:
    """``(file, start, end)`` of every bullet in ``lines``; ``end`` is exclusive and covers continuations."""
    spans: List[Tuple[str, int, int]] = []
    for index, line in enumerate(lines):
        match = _BULLET.match(line)
        if match:
            spans.append((match.group(1).strip(), index, index + 1))
        elif spans and _CONTINUATION.match(line) and spans[-1][2] == index:
            spans[-1] = (spans[-1][0], spans[-1][1], index + 1)
    return spans


def bullet_problems(commits: Mapping[int, Tuple[List[str], str]]) -> List[str]:
    """One problem per bullet whose file is not among its block's entries."""
    problems: List[str] = []
    for key in sorted(commits):
        paths, message = commits[key]
        for name, _, _ in _bullet_spans(message.splitlines()):
            if not any(_names_entry(name, entry) for entry in paths):
                problems.append(f"commit {key}: bullet names {name}, not in this block")
    return problems


def _take_bullet(message: str, names: Set[str]) -> Tuple[str, Optional[List[str]]]:
    """``message`` without the first bullet whose file is in ``names``, and that bullet's lines."""
    lines = message.splitlines()
    for name, start, end in _bullet_spans(lines):
        if name in names:
            return "\n".join(lines[:start] + lines[end:]), lines[start:end]
    return message, None


def _add_bullet(message: str, bullet: List[str]) -> str:
    """``message`` with ``bullet`` after its last bullet, else at the end."""
    lines = message.splitlines()
    spans = _bullet_spans(lines)
    at = spans[-1][2] if spans else len(lines)
    return "\n".join(lines[:at] + bullet + lines[at:])


def _owners(commits: Mapping[str, Block]) -> Dict[str, str]:
    """Block key holding each entry."""
    return {path: key for key, block in commits.items() for path in block[0]}


def _with_old_sides(
        paths: Sequence[str], payload: Mapping[str, Any], owners: Mapping[str, str],
) -> List[str]:
    """``paths`` plus the old side of each renamed path, when the old side sits in the same block."""
    olds = {entry["path"]: entry.get("old_path") for entry in payload.get("captured") or []}
    extra = [
        old for path in paths
        if (old := olds.get(path)) and old not in paths and owners.get(old) == owners.get(path)
    ]
    return [*paths, *extra]


def _check_request(
        paths: Sequence[str], to: Union[int, str], commits: Mapping[str, Block], owners: Mapping[str, str],
) -> List[str]:
    """Problems with a move request: no paths, unknown paths or target, paths already in the target."""
    if not paths:
        return ["no path given to move"]
    problems = [f"path {path!r} is in no block" for path in paths if path not in owners]
    if to != "new" and str(to) not in commits:
        known = ", ".join(sorted(commits, key=int))
        problems.append(f"block {to} is not in the skeleton (blocks: {known})")
    problems += [f"path {path!r} is already in block {to}" for path in paths if owners.get(path) == str(to)]
    return problems


def _bullet_for(
        commits: Blocks, path: str, key: str, moving: Sequence[str],
) -> Tuple[Optional[List[str]], str]:
    """Take the bullet naming ``path`` out of block ``key``; a note says why none was taken."""
    shared = [q for q in commits[key][0] if q not in moving and _base(q) == _base(path)]
    if shared:
        return None, f"note: bullet for {_base(path)} is ambiguous in block {key}; left in place"
    commits[key][1], bullet = _take_bullet(str(commits[key][1]), {_base(path), path})
    return bullet, "" if bullet else f"note: no bullet for {path} in block {key}"


def _detach(
        commits: Blocks, moving: Sequence[str], requested: Sequence[str],
) -> Tuple[List[List[str]], List[str]]:
    """Remove ``moving`` from their blocks; return the bullets taken and notes on bullets not taken."""
    owners = _owners(commits)
    taken: List[List[str]] = []
    notes: List[str] = []
    for path in requested:
        bullet, note = _bullet_for(commits, path, owners[path], moving)
        taken += [bullet] if bullet else []
        notes += [note] if note else []
    for path in moving:
        commits[owners[path]][0].remove(path)
    return taken, notes


def _renumbered(order: Sequence[Block]) -> Blocks:
    """Blocks keyed 1..N in ``order``, empty blocks dropped."""
    return {str(n): block for n, block in enumerate((b for b in order if b[0]), 1)}


def _land(target: Block, bullets: List[List[str]], to: Union[int, str]) -> List[str]:
    """Add ``bullets`` to ``target``'s message; return a note per bullet when the message is empty."""
    notes: List[str] = []
    for bullet in bullets:
        if target[1]:
            target[1] = _add_bullet(str(target[1]), bullet)
        else:
            notes.append(f"note: unplaced bullet for block {to}: {' / '.join(bullet)}")
    return notes


def move_paths(
        payload: Mapping[str, Any], paths: Sequence[str], to: Union[int, str],
) -> Tuple[Dict[str, Any], List[str]]:
    """Copy of ``payload`` with ``paths`` (and each rename's old side) moved to block ``to`` or a new block.

    ``to`` is a block key or ``"new"``. The bullet naming each moved path moves with it, landing after the
    target's last bullet; a bullet that cannot be attributed, or has no message to land in, is reported in
    the returned notes instead. A new block follows the lowest-keyed source block and has an empty message.
    Emptied blocks are dropped and every block is renumbered 1..N. Raises ``CaptureError`` for an unknown
    path or block, or a path already in the target.
    """
    commits: Blocks = copy.deepcopy(dict(payload.get("commits") or {}))
    owners = _owners(commits)
    problems = _check_request(paths, to, commits, owners)
    if problems:
        raise CaptureError(problems)
    moving = _with_old_sides(paths, payload, owners)
    keys = sorted(commits, key=int)
    first = min(keys.index(owners[path]) for path in paths)
    taken, notes = _detach(commits, moving, paths)
    target: Block = [[], ""] if to == "new" else commits[str(to)]
    target[0].extend(moving)
    notes += _land(target, taken, to)
    order = [commits[key] for key in keys]
    if to == "new":
        order.insert(first + 1, target)
    return {**payload, "commits": _renumbered(order)}, notes
