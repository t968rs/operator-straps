"""Vertical alignment pass of a pr-sum draft (levels 2 and 3), run by ``build`` before validation.

The pass changes only spaces in section bodies, so every line keeps its text in order:

- Markdown tables outside fences get padded cells, so their pipes line up; a separator cell keeps its
  alignment colons, which also set how the column's cells are padded.
- In the fences of flow sections, a hanging ``│`` or ``▼`` (no step text or connector above it) slides,
  with the connector run below it and any label it carries (``│yes``), up to ``MAX_SHIFT`` columns to the
  nearest column the line above feeds down, when the cells there are free.
- In a comparison fence (``pr_compare``), the gutter markers move to their most common column when the
  cells there are free, and every change tag, with the ``[CHANGE]`` header, moves to one column two spaces
  right of the widest line, within ``MONOSPACE_WIDTH``.

What the pass cannot place stays as written; ``build`` then reports it.
"""
from __future__ import annotations

import dataclasses
from collections import Counter
from typing import List, Optional, Sequence, Tuple

from harness_lib.pr_compare import TRAILING_TAG, is_comparison, markers
from harness_lib.pr_summary import (
    _CELL_SPLIT,
    _FENCE,
    _SEPARATOR_CELL,
    MONOSPACE_WIDTH,
    PrDraft,
    PrSection,
    _column_kinds,
    _feeds_down,
    _section_kind,
)

MAX_SHIFT = 4
_RUN_GLYPHS = "│▼"


def align_draft(draft: PrDraft, level: int) -> PrDraft:
    """``draft`` with every section body aligned; unchanged at level 1."""
    if level == 1:
        return draft
    sections = tuple(
        PrSection(s.heading, align_body(s.body, _section_kind(s.heading, level) == "flow"))
        for s in draft.sections
    )
    return dataclasses.replace(draft, sections=sections)


def align_body(body: str, flow: bool) -> str:
    """``body`` with its tables aligned and, when ``flow``, its fences; an unclosed fence stays as is."""
    out: List[str] = []
    table: List[str] = []
    fence: Optional[List[str]] = None
    for line in body.split("\n"):
        marker = line.strip().startswith(_FENCE)
        if fence is not None and not marker:
            fence.append(line)
        elif fence is not None:
            out += (align_fence(fence) if flow else fence) + [line]
            fence = None
        elif not marker and line.strip().startswith("|"):
            table.append(line)
        else:
            out += align_table(table) + [line]
            table = []
            fence = [] if marker else None
    return "\n".join(out + align_table(table) + (fence or []))


def _cells(row: str) -> List[str]:
    """Stripped cells of a table row; one outer pipe on each side dropped, ``\\|`` kept inside a cell."""
    inner = row.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [cell.strip() for cell in _CELL_SPLIT.split(inner)]


def _pad(cell: str, width: int, rule: str) -> str:
    """``cell`` padded to ``width`` as separator ``rule`` aligns it (right, center, else left)."""
    if rule.endswith(":") and rule.startswith(":"):
        return cell.center(width)
    return cell.rjust(width) if rule.endswith(":") else cell.ljust(width)


def _rule(cell: str, width: int) -> str:
    """Separator cell ``cell`` redrawn ``width`` wide, its colons kept."""
    left, right = cell.startswith(":"), cell.endswith(":")
    return (":" if left else "") + "-" * (width - left - right) + (":" if right else "")


def align_table(rows: Sequence[str]) -> List[str]:
    """``rows`` with cells padded so the pipes line up; unchanged unless every row has the same cell count
    and one row is a separator."""
    cells = [_cells(row) for row in rows]
    rules = [all(_SEPARATOR_CELL.fullmatch(cell) for cell in row) for row in cells]
    if len(rows) < 2 or len({len(row) for row in cells}) != 1 or not any(rules):
        return list(rows)
    separator = cells[rules.index(True)]
    widths = [
        max([3] + [len(row[col]) for row, rule in zip(cells, rules) if not rule])
        for col in range(len(separator))
    ]
    indent = rows[0][: len(rows[0]) - len(rows[0].lstrip())]
    return [
        indent + "| " + " | ".join(
            _rule(cell, w) if rule else _pad(cell, w, sep) for cell, w, sep in zip(row, widths, separator)
        ) + " |"
        for row, rule in zip(cells, rules)
    ]


def _span(line: str, column: int) -> Tuple[int, int]:
    """``(start, end)`` of the whitespace-free run of ``line`` that holds ``column``."""
    start, end = column, column + 1
    while start > 0 and not line[start - 1].isspace():
        start -= 1
    while end < len(line) and not line[end].isspace():
        end += 1
    return start, end


