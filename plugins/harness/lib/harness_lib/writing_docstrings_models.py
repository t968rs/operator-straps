"""Writing-docstrings: the tiers, layouts, labels and flags of the docstring convention, and one report row.

Enums are ``str`` enums, so a value serializes as its plain string. ``SymbolReport`` forbids extra keys. The
analysis module (``writing_docstrings_api``) builds the rows; this module imports no other ``harness_lib``
module.
"""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field

FULL_MIN_LINES = 50
FULL_MIN_FORKS = 2
PLACEHOLDER_WORDS = 4

#: Compact-layout labels in their required order; labels outside this list are not ordered.
SECTION_ORDER = ("Operation", "Tries", "Columns", "Rules", "Returns", "Raises", "Notes")
#: Every label the convention allows: the compact labels plus the full-layout ones.
KNOWN_LABELS = SECTION_ORDER + ("Parameters", "Example")
#: Flag names a report row can carry, in the order they are checked.
FLAG_NAMES = ("long-lines", "single-backticks", "citation", "section-order", "unknown-label", "misaligned",
              "blank", "separator-line")


class Tier(str, Enum):
    """A suggested docstring tier."""

    BRIEF = "1-brief"
    COMPACT = "2-compact"
    FULL = "3-full"


class Layout(str, Enum):
    """The layout an existing docstring is in."""

    NONE = "none"
    BLANK = "blank"
    FULL = "full"
    COMPACT = "compact"
    PLACEHOLDER = "placeholder?"
    BRIEF = "brief"
    PROSE = "prose"


def suggest_tier(lines: int, forks: int) -> Tier:
    """Brief when there are no forks; full when long and forked; compact otherwise."""
    if forks == 0:
        return Tier.BRIEF
    if lines > FULL_MIN_LINES and forks >= FULL_MIN_FORKS:
        return Tier.FULL
    return Tier.COMPACT


class SymbolReport(BaseModel):
    """One function or method: its size, forks, suggested tier, current layout and format flags."""

    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=1)
    qualname: str = Field(min_length=1)
    lines: int = Field(ge=0)
    forks: int = Field(ge=0)
    suggest: Tier
    current: Layout
    flags: List[str] = Field(default_factory=list)

    def row(self) -> str:
        """The printed line: ``<line> <qualname> lines= forks= suggest= current= [flags]``."""
        text = (f"{self.line:>5} {self.qualname} lines={self.lines} forks={self.forks} "
                f"suggest={self.suggest.value} current={self.current.value}")
        return text + (f" [{', '.join(self.flags)}]" if self.flags else "")
