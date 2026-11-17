"""Snapshot header round trip and rank order: report.snapshot_header writes what sources.parse_header
reads back, and sources.ranked_items / top_items order the catalog by rank."""
from __future__ import annotations

from typing import Any, Dict

import pytest

from harness_lib.todo_sync.report import snapshot_header
from harness_lib.todo_sync.sources import parse_header, ranked_items, top_items

_SHA = "0" * 64


def _item(ident: str, rank: Any) -> Dict[str, Any]:
    return {"id": ident, "rank": rank, "title": f"Title {ident}", "status": "OPEN"}


@pytest.mark.parametrize("source", ["docs/TODO/TodoCatalog.json", "docs/My TODO/TodoCatalog.json"])
def test_header_round_trips(source: str) -> None:
    header = parse_header(snapshot_header(source, 10, _SHA, "2026-10-19"))
    assert header is not None
    fields = (header.source, header.top, header.rows_sha256, header.rendered)
    assert fields == (source, 10, _SHA, "2026-10-19")


def test_header_without_fields_does_not_parse() -> None:
    assert parse_header("<!-- todo-snapshot source= top=10 -->") is None


def test_ranked_items_put_items_without_an_int_rank_last_in_catalog_order() -> None:
    items = [_item("todo-z", "x"), _item("todo-c", None), _item("todo-b", 2), _item("todo-a", 1)]
    assert [i["id"] for i in ranked_items(items)] == ["todo-a", "todo-b", "todo-z", "todo-c"]
    assert top_items(items, 2) == ranked_items(items)[:2]
