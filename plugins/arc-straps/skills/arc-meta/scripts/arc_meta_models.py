"""arc-meta: the records the ``arc-meta`` skill API and writers return, their enums and field constraints.

Enums are ``str`` enums, so a value compares equal to, and serializes as, its plain string. Every model
forbids extra keys and is frozen: the API builds each record once from the toolbox archive and the canonical
XML, and nothing downstream edits it. Imports only the standard library and pydantic, and avoids pydantic
features newer than 2.4 (the ArcGIS Pro environment pins an older pydantic).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class ApiError(ValueError):
    """A refused ``arc-meta`` call; the message names the defect."""


class ParamType(str, Enum):
    """A parameter's type as the canonical XML spells it; ``tool.content`` mixes cases."""

    REQUIRED = "Required"
    OPTIONAL = "Optional"
    DERIVED = "Derived"


class Direction(str, Enum):
    """A parameter's direction as the canonical XML spells it; ``tool.content`` uses ``in`` / ``out``."""

    INPUT = "Input"
    OUTPUT = "Output"


class ProblemCode(str, Enum):
    """One defect kind ``check_canonical`` or ``check_applied`` reports."""

    UNKNOWN_PARAM = "unknown_param"
    MISSING_PARAM = "missing_param"
    TYPE_MISMATCH = "type_mismatch"
    DIRECTION_MISMATCH = "direction_mismatch"
    PREFIXED_DISPLAYNAME = "prefixed_displayname"
    NON_ASCII = "non_ascii"
    THUMBNAIL = "thumbnail"
    UNSUPPORTED_TAG = "unsupported_tag"
    DEEP_NESTING = "deep_nesting"
    UNPARSEABLE = "unparseable"
    HOVER_UNWIRED = "hover_unwired"
    HOVER_STALE = "hover_stale"
    HOVER_STYLE_STALE = "hover_style_stale"
    PAGE_STALE = "page_stale"
    PAGE_STYLE_STALE = "page_style_stale"
    PAGE_IMAGE_STALE = "page_image_stale"


class Surface(str, Enum):
    """Which part of the archive an apply call writes."""

    RC = "rc"
    PAGE = "page"
    TOOLBOX = "toolbox"


class ParamRow(BaseModel):
    """One ``tool.content`` parameter: the join key and what the dialog shows for it."""

    model_config = _MODEL_CONFIG

    name: str = Field(min_length=1)
    title: str
    type: ParamType
    direction: Direction
    datatype: str
    hover_wired: bool
    symbology: Optional[str] = None
    values: List[str] = Field(default_factory=list)
    default: Optional[str] = None


class Problem(BaseModel):
    """One defect; ``param`` is None for a tool-level defect (summary, usage, the file as a whole)."""

    model_config = _MODEL_CONFIG

    code: ProblemCode
    tool: str = Field(min_length=1)
    param: Optional[str] = None
    detail: str = Field(min_length=1)


class ToolSources(BaseModel):
    """Where a tool's behavior lives: the entry module, the validator and the registry's claim."""

    model_config = _MODEL_CONFIG

    tool: str = Field(min_length=1)
    entry: Optional[str] = None
    entry_exists: bool = False
    embedded_script: Optional[str] = None
    validator: Optional[str] = None
    registry_path: Optional[str] = None
    registry_stale: bool = False


class ApplyOutcome(BaseModel):
    """What one apply call found and, with ``apply=True``, wrote.

    ``changed``: the archive differs from what the canonical source produces. ``applied``: the archive was
    rewritten in this call (``apply=True`` and ``changed``). ``lines``: the report, one string per line.
    """

    model_config = _MODEL_CONFIG

    surface: Surface
    tool: Optional[str] = None
    changed: bool
    applied: bool
    lines: List[str] = Field(default_factory=list)
