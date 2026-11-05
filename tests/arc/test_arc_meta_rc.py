"""arc-meta hover writer: the tool summary and parameter descriptions written into ``tool.content.rc``.

The archive under test is a small zip built in ``tmp_path`` with one tool's members. Covers the existing
rc update, the wiring of missing ``$rc:`` description references into ``tool.content``, and the
config-reading ``apply_rc`` entry point over a demo project.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Callable, Optional

import pytest

import arc_meta_rc as rc
from arc._arc_toolbox import ATBX, CANONICAL, TOOL_DIR, make_toolbox, toolbox_members, write_archive
from arc._arc_toolbox import RC as DEMO_RC
from arc._arc_toolbox import TOOL as DEMO_TOOL
from arc_meta_models import ApiError, Surface

TOOL = "Sample"

CANONICAL_XML = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <tool name="Sample" displayname="Sample Tool" xmlns="">
    <summary><![CDATA[<p>Makes a sample.</p>]]></summary>
    <parameters>
      <param name="wired" type="Required" direction="Input" datatype="GPDouble">
        <dialogReference><para>Wired text, 5 m².</para></dialogReference>
      </param>
      <param name="Out_Unwired" type="Derived" direction="Output" datatype="GPFeatureLayer">
        <dialogReference><para>Unwired text.</para></dialogReference>
      </param>
      <param name="hidden" type="Derived" direction="Output" datatype="GPLong">
        <dialogReference><para></para></dialogReference>
      </param>
    </parameters>
  </tool>
</metadata>
"""

CONTENT = {
    "type": "ScriptTool",
    "displayname": "$rc:title",
    "params": {
        "wired": {"displayname": "$rc:wired.title", "description": "$rc:wired.descr"},
        "Out_Unwired": {"type": "derived", "displayname": "$rc:out_unwired.title"},
        "hidden": {"type": "derived", "displayname": "$rc:hidden.title"},
    },
}

RC = {"map": {"title": "Sample", "wired.title": "W", "wired.descr": "old"}}

OTHER = {"toolbox.content": b'{"alias": "x"}', f"{TOOL}.tool/tool.metadata.xml": b"<metadata/>"}
CONTENT_NAME = f"{TOOL}.tool/tool.content"
RC_NAME = f"{TOOL}.tool/tool.content.rc"
WIRED_TEXT = "Wired text, 5 m²."
MATCHING_MAP = {"title": "Sample", "wired.title": "W", "wired.descr": WIRED_TEXT,
                "description": "Makes a sample.", "out_unwired.descr": "Unwired text."}
STALE_RC = {"map": {**DEMO_RC["map"], "description": "Old."}}


@pytest.fixture
def tool_dir(tmp_path: Path) -> Path:
    """Write the canonical source for the sample tool and return its folder."""
    folder = tmp_path / "tools"
    folder.mkdir()
    (folder / f"{TOOL}.xml").write_text(CANONICAL_XML, encoding="utf-8")
    return folder


def _members(rc_bytes: bytes, content: Optional[dict] = None) -> dict:
    text = json.dumps(CONTENT if content is None else content, indent=4)
    return {**OTHER, CONTENT_NAME: text.encode("utf-8"), RC_NAME: rc_bytes}


def _archive(tmp_path: Path, rc_data: object, content: Optional[dict] = None) -> Path:
    raw = json.dumps(rc_data, indent=1).encode("utf-8")
    return write_archive(tmp_path / "case.atbx", _members(raw, content))


def _member_bytes(atbx_path: Path, name: str) -> bytes:
    with zipfile.ZipFile(atbx_path) as zin:
        return zin.read(name)


@pytest.fixture
def atbx(tmp_path: Path) -> Path:
    """Build a toolbox-shaped zip holding the sample tool."""
    return write_archive(tmp_path / "sample.atbx", _members(json.dumps(RC, indent=1).encode("utf-8")))


