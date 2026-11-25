"""The spec sheet model: a title, the request, goal and avoid lines, rendered to markdown and parsed back.

A sheet carries no plan or skill-spec ids, no issue numbers, no URLs and no code fences, so it stands on its
own in a scenario fixture; every goal and avoid line is one statement on one line; the rendered page holds at
most ``MAX_LINES`` lines. Inline code and function or field names pass the model: keeping them out is the
skill's outcomes rule, not a model check.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from harness_lib.spec_it_models import (
    MAX_LINES,
    MAX_STATEMENT_CHARS,
    TARGET_LINES,
    SpecSheet,
    parse_sheet,
    render_sheet,
)

DAY = date(2026, 11, 25)


def _sheet(**over) -> SpecSheet:
    fields = {"title": "Spec sheet lite", "day": DAY,
              "request": "Replace the long design session with a short brief that write-plan reads.",
              "goals": ["The brief fits on one screen for a typical request.",
                        "write-plan starts from the brief without a second design document."],
              "avoid": ["The brief never restates the plan's items."]}
    fields.update(over)
    return SpecSheet(**fields)


def test_a_sheet_needs_a_title_a_request_and_a_goal() -> None:
    for field in ("title", "request"):
        with pytest.raises(ValidationError):
            _sheet(**{field: "  "})
    with pytest.raises(ValidationError):
        _sheet(goals=[])


def test_avoid_lines_are_optional() -> None:
    assert _sheet(avoid=[]).avoid == []


@pytest.mark.parametrize("text", [
    "Covers TASK-3 first.", "Keeps B4 as judgment.", "Draws SC-2 again.", "Records R-7.",
    "Follows EX6.", "Closes todo-k7qf.", "Fixes #171.", "See https://example.com/x for the shape.",
])
def test_ids_issue_numbers_and_urls_are_refused(text: str) -> None:
    with pytest.raises(ValidationError):
        _sheet(goals=[text])
    with pytest.raises(ValidationError):
        _sheet(request=text)


@pytest.mark.parametrize("text", ["Runs ```x = 1``` once.", "Keeps ~~~ fences out."])
def test_code_fences_are_refused(text: str) -> None:
    with pytest.raises(ValidationError):
        _sheet(avoid=[text])


def test_a_statement_is_one_line_within_the_char_cap() -> None:
    with pytest.raises(ValidationError):
        _sheet(goals=["First line.\nSecond line."])
    with pytest.raises(ValidationError):
        _sheet(goals=["x" * (MAX_STATEMENT_CHARS + 1)])
    assert _sheet(goals=["x" * MAX_STATEMENT_CHARS]).goals


def test_a_statement_appears_once() -> None:
    with pytest.raises(ValidationError):
        _sheet(goals=["Same line.", "Same line."])
    with pytest.raises(ValidationError):
        _sheet(goals=["Same line."], avoid=["same line."])


def test_render_lays_out_the_sections_in_order() -> None:
    lines = render_sheet(_sheet()).splitlines()
    assert lines[0] == "# Spec sheet lite"
    heads = [line for line in lines if line.startswith("## ")]
    assert heads == ["## Request", "## Goals", "## Avoid"]
    assert "- The brief fits on one screen for a typical request." in lines
    assert "2026-11-25" in lines[2]


def test_render_omits_an_empty_avoid_section() -> None:
    assert "## Avoid" not in render_sheet(_sheet(avoid=[]))


def test_parse_reverses_render() -> None:
    sheet = _sheet(request=" ".join(["A long request sentence."] * 20))
    assert parse_sheet(render_sheet(sheet)) == sheet


def test_parse_refuses_a_page_out_of_shape() -> None:
    text = render_sheet(_sheet()).replace("## Goals", "## Ideas")
    with pytest.raises(ValueError):
        parse_sheet(text)


@pytest.mark.parametrize("request_text", [
    "Date: shown in the banner.",
    "word " * 22 + "Date: tomorrow is fine.",
    "x " * 54 + "Date: 2026-01-01 later",
])
def test_parse_reverses_a_request_that_wraps_a_date_line(request_text: str) -> None:
    sheet = _sheet(request=request_text)
    assert any(line.startswith("Date: ") for line in render_sheet(sheet).splitlines()[3:])
    assert parse_sheet(render_sheet(sheet)) == sheet


@pytest.mark.parametrize("request_text", ["## Goals first then more", "x " * 55 + "## Avoid later"])
def test_a_request_that_wraps_a_heading_is_refused(request_text: str) -> None:
    with pytest.raises(ValidationError, match="the request"):
        _sheet(request=request_text)


@pytest.mark.parametrize("brk", ["\r", "\x0c", "\x1c", " "])
def test_a_title_or_statement_with_any_line_break_is_refused(brk: str) -> None:
    with pytest.raises(ValidationError, match="the title is one line"):
        _sheet(title=f"Spec{brk}sheet")
    with pytest.raises(ValidationError, match="one line"):
        _sheet(goals=[f"First.{brk}Second."])


def _goals(count: int) -> list:
    return [f"Goal number {n} holds." for n in range(count)]


def _goals_for(lines: int) -> list:
    """Goal lines that bring the default sheet's page to exactly ``lines`` lines."""
    base = len(render_sheet(_sheet(goals=_goals(1))).splitlines())
    return _goals(lines - base + 1)


def test_the_rendered_page_holds_at_most_max_lines() -> None:
    assert TARGET_LINES == 250 and MAX_LINES == 500
    assert len(render_sheet(_sheet(goals=_goals_for(MAX_LINES))).splitlines()) == MAX_LINES
    with pytest.raises(ValidationError, match="line cap"):
        _sheet(goals=_goals_for(MAX_LINES + 1))


def test_parse_refuses_a_page_over_max_lines() -> None:
    fields = {**_sheet().model_dump(), "goals": _goals_for(MAX_LINES + 1)}
    text = render_sheet(SpecSheet.model_construct(**fields))
    assert len(text.splitlines()) == MAX_LINES + 1
    with pytest.raises(ValueError, match="line cap") as caught:
        parse_sheet(text)
    assert not isinstance(caught.value, ValidationError)
