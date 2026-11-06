"""Adding a local-only item (no GitHub issue) to the TODO catalog: the ``note`` source.

An add spec item without ``issue`` and ``url`` becomes an item whose one source is ``{"type": "note", "ref":
"<date added>"}``; it resolves no issue, so ``gh_issues`` stays empty. Copies of ``TodoCatalog.min.json``.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, MIN_CATALOG, build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, check  # noqa: E402
from harness_lib.todo_sync.ranking import SOURCE_TYPE_ORDER  # noqa: E402
from harness_lib.todo_sync.reshape import NOTE_SOURCE, add_items, apply_add, summary_lines  # noqa: E402

CATALOG_RULES = ["T1", "T6", "T7", "T8", "T9", "T10"]
DAY = "2026-11-06"


def _note(**over: Any) -> Dict[str, Any]:
    """A spec item with no issue: the scoring fields of a low-value reminder."""
    base = {"title": "Bump the README key table", "kind": "docs", "summary": "A reminder.",
            "proposed_change": "Add the row.", "impact": "docs_tooling", "severity": 1,
            "blast_radius": {"level": "S", "reasoning": "One file.", "consumers": []},
            "loe": {"size": "XS", "reasoning": "One line."}, "why_ranked": "Computed from ranking_method."}
    return {**base, **over}


def _catalog() -> Dict[str, Any]:
    return copy.deepcopy(MIN_CATALOG)


def test_note_item_gets_a_dated_note_source() -> None:
    out = add_items(_catalog(), [_note()], today=DAY)
    (new_id, issue), = out.added
    item = next(i for i in out.catalog["items"] if i["id"] == new_id)
    assert NOTE_SOURCE == "note"
    assert issue is None
    assert item["sources"] == [{"type": "note", "ref": DAY}]
    assert item["gh_issues"] == []


def test_note_count_is_created_then_incremented() -> None:
    catalog = _catalog()
    catalog["counts"]["sources_absorbed"].pop("note", None)
    once = add_items(catalog, [_note()], today=DAY)
    assert once.catalog["counts"]["sources_absorbed"]["note"] == 1
    twice = add_items(once.catalog, [_note(title="Second reminder")], today=DAY)
    assert twice.catalog["counts"]["sources_absorbed"]["note"] == 2
    assert twice.catalog["counts"]["sources_absorbed"]["gh_issue"] == \
        catalog["counts"]["sources_absorbed"]["gh_issue"]


@pytest.mark.parametrize("over, fragment", [
    ({"issue": 9}, "issue and url"),
    ({"url": "https://github.com/example/widgets/issues/9"}, "issue and url"),
])
def test_issue_and_url_come_together_or_not_at_all(over: Dict[str, Any], fragment: str) -> None:
    with pytest.raises(TodoSyncError, match=fragment):
        add_items(_catalog(), [_note(**over)], today=DAY)


def test_note_sorts_after_every_other_source_type_on_a_tie() -> None:
    assert SOURCE_TYPE_ORDER[NOTE_SOURCE] > max(v for k, v in SOURCE_TYPE_ORDER.items() if k != NOTE_SOURCE)


def test_note_item_passes_the_catalog_rules(make_project) -> None:
    cfg = build(make_project)
    spec = cfg.project_root / "add.json"
    spec.write_text(json.dumps({"items": [_note()]}), encoding="utf-8")
    done = apply_add(cfg, spec, today=DAY)
    assert re.fullmatch(r"added TODO-\d{3} \(note\); 4 item\(s\) now", summary_lines(done, False)[0])
    written = json.loads((cfg.project_root / CATALOG_REL).read_text(encoding="utf-8"))
    assert [i["sources"] for i in written["items"]].count([{"type": "note", "ref": DAY}]) == 1
    assert check(cfg, rules=CATALOG_RULES).findings == ()
