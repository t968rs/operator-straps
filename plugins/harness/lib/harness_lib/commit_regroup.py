"""Regroup a branch-commit-msg skeleton: move paths, with their message bullets, between blocks.

A skeleton block is ``[[paths], message]`` and a message lists one ``  - file: change`` bullet per path.
``move_paths`` keeps the two together so an amended grouping stays consistent; ``bullet_problems`` reports
any bullet that names a file of another block and none of its own, which is what a hand edit of the
skeleton leaves behind.
Both functions are pure: no configuration, no file access.
"""
from __future__ import annotations

import copy
import fnmatch
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

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


def _names_any(name: str, entries: Sequence[str]) -> bool:
    """True when a bullet's file ``name`` refers to any of ``entries``."""
    return any(_names_entry(name, entry) for entry in entries)


def _foreign_owner(
        name: str, key: int, commits: Mapping[int, Tuple[List[str], str]],
) -> Optional[int]:
    """Lowest other block whose entries ``name`` refers to, when none of block ``key``'s entries match."""
    if _names_any(name, commits[key][0]):
        return None
    others = (other for other in sorted(commits) if other != key and _names_any(name, commits[other][0]))
    return next(others, None)


def bullet_problems(commits: Mapping[int, Tuple[List[str], str]]) -> List[str]:
    """One problem per bullet that names a file of another block and none of its own.

    A bullet that names no entry of any block (an abbreviated name, a folder) is left alone: a plain build
    accepts it, so an amendment that never touched its block must too.
    """
    problems: List[str] = []
    for key in sorted(commits):
        for name, _, _ in _bullet_spans(commits[key][1].splitlines()):
            other = _foreign_owner(name, key, commits)
            if other is not None:
                problems.append(f"commit {key}: bullet names {name}, which is in commit {other}")
    return problems


def _add_bullet(message: str, bullet: List[str]) -> str:
    """``message`` with ``bullet`` after its last bullet, else at the end."""
    lines = message.splitlines()
    spans = _bullet_spans(lines)
    at = spans[-1][2] if spans else len(lines)
    return "\n".join(lines[:at] + bullet + lines[at:])


def _owners(commits: Mapping[str, Block]) -> Dict[str, str]:
    """Block key holding each entry."""
    return {path: key for key, block in commits.items() for path in block[0]}


def _old_sides(
        paths: Sequence[str], payload: Mapping[str, Any], owners: Mapping[str, str],
) -> Dict[str, str]:
    """Old side of each renamed path in ``paths``, keyed by new path, when it sits in the same block."""
    olds = {entry["path"]: entry.get("old_path") for entry in payload.get("captured") or []}
    return {
        path: old for path in paths
        if (old := olds.get(path)) and old not in paths and owners.get(old) == owners.get(path)
    }


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
        commits: Blocks, path: str, key: str, moving: Sequence[str], old: Optional[str] = None,
) -> Tuple[Optional[List[str]], str]:
    """Take the bullets naming ``path`` (or its rename's ``old`` side) out of block ``key``.

    Matching is that of ``bullet_problems`` (basename, path or glob entry). A matching bullet that also names
    an entry staying in the block is left in place; the note says why no bullet was taken.
    """
    lines = str(commits[key][1]).splitlines()
    names = [path, old] if old else [path]
    spans = [(name, s, e) for name, s, e in _bullet_spans(lines) if _names_any(name, names)]
    staying = [q for q in commits[key][0] if q not in moving]
    if any(_names_any(name, staying) for name, _, _ in spans):
        return None, f"note: bullet for {_base(path)} is ambiguous in block {key}; left in place"
    if not spans:
        return None, f"note: no bullet for {path} in block {key}"
    drop = {index for _, s, e in spans for index in range(s, e)}
    commits[key][1] = "\n".join(line for index, line in enumerate(lines) if index not in drop)
    return [line for _, s, e in spans for line in lines[s:e]], ""


def _detach(
        commits: Blocks, moving: Sequence[str], requested: Sequence[str], olds: Mapping[str, str],
) -> Tuple[List[List[str]], List[str]]:
    """Remove ``moving`` from their blocks; return the bullets taken and notes on bullets not taken."""
    owners = _owners(commits)
    taken: List[List[str]] = []
    notes: List[str] = []
    for path in requested:
        bullet, note = _bullet_for(commits, path, owners[path], moving, olds.get(path))
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


def _shape_problems(payload: Mapping[str, Any]) -> List[str]:
    """Problems that would stop a move: non-numeric block keys, misshapen blocks, path-less captured entries."""
    commits = payload.get("commits") or {}
    if not isinstance(commits, Mapping):
        return ["commits must be an object keyed by block number"]
    problems: List[str] = []
    for key, block in commits.items():
        if not str(key).isdigit():
            problems.append(f"block key {key!r} is not a block number")
        if not (isinstance(block, list) and len(block) == 2 and isinstance(block[0], list)
                and isinstance(block[1], str)):
            problems.append(f"block {key} is not [[paths], message]")
    captured = payload.get("captured") or []
    well_formed = isinstance(captured, list) and all(isinstance(e, dict) and "path" in e for e in captured)
    if not well_formed:
        problems.append("a captured entry has no path")
    return problems


def landed_key(blocks: Mapping[str, Block], path: str) -> str:
    """Key of the block holding ``path`` in a renumbered skeleton: where a move of that path landed."""
    return next(key for key, block in blocks.items() if path in block[0])


def move_paths(
        payload: Mapping[str, Any], paths: Sequence[str], to: Union[int, str],
) -> Tuple[Dict[str, Any], List[str]]:
    """Copy of ``payload`` with ``paths`` (and each rename's old side) moved to block ``to`` or a new block.

    ``to`` is a block key or ``"new"``. Repeated paths count once. The bullet naming each moved path moves
    with it, landing after the target's last bullet; a bullet that cannot be attributed, or has no message to
    land in, is reported in the returned notes instead, naming the target by its final key. A new block
    follows the lowest-keyed source block and has an empty message. Emptied blocks are dropped and every
    block is renumbered 1..N; ``landed_key`` finds the moved paths' block in the result. Raises
    ``CaptureError`` for a malformed skeleton, an unknown path or block, or a path already in the target.
    """
    problems = _shape_problems(payload)
    if problems:
        raise CaptureError(problems)
    paths = list(dict.fromkeys(paths))
    commits: Blocks = copy.deepcopy(dict(payload.get("commits") or {}))
    owners = _owners(commits)
    problems = _check_request(paths, to, commits, owners)
    if problems:
        raise CaptureError(problems)
    olds = _old_sides(paths, payload, owners)
    moving = [*paths, *olds.values()]
    keys = sorted(commits, key=int)
    first = min(keys.index(owners[path]) for path in paths)
    taken, notes = _detach(commits, moving, paths, olds)
    target: Block = [[], ""] if to == "new" else commits[str(to)]
    target[0].extend(moving)
    order = [commits[key] for key in keys]
    if to == "new":
        order.insert(first + 1, target)
    renumbered = _renumbered(order)
    notes += _land(target, taken, landed_key(renumbered, paths[0]))
    return {**payload, "commits": renumbered}, notes
