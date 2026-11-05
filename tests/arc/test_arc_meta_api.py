"""The arc-meta check API on a demo toolbox project: parameters, canonical lint, applied state, sources.

Each test builds a committed project with ``make_toolbox`` (one archive at the root, the canonical XML in
the default ``tool_dir``) and calls the API with ``repo=root``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from xml.etree import ElementTree as ET

import pytest

import arc_meta_api as api
import arc_meta_canonical
import arc_meta_format as mf
import arc_meta_models
from arc._arc_toolbox import (
    ATBX, BAD_CANONICAL, CANONICAL, ILLUSTRATION_ENTRY, LYRX, PNG_A, PNG_B, RC, TOOL, default_page,
    make_toolbox, toolbox_members, write_archive,
)
from harness_lib.config import ConfigError

PAGE = f"{TOOL}.tool/tool.metadata.xml"
CONTENT_MEMBER = f"{TOOL}.tool/tool.content"
RC_MEMBER = f"{TOOL}.tool/tool.content.rc"
USAGE = "<p><b>Outputs:</b></p><ul><li>One polygon class.</li></ul>"
UNPARSEABLE = "<ul><li>A<ul><li>B</li></ul>tail</li></ul>"
DEEP = "<ul><li>A<ul><li>B<ul><li>C</li></ul></li></ul></li></ul>"
BOLD_OUT = "<p><b>Derived</b> output set to the polygons.</p>"


def _page(canonical: str, div_style: Optional[str] = None, drop_param: Optional[str] = None,
          illustration: Optional[bytes] = None) -> str:
    """The writer's tool.metadata.xml for ``canonical``, optionally made stale: ``div_style`` replaces
    the generator's outer DIV style, ``drop_param`` removes one parameter."""
    page = default_page(canonical, illustration)
    if div_style is None and drop_param is None:
        return page
    root = ET.fromstring(page.encode("utf-8"))
    for el in root.iter():
        if div_style is not None and el.text:
            el.text = el.text.replace(mf.PRO_DIV_STYLE, div_style)
    params = root.find("tool/parameters")
    for param in [p for p in params if p.get("name") == drop_param]:
        params.remove(param)
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")


def _edit_page(edit: Callable[[ET.Element], None], canonical: str = CANONICAL) -> str:
    """``default_page(canonical)`` after ``edit`` changed its parsed root in place."""
    root = ET.fromstring(default_page(canonical).encode("utf-8"))
    edit(root)
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")


def _toolbox(make_project, canonical: str = CANONICAL, config: Optional[dict] = None, **members) -> Path:
    """``make_toolbox`` over ``toolbox_members(canonical, **members)``."""
    return make_toolbox(make_project, canonical=canonical, config=config,
                        members=toolbox_members(canonical, **members))


def _codes(problems) -> List[Tuple[str, Optional[str]]]:
    """Every ``(code, param)`` pair, sorted, duplicates kept."""
    return sorted(((p.code.value, p.param) for p in problems), key=lambda pair: (pair[0], pair[1] or ""))


def _assert_found(problems, expected: list) -> None:
    """``problems`` are exactly ``expected``: ``(code, param)`` or ``(code, param, detail fragment)`` rows.

    The pairs compare as sorted lists; each fragment row then claims one problem whose detail holds it, so
    two problems that share a code and parameter are told apart.
    """
    shown = [(p.code.value, p.param, p.detail) for p in problems]
    assert _codes(problems) == sorted(((e[0], e[1]) for e in expected),
                                      key=lambda pair: (pair[0], pair[1] or "")), shown
    left = list(shown)
    for code, param, fragment in [e for e in expected if len(e) == 3]:
        hit = next((row for row in left if row[:2] == (code, param) and fragment in row[2]), None)
        assert hit is not None, (code, param, fragment, shown)
        left.remove(hit)


def _meta(**meta) -> dict:
    return {"plugins": {"arc-straps": {"arc_meta": meta}}}


def _rc(**changes) -> dict:
    return {"map": {**RC["map"], **changes}}


# --- param table ----------------------------------------------------------------------------------------