def _fits(line: str, span: Tuple[int, int], shift: int) -> bool:
    """True when the run at ``span`` moved by ``shift`` lands on blanks with a blank (or an edge) on each
    side, its own cells counted as blank."""
    start, end = span
    rest = line[:start] + " " * (end - start) + line[end:]
    lo, hi = start + shift, end + shift
    return lo >= 0 and not rest[max(lo - 1, 0):hi + 1].strip()


def _move(line: str, span: Tuple[int, int], shift: int) -> str:
    """``line`` with the run at ``span`` moved by ``shift`` columns, trailing blanks dropped."""
    start, end = span
    cells = list((line[:start] + " " * (end - start) + line[end:]).ljust(end + shift))
    cells[start + shift:end + shift] = line[start:end]
    return "".join(cells).rstrip()


def _run(lines: Sequence[str], row: int, column: int) -> List[int]:
    """Rows of the connector run that starts at ``row``: each holds ``│`` or ``▼`` at ``column`` as the
    first character of its run; it stops after a ``▼``."""
    rows: List[int] = []
    for below in range(row, len(lines)):
        line = lines[below]
        if column >= len(line) or line[column] not in _RUN_GLYPHS or _span(line, column)[0] != column:
            break
        rows.append(below)
        if line[column] == "▼":
            break
    return rows


def _shift(lines: List[str], row: int, column: int) -> None:
    """Slide the run hanging at ``(row, column)`` to the nearest column the line above feeds down."""
    rows = _run(lines, row, column)
    above = _column_kinds(lines[row - 1])
    for distance in range(1, MAX_SHIFT + 1):
        for shift in (-distance, distance):
            spans = [_span(lines[r], column) for r in rows]
            if rows and column + shift >= 0 and _feeds_down(above, column + shift) and all(
                    _fits(lines[r], span, shift) for r, span in zip(rows, spans)):
                for r, span in zip(rows, spans):
                    lines[r] = _move(lines[r], span, shift)
                return


def snap_connectors(lines: Sequence[str]) -> List[str]:
    """``lines`` with each hanging connector run slid under the step text above it, where one fits."""
    out = list(lines)
    for row in range(1, len(out)):
        kinds = _column_kinds(out[row - 1])
        hanging = [
            c for c, glyph in enumerate(out[row]) if glyph in _RUN_GLYPHS and not _feeds_down(kinds, c)
        ]
        for column in reversed(hanging):
            if column < len(out[row]) and out[row][column] in _RUN_GLYPHS:
                _shift(out, row, column)
    return out


def align_markers(lines: Sequence[str]) -> List[str]:
    """``lines`` with every gutter marker in one column: the first marker column, most common first (ties:
    the leftmost), that every marker can reach; unchanged when none can be reached by all."""
    found = markers(lines)
    counts = Counter(column for _, column, _ in found)
    if len(counts) < 2:
        return list(lines)
    for target in sorted(counts, key=lambda column: (-counts[column], column)):
        if all(_fits(lines[row], (column, column + 2), target - column) for row, column, _ in found):
            out = list(lines)
            for row, column, _ in found:
                out[row] = _move(out[row], (column, column + 2), target - column)
            return out
    return list(lines)


def align_tags(lines: Sequence[str]) -> List[str]:
    """``lines`` with the ``[CHANGE]`` header and every trailing change tag in one column, two spaces right
    of the widest line; the tagged lines alone set the column when that would pass ``MONOSPACE_WIDTH``."""
    parts = [TRAILING_TAG.match(line) for line in lines]
    texts = [(m.group("text") or "") if m else line.rstrip() for m, line in zip(parts, lines)]
    tagged = [len(text) for m, text in zip(parts, texts) if m]
    if not tagged:
        return list(lines)
    widest = max(len(m.group("tag")) for m in parts if m)
    column = max(len(text) for text in texts) + 2
    column = column if column + widest <= MONOSPACE_WIDTH else max(tagged) + 2
    if column + widest > MONOSPACE_WIDTH:
        return list(lines)
    return [text.ljust(column) + m.group("tag") if m else line for m, text, line in zip(parts, texts, lines)]


def align_fence(block: Sequence[str]) -> List[str]:
    """One flow fence aligned (connectors; markers and tags in a comparison fence); ``block`` itself when
    nothing moved or when any line's text would change."""
    lines = snap_connectors([line.expandtabs() for line in block])
    if lines and is_comparison(lines[0]):
        lines = align_tags(align_markers(lines))
    same_text = len(lines) == len(block) and all(
        "".join(new.split()) == "".join(old.split()) for new, old in zip(lines, block)
    )
    unmoved = [line.rstrip() for line in lines] == [line.expandtabs().rstrip() for line in block]
    return list(block) if unmoved or not same_text else lines
