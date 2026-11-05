"""arc-meta shared records and archive helpers: the apply outcome model and the ``.atbx`` read/rewrite."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Dict
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

import arc_meta_archive as archive
from arc._arc_toolbox import (ATBX, CANONICAL, RC, TOOL, default_page, make_toolbox, toolbox_members,
                              write_archive)
from arc_meta_models import ApiError, ApplyOutcome, Surface
from conftest import git

CONTENT_NAME = f"{TOOL}.tool/tool.content"
RC_NAME = f"{TOOL}.tool/tool.content.rc"
PAGE_NAME = f"{TOOL}.tool/tool.metadata.xml"
MEMBERS: Dict[str, bytes] = {
    CONTENT_NAME: json.dumps({"params": {}}).encode("utf-8"),
    RC_NAME: json.dumps({"map": {"description": "Old."}}).encode("utf-8"),
    f"{TOOL}.tool/tool.illustration.png": b"\x89PNG\r\n\x1a\nimage",
}


# --- models ---------------------------------------------------------------------------------------------

def test_apply_outcome_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        ApplyOutcome(surface="rc", changed=True, applied=False, extra=1)


def test_apply_outcome_is_frozen() -> None:
    outcome = ApplyOutcome(surface="rc", changed=True, applied=False)
    with pytest.raises(ValidationError):
        outcome.applied = True


def test_apply_outcome_defaults_and_surface_values() -> None:
    outcome = ApplyOutcome(surface="toolbox", changed=False, applied=False)
    assert (outcome.surface, outcome.tool, outcome.lines) == (Surface.TOOLBOX, None, [])
    assert [s.value for s in Surface] == ["rc", "page", "toolbox"]


def test_api_error_is_a_value_error() -> None:
    assert issubclass(ApiError, ValueError)


# --- decode / read_text / read_json ---------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "h\u00e9".encode("utf-8"),
    b"\xef\xbb\xbf" + "h\u00e9".encode("utf-8"),
    b"\xff\xfe" + "h\u00e9".encode("utf-16-le"),
], ids=["utf-8", "utf-8-bom", "utf-16-le-bom"])
def test_decode_reads_utf8_with_or_without_bom_and_utf16(raw: bytes) -> None:
    assert archive.decode(raw) == "h\u00e9"


def test_read_text_returns_none_for_an_absent_member(tmp_path: Path) -> None:
    path = write_archive(tmp_path / ATBX, MEMBERS)
    with zipfile.ZipFile(path) as zf:
        assert archive.read_text(zf, PAGE_NAME, ATBX) is None
        assert archive.read_text(zf, RC_NAME, ATBX) == MEMBERS[RC_NAME].decode("utf-8")


def test_read_text_refuses_undecodable_bytes_naming_the_label(tmp_path: Path) -> None:
    path = write_archive(tmp_path / ATBX, {RC_NAME: b"\xff\x00\xd8"})
    refused = pytest.raises(ApiError, match=f"{RC_NAME} in {ATBX} is not UTF-8")
    with zipfile.ZipFile(path) as zf, refused as got:
        archive.read_text(zf, RC_NAME, ATBX)
    assert isinstance(got.value.__cause__, UnicodeDecodeError)


def test_read_json_parses_a_member_and_returns_none_when_absent(tmp_path: Path) -> None:
    path = write_archive(tmp_path / ATBX, MEMBERS)
    with zipfile.ZipFile(path) as zf:
        assert archive.read_json(zf, RC_NAME, ATBX) == {"map": {"description": "Old."}}
        assert archive.read_json(zf, PAGE_NAME, ATBX) is None


def test_read_json_refuses_invalid_json_naming_the_label(tmp_path: Path) -> None:
    path = write_archive(tmp_path / ATBX, {RC_NAME: b"{not json"})
    with zipfile.ZipFile(path) as zf, pytest.raises(ApiError, match=f"{RC_NAME} in {ATBX} is not valid JSON"):
        archive.read_json(zf, RC_NAME, ATBX)


# --- rewrite --------------------------------------------------------------------------------------------

def _temp(atbx: Path) -> Path:
    return atbx.with_name(atbx.name + ".tmp")


def _members(atbx: Path) -> Dict[str, bytes]:
    with zipfile.ZipFile(atbx) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_rewrite_replaces_appends_and_keeps_the_rest(tmp_path: Path) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    before = atbx.read_bytes()
    new_rc = json.dumps({"map": {"description": "New."}}).encode("utf-8")
    page = b'<?xml version="1.0"?>\n<metadata/>'
    archive.rewrite(atbx, {RC_NAME: new_rc, PAGE_NAME: page})
    got = _members(atbx)
    assert list(got) == [*MEMBERS, PAGE_NAME]
    assert (got[RC_NAME], got[PAGE_NAME]) == (new_rc, page)
    assert all(got[name] == data for name, data in MEMBERS.items() if name != RC_NAME)
    assert atbx.with_name(atbx.name + ".bak").read_bytes() == before
    assert not _temp(atbx).exists()


def test_rewrite_keeps_each_member_compression_and_deflates_appended_ones(tmp_path: Path) -> None:
    atbx = tmp_path / ATBX
    with zipfile.ZipFile(atbx, "w") as zf:
        zf.writestr(CONTENT_NAME, MEMBERS[CONTENT_NAME], compress_type=zipfile.ZIP_STORED)
        zf.writestr(RC_NAME, MEMBERS[RC_NAME], compress_type=zipfile.ZIP_DEFLATED)
    archive.rewrite(atbx, {CONTENT_NAME: b"{}", PAGE_NAME: b"<metadata/>"})
    with zipfile.ZipFile(atbx) as zf:
        kinds = {info.filename: info.compress_type for info in zf.infolist()}
    assert kinds == {CONTENT_NAME: zipfile.ZIP_STORED, RC_NAME: zipfile.ZIP_DEFLATED,
                     PAGE_NAME: zipfile.ZIP_DEFLATED}


def test_rewrite_refuses_a_corrupt_result_and_keeps_the_archive(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    before = atbx.read_bytes()
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: CONTENT_NAME)
    with pytest.raises(ApiError, match=CONTENT_NAME):
        archive.rewrite(atbx, {RC_NAME: MEMBERS[RC_NAME]})
    assert atbx.read_bytes() == before
    assert not _temp(atbx).exists()


@pytest.mark.parametrize("name,data,cause", [
    (RC_NAME, b"{not json", json.JSONDecodeError),
    (PAGE_NAME, b"<metadata><unclosed></metadata>", ET.ParseError),
], ids=["rc-json", "page-xml"])
def test_rewrite_refuses_a_member_that_does_not_parse(tmp_path: Path, name: str, data: bytes,
                                                      cause: type) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    before = atbx.read_bytes()
    with pytest.raises(ApiError, match=name) as got:
        archive.rewrite(atbx, {name: data})
    assert isinstance(got.value.__cause__, cause)
    assert atbx.read_bytes() == before
    assert not _temp(atbx).exists()


def test_rewrite_parses_bom_and_utf16_json_members(tmp_path: Path) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    utf16 = b"\xff\xfe" + json.dumps({"map": {}}).encode("utf-16-le")
    archive.rewrite(atbx, {RC_NAME: b"\xef\xbb\xbf{}", CONTENT_NAME: utf16})
    assert _members(atbx)[CONTENT_NAME] == utf16


# --- the shared builder ---------------------------------------------------------------------------------

def test_make_toolbox_commits_the_archive_and_the_canonical_source(make_project) -> None:
    root = make_toolbox(make_project)
    assert git(root, "status", "--porcelain") == ""
    assert (root / "tool_metadata" / "tools" / f"{TOOL}.xml").read_text(encoding="utf-8") == CANONICAL
    with zipfile.ZipFile(root / ATBX) as zf:
        assert archive.read_text(zf, PAGE_NAME, ATBX) == default_page()
        assert archive.read_json(zf, RC_NAME, ATBX) == RC
    assert list(toolbox_members(extra={"x": b""})) == [CONTENT_NAME, RC_NAME, PAGE_NAME, "x"]


# --- rewrite: refusals, backups and duplicates ----------------------------------------------------------

def test_rewrite_refuses_a_locked_archive_and_leaves_no_temp(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    before = atbx.read_bytes()

    def _locked(src: object, dst: object) -> None:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(archive.os, "replace", _locked)
    with pytest.raises(ApiError, match=f"{ATBX} is locked") as got:
        archive.rewrite(atbx, {RC_NAME: MEMBERS[RC_NAME]})
    assert isinstance(got.value.__cause__, PermissionError)
    assert atbx.read_bytes() == before
    assert not _temp(atbx).exists()


def test_failed_rewrite_leaves_an_existing_backup_untouched(tmp_path: Path) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    backup = atbx.with_name(atbx.name + ".bak")
    backup.write_bytes(b"earlier backup")
    with pytest.raises(ApiError):
        archive.rewrite(atbx, {RC_NAME: b"{not json"})
    assert backup.read_bytes() == b"earlier backup"


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_rewrite_keeps_the_bytes_of_each_duplicate_named_member(tmp_path: Path) -> None:
    atbx = tmp_path / ATBX
    with zipfile.ZipFile(atbx, "w") as zf:
        zf.writestr(CONTENT_NAME, b"{}")
        zf.writestr(CONTENT_NAME, b'{"second": 1}')
        zf.writestr(RC_NAME, MEMBERS[RC_NAME])
    archive.rewrite(atbx, {RC_NAME: b'{"map": {}}'})
    with zipfile.ZipFile(atbx) as zf:
        got = [zf.read(info) for info in zf.infolist()]
    assert got == [b"{}", b'{"second": 1}', b'{"map": {}}']


def test_rewrite_refuses_a_rewritten_archive_that_is_not_a_zip(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    atbx = write_archive(tmp_path / ATBX, MEMBERS)
    before = atbx.read_bytes()

    def _broken(self: zipfile.ZipFile) -> None:
        raise zipfile.BadZipFile("bad CRC")

    monkeypatch.setattr(zipfile.ZipFile, "testzip", _broken)
    with pytest.raises(ApiError, match=f"the rewritten {ATBX} is corrupt") as got:
        archive.rewrite(atbx, {RC_NAME: MEMBERS[RC_NAME]})
    assert isinstance(got.value.__cause__, zipfile.BadZipFile)
    assert atbx.read_bytes() == before
    assert not _temp(atbx).exists()
