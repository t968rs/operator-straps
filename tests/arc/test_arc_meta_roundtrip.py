"""The apply writers' output passes ``check_applied``: checker and writers agree on every surface.

Each case starts from a stale archive (an old summary in the rc, a ``Mode`` hover with canonical text but no
``$rc:`` reference, a blank "?" page and an illustration the page does not show), applies the hover and page
writers, and expects ``check_applied`` to find nothing left. The bold case puts rich text in the summary and
in one ``dialogReference``, where the rc holds plain text for the summary and ``xdoc`` for the parameter.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from arc._arc_toolbox import CANONICAL, ILLUSTRATION_ENTRY, PNG_A, RC, TOOL, make_toolbox, toolbox_members
from arc_meta_api import check_applied
from arc_meta_page import apply_page
from arc_meta_rc import apply_rc

PLAIN = CANONICAL.replace("<para></para>", "<para>Processing speed.</para>")
BOLD = (PLAIN.replace("<![CDATA[<p>Makes polygons.</p>]]>", "<![CDATA[<p><b>Makes</b> polygons.</p>]]>")
        .replace("<para>Derived output set to the polygons.</para>",
                 "<![CDATA[<p><b>Derived</b> output set to the polygons.</p>]]>"))


def _stale_project(make_project: Callable[..., Path], canonical: str) -> Path:
    """A project whose archive is stale on the hover, the wiring, the page and the illustration."""
    members = toolbox_members(canonical=canonical, rc={"map": {**RC["map"], "description": "Old."}},
                              page="<metadata/>", extra={ILLUSTRATION_ENTRY: PNG_A})
    return make_toolbox(make_project, canonical=canonical, members=members)


def _codes(problems) -> set:
    return {(p.code.value, p.param) for p in problems}


@pytest.mark.parametrize("canonical", [PLAIN, BOLD], ids=["plain", "bold"])
def test_applied_writers_leave_check_applied_clean(make_project, canonical: str) -> None:
    root = _stale_project(make_project, canonical)
    before = _codes(check_applied(TOOL, repo=root))
    assert {("hover_stale", None), ("hover_unwired", "Mode"), ("page_stale", None)} <= before, before
    assert apply_rc(TOOL, apply=True, repo=root).applied
    assert apply_page(TOOL, apply=True, repo=root).applied
    assert _codes(check_applied(TOOL, repo=root)) == set()


@pytest.mark.parametrize("canonical", [PLAIN, BOLD], ids=["plain", "bold"])
def test_a_second_apply_finds_nothing_to_write(make_project, canonical: str) -> None:
    root = _stale_project(make_project, canonical)
    apply_rc(TOOL, apply=True, repo=root)
    apply_page(TOOL, apply=True, repo=root)
    assert not apply_rc(TOOL, repo=root).changed
    assert not apply_page(TOOL, repo=root).changed