@pytest.fixture
def stale_root(make_project: Callable[..., Path]) -> Path:
    """A demo project whose rc summary differs from the canonical summary."""
    return make_toolbox(make_project, members=toolbox_members(rc=STALE_RC))


def _read_json(atbx_path: Path, name: str) -> dict:
    with zipfile.ZipFile(atbx_path) as zin:
        return json.loads(zin.read(name))


def _bak(atbx_path: Path) -> Path:
    return atbx_path.with_name(atbx_path.name + ".bak")


# --- pure helpers ---------------------------------------------------------------------------------------

def test_missing_refs_lists_description_and_unwired_params_with_text() -> None:
    descr = {"wired": "Wired text.", "out_unwired": "Unwired text.", "hidden": ""}
    keys = rc.missing_refs(CONTENT, "Makes a sample.", descr)
    assert keys == ("description", "out_unwired.descr")


def test_missing_refs_skips_description_without_summary() -> None:
    assert rc.missing_refs(CONTENT, "", {"out_unwired": "Text."}) == ("out_unwired.descr",)


def test_wire_content_adds_refs_without_mutating_input() -> None:
    wired = rc.wire_content(CONTENT, ("description", "out_unwired.descr"))
    assert wired["description"] == "$rc:description"
    assert wired["params"]["Out_Unwired"]["description"] == "$rc:out_unwired.descr"
    assert "description" not in wired["params"]["hidden"]
    assert list(wired)[-1] == "params"
    assert "description" not in CONTENT
    assert "description" not in CONTENT["params"]["Out_Unwired"]
    assert "description" not in CONTENT["params"]["hidden"]


def test_wire_content_keeps_the_original_key_order() -> None:
    content = {**CONTENT, "environments": ["extent"]}
    wired = rc.wire_content(content, ("description",))
    assert list(wired) == ["type", "displayname", "description", "params", "environments"]
    assert list(rc.wire_content(content, ())) == list(content)


def test_apply_to_rc_adds_only_wired_keys() -> None:
    descr = {"wired": "New.", "out_unwired": "Unwired text."}
    _, unwired_changes = rc._apply_to_rc(RC, "Sum.", descr)
    assert "out_unwired.descr" not in unwired_changes
    new_rc, changes = rc._apply_to_rc(RC, "Sum.", descr, ("description", "out_unwired.descr"))
    rc_map = json.loads(new_rc)["map"]
    assert rc_map["out_unwired.descr"] == "Unwired text."
    assert rc_map["description"] == "Sum."
    assert changes["wired.descr"] == ("old", "New.")
    assert RC["map"]["wired.descr"] == "old"


# --- run_rc over an injected archive --------------------------------------------------------------------

def test_run_dry_run_leaves_archive_unchanged(atbx: Path, tool_dir: Path) -> None:
    before = atbx.read_bytes()
    outcome = rc.run_rc(TOOL, atbx, tool_dir, apply=False)
    assert atbx.read_bytes() == before
    assert not _bak(atbx).exists()
    assert (outcome.surface, outcome.tool) == (Surface.RC, TOOL)
    assert (outcome.changed, outcome.applied) == (True, False)
    assert outcome.lines[0] == f"{TOOL}: 3 field(s) would change"
    assert "  tool.content: add reference $rc:out_unwired.descr" in outcome.lines
    assert outcome.lines[-1].startswith("DRY-RUN: nothing written.")


