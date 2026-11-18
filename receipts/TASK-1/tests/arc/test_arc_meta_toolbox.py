"""arc-meta toolbox writer: the toolbox-level resource and item page written from the canonical source.

The archive under test is a small zip built in ``tmp_path`` with the toolbox-level member names of a real
``.atbx``; the project cases build a ``make_project`` repo through the shared demo builder.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

import pytest

import arc_meta_toolbox as tbx
from arc._arc_toolbox import ATBX, make_toolbox, toolbox_members
from arc_meta_models import ApiError, Surface

SOURCE_XML = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <Esri><ArcGISFormat>1.0</ArcGISFormat><ArcGISProfile>ItemDescription</ArcGISProfile></Esri>
  <dataIdInfo>
    <idCitation><resTitle>Sample Title</resTitle></idCitation>
    <idPurp>One-line summary.</idPurp>
    <idAbs><![CDATA[<p>First <b>bold</b> paragraph.</p><ul><li>Item one</li><li>Item two</li></ul>]]></idAbs>
    <idCredit>Someone</idCredit>
    <searchKeys><keyword>flood</keyword><keyword>fema</keyword></searchKeys>
    <resConst><Consts><useLimit><![CDATA[<p>Review outputs.</p>]]></useLimit></Consts></resConst>
  </dataIdInfo>
</metadata>
"""

OLD_RC = {"map": {"descr": "old", "title": "Old Title", "toolset1.name": "Data_Management"}}

OLD_META = (
    '<?xml version="1.0"?><metadata><Esri><DataProperties><lineage><Process>x</Process>'
    "</lineage></DataProperties></Esri><Binary><Thumbnail><Data>AAAA</Data></Thumbnail>"
    "</Binary></metadata>"
)

OTHER_ENTRIES = {
    "toolbox.content": b'{"version": "1.0", "alias": "demo"}',
    "Tool.tool/tool.content": b'{"type": "ScriptTool"}',
}

PROJECT_RC = {"map": {"title": "Old", "descr": "old"}}


@pytest.fixture
def source_path(tmp_path: Path) -> Path:
    """Write the sample canonical source and return its path."""
    path = tmp_path / "toolbox_source.xml"
    path.write_text(SOURCE_XML, encoding="utf-8")
    return path


@pytest.fixture
def atbx(tmp_path: Path) -> Path:
    """Build a toolbox-shaped zip with a thumbnail-laden metadata entry."""
    path = tmp_path / "sample.atbx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in OTHER_ENTRIES.items():
            zout.writestr(name, data)
        zout.writestr(tbx.RC_ENTRY, json.dumps(OLD_RC, indent=4))
        zout.writestr(tbx.META_ENTRY, OLD_META)
    return path


def _read(atbx_path: Path, name: str) -> bytes:
    with zipfile.ZipFile(atbx_path) as zin:
        return zin.read(name)


def _project(make_project: Callable[..., Path], rc: bool = True, source: bool = True) -> Path:
    """A demo project whose archive carries a stale toolbox rc and, with ``source``, the toolbox source."""
    extra = {tbx.RC_ENTRY: json.dumps(PROJECT_RC).encode("utf-8")} if rc else {}
    root = make_toolbox(make_project, members=toolbox_members(extra=extra))
    if source:
        (root / "tool_metadata" / f"{ATBX}.xml").write_text(SOURCE_XML, encoding="utf-8")
    return root


# --- load_source / build_metadata / build_rc / run_toolbox ---------------------------------------------

def test_load_source_reads_fields(source_path: Path) -> None:
    source = tbx.load_source(source_path)
    assert source.title == "Sample Title"
    assert source.summary == "One-line summary."
    assert source.credit == "Someone"
    assert source.keywords == ("flood", "fema")


def test_build_metadata_drops_thumbnail_and_lineage(source_path: Path) -> None:
    text = tbx.build_metadata(tbx.load_source(source_path))
    root = ET.fromstring(text)
    assert root.find("Binary") is None
    assert root.find(".//lineage") is None
    assert root.findtext("dataIdInfo/idCitation/resTitle") == "Sample Title"
    assert root.findtext("dataIdInfo/idPurp") == "One-line summary."
    assert '<SPAN STYLE="font-weight:bold;">bold</SPAN>' in root.findtext("dataIdInfo/idAbs")
    assert [k.text for k in root.iter("keyword")] == ["flood", "fema"]
    assert root.findtext("Esri/ArcGISProfile") == "ItemDescription"


def test_build_rc_sets_title_and_descr_and_keeps_toolsets(source_path: Path) -> None:
    rc = json.loads(tbx.build_rc(json.dumps(OLD_RC), tbx.load_source(source_path)))
    assert rc["map"]["title"] == "Sample Title"
    assert rc["map"]["descr"] == "First bold paragraph.\r\nItem one\r\nItem two"
    assert rc["map"]["toolset1.name"] == "Data_Management"


def test_run_dry_run_leaves_archive_unchanged(atbx: Path, source_path: Path) -> None:
    before = atbx.read_bytes()
    outcome = tbx.run_toolbox(atbx, source_path, apply=False)
    assert outcome.applied is False
    assert outcome.changed is True
    assert outcome.surface is Surface.TOOLBOX
    assert any(line.startswith("DRY-RUN") for line in outcome.lines)
    assert atbx.read_bytes() == before
    assert not atbx.with_name(atbx.name + ".bak").exists()


def test_run_apply_rewrites_toolbox_entries_only(atbx: Path, source_path: Path) -> None:
    before = atbx.read_bytes()
    outcome = tbx.run_toolbox(atbx, source_path, apply=True)
    assert outcome.applied is True
    assert atbx.with_name(atbx.name + ".bak").read_bytes() == before
    assert json.loads(_read(atbx, tbx.RC_ENTRY))["map"]["title"] == "Sample Title"
    assert b"<Binary>" not in _read(atbx, tbx.META_ENTRY)
    for name, data in OTHER_ENTRIES.items():
        assert _read(atbx, name) == data