def test_param_table_reads_join_keys_and_hover_wiring(make_project) -> None:
    root = _toolbox(make_project)
    rows = {row.name: row for row in api.param_table(TOOL, repo=root)}
    assert list(rows) == ["in_poly", "Mode", "Out_Poly"]
    assert (rows["in_poly"].title, rows["in_poly"].type, rows["in_poly"].direction) == (
        "Input Polygons", "Required", "Input")
    assert rows["in_poly"].datatype == "GPFeatureLayer" and rows["in_poly"].hover_wired is True
    assert (rows["Mode"].type, rows["Mode"].hover_wired) == ("Optional", False)
    assert (rows["Mode"].values, rows["Mode"].default) == (["Fast", "Slow"], "Fast")
    assert (rows["Out_Poly"].type, rows["Out_Poly"].direction) == ("Derived", "Output")
    assert rows["Out_Poly"].symbology == LYRX
    with pytest.raises(api.ApiError):
        api.param_table("Nope", repo=root)


@pytest.mark.parametrize("raw", [b"", b"\r\n", b'{"map": null}', b'{"map": [1]}', b"[]"])
def test_param_table_reads_a_blank_or_mapless_rc_as_empty(make_project, raw: bytes) -> None:
    root = _toolbox(make_project, extra={RC_MEMBER: raw})
    rows = {row.name: row for row in api.param_table(TOOL, repo=root)}
    assert rows["in_poly"].title == "$rc:in_poly.title"
    assert not any(row.hover_wired for row in rows.values())


@pytest.mark.parametrize("raw", [b"[]", b'{"params": []}', b'{"params": {"x": 3}}', b'{"params": null}'])
def test_param_table_refuses_a_non_object_tool_content(make_project, raw: bytes) -> None:
    root = _toolbox(make_project, extra={CONTENT_MEMBER: raw})
    with pytest.raises(api.ApiError, match="tool.content"):
        api.param_table(TOOL, repo=root)


def test_a_non_zip_archive_is_refused(make_project) -> None:
    root = _toolbox(make_project)
    (root / ATBX).write_bytes(b"not a zip")
    with pytest.raises(api.ApiError, match=rf"{ATBX} is not a zip archive"):
        api.tool_names(repo=root)


# --- canonical source check -----------------------------------------------------------------------------

def test_check_canonical_flags_join_key_and_lint_problems(make_project) -> None:
    root = _toolbox(make_project, canonical=BAD_CANONICAL, page="<metadata/>")
    _assert_found(api.check_canonical(TOOL, repo=root), [
        ("prefixed_displayname", None), ("unknown_param", "inpoly"), ("missing_param", "in_poly"),
        ("type_mismatch", "Mode"), ("direction_mismatch", "Out_Poly"), ("non_ascii", None),
        ("unsupported_tag", None), ("deep_nesting", None), ("thumbnail", None), ("unparseable", "Mode"),
    ])


def test_check_canonical_clean_source_has_no_problems(make_project) -> None:
    assert api.check_canonical(TOOL, repo=_toolbox(make_project)) == []


def test_check_canonical_refuses_a_tool_without_canonical_xml(make_project) -> None:
    with pytest.raises(api.ApiError, match="no canonical source"):
        api.check_canonical("Nope", repo=_toolbox(make_project))


# --- applied-state check --------------------------------------------------------------------------------

def test_check_applied_flags_stale_surfaces(make_project) -> None:
    canonical = CANONICAL.replace("<para></para>", "<para>Processing speed.</para>")
    page = _page(canonical, div_style="text-align:Left;", drop_param="Out_Poly")
    root = _toolbox(make_project, canonical=canonical, rc=_rc(description="Old summary text."), page=page)
    _assert_found(api.check_applied(TOOL, repo=root), [
        ("hover_stale", None), ("hover_unwired", "Mode"), ("page_style_stale", None, "summary"),
        ("page_style_stale", None, "usage"), ("page_stale", "Out_Poly")])


def test_check_applied_flags_text_attribute_and_hover_markup_drift(make_project) -> None:
    canonical = CANONICAL.replace("<para>Derived output set to the polygons.</para>",
                                  f"<![CDATA[{BOLD_OUT}]]>")
    old = (canonical.replace("One polygon class.", "Two polygon classes.")
           .replace('displayname="Demo Tool"', 'displayname="Old Demo Tool"')
           .replace('displayname="Input Polygons"', 'displayname="Old Polygons"'))
    root = _toolbox(make_project, canonical=canonical, rc=_rc(**{"in_poly.descr": "Old polygons text."}),
                    page=_page(old))
    _assert_found(api.check_applied(TOOL, repo=root), [
        ("hover_stale", "in_poly"), ("hover_style_stale", "Out_Poly"), ("page_stale", None, "displayname"),
        ("page_stale", None, "usage"), ("page_stale", None, "resTitle"), ("page_stale", "in_poly")])


def test_check_applied_clean_when_atbx_matches_canonical(make_project) -> None:
    assert api.check_applied(TOOL, repo=_toolbox(make_project)) == []


