"""arc-meta generator ``arc_meta_format``: nested-list parsing and rendering, and the Pro help-page spacing.

The second half tests ``arc_meta_canonical``, the readers and builders the checks and writers share:
``rc_text``, ``fields``, ``load``, ``add_dialog_ref`` and ``page``.

Pro wraps decoded summary/usage HTML in ``<pre class="wrap">``, whose stylesheet pads every ``p`` and
``li`` by 1em, so list items carry no inner ``<P>`` and every block carries an inline padding style.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import arc_meta_canonical as canonical
import arc_meta_format as mf
from arc._arc_toolbox import CANONICAL, PNG_A, TOOL
from arc_meta_format import Run
from arc_meta_models import ApiError

NESTED = "<p>Intro.</p><ul><li>A<ul><li>a1</li><li><b>a2</b></li></ul></li><li>B</li></ul>"


def _r(text: str, bold: bool = False) -> Run:
    return Run(text, bold, False)


def test_parse_flat_list_unchanged() -> None:
    blocks = mf.parse("<ul><li>A</li><li>B</li></ul>")
    assert blocks == [("ul", [[_r("A")], [_r("B")]])]


def test_parse_nested_list_emits_sub_block_after_parent_item() -> None:
    assert mf.parse(NESTED) == [
        ("p", [_r("Intro.")]),
        ("ul", [[_r("A")]]),
        ("sub", [[_r("a1")], [_r("a2", bold=True)]]),
        ("ul", [[_r("B")]]),
    ]


def test_to_pro_html_spacing_styles_and_no_p_inside_li() -> None:
    html = mf.to_pro_html(mf.parse("<p>Head</p><ul><li>One</li></ul>"))
    assert f'<P STYLE="{mf.PRO_P_STYLE}"><SPAN>Head</SPAN></P>' in html
    assert f'<UL STYLE="{mf.PRO_UL_STYLE}"><LI STYLE="{mf.PRO_LI_STYLE}"><SPAN>One</SPAN></LI></UL>' in html
    assert "<LI><P>" not in html


def test_to_pro_html_div_collapses_injected_whitespace() -> None:
    """Pro pretty-prints the help HTML inside pre.wrap; the outer DIV resets white-space."""
    html = mf.to_pro_html(mf.parse("<p>Head</p>"))
    assert html.startswith(f'<DIV STYLE="{mf.PRO_DIV_STYLE}">')
    assert "white-space:normal;" in mf.PRO_DIV_STYLE
    assert "margin-top:-" in mf.PRO_DIV_STYLE and "margin-bottom:-" in mf.PRO_DIV_STYLE


def test_to_pro_html_nests_sub_list_inside_parent_item() -> None:
    html = mf.to_pro_html(mf.parse(NESTED))
    li = f'<LI STYLE="{mf.PRO_LI_STYLE}">'
    expected = (
        f'<UL STYLE="{mf.PRO_UL_STYLE}">{li}<SPAN>A</SPAN>'
        f'<UL STYLE="{mf.PRO_SUBUL_STYLE}">{li}<SPAN>a1</SPAN></LI>'
        f'{li}<SPAN STYLE="font-weight:bold;">a2</SPAN></LI></UL></LI>'
        f"{li}<SPAN>B</SPAN></LI></UL>"
    )
    assert expected in html
    assert html.count("<UL") == 2


def test_to_xdoc_nests_sub_list_inside_parent_item() -> None:
    xdoc = mf.to_xdoc(mf.parse(NESTED))
    assert "<li><p><span>A</span></p><ul><li><p><span>a1</span></p></li>" in xdoc
    assert xdoc.count("<ul>") == 2


def test_to_canonical_round_trips_nested_list() -> None:
    blocks = mf.parse(NESTED)
    assert mf.to_canonical(blocks) == NESTED
    assert mf.parse(mf.to_canonical(blocks)) == blocks


def test_plain_text_includes_sub_items() -> None:
    assert mf.plain_text(mf.parse(NESTED)) == "Intro. A a1 a2 B"


def test_parse_reads_back_generated_pro_html() -> None:
    blocks = mf.parse(NESTED)
    assert mf.parse(mf.to_pro_html(blocks)) == blocks


def test_orphan_sub_block_renders_as_top_level_list() -> None:
    """A sub block with no preceding list item becomes a single top-level list."""
    blocks = [("sub", [[_r("x")]])]
    li = f'<LI STYLE="{mf.PRO_LI_STYLE}">'
    assert mf.to_pro_html(blocks) == (
        f'<DIV STYLE="{mf.PRO_DIV_STYLE}"><UL STYLE="{mf.PRO_UL_STYLE}">'
        f"{li}<SPAN>x</SPAN></LI></UL></DIV>"
    )
    assert mf.to_xdoc(blocks) == "<xdoc><ul><li><p><span>x</span></p></li></ul></xdoc>"
    assert mf.to_canonical(blocks) == "<ul><li>x</li></ul>"


def test_parse_emits_orphan_sub_block_for_textless_parent_item() -> None:
    assert mf.parse("<ul><li><ul><li>x</li></ul></li></ul>") == [("sub", [[_r("x")]])]


def test_sibling_nested_lists_merge_under_one_parent_item() -> None:
    markup = "<ul><li>A<ul><li>a1</li></ul><ul><li>a2</li></ul></li><li>B</li></ul>"
    assert mf.to_canonical(mf.parse(markup)) == (
        "<ul><li>A<ul><li>a1</li><li>a2</li></ul></li><li>B</li></ul>"
    )


def test_item_text_after_nested_list_raises() -> None:
    markup = "<ul><li>A<ul><li>a1</li></ul> tail</li><li>B</li></ul><p>End.</p>"
    with pytest.raises(ValueError, match="after a nested list"):
        mf.parse(markup)


def test_list_nested_deeper_than_one_level_raises() -> None:
    markup = "<ul><li>A<ul><li>a<ul><li>x</li></ul></li></ul></li></ul>"
    with pytest.raises(ValueError, match="deeper than one level"):
        mf.parse(markup)


# --- arc_meta_canonical: the readers and builders shared by the checks and the writers ------------------

def _tool_dir(tmp_path: Path, text: str = CANONICAL) -> Path:
    (tmp_path / f"{TOOL}.xml").write_text(text, encoding="utf-8")
    return tmp_path


def test_rc_text_is_empty_plain_or_xdoc() -> None:
    assert canonical.rc_text(mf.parse("")) == ""
    assert canonical.rc_text(mf.parse("<p>Plain words.</p>")) == "Plain words."
    bold = mf.parse("<p><b>X</b> y</p>")
    assert canonical.rc_text(bold) == mf.to_xdoc(bold) == "<xdoc><p><b>X</b><span> y</span></p></xdoc>"


def test_rc_text_summary_is_always_plain() -> None:
    assert canonical.rc_text(mf.parse("<p><b>X</b> y</p>"), summary=True) == "X y"
    assert canonical.rc_text(mf.parse("<p> </p>"), summary=True) == ""


def test_fields_read_the_plain_summary_and_lowercased_parameter_text(tmp_path: Path) -> None:
    assert canonical.fields(_tool_dir(tmp_path), TOOL) == ("Makes polygons.", {
        "in_poly": "Polygons to process.",
        "mode": "",
        "out_poly": "Derived output set to the polygons.",
    })


def test_fields_refuse_a_tool_without_canonical_xml(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="no canonical source"):
        canonical.fields(_tool_dir(tmp_path), "Nope")


def test_load_returns_the_text_and_the_root(tmp_path: Path) -> None:
    text, root = canonical.load(_tool_dir(tmp_path), TOOL)
    assert text == CANONICAL
    assert (root.tag, root.find("tool").get("name")) == ("metadata", TOOL)


def test_load_refuses_a_missing_or_broken_source(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="no canonical source at"):
        canonical.load(tmp_path, "Nope")
    with pytest.raises(ApiError, match="not well-formed XML") as got:
        canonical.load(_tool_dir(tmp_path, "<metadata><tool></metadata>"), TOOL)
    assert isinstance(got.value.__cause__, ET.ParseError)


def test_load_refuses_a_source_that_is_not_utf8(tmp_path: Path) -> None:
    folder = tmp_path / "tools"
    folder.mkdir()
    (folder / f"{TOOL}.xml").write_bytes(b"<metadata><tool name='caf\xe9'/></metadata>")
    with pytest.raises(ApiError, match="is not UTF-8 text") as got:
        canonical.load(folder, TOOL)
    assert isinstance(got.value.__cause__, UnicodeDecodeError)


def test_add_dialog_ref_writes_a_para_when_plain_and_pro_html_when_formatted() -> None:
    plain, rich = ET.Element("param"), ET.Element("param")
    canonical.add_dialog_ref(plain, mf.parse("<p>Plain.</p>"))
    blocks = mf.parse("<p><b>Rich</b> text.</p>")
    canonical.add_dialog_ref(rich, blocks)
    assert plain.findtext("dialogReference/para") == "Plain."
    assert rich.find("dialogReference/para") is None
    assert rich.findtext("dialogReference") == mf.to_pro_html(blocks)


def test_page_carries_every_param_attribute_and_no_illustration_by_default() -> None:
    page = ET.fromstring(canonical.page(ET.fromstring(CANONICAL.encode("utf-8"))).encode("utf-8"))
    params = page.findall("tool/parameters/param")
    assert [p.get("name") for p in params] == ["in_poly", "Mode", "Out_Poly"]
    assert all(p.get("direction") and p.get("datatype") for p in params)
    assert page.find("Binary") is None
    assert page.findtext("dataIdInfo/idCitation/resTitle") == "Demo Tool"


def test_page_embeds_a_given_illustration_last() -> None:
    text = canonical.page(ET.fromstring(CANONICAL.encode("utf-8")), PNG_A)
    assert text.startswith('<?xml version="1.0"?>\n<metadata')
    page = ET.fromstring(text.encode("utf-8"))
    assert page.find("Binary/Thumbnail/img").get("src") == mf.illustration_data_uri(PNG_A)
    assert list(page)[-1].tag == "Binary"


def test_page_refuses_a_tool_without_a_name() -> None:
    src = ET.fromstring(CANONICAL.replace('<tool name="Demo" ', "<tool ").encode("utf-8"))
    with pytest.raises(ApiError, match="the canonical <tool> has no name"):
        canonical.page(src)


def test_page_writes_an_empty_displayname_when_the_tool_has_none() -> None:
    src = ET.fromstring(CANONICAL.replace(' displayname="Demo Tool"', "").encode("utf-8"))
    page = ET.fromstring(canonical.page(src).encode("utf-8"))
    assert page.find("tool").get("displayname") == ""
