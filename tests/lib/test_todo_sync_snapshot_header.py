"""Snapshot header round trip: report.snapshot_header writes what sources.parse_header reads back."""
from __future__ import annotations

import pytest

from harness_lib.todo_sync.report import snapshot_header
from harness_lib.todo_sync.sources import parse_header

_SHA = "0" * 64


@pytest.mark.parametrize("source", ["docs/TODO/TodoCatalog.json", "docs/My TODO/TodoCatalog.json"])
def test_header_round_trips(source: str) -> None:
    header = parse_header(snapshot_header(source, 10, _SHA, "2026-10-19"))
    assert header is not None
    fields = (header.source, header.top, header.rows_sha256, header.rendered)
    assert fields == (source, 10, _SHA, "2026-10-19")


def test_header_without_fields_does_not_parse() -> None:
    assert parse_header("<!-- todo-snapshot source= top=10 -->") is None