def test_check_applied_clean_for_a_blank_usage(make_project) -> None:
    canonical = CANONICAL.replace(USAGE, "")
    assert api.check_applied(TOOL, repo=_toolbox(make_project, canonical=canonical)) == []


def test_check_applied_flags_an_old_parameter_text_on_the_page(make_project) -> None:
    old = CANONICAL.replace("Polygons to process.", "Old polygons text.")
    root = _toolbox(make_project, page=default_page(old))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", "in_poly", "dialogReference")])


def test_check_applied_flags_a_plain_page_ref_for_a_rich_canonical_ref(make_project) -> None:
    canonical = CANONICAL.replace("<para>Derived output set to the polygons.</para>",
                                  f"<![CDATA[{BOLD_OUT}]]>")
    rc = _rc(**{"out_poly.descr": arc_meta_canonical.rc_text(mf.parse(BOLD_OUT))})
    root = _toolbox(make_project, canonical=canonical, rc=rc, page=default_page(CANONICAL))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_style_stale", "Out_Poly", "dialogReference")])


def test_check_applied_flags_an_extra_parameter_on_the_page(make_project) -> None:
    def add_ghost(root: ET.Element) -> None:
        params = root.find("tool/parameters")
        ghost = copy.deepcopy(params[0])
        ghost.set("name", "Ghost")
        params.append(ghost)

    root = _toolbox(make_project, page=_edit_page(add_ghost))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", "Ghost", "not in the canonical")])


def test_check_applied_flags_summary_only_text_drift(make_project) -> None:
    old = CANONICAL.replace("<p>Makes polygons.</p>", "<p>Makes old polygons.</p>")
    root = _toolbox(make_project, page=default_page(old))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", None, "summary")])


def test_check_applied_flags_an_order_only_parameter_difference(make_project) -> None:
    def last_first(root: ET.Element) -> None:
        params = root.find("tool/parameters")
        last = params[-1]
        params.remove(last)
        params.insert(0, last)

    root = _toolbox(make_project, page=_edit_page(last_first))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_style_stale", None, "order")])


def test_check_applied_reads_every_para_of_a_page_reference(make_project) -> None:
    def add_para(root: ET.Element) -> None:
        ref = root.find("tool/parameters/param[@name='in_poly']/dialogReference")
        ET.SubElement(ref, "para").text = "Extra."

    root = _toolbox(make_project, page=_edit_page(add_para))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", "in_poly", "dialogReference")])


def test_check_applied_reads_a_para_summary_on_the_page(make_project) -> None:
    def para_summary(root: ET.Element) -> None:
        summary = root.find("tool/summary")
        summary.text = None
        ET.SubElement(summary, "para").text = "Makes polygons."

    root = _toolbox(make_project, page=_edit_page(para_summary))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_style_stale", None, "summary")])


def test_check_applied_flags_keyword_drift(make_project) -> None:
    canonical = CANONICAL.replace("</idCitation></dataIdInfo>",
                                  "</idCitation><searchKeys><keyword>flood</keyword></searchKeys></dataIdInfo>")
    root = _toolbox(make_project, canonical=canonical, page=default_page(CANONICAL))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", None, "keywords")])


def test_check_applied_flags_res_title_drift(make_project) -> None:
    def old_title(root: ET.Element) -> None:
        root.find("dataIdInfo/idCitation/resTitle").text = "Old Demo Tool"

    root = _toolbox(make_project, page=_edit_page(old_title))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", None, "resTitle")])


def test_check_applied_reads_a_utf16_page_with_its_declaration(make_project) -> None:
    page = default_page().replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>')
    members = toolbox_members()
    members[PAGE] = page.encode("utf-16")
    assert api.check_applied(TOOL, repo=make_toolbox(make_project, members=members)) == []


def test_check_applied_blames_an_unparseable_rc_on_the_archive(make_project) -> None:
    root = _toolbox(make_project, rc=_rc(**{"in_poly.descr": DEEP}))
    _assert_found(api.check_applied(TOOL, repo=root), [("hover_stale", "in_poly")])


def test_check_applied_without_a_page_skips_the_page_build(make_project) -> None:
    canonical = CANONICAL.replace(USAGE, UNPARSEABLE)
    members = toolbox_members(canonical, rc=_rc(description="Old."), page="")
    members.pop(PAGE)
    root = make_toolbox(make_project, canonical=canonical, members=members)
    _assert_found(api.check_applied(TOOL, repo=root), [
        ("hover_stale", None), ("page_stale", None, "no tool.metadata.xml")])


