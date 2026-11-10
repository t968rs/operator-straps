"""arc-help-pages: the records the source reader, the page builder and the checks share.

Enums are ``str`` enums, so a value compares equal to, and serializes as, its plain string. Every model
forbids extra keys and is frozen: each record is built once from the canonical XML, the archive or a page
fragment, and nothing downstream edits it. Imports only the standard library and pydantic.
"""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class HelpError(ValueError):
    """A refused arc-help-pages call; the message names the defect."""


class FragmentError(HelpError):
    """A page fragment that breaks the fragment contract; the message names the fragment."""


class ParamKind(str, Enum):
    """A parameter's type as the canonical XML spells it."""

    REQUIRED = "Required"
    OPTIONAL = "Optional"
    DERIVED = "Derived"


class HelpProblemCode(str, Enum):
    """The defect a help check reports."""

    HELP_PAGE_STALE = "help_page_stale"
    HELP_PAGE_UNLINKED = "help_page_unlinked"
    FRAGMENT_INVALID = "fragment_invalid"
    LINK_TARGET_MISSING = "link_target_missing"
    LINK_OUTSIDE_CHECKOUT = "link_outside_checkout"
    LINK_RELATIVE = "link_relative"


class ParamDoc(BaseModel):
    """One parameter of a tool: canonical attributes plus the reference text as HTML."""

    model_config = _MODEL_CONFIG

    name: str
    displayname: str
    type: ParamKind
    direction: str
    datatype: str
    reference_html: str


class ToolDoc(BaseModel):
    """What a help page is built from: titles, summary, toolbox alias and parameters in dialog order."""

    model_config = _MODEL_CONFIG

    name: str
    displayname: str
    summary: str
    alias: str
    params: List[ParamDoc]


class Fragment(BaseModel):
    """A parsed page fragment: its page name, the tool its first line names and the remaining lines."""

    model_config = _MODEL_CONFIG

    page: str
    tool: str
    body: str


class HelpProblem(BaseModel):
    """One defect found by a help check."""

    model_config = _MODEL_CONFIG

    code: HelpProblemCode
    subject: str
    detail: str


class HelpOutcome(BaseModel):
    """The result of building or writing one help page."""

    model_config = _MODEL_CONFIG

    page: str
    changed: bool
    applied: bool
    lines: List[str]
