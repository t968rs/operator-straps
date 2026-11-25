"""``inbox put`` requires a keyword on every drafted item and names the guess when one is missing (plan 2028).

The agent path (``todo_sync.py inbox put``, run by the todo-editor agent for add-todo and sync-gh-todo)
refuses an item without a one-word ``keyword``, its refusal naming ``guess_keyword``'s answer or saying there
is none; the agent may set any one-word value, and a value with a trailing newline is no one word. ``add
--spec``, the drain and an update take ``keyword`` and keep it right after the title.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, MIN_CATALOG, build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, inbox, updates  # noqa: E402
from harness_lib.todo_sync.reshape import add_items  # noqa: E402

WALK_ROOTS = ()
DAY = dt.date(2026, 11, 13)


def _item(**over: Any) -> Dict[str, Any]:
    base = {"title": "parser: the last row drops", "kind": "bug", "summary": "The parser skips a row.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}, "why_ranked": "Computed from ranking_method.",
            "files": ["src/parser.py"]}
    return {k: v for k, v in {**base, **over}.items() if v is not None}


def _spec(tmp_path: Path, items: List[Dict[str, Any]]) -> Path:
    path = tmp_path / "add.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


def _refusal(cfg, spec: Path) -> str:
    """The put's refusal text, or '' when it queued the spec."""
    try:
        inbox.put(cfg, spec)
    except TodoSyncError as exc:
        return str(exc)
    return ""


def test_put_refuses_an_item_without_a_keyword_naming_the_guess(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    message = _refusal(cfg, _spec(tmp_path, [_item()]))
    assert message == "item 1 lacks keyword (suggested: parser)"


def test_put_says_when_there_is_no_guess(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    message = _refusal(cfg, _spec(tmp_path, [_item(title="Rows drop", files=[])]))
    assert message.startswith("item 1 lacks keyword (no confident guess")


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
def test_put_counts_a_blank_keyword_as_missing(make_project, tmp_path: Path, blank: str) -> None:
    cfg = build(make_project)
    assert _refusal(cfg, _spec(tmp_path, [_item(keyword=blank)])).startswith("item 1 lacks keyword")


def test_put_queues_the_agents_own_keyword(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    spec = _spec(tmp_path, [_item(keyword="rows")])
    assert _refusal(cfg, spec) == ""
    [queued] = sorted(inbox.inbox_dir(cfg).glob("*.json"))
    assert json.loads(queued.read_text(encoding="utf-8"))["items"][0]["keyword"] == "rows"


def test_put_refuses_a_keyword_of_two_words(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    assert _refusal(cfg, _spec(tmp_path, [_item(keyword="two words")])).startswith("item 1: keyword")


def test_add_keeps_a_keyword_right_after_the_title() -> None:
    try:
        out = add_items(copy.deepcopy(MIN_CATALOG), [_item(keyword="rows")])
    except TodoSyncError as exc:
        raise AssertionError(str(exc)) from exc
    [(new, _issue)] = out.added
    item = next(i for i in out.catalog["items"] if i["id"] == new)
    keys = list(item)
    assert item["keyword"] == "rows" and keys[keys.index("title") + 1] == "keyword"


def test_put_refuses_a_keyword_ending_in_a_newline(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    assert _refusal(cfg, _spec(tmp_path, [_item(keyword="parser\n")])).startswith("item 1: keyword")


def _after_title(item: Dict[str, Any]) -> bool:
    keys = list(item)
    return keys[keys.index("title") + 1] == "keyword"


def test_the_drain_keeps_a_keyword_right_after_the_title(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    assert _refusal(cfg, _spec(tmp_path, [_item(keyword="rows")])) == ""
    [(new, _issue)] = inbox.drain(cfg, today=DAY).added
    catalog = json.loads(cfg.path(CATALOG_REL).read_text(encoding="utf-8"))
    item = next(i for i in catalog["items"] if i["id"] == new)
    assert item["keyword"] == "rows" and _after_title(item)


def test_an_update_sets_the_keyword_right_after_the_title() -> None:
    catalog = copy.deepcopy(MIN_CATALOG)
    target = next(i for i in catalog["items"] if "keyword" not in i)
    out = updates.apply_updates(catalog, [{"id": target["id"], "fields": {"keyword": "rows"}}])
    item = next(i for i in out.catalog["items"] if i["id"] == target["id"])
    assert item["keyword"] == "rows" and _after_title(item)
    assert out.updated == ((target["id"], ("keyword",)),)
