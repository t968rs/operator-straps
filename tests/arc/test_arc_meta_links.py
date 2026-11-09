"""arc-meta link pass-through: the generator keeps ``<a href>`` and the writers carry it to the "?" page.

The parser keeps each link's href on its runs and refuses an ``<a>`` without ``href`` (or with an empty one),
nested in another ``<a>``, or still open where its block ends. The "?" page renders an anchor inside the
run's span, the hover rc keeps the link text only, and the canonical form round-trips the link. The writer
tests run the apply calls a project runs (``apply_page``, ``apply_rc``) on the demo toolbox ``make_toolbox``
builds, then ``check_applied`` over the result.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import pytest

import arc_meta_api as api
import arc_meta_canonical as canonical
import arc_meta_format as mf
import arc_meta_page
import arc_meta_rc
import arc_meta_toolbox
from arc._arc_toolbox import ATBX, CANONICAL, RC, TOOL, make_toolbox, toolbox_members
from arc_meta_format import Run
from arc_meta_models import ApiError

HREF = "file:///srv/help/demo.html"
SEE = f'<p>See <a href="{HREF}">the guide</a>.</p>'
LONE = f'<p><a href="{HREF}">Guide</a></p>'
MIXED = '<p><b><a href="u">B</a></b> and <a href="v"><i>I</i> j</a></p>'
LIST = '<ul><li>See <a href="u">the guide</a>.</li><li>Plain.</li></ul>'
AMP = '<p><a href="a?x=1&amp;y=&quot;2&quot;">q</a></p>'
PLAIN_DIALOG = "<para>Polygons to process.</para>"
USAGE = "<p><b>Outputs:</b></p><ul><li>One polygon class.</li></ul>"
TOOLBOX_SOURCE = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <dataIdInfo>
    <idCitation><resTitle>Tools</resTitle></idCitation>
    <idPurp>One line.</idPurp>
    <idAbs><![CDATA[{abstract}]]></idAbs>
  </dataIdInfo>
</metadata>
"""


def _refusal(markup: str) -> str:
    """The message ``mf.parse`` raises for ``markup``; empty when it parses."""
    try:
        mf.parse(markup)
    except ValueError as exc:
        return str(exc)
    return ""


def _member(root: Path, name: str) -> str:
    """Archive member ``name`` of the demo toolbox under ``root``, decoded."""
    with zipfile.ZipFile(root / ATBX) as zf:
        return zf.read(name).decode("utf-8-sig")


def _with_dialog(dialog: str, usage: Optional[str] = None) -> str:
    """CANONICAL with the in_poly dialogReference as CDATA ``dialog`` and, when given, the usage replaced."""
    text = CANONICAL.replace(PLAIN_DIALOG, f"<![CDATA[{dialog}]]>")
    return text if usage is None else text.replace(USAGE, usage)


# --- the parser -----------------------------------------------------------------------------------------

def test_parse_keeps_the_href_on_the_link_run() -> None:
    assert mf.parse(SEE) == [("p", [Run("See ", False, False), Run("the guide", False, False, HREF),
                                    Run(".", False, False)])]


def test_a_link_may_wrap_or_sit_inside_bold_and_italic() -> None:
    assert mf.parse(MIXED) == [("p", [Run("B", True, False, "u"), Run(" and ", False, False),
                                      Run("I", False, True, "v"), Run(" j", False, False, "v")])]


def test_an_a_without_href_is_refused() -> None:
    assert "href" in _refusal("<p>See <a>the guide</a>.</p>")
    assert "href" in _refusal('<p>See <a name="x">the guide</a>.</p>')
    assert "href" in _refusal('<p>See <a href="">the guide</a>.</p>')


def test_an_a_nested_in_another_a_is_refused() -> None:
    assert "nested" in _refusal('<p><a href="u">outer <a href="v">inner</a></a></p>')


@pytest.mark.parametrize("markup", ['<p>See <a href="u">open</p><p>Next.</p>',
                                    '<ul><li>See <a href="u">open</li><li>Next.</li></ul>',
                                    'See <a href="u">open'], ids=["p", "li", "markup_end"])
def test_an_unclosed_a_is_refused_at_the_end_of_its_block(markup: str) -> None:
    assert "unclosed" in _refusal(markup)


def test_a_closed_link_does_not_leak_into_the_next_block() -> None:
    blocks = mf.parse('<p><a href="u">x</a></p><p>Next.</p><ul><li>Item.</li></ul>')
    assert [run.href for run in blocks[0][1]] == ["u"]
    assert [run.href for run in blocks[1][1]] == [None]
    assert [run.href for run in blocks[2][1][0]] == [None]


# --- the renderers --------------------------------------------------------------------------------------

def test_to_pro_html_writes_an_anchor_inside_the_run_span() -> None:
    html = mf.to_pro_html(mf.parse(SEE))
    assert f'<SPAN>See </SPAN><SPAN><A HREF="{HREF}">the guide</A></SPAN><SPAN>.</SPAN>' in html
    bold = mf.to_pro_html(mf.parse('<p><b><a href="u">B</a></b></p>'))
    assert '<SPAN STYLE="font-weight:bold;"><A HREF="u">B</A></SPAN>' in bold