@pytest.mark.parametrize("raw, fragment", [
    (b"<metadata><tool>", "not readable XML"),
    (b"<metadata>\xff</metadata>", "not readable XML"),
    (b"<metadata/>", "no <tool> element"),
])
def test_check_applied_reads_an_unreadable_page_as_stale(make_project, raw: bytes, fragment: str) -> None:
    members = toolbox_members()
    members[PAGE] = raw
    root = make_toolbox(make_project, members=members)
    _assert_found(api.check_applied(TOOL, repo=root), [("page_stale", None, fragment)])


def test_check_applied_raises_config_error_unwrapped(make_project) -> None:
    root = _toolbox(make_project)
    write_archive(root / "other_toolbox.atbx", toolbox_members())
    with pytest.raises(ConfigError, match="2 .atbx files"):
        api.check_applied(TOOL, repo=root)


# --- the illustration on the "?" page -------------------------------------------------------------------

def test_check_applied_clean_when_the_page_shows_the_archive_illustration(make_project) -> None:
    root = _toolbox(make_project, page=_page(CANONICAL, illustration=PNG_A),
                    extra={ILLUSTRATION_ENTRY: PNG_A})
    assert api.check_applied(TOOL, repo=root) == []


def test_check_applied_clean_after_applying_an_empty_illustration_member(make_project) -> None:
    root = _toolbox(make_project, page=_page(CANONICAL, illustration=b""), extra={ILLUSTRATION_ENTRY: b""})
    assert api.check_applied(TOOL, repo=root) == []


def test_check_applied_flags_a_page_missing_the_archive_illustration(make_project) -> None:
    root = _toolbox(make_project, extra={ILLUSTRATION_ENTRY: PNG_A})
    _assert_found(api.check_applied(TOOL, repo=root), [("page_image_stale", None)])


def test_check_applied_flags_a_page_showing_an_outdated_illustration(make_project) -> None:
    root = _toolbox(make_project, page=_page(CANONICAL, illustration=PNG_B),
                    extra={ILLUSTRATION_ENTRY: PNG_A})
    _assert_found(api.check_applied(TOOL, repo=root), [("page_image_stale", None)])


def test_check_applied_flags_a_page_image_the_archive_no_longer_holds(make_project) -> None:
    root = _toolbox(make_project, page=_page(CANONICAL, illustration=PNG_A))
    _assert_found(api.check_applied(TOOL, repo=root), [("page_image_stale", None)])


def _crc_corrupt_illustration(atbx: Path, members: dict) -> None:
    """Rewrite ``atbx`` uncompressed from ``members`` with the illustration's last byte flipped (bad CRC)."""
    with zipfile.ZipFile(atbx, "w", zipfile.ZIP_STORED) as zf:
        for member, data in members.items():
            zf.writestr(member, data)
    raw, payload = atbx.read_bytes(), members[ILLUSTRATION_ENTRY]
    assert raw.count(payload) == 1
    end = raw.index(payload) + len(payload) - 1
    atbx.write_bytes(raw[:end] + bytes([raw[end] ^ 0xFF]) + raw[end + 1:])


def test_check_applied_refuses_a_corrupt_illustration_as_an_api_error(make_project) -> None:
    members = toolbox_members(CANONICAL, page=_page(CANONICAL, illustration=PNG_A),
                              extra={ILLUSTRATION_ENTRY: PNG_A})
    root = make_toolbox(make_project, members=members)
    _crc_corrupt_illustration(root / ATBX, members)
    with pytest.raises(api.ApiError, match=f"{ILLUSTRATION_ENTRY} in {ATBX} is corrupt"):
        api.check_applied(TOOL, repo=root)


def test_check_applied_sends_unparseable_markup_to_check_canonical(make_project) -> None:
    canonical = CANONICAL.replace("<para>Polygons to process.</para>", f"<![CDATA[{UNPARSEABLE}]]>")
    root = _toolbox(make_project, canonical=canonical, page="<metadata/>")
    with pytest.raises(api.ApiError, match="run check_canonical"):
        api.check_applied(TOOL, repo=root)


def test_check_applied_keeps_archive_refusals_apart_from_the_canonical(make_project) -> None:
    root = _toolbox(make_project)
    (root / "tool_metadata" / "tools" / "Ghost.xml").write_text(CANONICAL, encoding="utf-8")
    with pytest.raises(api.ApiError, match="is not a tool") as raised:
        api.check_applied("Ghost", repo=root)
    assert "check_canonical" not in str(raised.value)


