"""Comparison flow rules of a pr-sum ``Behavior:`` section: one fence, BEFORE / AFTER / [CHANGE] columns.

The fence's first line is the header: ``BEFORE``, then ``AFTER``, then ``[CHANGE]``. A gutter marker between
the two flows pairs each changed step with one tag in the ``[CHANGE]`` column:

- ``<>``: the BEFORE step on its left becomes the AFTER step on its right; tag ``[changed]``.
- ``>>``: an AFTER step BEFORE lacks; tag ``[new]``.
- ``<<``: a BEFORE step AFTER drops; tag ``[removed]``.

A step runs from its marker line down through the lines that continue its text (a line holding text other
than connectors, arms and markers). ``[[`` and ``]]`` mark the changed words of an AFTER step and may span
lines. Every check reads the lines with tabs expanded to 8-column stops; columns print 1-based.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

CHANGE_HEADER = "[CHANGE]"
MARKER_TAGS: Dict[str, str] = {"<>": "[changed]", ">>": "[new]", "<<": "[removed]"}
TAG_MARKERS: Dict[str, str] = {tag: marker for marker, tag in MARKER_TAGS.items()}
TRAILING_TAG = re.compile(r"^(?P<text>.*?\S)?\s*(?P<tag>\[(?:changed|new|removed|CHANGE)\])\s*$")
_TAG = re.compile(r"(?<!\[)\[(?:changed|new|removed)\](?!\])")
_BEFORE = re.compile(r"BEFORE\b")
_AFTER = re.compile(r"\bAFTER\b")
_UP_GLYPHS = "│▼├└"
_DOWN_GLYPHS = "│▼├┤┬┼┌┐╭╮"
_ARM_GLYPHS = "─━═►▶◄◀→←└┘┴╰╯"
_GLYPHS = _UP_GLYPHS + _DOWN_GLYPHS + _ARM_GLYPHS


def is_comparison(first_line: str) -> bool:
    """True when a fence's first line holds BEFORE, AFTER and the ``[CHANGE]`` header."""
    line = first_line.strip()
    return bool(_BEFORE.match(line) and _AFTER.search(line)) and CHANGE_HEADER in line


def markers(lines: Sequence[str]) -> List[Tuple[int, int, str]]:
    """``(row, column, marker)`` of every gutter marker below the header, 0-based."""
    return [
        (row, token.start(), token.group())
        for row, line in enumerate(lines) if row
        for token in re.finditer(r"\S+", line) if token.group() in MARKER_TAGS
    ]


def _is_step(line: str) -> bool:
    """True when ``line`` holds step text: a token that is no tag, no marker and starts with no glyph."""
    tokens = _TAG.sub(" ", line).split()
    return any(token not in MARKER_TAGS and token[0] not in _GLYPHS for token in tokens)


def _steps(lines: Sequence[str], found: Sequence[Tuple[int, int, str]]) -> Dict[int, Tuple[int, str]]:
    """Owning ``(marker row, marker)`` of each row inside a marked step: the marker line and the step lines
    after it, up to the next marker line or the first line without step text."""
    owner: Dict[int, Tuple[int, str]] = {}
    marked = {row for row, _, _ in found}
    for row, _, marker in found:
        owner[row] = (row, marker)
        below = row + 1
        while below < len(lines) and below not in marked and _is_step(lines[below]):
            owner[below] = (row, marker)
            below += 1
    return owner


def _tags(lines: Sequence[str]) -> List[Tuple[int, int, str]]:
    """``(row, column, tag)`` of every change tag below the header, 0-based."""
    return [(row, m.start(), m.group()) for row, line in enumerate(lines) if row for m in _TAG.finditer(line)]


def _header_problems(where: str, header: str) -> List[str]:
    """The header names its columns in the order BEFORE, AFTER, [CHANGE]."""
    after = _AFTER.search(header)
    if after and after.start() < header.index(CHANGE_HEADER):
        return []
    return [f"{where}: the first line names the columns in the order BEFORE, AFTER, {CHANGE_HEADER}"]


def _tag_problems(where: str, lines: Sequence[str], owner: Dict[int, Tuple[int, str]]) -> List[str]:
    """Each tag is the last text of its line, sits on a marked step and matches that step's marker."""
    problems = []
    for row, column, tag in _tags(lines):
        at = f"{where}, fence line {row + 1}"
        if lines[row][column + len(tag):].strip():
            problems.append(f"{at}: {tag} is not the last text on its line")
        if row not in owner:
            problems.append(f"{at}: {tag} has no marker on its step; mark the step '{TAG_MARKERS[tag]}'")
        elif MARKER_TAGS[owner[row][1]] != tag:
            marker = owner[row][1]
            problems.append(f"{at}: marker '{marker}' takes {MARKER_TAGS[marker]}, not {tag}")
    return problems


def _step_tag_problems(where: str, lines: Sequence[str], owner: Dict[int, Tuple[int, str]]) -> List[str]:
    """Each marked step holds exactly one tag."""
    counts = Counter(owner[row][0] for row, _, _ in _tags(lines) if row in owner)
    problems = []
    for start, marker in sorted(set(owner.values())):
        found = counts.get(start, 0)
        if found != 1:
            need = f"needs {MARKER_TAGS[marker]}" if not found else f"holds {found} tags; one per step"
            problems.append(f"{where}, fence line {start + 1}: the step marked '{marker}' {need}")
    return problems


def _column_problems(where: str, lines: Sequence[str], found: Sequence[Tuple[int, int, str]]) -> List[str]:
    """Every tag starts at the ``[CHANGE]`` column; every marker sits in one gutter column."""
    column = lines[0].index(CHANGE_HEADER)
    problems = [
        f"{where}, fence line {row + 1}: {tag} starts at column {start + 1}; the {CHANGE_HEADER} column is "
        f"{column + 1}"
        for row, start, tag in _tags(lines) if start != column
    ]
    gutter = sorted({start + 1 for _, start, _ in found})
    return problems + ([] if len(gutter) < 2 else [
        f"{where}: markers sit in columns {', '.join(map(str, gutter))}; use one gutter column",
    ])


def _emphasis_problems(where: str, lines: Sequence[str]) -> List[str]:
    """``[[`` and ``]]`` alternate, opening first, and close before the fence ends."""
    opened: Optional[int] = None
    for row, line in enumerate(lines):
        for mark in re.finditer(r"\[\[|\]\]", line):
            if (mark.group() == "[[") == (opened is not None):
                return [f"{where}, fence line {row + 1}: unbalanced {mark.group()} emphasis"]
            opened = row if mark.group() == "[[" else None
    return [] if opened is None else [f"{where}, fence line {opened + 1}: [[ emphasis never closes with ]]"]


def comparison_problems(name: str, fence: int, block: Sequence[str]) -> List[str]:
    """Every comparison rule broken by one fence (1-based ``fence``) of section ``name``."""
    where = f"{name}: fence {fence}"
    lines = [line.expandtabs() for line in block]
    found = markers(lines)
    problems = _header_problems(where, lines[0])
    problems += [
        f"{where}, fence line {row + 1}: {count} markers on one line; one step per marker"
        for row, count in Counter(row for row, _, _ in found).items() if count > 1
    ]
    if not found:
        problems.append(f"{where}: a comparison flow marks each changed step with '<>', '>>' or '<<'")
    owner = _steps(lines, found)
    problems += _tag_problems(where, lines, owner) + _step_tag_problems(where, lines, owner)
    return problems + _column_problems(where, lines, found) + _emphasis_problems(where, lines)
