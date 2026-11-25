"""spec-it: the spec sheet the ``spec-it`` skill writes, its rules and its markdown page.

A sheet is a title, a date, the developer's request and the goal and avoid lines a plan must meet. It names
no plan, skill-spec or TODO id, no issue number, no URL and no code fence, so it stands on its own in a
scenario fixture and syncs with nothing. The model refuses only those patterns (``BANNED``); keeping
function, field and module names out of the prose is the skill's rule, not the model's. Each goal and avoid
line is one statement on one line, so a plan item or a skill behavior can take it whole. The page is the
only stored form: ``render_sheet`` writes it, ``parse_sheet`` reads it back and refuses any other layout.
This module imports no other ``harness_lib`` module.
"""
from __future__ import annotations

import re
import textwrap
from datetime import date
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_LINES = 500
TARGET_LINES = 250
MAX_STATEMENT_CHARS = 200
MAX_TITLE_CHARS = 80
WRAP = 110
REQUEST, GOALS, AVOID = "Request", "Goals", "Avoid"
DATE_PREFIX = "Date: "

BANNED: Dict[str, str] = {
    "a plan item id": r"\bTASK-\d+\b",
    "a skill-spec behavior id": r"\bB\d+\b",
    "a scenario id": r"\bSC-\d+\b",
    "a run id": r"\bR-\d+\b",
    "a design-evolution id": r"\bEX\d+\b",
    "a TODO id": r"\btodo-[a-z0-9]{4}\b",
    "an issue number": r"(?<![\w&])#\d+\b",
    "a URL": r"\bhttps?://",
    "a code fence": r"```|~~~",
}
_BANNED = {label: re.compile(pattern) for label, pattern in BANNED.items()}


def banned_in(text: str) -> List[str]:
    """Labels of the ``BANNED`` patterns ``text`` holds, in table order."""
    return [label for label, pattern in _BANNED.items() if pattern.search(text)]


def _clean(text: str, field: str) -> str:
    """``text`` stripped, refused when it holds a banned pattern."""
    found = banned_in(text)
    if found:
        raise ValueError(f"{field} holds {', '.join(found)}; a spec sheet carries none")
    return text.strip()


def _one_line(text: str) -> bool:
    """True when ``text`` holds no break ``str.splitlines`` honors, the split ``parse_sheet`` reads with."""
    return text.splitlines() in ([], [text])


def _statement(text: str) -> str:
    """One goal or avoid line: a single non-blank line of at most ``MAX_STATEMENT_CHARS``."""
    if not _one_line(text):
        raise ValueError("a goal or avoid line is one line")
    text = _clean(text, "a goal or avoid line")
    if not text:
        raise ValueError("a goal or avoid line is blank")
    if len(text) > MAX_STATEMENT_CHARS:
        raise ValueError(f"a goal or avoid line holds {len(text)} characters, over {MAX_STATEMENT_CHARS}")
    return text


class SpecSheet(BaseModel):
    """A spec sheet: what the developer asked for and the outcomes a plan must reach or avoid."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    day: date
    request: str = Field(min_length=1)
    goals: List[str] = Field(min_length=1)
    avoid: List[str] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, value: str) -> str:
        if not _one_line(str(value)):
            raise ValueError("the title is one line")
        return _clean(str(value), "the title")

    @field_validator("request", mode="before")
    @classmethod
    def _request(cls, value: str) -> str:
        return " ".join(_clean(str(value), "the request").split())

    @field_validator("goals", "avoid", mode="before")
    @classmethod
    def _statements(cls, value: List[str]) -> List[str]:
        if isinstance(value, str):
            raise ValueError("goals and avoid are lists of lines, not one string")
        return [_statement(str(item)) for item in value]

    @model_validator(mode="after")
    def _whole(self) -> "SpecSheet":
        seen: Dict[str, str] = {}
        for line in [*self.goals, *self.avoid]:
            key = line.casefold()
            if key in seen:
                raise ValueError(f"the line {line!r} appears twice")
            seen[key] = line
        headed = [line for line in _wrapped(self.request) if line.startswith("## ")]
        if headed:
            raise ValueError(f"the request wraps to a line opening with '## ' ({headed[0][:40]!r}), "
                             "which reads as a section heading; reword the request")
        count = len(render_sheet(self).splitlines())
        if count > MAX_LINES:
            raise ValueError(f"the page runs {count} lines, over the {MAX_LINES}-line cap")
        return self


def _wrapped(request: str) -> List[str]:
    """The request's page lines, wrapped at ``WRAP`` columns."""
    return textwrap.wrap(request, WRAP, break_long_words=False, break_on_hyphens=False)


def render_sheet(sheet: SpecSheet) -> str:
    """The sheet's markdown page: title, date, then Request, Goals and (when any) Avoid."""
    lines = [f"# {sheet.title}", "", f"{DATE_PREFIX}{sheet.day.isoformat()}", "", f"## {REQUEST}", ""]
    lines += _wrapped(sheet.request)
    sections = [(GOALS, sheet.goals)] + ([(AVOID, sheet.avoid)] if sheet.avoid else [])
    for head, items in sections:
        lines += ["", f"## {head}", ""] + [f"- {item}" for item in items]
    return "\n".join(lines) + "\n"


def _sections(lines: List[str]) -> Dict[str, List[str]]:
    """The body lines under each ``## `` heading; refuses an unknown or repeated heading."""
    found: Dict[str, List[str]] = {}
    current = None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            if current not in (REQUEST, GOALS, AVOID) or current in found:
                raise ValueError(f"unexpected section {line!r}; a sheet holds {REQUEST}, {GOALS} and {AVOID}")
            found[current] = []
        elif current is not None and line.strip():
            found[current].append(line)
    return found


def _items(head: str, body: List[str]) -> List[str]:
    """The ``- `` lines of a Goals or Avoid section; refuses any other line."""
    stray = [line for line in body if not line.startswith("- ")]
    if stray:
        raise ValueError(f"{head} holds a line that is not a '- ' item: {stray[0]!r}")
    return [line[2:] for line in body]


def parse_sheet(text: str) -> SpecSheet:
    """The sheet ``text`` renders; raises ``ValueError`` for a page out of shape or over ``MAX_LINES``."""
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise ValueError(f"the page runs {len(lines)} lines, over the {MAX_LINES}-line cap")
    if not lines or not lines[0].startswith("# "):
        raise ValueError("the page does not open with a '# ' title")
    if len(lines) < 3 or not lines[2].startswith(DATE_PREFIX):
        raise ValueError(f"the page needs its '{DATE_PREFIX}YYYY-MM-DD' line third, under the title")
    found = _sections(lines)
    if list(found)[:2] != [REQUEST, GOALS]:
        raise ValueError(f"the page needs the sections {REQUEST} and {GOALS}, in that order")
    sheet = SpecSheet(title=lines[0][2:], day=date.fromisoformat(lines[2][len(DATE_PREFIX):].strip()),
                      request=" ".join(found[REQUEST]), goals=_items(GOALS, found[GOALS]),
                      avoid=_items(AVOID, found.get(AVOID, [])))
    if render_sheet(sheet) != text:
        raise ValueError("the page is not in the layout render_sheet writes; rewrite it through the API")
    return sheet