def test_check_applied_keeps_a_plain_summary_hover_for_a_bold_summary(make_project) -> None:
    canonical = CANONICAL.replace("<p>Makes polygons.</p>", "<p><b>Makes</b> polygons.</p>")
    root = _toolbox(make_project, canonical=canonical, rc=_rc(description="Makes polygons."))
    problems = api.check_applied(TOOL, repo=root)
    assert problems == [], _codes(problems)


# --- listing and printing -------------------------------------------------------------------------------

def test_tool_names_and_formatters(make_project) -> None:
    root = _toolbox(make_project, canonical=BAD_CANONICAL, page="<metadata/>")
    assert api.tool_names(repo=root) == [TOOL]
    rows = api.format_rows(api.param_table(TOOL, repo=root)).splitlines()
    assert rows[0].startswith("name | title | type") and len(rows) == 4
    assert rows[1].startswith("in_poly | Input Polygons | Required | Input | GPFeatureLayer | wired")
    assert api.format_problems([]) == "clean"
    problems = api.check_canonical(TOOL, repo=root)
    lines = api.format_problems(problems).splitlines()
    assert len(lines) == len(problems) and lines[0].count(" | ") >= 2


def test_tool_names_refuses_two_archives_without_an_atbx_key(make_project) -> None:
    root = _toolbox(make_project)
    write_archive(root / "other_toolbox.atbx", toolbox_members())
    with pytest.raises(ConfigError, match="2 .atbx files"):
        api.tool_names(repo=root)


# --- implementing sources -------------------------------------------------------------------------------

def _entry_extra() -> dict:
    return {
        f"{TOOL}.tool/tool.script.execute.link": b"..\\..\\tools\\demo\\run.py",
        f"{TOOL}.tool/tool.script.validate.py": b"class ToolValidator:\n    pass\n",
    }


def _registry_project(make_project, raw: Optional[bytes]) -> Path:
    root = _toolbox(make_project, config=_meta(registry="registry/tools.json"), extra=_entry_extra())
    if raw is not None:
        (root / "registry").mkdir()
        (root / "registry" / "tools.json").write_bytes(raw)
    return root


def test_entry_sources_prefers_link_over_registry(make_project) -> None:
    raw = json.dumps({"tools": [{"tool_name": TOOL, "py_path": "tools/old_demo.py"}]}).encode("utf-8")
    root = _registry_project(make_project, raw)
    entry = root / "tools" / "demo" / "run.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")
    sources = api.entry_sources(TOOL, repo=root)
    assert (sources.entry, sources.entry_exists) == ("tools/demo/run.py", True)
    assert sources.validator == f"{TOOL}.tool/tool.script.validate.py"
    assert (sources.registry_path, sources.registry_stale) == ("tools/old_demo.py", True)


def test_entry_sources_skips_an_absent_configured_registry(make_project) -> None:
    sources = api.entry_sources(TOOL, repo=_registry_project(make_project, None))
    assert (sources.entry, sources.entry_exists) == ("tools/demo/run.py", False)
    assert (sources.registry_path, sources.registry_stale) == (None, False)


BAD_REGISTRIES = [b"{not json", b"\xff\xfe{}", b"[1]", b'{"tools": 3}', b'{"tools": ["Demo"]}']


@pytest.mark.parametrize("raw", BAD_REGISTRIES)
def test_entry_sources_refuses_a_malformed_registry(make_project, raw: bytes) -> None:
    root = _registry_project(make_project, raw)
    with pytest.raises(api.ApiError, match="registry/tools.json"):
        api.entry_sources(TOOL, repo=root)


# --- surface --------------------------------------------------------------------------------------------

def test_api_records_are_the_models_module_classes() -> None:
    assert (api.ParamRow, api.ProblemCode) == (arc_meta_models.ParamRow, arc_meta_models.ProblemCode)
    assert api.ApiError is arc_meta_models.ApiError


def test_every_public_call_leaves_the_archive_unchanged(make_project) -> None:
    root = _toolbox(make_project, extra=_entry_extra())
    before = hashlib.sha256((root / ATBX).read_bytes()).hexdigest()
    rows = api.param_table(TOOL, repo=root)
    api.format_rows(rows)
    api.format_problems(api.check_canonical(TOOL, repo=root) + api.check_applied(TOOL, repo=root))
    api.tool_names(repo=root)
    api.entry_sources(TOOL, repo=root)
    api.paths(root)
    assert hashlib.sha256((root / ATBX).read_bytes()).hexdigest() == before
    assert "rewrite" not in vars(api)
