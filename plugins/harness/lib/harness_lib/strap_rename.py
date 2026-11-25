"""The file work of ``strap.py rename``: the moves a rename needs, the old name's forms swapped inside the
moved files, and the old name reported where it lingers in other tracked files.

A name has three forms: kebab (``demo-skill``), snake (``demo_skill``) and title (``Demo Skill``). The kebab
and title forms swap as whole words; the snake form also swaps inside an identifier (``demo_skill_api``,
``test_demo_skill_extra.py``), since modules and test files are made from it. A move whose target exists is
refused before anything moves; each move done is recorded so a failure later in the rename undoes it.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

Move = Tuple[str, str]


# --- name forms -------------------------------------------------------------------------------------------

def name_forms(name: str) -> Tuple[str, str, str]:
    """``(kebab, snake, title)`` of a hyphenated skill name."""
    return name, name.replace("-", "_"), " ".join(word.capitalize() for word in name.split("-"))


def _kebab(form: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9-]){re.escape(form)}(?![A-Za-z0-9-])")


def _word(form: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(form)}(?![A-Za-z0-9])")


def _patterns(name: str) -> List[re.Pattern]:
    kebab, snake, title = name_forms(name)
    return [_kebab(kebab), *([_word(snake)] if snake != kebab else []), _word(title)]


def _underscored(match: re.Match) -> bool:
    """True when an underscore touches the match, so it sits inside a snake identifier."""
    text, start, end = match.string, match.start(), match.end()
    return (start > 0 and text[start - 1] == "_") or (end < len(text) and text[end] == "_")


def swapper(old: str, new: str) -> Callable[[str], str]:
    """A function replacing each form of ``old`` in a text with the same form of ``new``. A one-word old name
    has one spelling for kebab and snake, so the context picks: the snake form inside an identifier, the
    kebab form elsewhere."""
    (old_kebab, old_snake, old_title), (kebab, snake, title) = name_forms(old), name_forms(new)
    subs: List[Tuple[re.Pattern, Callable[[re.Match], str]]] = []
    if old_snake != old_kebab:
        subs += [(_kebab(old_kebab), lambda m: kebab), (_word(old_snake), lambda m: snake)]
    else:
        subs.append((_kebab(old_kebab), lambda m: snake if _underscored(m) else kebab))
    subs.append((_word(old_title), lambda m: title))

    def swap(text: str) -> str:
        for pattern, replace in subs:
            text = pattern.sub(replace, text)
        return text
    return swap


def names_old(text: str, old: str) -> bool:
    """True when ``text`` holds any form of ``old``."""
    return any(pattern.search(text) for pattern in _patterns(old))


def renamed_file(path: str, old: str, new: str) -> Optional[str]:
    """``path`` with the old snake form in its file name replaced, or None when the name holds none."""
    posix = PurePosixPath(path)
    pattern = _word(name_forms(old)[1])
    if not pattern.search(posix.name):
        return None
    return str(posix.with_name(pattern.sub(name_forms(new)[1], posix.name)))


# --- git ---------------------------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")


def tracked(root: Path, rel: str) -> bool:
    """True when git tracks ``rel`` or any file under it."""
    return bool(_git(root, "ls-files", "--", rel).stdout.strip())


# --- moves -------------------------------------------------------------------------------------------------

def move_problems(root: Path, moves: Sequence[Move]) -> List[str]:
    """Refusals for ``moves`` before any runs: a target that exists while its source is still there."""
    problems = []
    for old, new in moves:
        if not (root / old).exists() or not (root / new).exists():
            continue
        if (root / old).is_dir() and not tracked(root, old):
            problems.append(f"{old} still exists; move it to {new} (remove leftover untracked files)")
        else:
            problems.append(f"move target {new} already exists")
    return problems


def pending_moves(root: Path, moves: Iterable[Move]) -> List[Move]:
    """The moves still to run: each pair whose source exists and whose target does not, deduplicated; a pair
    the developer already moved by hand is dropped."""
    out: List[Move] = []
    for old, new in moves:
        if old != new and (old, new) not in out and (root / old).exists() and not (root / new).exists():
            out.append((old, new))
    return out


def run_moves(root: Path, moves: Sequence[Move], done: List[Move]) -> None:
    """Run each move (``git mv`` for a tracked path, a plain rename otherwise), recording each in ``done``."""
    for old, new in moves:
        (root / new).parent.mkdir(parents=True, exist_ok=True)
        if tracked(root, old):
            result = _git(root, "mv", old, new)
            if result.returncode != 0:
                raise OSError(f"git mv {old} {new} failed: {result.stderr.strip()}")
        else:
            (root / old).rename(root / new)
        done.append((old, new))


def undo_moves(root: Path, done: Sequence[Move]) -> None:
    """Move each done move back, last first; a move that cannot be undone is left as it is."""
    for old, new in reversed(done):
        if not (root / new).exists() or (root / old).exists():
            continue
        if tracked(root, new):
            _git(root, "mv", new, old)
        else:
            (root / new).rename(root / old)


# --- swap inside files -------------------------------------------------------------------------------------

@dataclass
class Swaps:
    """The files a swap rewrote: their original bytes, and one ``path:line`` per changed line."""
    originals: Dict[str, bytes] = field(default_factory=dict)
    lines: List[str] = field(default_factory=list)


def swap_files(root: Path, paths: Iterable[str], swap: Callable[[str], str], swaps: Swaps) -> None:
    """Rewrite each existing text file of ``paths`` through ``swap``, line by line, keeping its line ends."""
    for rel in dict.fromkeys(paths):
        path = root / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.splitlines(keepends=True)
        changed = [swap(line) for line in lines]
        numbers = [n for n, (a, b) in enumerate(zip(lines, changed), start=1) if a != b]
        if numbers:
            swaps.originals[rel] = raw
            path.write_bytes("".join(changed).encode("utf-8"))
            swaps.lines += [f"{rel}:{n}" for n in numbers]


def restore_files(root: Path, swaps: Swaps) -> None:
    """Put back the original bytes of every file the swap rewrote."""
    for rel, raw in swaps.originals.items():
        (root / rel).write_bytes(raw)


# --- report ------------------------------------------------------------------------------------------------

def stale_hits(root: Path, old: str, skip: Sequence[str]) -> List[str]:
    """``path:line`` of each tracked text line naming a form of ``old``, outside the files and folders in
    ``skip``."""
    kebab, snake, title = name_forms(old)
    grep = _git(root, "grep", "-n", "-I", "-F", "-e", kebab, "-e", snake, "-e", title)
    out = []
    for line in grep.stdout.splitlines():
        rel, _, rest = line.partition(":")
        number, _, text = rest.partition(":")
        if any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in skip):
            continue
        if names_old(text, old):
            out.append(f"{rel}:{number}")
    return out