def test_to_pro_html_escapes_the_href_attribute() -> None:
    html = mf.to_pro_html(mf.parse(AMP))
    assert '<A HREF="a?x=1&amp;y=&quot;2&quot;">q</A>' in html


def test_parse_reads_back_a_link_from_pro_html() -> None:
    blocks = mf.parse(MIXED)
    assert [run.href for run in blocks[0][1]] == ["u", None, "v", "v"]
    assert mf.parse(mf.to_pro_html(blocks)) == blocks


def test_to_xdoc_writes_the_link_text_only() -> None:
    blocks = mf.parse(SEE)
    assert blocks[0][1][1].href == HREF
    xdoc = mf.to_xdoc(blocks)
    assert xdoc == "<xdoc><p><span>See </span><span>the guide</span><span>.</span></p></xdoc>"
    assert "href" not in xdoc.lower()


def test_to_canonical_round_trips_a_link() -> None:
    assert mf.to_canonical(mf.parse(SEE)) == SEE
    blocks = mf.parse(MIXED)
    assert mf.parse(mf.to_canonical(blocks)) == blocks


def test_a_link_inside_a_list_item_round_trips() -> None:
    blocks = mf.parse(LIST)
    assert mf.to_canonical(blocks) == LIST
    assert '<A HREF="u">the guide</A>' in mf.to_pro_html(blocks)
    assert mf.parse(mf.to_pro_html(blocks)) == blocks


def test_to_canonical_keeps_an_href_with_an_ampersand_and_quotes() -> None:
    assert mf.to_canonical(mf.parse(AMP)) == AMP


def test_is_plain_is_false_for_a_lone_link() -> None:
    assert mf.is_plain(mf.parse("<p>Guide</p>"))
    assert not mf.is_plain(mf.parse(LONE))


def test_text_with_links_appends_each_href() -> None:
    text = mf.text_with_links(mf.parse(SEE))
    assert "the guide" in text and HREF in text
    assert text != mf.text_with_links(mf.parse(SEE.replace(HREF, "file:///srv/help/other.html")))
    assert mf.text_with_links(mf.parse(LIST)) == "See the guide [u]. Plain."
    plain = mf.parse("<p>No <b>links</b> here.</p><ul><li>Item.</li></ul>")
    assert mf.text_with_links(plain) == mf.plain_text(plain) == "No links here. Item."


# --- the writers ----------------------------------------------------------------------------------------

def test_add_dialog_ref_writes_pro_html_for_a_lone_link() -> None:
    param = ET.Element("param")
    canonical.add_dialog_ref(param, mf.parse(LONE))
    assert param.find("dialogReference/para") is None
    assert f'<A HREF="{HREF}">Guide</A>' in (param.findtext("dialogReference") or "")


def test_apply_page_writes_the_links_into_the_help_page(make_project) -> None:
    text = _with_dialog(LONE, usage=SEE)
    rc = {"map": {**RC["map"], "in_poly.descr": canonical.rc_text(mf.parse(LONE))}}
    root = make_toolbox(make_project, canonical=text,
                        members=toolbox_members(text, rc=rc, page="<metadata/>"))
    assert arc_meta_page.apply_page(TOOL, apply=True, repo=root).applied
    page = ET.fromstring(_member(root, f"{TOOL}.tool/tool.metadata.xml").encode("utf-8"))
    assert f'<A HREF="{HREF}">the guide</A>' in (page.findtext("tool/usage") or "")
    ref = page.find("tool/parameters/param[@name='in_poly']/dialogReference")
    assert ref.find("para") is None and f'<A HREF="{HREF}">Guide</A>' in (ref.text or "")
    assert api.check_applied(TOOL, repo=root) == []


def _toolbox_source(tmp_path: Path, abstract: str) -> Path:
    path = tmp_path / "Tools.atbx.xml"
    path.write_text(TOOLBOX_SOURCE.format(abstract=abstract), encoding="utf-8")
    return path


def test_the_toolbox_page_carries_a_link_and_its_rc_the_text(tmp_path: Path) -> None:
    """The toolbox surface passes links through like the tool page; its rc description keeps the text."""
    source = arc_meta_toolbox.load_source(_toolbox_source(tmp_path, SEE))
    page = ET.fromstring(arc_meta_toolbox.build_metadata(source).encode("utf-8"))
    assert f'<A HREF="{HREF}">the guide</A>' in (page.findtext("dataIdInfo/idAbs") or "")
    assert arc_meta_toolbox.rc_description(source) == "See the guide."


def test_load_source_refuses_an_a_without_href(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as caught:
        arc_meta_toolbox.load_source(_toolbox_source(tmp_path, "<p>See <a>the guide</a>.</p>"))
    assert "idAbs" in str(caught.value) and "href" in str(caught.value)


def test_apply_rc_writes_the_link_text_without_the_href(make_project) -> None:
    root = make_toolbox(make_project, canonical=_with_dialog(LONE))
    assert arc_meta_rc.apply_rc(TOOL, apply=True, repo=root).applied
    rc = json.loads(_member(root, f"{TOOL}.tool/tool.content.rc"))
    assert rc["map"]["in_poly.descr"] == "<xdoc><p><span>Guide</span></p></xdoc>"
    assert api.check_applied(TOOL, repo=root) == []
