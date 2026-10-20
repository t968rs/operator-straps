"""Snapshot item links: ``item_stubs`` finds an item's ``_IMPL_TODO.md`` files, ``link_target`` encodes them.

Projects are built on copies of ``TodoCatalog.min.json`` through ``_todo_helpers``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import (RESEARCH_REL, SNAP_DIR, STUB_REL, TODO_DIR, build, config, stub_text,  # noqa: E402
                           todo_files)
from harness_lib.todo_sync.sources import Sources  # noqa: E402
from harness_lib.todo_sync.stub_links import item_stubs, link_target  # noqa: E402

BETA_STUB = "docs/RESEARCH/Beta/_IMPL_TODO.md"


def _item(sources: Optional[List[Dict[str, Any]]] = None,
          entry_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"id": "TODO-009", "sources": sources or [], "catalog_entry_ids": entry_ids or []}


def _impl(ref: str) -> Dict[str, Any]:
    return {"type": "impl_stub", "ref": ref}


def _stubs(make_project, item: Dict[str, Any], files: Optional[Dict[str, Any]] = None,
           cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    return item_stubs(Sources(build(make_project, files, cfg)), item)


def _with_beta() -> Dict[str, Any]:
    files = todo_files()
    files[BETA_STUB] = stub_text("beta-cache")
    return files


def test_impl_stub_source_wins(make_project) -> None:
    assert _stubs(make_project, _item([_impl(STUB_REL)])) == [STUB_REL]


def test_research_folder_holds_the_stub(make_project) -> None:
    item = _item([{"type": "research_folder", "ref": "docs/RESEARCH/Alpha"}])
    assert _stubs(make_project, item) == [STUB_REL]


def test_entry_id_matches_a_stub(make_project) -> None:
    assert _stubs(make_project, _item(entry_ids=["alpha-loader"])) == [STUB_REL]


def test_entry_anchor_scan_finds_a_stub_without_stub_path(make_project) -> None:
    assert _stubs(make_project, _item(entry_ids=["beta-cache"]), _with_beta()) == [BETA_STUB]


def test_one_stub_by_three_routes_is_one_link(make_project) -> None:
    item = _item([_impl(STUB_REL), {"type": "research_folder", "ref": "docs/RESEARCH/Alpha"},
                  _impl("./docs/RESEARCH/Alpha/_IMPL_TODO.md")], ["alpha-loader"])
    assert _stubs(make_project, item) == [STUB_REL]


def test_missing_impl_stub_falls_through(make_project) -> None:
    item = _item([_impl("docs/RESEARCH/Gone/_IMPL_TODO.md")], ["alpha-loader"])
    assert _stubs(make_project, item) == [STUB_REL]


def test_two_stubs_in_route_order(make_project) -> None:
    item = _item([_impl(BETA_STUB)], ["alpha-loader"])
    assert _stubs(make_project, item, _with_beta()) == [BETA_STUB, STUB_REL]


def test_no_stub_is_empty(make_project) -> None:
    item = _item([{"type": "gh_issue", "ref": "#11", "url": "https://example.invalid/11"}])
    assert _stubs(make_project, item) == []


def test_null_stub_name_uses_impl_stub_only(make_project) -> None:
    item = _item([_impl(BETA_STUB), {"type": "research_folder", "ref": "docs/RESEARCH/Alpha"}])
    cfg = config({"folder": TODO_DIR, "stub_name": None})
    assert _stubs(make_project, item, _with_beta(), cfg) == [BETA_STUB]


def test_anchor_scan_is_rooted_at_artifacts_research(make_project) -> None:
    cfg = config(artifacts={"research": "docs/NOWHERE"})
    assert _stubs(make_project, _item(entry_ids=["beta-cache"]), _with_beta(), cfg) == []


def test_entry_stub_path_alone_finds_a_stub(make_project) -> None:
    files = todo_files()
    files[BETA_STUB] = stub_text("other-id")
    files[RESEARCH_REL]["entries"][1]["stub_path"] = BETA_STUB
    assert _stubs(make_project, _item(entry_ids=["beta-cache"]), files) == [BETA_STUB]


def test_null_stub_name_keeps_the_entry_stub_path(make_project) -> None:
    cfg = config({"folder": TODO_DIR, "stub_name": None})
    assert _stubs(make_project, _item(entry_ids=["alpha-loader"]), cfg=cfg) == [STUB_REL]


def test_missing_research_catalog_still_scans_anchors(make_project) -> None:
    files = todo_files()
    del files[RESEARCH_REL]
    cfg = build(make_project, files)
    assert cfg.todo.research.catalog is None
    assert item_stubs(Sources(cfg), _item(entry_ids=["alpha-loader"])) == [STUB_REL]


def test_case_variant_ref_is_one_link_spelled_as_on_disk(make_project) -> None:
    cfg = build(make_project)
    variant = STUB_REL.lower()
    if not cfg.path(variant).is_file():
        pytest.skip("case-sensitive filesystem")
    assert item_stubs(Sources(cfg), _item([_impl(variant), _impl(STUB_REL)])) == [STUB_REL]


@pytest.mark.parametrize("field", ["sources", "catalog_entry_ids"])
@pytest.mark.parametrize("value", [5, "docs/RESEARCH/Alpha/_IMPL_TODO.md", {"type": "impl_stub"}])
def test_non_list_fields_count_as_empty(make_project, field: str, value: Any) -> None:
    item = {**_item(), field: value}
    assert _stubs(make_project, item) == []


def _abs_ref(root: Path) -> str:
    return (root / STUB_REL).as_posix()


def _drive_ref(root: Path) -> str:
    return "C:/x/_IMPL_TODO.md"


def _escaping_ref(root: Path) -> str:
    outside = root.parent / "x" / "_IMPL_TODO.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text(stub_text(), encoding="utf-8")
    return "docs/../../x/_IMPL_TODO.md"


@pytest.mark.parametrize("make_ref", [_abs_ref, _drive_ref, _escaping_ref])
def test_refs_outside_the_project_never_link(make_project, make_ref) -> None:
    cfg = build(make_project)
    item = _item([_impl(make_ref(cfg.project_root))])
    assert item_stubs(Sources(cfg), item) == []


def test_link_target() -> None:
    assert link_target(STUB_REL, SNAP_DIR) == "../../Alpha/_IMPL_TODO.md"
    spaced = "docs/RESEARCH/A B (x)/_IMPL_TODO.md"
    assert link_target(spaced, SNAP_DIR) == "../../A%20B%20%28x%29/_IMPL_TODO.md"
    angled = "docs/RESEARCH/a<b>|c/_IMPL_TODO.md"
    assert link_target(angled, SNAP_DIR) == "../../a%3Cb%3E%7Cc/_IMPL_TODO.md"
