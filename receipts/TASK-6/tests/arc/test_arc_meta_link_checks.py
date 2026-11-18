"""arc-meta checks over links: ``<a>`` is a supported tag, and an href-only change is unpublished text.

``check_canonical`` accepts ``<a href>`` and reports an ``<a>`` the generator refuses as ``unparseable``. A
``<para>`` field holds plain text only: the readers flatten its child elements, so an ``<a>`` or ``<b>``
inside one would vanish without a word; ``check_canonical`` reports it as ``unsupported_para_markup``.
``check_applied`` compares each surface's text with every link's href appended (``text_with_links``), so a
page whose links point elsewhere reports ``page_stale``: an href nobody checked is new text, and a
``page_style_stale`` would let a generator sweep publish it.
"""
from __future__ import annotations

from typing import List, Tuple
from xml.etree import ElementTree as ET

import pytest

import arc_meta_api as api
import arc_meta_canonical
from arc._arc_toolbox import CANONICAL, RC, TOOL, default_page, make_toolbox, toolbox_members

OLD = "file:///srv/help/old.html"
NEW = "file:///srv/help/new.html"
PLAIN_DIALOG = "<para>Polygons to process.</para>"
USAGE = "<p><b>Outputs:</b></p><ul><li>One polygon class.</li></ul>"
SUMMARY = "<p>Makes polygons.</p>"


def _canonical(href: str) -> str:
    """CANONICAL with a link to ``href`` in the summary, the usage and the in_poly dialogReference."""
    dialog = f'<p>See <a href="{href}">the guide</a>.</p>'
    return (CANONICAL.replace(SUMMARY, f'<p>Makes polygons; see <a href="{href}">the guide</a>.</p>')
            .replace(USAGE, f'{USAGE}<p>Details: <a href="{href}">help page</a>.</p>')
            .replace(PLAIN_DIALOG, f"<![CDATA[{dialog}]]>"))


def _rc_for(text: str) -> dict:
    """The rc map the hover writer produces for canonical ``text``, over the demo rc."""
    summary, descr = arc_meta_canonical.fields_of(ET.fromstring(text.encode("utf-8")), f"{TOOL}.xml")
    rc_map = {**RC["map"], "description": summary}
    rc_map.update({f"{name}.descr": value for name, value in descr.items() if value})
    return {"map": rc_map}


def _codes(problems) -> List[Tuple[str, str]]:
    """Every ``(code, param or "-")`` pair, sorted."""
    return sorted((p.code.value, p.param or "-") for p in problems)


def test_the_anchor_is_a_supported_tag() -> None:
    assert "a" in api.SUPPORTED_TAGS


def test_check_canonical_accepts_links(make_project) -> None:
    root = make_toolbox(make_project, canonical=_canonical(NEW))
    assert api.check_canonical(TOOL, repo=root) == []


def test_check_canonical_reports_an_a_without_href_as_unparseable(make_project) -> None:
    text = CANONICAL.replace(PLAIN_DIALOG, "<![CDATA[<p>See <a>the guide</a>.</p>]]>")
    root = make_toolbox(make_project, canonical=text, members=toolbox_members(text, page="<metadata/>"))
    assert _codes(api.check_canonical(TOOL, repo=root)) == [("unparseable", "in_poly")]


@pytest.mark.parametrize("child", ['<a href="u">the guide</a>', "<b>the guide</b>"], ids=["a", "b"])
def test_check_canonical_flags_markup_inside_a_para(make_project, child: str) -> None:
    text = CANONICAL.replace(PLAIN_DIALOG, f"<para>See {child}.</para>")
    root = make_toolbox(make_project, canonical=text, members=toolbox_members(text, page="<metadata/>"))
    problems = api.check_canonical(TOOL, repo=root)
    assert _codes(problems) == [("unsupported_para_markup", "in_poly")], [p.detail for p in problems]
    assert "CDATA" in problems[0].detail


def test_check_applied_reports_an_href_only_change_as_page_stale(make_project) -> None:
    old, new = _canonical(OLD), _canonical(NEW)
    root = make_toolbox(make_project, canonical=new,
                        members=toolbox_members(new, rc=_rc_for(new), page=default_page(old)))
    problems = api.check_applied(TOOL, repo=root)
    shown = [(p.code.value, p.param, p.detail) for p in problems]
    assert _codes(problems) == [("page_stale", "-"), ("page_stale", "-"), ("page_stale", "in_poly")], shown
    details = " | ".join(p.detail for p in problems)
    assert "summary" in details and "usage" in details and "dialogReference" in details, shown


def test_an_unchanged_href_leaves_the_hover_and_the_page_clean(make_project) -> None:
    """Guard: the rc never holds an href, so the hover compares text alone and a matching page is clean."""
    new = _canonical(NEW)
    root = make_toolbox(make_project, canonical=new,
                        members=toolbox_members(new, rc=_rc_for(new), page=default_page(new)))
    assert api.check_applied(TOOL, repo=root) == []
