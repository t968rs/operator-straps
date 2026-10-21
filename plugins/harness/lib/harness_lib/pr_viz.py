"""Diagram-block rule behind ``pr_sum.py --min-viz``.

A qualifying block is a closed fenced code block with more than ``MIN_BLOCK_CHARS`` characters between the
fences and at least one arrow glyph. ``min_viz_problems`` counts them across a draft's summary and section
bodies.
"""
from __future__ import annotations

from typing import List, Sequence

from harness_lib.pr_summary import PrDraft, _fence_blocks

MIN_BLOCK_CHARS = 200
DEFAULT_MIN_VIZ = 3
ARROWS = ("→", "←", "↑", "↓", "►", "◄", "▶", "▲", "▼", "➜", "⟶", "->", "=>")
_FENCE = "```"


def is_qualifying(lines: Sequence[str]) -> bool:
    """True when the fenced ``lines`` hold more than ``MIN_BLOCK_CHARS`` characters and an arrow."""
    text = "\n".join(lines)
    return len(text) > MIN_BLOCK_CHARS and any(arrow in text for arrow in ARROWS)


def _closed_blocks(text: str) -> List[List[str]]:
    """Fenced blocks of ``text`` that have a closing fence; an unclosed trailing fence is dropped."""
    blocks = _fence_blocks(text)
    unclosed = sum(1 for line in text.splitlines() if line.strip().startswith(_FENCE)) % 2 == 1
    return blocks[:-1] if unclosed else blocks


def count_qualifying(text: str) -> int:
    """Number of qualifying blocks in ``text``."""
    return sum(1 for block in _closed_blocks(text) if is_qualifying(block))


def min_viz_problems(draft: PrDraft, minimum: int) -> List[str]:
    """One problem line when the draft's summary and sections hold fewer than ``minimum`` qualifying blocks."""
    if minimum <= 0:
        return []
    text = "\n".join([draft.summary, *(section.body for section in draft.sections)])
    found = count_qualifying(text)
    if found >= minimum:
        return []
    return [
        f"--min-viz needs {minimum} diagram blocks (fenced, over {MIN_BLOCK_CHARS} characters, with an arrow); "
        f"found {found}",
    ]
