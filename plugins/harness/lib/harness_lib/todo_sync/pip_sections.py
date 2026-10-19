"""PIP Markdown parser: ATX headings, the section each heading opens, and its checkbox states.

A section runs from its heading to the next heading of the same or a higher level (sub-headings stay
inside). Checkboxes are list items ``- [ ]``, ``- [x]``, ``- [X]`` (``*`` and ``+`` bullets too) at any
indent. Lines inside fenced code blocks are neither headings nor checkboxes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_BOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]")
_FENCE = re.compile(r"^\s*(```|~~~)")
_KEY_STRIP = "`*_[]# "
_TASK_WORD = re.compile(r"^task\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Heading:
    """One ATX heading: level 1-6, its text and 1-based line."""

    level: int
    text: str
    line: int


@dataclass(frozen=True)
class Checkbox:
    """One task-list box and its 1-based line."""

    checked: bool
    line: int


@dataclass(frozen=True)
class PipDoc:
    """Every heading and checkbox of one PIP file, in file order."""

    headings: Tuple[Heading, ...]
    boxes: Tuple[Checkbox, ...]


@dataclass(frozen=True)
class Section:
    """The checkboxes between a heading and the next heading of the same or higher level."""

    heading: Heading
    boxes: Tuple[Checkbox, ...]

    @property
    def unchecked(self) -> Tuple[Checkbox, ...]:
        """Open boxes, in file order."""
        return tuple(b for b in self.boxes if not b.checked)


def parse_pip(text: str) -> PipDoc:
    """Headings and checkboxes of ``text``, skipping fenced code blocks."""
    headings: List[Heading] = []
    boxes: List[Checkbox] = []
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = _HEADING.match(line)
        if heading:
            headings.append(Heading(len(heading.group(1)), heading.group(2), n))
            continue
        box = _BOX.match(line)
        if box:
            boxes.append(Checkbox(box.group(1) != " ", n))
    return PipDoc(tuple(headings), tuple(boxes))


def section_key(raw: str) -> str:
    """An item's ``markdown_section`` without any ``path#`` prefix or leading ``#``."""
    return raw.strip().rpartition("#")[2].strip()


def slug(text: str) -> str:
    """GitHub-style heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _bounded_prefix(text: str, key: str) -> bool:
    """``text`` starts with ``key`` followed by a non-alphanumeric character or the end."""
    if not text.startswith(key):
        return False
    rest = text[len(key):]
    return not rest or not rest[0].isalnum()


def _matches(heading: Heading, key: str) -> bool:
    """Heading text (markup, a literal ``#`` and a ``Task`` word dropped) starts with ``key`` at a
    boundary, or the heading's slug equals ``key`` or starts with ``key`` and a hyphen."""
    lowered = key.lower()
    text = _TASK_WORD.sub("", heading.text.replace("`", "").lstrip(_KEY_STRIP)).lower()
    anchor = slug(heading.text)
    return (_bounded_prefix(text, lowered) or anchor == lowered
            or (anchor.startswith(lowered) and anchor[len(lowered):][:1] == "-"))


def find_section(doc: PipDoc, key: str) -> Optional[Section]:
    """The first section whose heading starts with ``key`` (at a boundary) or whose slug equals it."""
    for i, heading in enumerate(doc.headings):
        if not _matches(heading, key):
            continue
        end = next((h.line for h in doc.headings[i + 1:] if h.level <= heading.level), None)
        boxes = tuple(b for b in doc.boxes if b.line > heading.line and (end is None or b.line < end))
        return Section(heading, boxes)
    return None