def test_run_apply_wires_content_and_rc(atbx: Path, tool_dir: Path) -> None:
    before = atbx.read_bytes()
    outcome = rc.run_rc(TOOL, atbx, tool_dir, apply=True)
    params = CONTENT["params"]
    expected_content = {
        "type": "ScriptTool", "displayname": "$rc:title", "description": "$rc:description",
        "params": {"wired": params["wired"],
                   "Out_Unwired": {**params["Out_Unwired"], "description": "$rc:out_unwired.descr"},
                   "hidden": params["hidden"]},
    }
    expected_rc = {"map": {"title": "Sample", "wired.title": "W", "wired.descr": WIRED_TEXT,
                           "description": "Makes a sample.", "out_unwired.descr": "Unwired text."}}
    content_bytes = json.dumps(expected_content, ensure_ascii=False, indent=4).encode("utf-8") + b"\n"
    assert _member_bytes(atbx, CONTENT_NAME) == content_bytes
    rc_bytes = json.dumps(expected_rc, ensure_ascii=False, indent=1).encode("utf-8")
    assert _member_bytes(atbx, RC_NAME) == rc_bytes
    assert _bak(atbx).read_bytes() == before
    with zipfile.ZipFile(atbx) as zin:
        for name, data in OTHER.items():
            assert zin.read(name) == data
    assert (outcome.changed, outcome.applied) == (True, True)
    assert outcome.lines[-1].startswith(f"APPLIED. Backup at {_bak(atbx).name}.")


def test_run_apply_twice_is_idempotent(atbx: Path, tool_dir: Path) -> None:
    rc.run_rc(TOOL, atbx, tool_dir, apply=True)
    first = atbx.read_bytes()
    second = rc.run_rc(TOOL, atbx, tool_dir, apply=True)
    assert atbx.read_bytes() == first
    assert any("Sample: no changes" in line for line in second.lines)
    assert not any("APPLIED" in line for line in second.lines)
    assert (second.changed, second.applied) == (False, False)


def test_run_reads_a_bom_rc_and_rewrites_it_as_utf8_without_bom(tmp_path: Path, tool_dir: Path) -> None:
    """SRC wrote the rc as UTF-8 without a byte-order mark; a BOM source member comes back without one."""
    raw = b"\xef\xbb\xbf" + json.dumps(RC, indent=1).encode("utf-8")
    atbx = write_archive(tmp_path / "bom.atbx", _members(raw))
    rc.run_rc(TOOL, atbx, tool_dir, apply=True)
    with zipfile.ZipFile(atbx) as zin:
        written = zin.read(RC_NAME)
    assert written.startswith(b"{")
    assert json.loads(written.decode("utf-8"))["map"]["wired.descr"] == WIRED_TEXT


@pytest.mark.parametrize("member", [RC_NAME, CONTENT_NAME])
def test_run_refuses_an_archive_missing_a_member(tmp_path: Path, tool_dir: Path, member: str) -> None:
    members = _members(json.dumps(RC).encode("utf-8"))
    del members[member]
    atbx = write_archive(tmp_path / "short.atbx", members)
    with pytest.raises(ApiError, match=rf"{member}.*short\.atbx"):
        rc.run_rc(TOOL, atbx, tool_dir)


@pytest.mark.parametrize("params", [["wired"], {"wired": "$rc:wired.descr"}])
def test_run_refuses_a_malformed_params_object(tmp_path: Path, tool_dir: Path, params: object) -> None:
    atbx = _archive(tmp_path, RC, {**CONTENT, "params": params})
    with pytest.raises(ApiError, match=rf"{CONTENT_NAME} in case\.atbx has a malformed params object"):
        rc.run_rc(TOOL, atbx, tool_dir)


def _corrupt_member(atbx_path: Path, name: str) -> None:
    """Overwrite the first deflate byte of ``name`` with a reserved block type (a zlib error on read)."""
    with zipfile.ZipFile(atbx_path) as zf:
        info = zf.getinfo(name)
    raw = bytearray(atbx_path.read_bytes())
    offset = info.header_offset
    start = offset + 30 + int.from_bytes(raw[offset + 26:offset + 28], "little") \
        + int.from_bytes(raw[offset + 28:offset + 30], "little")
    raw[start] = 0xFF
    atbx_path.write_bytes(bytes(raw))