def test_run_apply_invalid_metadata_keeps_archive(
    atbx: Path, source_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = atbx.read_bytes()
    monkeypatch.setattr(tbx, "build_metadata", lambda source: "<metadata><unclosed></metadata>")
    with pytest.raises(ApiError) as caught:
        tbx.run_toolbox(atbx, source_path, apply=True)
    assert isinstance(caught.value.__cause__, ET.ParseError)
    assert atbx.read_bytes() == before
    assert not atbx.with_name(atbx.name + ".tmp").exists()
    assert not atbx.with_name(atbx.name + ".bak").exists()


# --- report, rc encoding and formatting, refusals, apply_toolbox --------------------------------------

def test_report_notes_the_removed_thumbnail(atbx: Path, source_path: Path) -> None:
    lines = tbx.run_toolbox(atbx, source_path).lines
    assert any(line.startswith(tbx.META_ENTRY) and "thumbnail removed" in line for line in lines)
    assert f"--- new {tbx.RC_ENTRY} ---" in lines


def test_rc_with_a_bom_is_read_and_written_as_utf8(source_path: Path, tmp_path: Path) -> None:
    bom = tmp_path / "bom.atbx"
    with zipfile.ZipFile(bom, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(tbx.RC_ENTRY, b"\xef\xbb\xbf" + json.dumps(OLD_RC).encode("utf-8"))
    tbx.run_toolbox(bom, source_path, apply=True)
    raw = _read(bom, tbx.RC_ENTRY)
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["map"]["toolset1.name"] == "Data_Management"
    with zipfile.ZipFile(bom) as zin:
        assert tbx.META_ENTRY in zin.namelist()
    assert tbx.run_toolbox(bom, source_path).changed is False


def test_rc_in_another_formatting_with_the_same_meaning_is_unchanged(source_path: Path,
                                                                    tmp_path: Path) -> None:
    source = tbx.load_source(source_path)
    target = json.loads(tbx.build_rc(json.dumps(OLD_RC), source))
    resaved = json.dumps(target, indent=2).replace("\n", "\r\n").encode("utf-8")
    path = tmp_path / "resaved.atbx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(tbx.RC_ENTRY, resaved)
        zout.writestr(tbx.META_ENTRY, tbx.build_metadata(source).encode("utf-8"))
    before = path.read_bytes()
    outcome = tbx.run_toolbox(path, source_path, apply=True)
    assert (outcome.changed, outcome.applied) == (False, False)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".bak").exists()


def test_load_source_refuses_html_the_generator_cannot_convert(tmp_path: Path) -> None:
    deep = "<ul><li>A<ul><li>B<ul><li>C</li></ul></li></ul></li></ul>"
    path = tmp_path / "deep.xml"
    path.write_text(SOURCE_XML.replace("<li>Item two</li></ul>", f"<li>Item two</li></ul>{deep}"),
                    encoding="utf-8")
    with pytest.raises(ApiError, match="deep.xml") as caught:
        tbx.load_source(path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert not isinstance(caught.value.__cause__, ApiError)


def test_apply_toolbox_dry_run_on_a_stale_project(make_project: Callable[..., Path]) -> None:
    root = _project(make_project)
    before = (root / ATBX).read_bytes()
    outcome = tbx.apply_toolbox(repo=root)
    assert (outcome.changed, outcome.applied, outcome.tool) == (True, False, None)
    assert (root / ATBX).read_bytes() == before


def test_apply_toolbox_writes_what_the_builders_produce(make_project: Callable[..., Path]) -> None:
    root = _project(make_project)
    atbx = root / ATBX
    source = tbx.load_source(root / "tool_metadata" / f"{ATBX}.xml")
    outcome = tbx.apply_toolbox(apply=True, repo=root)
    assert (outcome.changed, outcome.applied) == (True, True)
    assert atbx.with_name(atbx.name + ".bak").exists()
    assert _read(atbx, tbx.RC_ENTRY).decode("utf-8") == tbx.build_rc(json.dumps(PROJECT_RC), source)
    assert _read(atbx, tbx.META_ENTRY).decode("utf-8") == tbx.build_metadata(source)
    backup = atbx.with_name(atbx.name + ".bak")
    archive_before, backup_before = atbx.read_bytes(), backup.read_bytes()
    rerun = tbx.apply_toolbox(apply=True, repo=root)
    assert (rerun.changed, rerun.applied) == (False, False)
    assert (atbx.read_bytes(), backup.read_bytes()) == (archive_before, backup_before)
    assert any(line.startswith("UNCHANGED") for line in rerun.lines)


def test_apply_toolbox_without_a_source_names_the_path(make_project: Callable[..., Path]) -> None:
    root = _project(make_project, source=False)
    with pytest.raises(ApiError, match=f"tool_metadata/{ATBX}.xml"):
        tbx.apply_toolbox(repo=root)


def test_apply_toolbox_without_the_rc_member_names_it(make_project: Callable[..., Path]) -> None:
    root = _project(make_project, rc=False)
    with pytest.raises(ApiError, match=rf"{tbx.RC_ENTRY}.*{ATBX}"):
        tbx.apply_toolbox(repo=root)


def test_load_source_refuses_malformed_xml(tmp_path: Path) -> None:
    path = tmp_path / "broken.xml"
    path.write_text("<metadata><unclosed></metadata>", encoding="utf-8")
    with pytest.raises(ApiError, match="broken.xml") as caught:
        tbx.load_source(path)
    assert isinstance(caught.value.__cause__, ET.ParseError)
