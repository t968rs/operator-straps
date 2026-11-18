"""arc-meta "?" page writer: the illustration embed, the archive reader and ``apply_page`` on a demo repo."""
from __future__ import annotations

import base64
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import arc_meta_page as page
from arc._arc_toolbox import (ATBX, CANONICAL, ILLUSTRATION_ENTRY, PNG_A, TOOL, TOOL_DIR, default_page,
                              make_toolbox, toolbox_members, write_archive)
from arc_meta_models import ApiError, Surface

PAGE_NAME = f"{TOOL}.tool/tool.metadata.xml"
LINK_NAME = f"{TOOL}.tool/tool.script.execute.link"


def _tool_dir(tmp_path: Path) -> Path:
    """A folder holding the canonical ``Demo.xml``."""
    folder = tmp_path / "tools"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{TOOL}.xml").write_text(CANONICAL, encoding="utf-8")
    return folder


def _member(atbx: Path, name: str) -> bytes:
    with zipfile.ZipFile(atbx) as zf:
        return zf.read(name)


def _names(atbx: Path) -> list:
    with zipfile.ZipFile(atbx) as zf:
        return zf.namelist()


def _crc_corrupt(path: Path, members: dict, name: str) -> Path:
    """An uncompressed archive of ``members`` whose ``name`` payload has its last byte flipped (bad CRC)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for member, data in members.items():
            zf.writestr(member, data)
    raw, payload = path.read_bytes(), members[name]
    assert raw.count(payload) == 1
    end = raw.index(payload) + len(payload) - 1
    path.write_bytes(raw[:end] + bytes([raw[end] ^ 0xFF]) + raw[end + 1:])
    return path


# --- build_page / read_illustration ---------------------------------------------------------------------

def test_built_page_embeds_the_illustration_as_a_data_uri(tmp_path: Path) -> None:
    root = ET.fromstring(page.build_page(TOOL, _tool_dir(tmp_path), PNG_A).encode("utf-8"))
    img = root.find("Binary/Thumbnail/img")
    assert img is not None
    assert img.get("src") == "data:image/png;base64," + base64.b64encode(PNG_A).decode("ascii")
    assert list(root)[-1].tag == "Binary"


def test_built_page_without_an_illustration_has_no_binary_block(tmp_path: Path) -> None:
    assert ET.fromstring(page.build_page(TOOL, _tool_dir(tmp_path)).encode("utf-8")).find("Binary") is None


def test_read_illustration_returns_the_archive_member_or_none(tmp_path: Path) -> None:
    with_member = write_archive(tmp_path / "with_member.atbx", {ILLUSTRATION_ENTRY: PNG_A})
    assert page.read_illustration(with_member, TOOL) == PNG_A
    without_member = write_archive(tmp_path / "without_member.atbx", {f"{TOOL}.tool/tool.content": b"{}"})
    assert page.read_illustration(without_member, TOOL) is None


def test_build_page_is_the_shared_canonical_builder(tmp_path: Path) -> None:
    assert page.build_page(TOOL, _tool_dir(tmp_path)) == default_page()


# --- run_page (pure core) --------------------------------------------------------------------------------

def test_linked_script_tool_without_a_page_gets_one_appended(tmp_path: Path) -> None:
    members = {k: v for k, v in toolbox_members().items() if k != PAGE_NAME}
    members[LINK_NAME] = b"..\\..\\tools\\demo\\run.py"
    atbx = write_archive(tmp_path / ATBX, members)
    outcome = page.run_page(TOOL, atbx, _tool_dir(tmp_path), apply=True)
    assert (outcome.changed, outcome.applied) == (True, True)
    assert "new entry" in outcome.lines[0]
    assert _names(atbx)[-1] == PAGE_NAME
    assert _member(atbx, PAGE_NAME).decode("utf-8") == default_page()


def test_run_page_embeds_the_archive_illustration_and_elides_it_in_the_report(tmp_path: Path) -> None:
    atbx = write_archive(tmp_path / ATBX, toolbox_members(extra={ILLUSTRATION_ENTRY: PNG_A}))
    outcome = page.run_page(TOOL, atbx, _tool_dir(tmp_path), apply=True)
    assert outcome.applied is True
    assert _member(atbx, PAGE_NAME).decode("utf-8") == default_page(illustration=PNG_A)
    assert any('src="data:image/png;base64,..."' in line for line in outcome.lines)
    assert not any(base64.b64encode(PNG_A).decode("ascii") in line for line in outcome.lines)


def test_run_page_refuses_a_tool_the_archive_does_not_hold(tmp_path: Path) -> None:
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / "Ghost.xml").write_text(CANONICAL, encoding="utf-8")
    atbx = write_archive(tmp_path / ATBX, toolbox_members())
    before = atbx.read_bytes()
    with pytest.raises(ApiError, match="is not a tool"):
        page.run_page("Ghost", atbx, tool_dir, apply=True)
    assert atbx.read_bytes() == before


def test_run_page_refuses_a_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="no toolbox"):
        page.run_page(TOOL, tmp_path / "absent.atbx", _tool_dir(tmp_path))


def test_run_page_repairs_a_page_that_is_not_utf8(tmp_path: Path) -> None:
    old = b"<metadata>caf\xe9 page</metadata>"
    atbx = write_archive(tmp_path / ATBX, toolbox_members(extra={PAGE_NAME: old}))
    outcome = page.run_page(TOOL, atbx, _tool_dir(tmp_path), apply=True)
    assert (outcome.changed, outcome.applied) == (True, True)
    assert f"unreadable page ({len(old)} bytes)" in outcome.lines[0]
    assert _member(atbx, PAGE_NAME).decode("utf-8") == default_page()


def test_run_page_repairs_a_crc_corrupt_page(tmp_path: Path) -> None:
    members = toolbox_members(page="<metadata>stale page body</metadata>")
    atbx = _crc_corrupt(tmp_path / ATBX, members, PAGE_NAME)
    outcome = page.run_page(TOOL, atbx, _tool_dir(tmp_path), apply=True)
    assert (outcome.changed, outcome.applied) == (True, True)
    assert f"unreadable page ({len(members[PAGE_NAME])} bytes)" in outcome.lines[0]
    assert _member(atbx, PAGE_NAME).decode("utf-8") == default_page()


def test_run_page_reports_the_old_page_size_in_bytes(tmp_path: Path) -> None:
    old = "<metadata>café</metadata>".encode("utf-8")
    atbx = write_archive(tmp_path / ATBX, toolbox_members(extra={PAGE_NAME: old}))
    outcome = page.run_page(TOOL, atbx, _tool_dir(tmp_path))
    assert f"metadata.xml {len(old)} bytes ->" in outcome.lines[0]


def test_read_illustration_refuses_a_corrupt_member(tmp_path: Path) -> None:
    atbx = _crc_corrupt(tmp_path / ATBX, toolbox_members(extra={ILLUSTRATION_ENTRY: PNG_A}),
                        ILLUSTRATION_ENTRY)
    with pytest.raises(ApiError, match=f"{ILLUSTRATION_ENTRY} in {ATBX} is corrupt"):
        page.read_illustration(atbx, TOOL)


# --- apply_page (config entry point) ---------------------------------------------------------------------

def _stale(make_project) -> Path:
    return make_toolbox(make_project, members=toolbox_members(page="<metadata/>"))


def test_apply_page_dry_run_reports_without_writing(make_project) -> None:
    root = _stale(make_project)
    before = (root / ATBX).read_bytes()
    outcome = page.apply_page(TOOL, repo=root)
    assert (outcome.surface, outcome.tool) == (Surface.PAGE, TOOL)
    assert (outcome.changed, outcome.applied) == (True, False)
    assert outcome.lines[-1].startswith("DRY-RUN")
    assert (root / ATBX).read_bytes() == before
    assert not (root / f"{ATBX}.bak").exists()


def test_apply_page_writes_a_backup_and_is_idempotent(make_project) -> None:
    root = _stale(make_project)
    before = (root / ATBX).read_bytes()
    outcome = page.apply_page(TOOL, apply=True, repo=root)
    assert (outcome.changed, outcome.applied) == (True, True)
    assert outcome.lines[-1].startswith("APPLIED")
    assert (root / f"{ATBX}.bak").read_bytes() == before
    assert _member(root / ATBX, PAGE_NAME).decode("utf-8") == default_page()
    again = page.apply_page(TOOL, repo=root)
    assert (again.changed, again.applied) == (False, False)


def test_apply_page_refuses_an_unknown_tool(make_project) -> None:
    root = _stale(make_project)
    before = (root / ATBX).read_bytes()
    with pytest.raises(ApiError, match="Nope is not a tool"):
        page.apply_page("Nope", apply=True, repo=root)
    assert (root / ATBX).read_bytes() == before


def test_apply_page_refuses_a_tool_without_canonical_xml(make_project) -> None:
    root = _stale(make_project)
    (root / TOOL_DIR / f"{TOOL}.xml").unlink()
    with pytest.raises(ApiError, match="no canonical source"):
        page.apply_page(TOOL, repo=root)