def test_run_refuses_a_member_whose_compressed_data_is_corrupt(tmp_path: Path, tool_dir: Path) -> None:
    atbx = _archive(tmp_path, RC)
    _corrupt_member(atbx, RC_NAME)
    with pytest.raises(ApiError, match=r"case\.atbx cannot be read"):
        rc.run_rc(TOOL, atbx, tool_dir)


def test_run_reports_a_null_rc_value_as_an_empty_old_value(tmp_path: Path, tool_dir: Path) -> None:
    atbx = _archive(tmp_path, {"map": {**MATCHING_MAP, "wired.descr": None}}, _wired_content())
    outcome = rc.run_rc(TOOL, atbx, tool_dir)
    assert outcome.changed is True
    assert outcome.lines[2:5] == ["  [wired.descr]", "    - ", f"    + {WIRED_TEXT}"]


def _wired_content() -> dict:
    """CONTENT with every reference the canonical text needs already in place."""
    out = rc.wire_content(CONTENT, ("description", "out_unwired.descr"))
    assert out != CONTENT
    return out


def test_run_names_a_reference_the_rc_lacks_and_leaves_it_out(tmp_path: Path, tool_dir: Path) -> None:
    rc_map = {k: v for k, v in MATCHING_MAP.items() if k != "wired.descr"}
    atbx = _archive(tmp_path, {"map": rc_map}, _wired_content())
    before = atbx.read_bytes()
    outcome = rc.run_rc(TOOL, atbx, tool_dir, apply=True)
    assert (outcome.changed, outcome.applied) == (False, False)
    assert atbx.read_bytes() == before
    assert not any("already matches" in line for line in outcome.lines)
    assert any("$rc:wired.descr" in line and "not added" in line for line in outcome.lines)


def test_run_wires_content_without_touching_a_matching_rc(tmp_path: Path, tool_dir: Path) -> None:
    atbx = _archive(tmp_path, {"map": MATCHING_MAP})
    rc_before = _member_bytes(atbx, RC_NAME)
    outcome = rc.run_rc(TOOL, atbx, tool_dir, apply=True)
    assert (outcome.changed, outcome.applied) == (True, True)
    assert _member_bytes(atbx, RC_NAME) == rc_before
    content = _read_json(atbx, CONTENT_NAME)
    assert content["description"] == "$rc:description"
    assert content["params"]["Out_Unwired"]["description"] == "$rc:out_unwired.descr"


# --- apply_rc over a configured project -----------------------------------------------------------------

def test_apply_rc_dry_run_reports_a_stale_project_without_writing(stale_root: Path) -> None:
    before = (stale_root / ATBX).read_bytes()
    outcome = rc.apply_rc(DEMO_TOOL, repo=stale_root)
    assert (outcome.changed, outcome.applied) == (True, False)
    assert (stale_root / ATBX).read_bytes() == before


def test_apply_rc_apply_writes_and_backs_up(stale_root: Path) -> None:
    archive = stale_root / ATBX
    before = archive.read_bytes()
    outcome = rc.apply_rc(DEMO_TOOL, apply=True, repo=stale_root)
    assert outcome.applied is True
    assert _bak(archive).read_bytes() == before
    assert _read_json(archive, f"{DEMO_TOOL}.tool/tool.content.rc")["map"]["description"] == "Makes polygons."
    assert rc.apply_rc(DEMO_TOOL, repo=stale_root).changed is False


def test_apply_rc_refuses_an_unknown_tool(stale_root: Path) -> None:
    with pytest.raises(ApiError, match=r"no canonical source.*Nope\.xml"):
        rc.apply_rc("Nope", repo=stale_root)


def test_apply_rc_refuses_a_tool_the_archive_lacks(stale_root: Path) -> None:
    (stale_root / TOOL_DIR / "Nope.xml").write_text(CANONICAL, encoding="utf-8")
    with pytest.raises(ApiError, match=rf"Nope\.tool/tool\.content\.rc is missing from {re.escape(ATBX)}"):
        rc.apply_rc("Nope", repo=stale_root)
