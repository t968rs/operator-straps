"""The spec sheet model: a title, the request, goal and avoid lines, rendered to markdown and parsed back.

A sheet carries no plan or skill-spec ids, no issue numbers, no URLs and no code, so it stands on its own in a
scenario fixture; every goal and avoid line is one statement on one line; the rendered page holds at most
``MAX_LINES`` lines.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from harness_lib.specsheet_lite_models import (
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


def test_the_rendered_page_holds_at_most_max_lines() -> None:
    assert TARGET_LINES == 250 and MAX_LINES == 500
    many = [f"Goal number {n} holds." for n in range(MAX_LINES)]
    with pytest.raises(ValidationError):
        _sheet(goals=many)


def test_parse_refuses_a_page_over_max_lines() -> None:
    text = render_sheet(_sheet()) + "\n" * MAX_LINES
    with pytest.raises(ValueError):
        parse_sheet(text)
