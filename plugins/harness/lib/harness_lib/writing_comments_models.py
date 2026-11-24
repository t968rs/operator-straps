"""Models of the writing-comments section report: a module's dividers and the flags its comments raise."""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field

_CLOSED = ConfigDict(extra="forbid", frozen=True)


class DividerLevel(str, Enum):
    """A major divider opens a top-level group; a minor one a group inside it."""

    MAJOR = "major"
    MINOR = "minor"


class FlagKind(str, Enum):
    """``width``: a divider line off the configured width; ``style``: a separator comment in no canonical
    form; ``banner``: a rule outside a complete rule / title / rule banner."""

    WIDTH = "width"
    STYLE = "style"
    BANNER = "banner"


class Divider(BaseModel):
    """One canonical divider, at the 1-based line where it starts."""

    model_config = _CLOSED

    line: int = Field(ge=1)
    level: DividerLevel
    title: str = Field(min_length=1)


class CommentFlag(BaseModel):
    """One comment line off the convention, with its text as written (indentation removed)."""

    model_config = _CLOSED

    line: int = Field(ge=1)
    kind: FlagKind
    text: str


class SectionReport(BaseModel):
    """Every divider and every flag of one source text, each list in line order."""

    model_config = _CLOSED

    dividers: List[Divider] = Field(default_factory=list)
    flags: List[CommentFlag] = Field(default_factory=list)
