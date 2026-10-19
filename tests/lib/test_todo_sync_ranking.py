"""harness_lib.todo_sync.ranking: the ranking_method score and the deterministic rank order."""
from __future__ import annotations

import copy
import json

import pytest

from conftest import FIXTURES
from harness_lib.todo_sync.ranking import RankingError, expected_order, method_from, score, sort_key

CATALOG = json.loads((FIXTURES / "todo_sync" / "TodoCatalog.min.json").read_text(encoding="utf-8"))


@pytest.fixture()
def doc():
    return copy.deepcopy(CATALOG)


def test_scores_reproduce_the_fixture(doc) -> None:
    method = method_from(doc["ranking_method"])
    for item in doc["items"]:
        value, components = score(item, method)
        assert value == item["priority"]["score"]
        assert components == pytest.approx(item["priority"]["components"])


def test_unblock_bonus_only_when_the_item_unblocks(doc) -> None:
    method = method_from(doc["ranking_method"])
    item = doc["items"][0]
    _, with_bonus = score(item, method)
    item["unblocks"] = []
    value, without = score(item, method)
    assert with_bonus["unblock_bonus"] == 0.15 and without["unblock_bonus"] == 0.0
    assert value == without["base_score"]


def test_expected_order_matches_ranks(doc) -> None:
    method = method_from(doc["ranking_method"])
    assert expected_order(doc["items"], method) == ["TODO-001", "TODO-002", "TODO-003"]


def test_tie_breaks_on_severity_then_loe_then_source(doc) -> None:
    method = method_from(doc["ranking_method"])
    a, b = doc["items"][1], copy.deepcopy(doc["items"][1])
    b["id"], b["title"] = "TODO-009", "Another"
    b["sources"] = [{"type": "gh_issue", "ref": "#5", "url": "u"}]
    assert sort_key(b, method, 1.0) < sort_key(a, method, 1.0)
    b["sources"] = [{"type": "impl_stub", "ref": "docs/A/_IMPL_TODO.md", "item": "Z"}]
    assert sort_key(b, method, 1.0) < sort_key(a, method, 1.0)
    b["severity"] = 1
    assert sort_key(a, method, 1.0) < sort_key(b, method, 1.0)
    b["severity"] = a["severity"]
    b["loe"]["size"] = "L"
    assert sort_key(a, method, 1.0) < sort_key(b, method, 1.0)


def test_gh_refs_compare_numerically(doc) -> None:
    method = method_from(doc["ranking_method"])
    a, b = copy.deepcopy(doc["items"][0]), copy.deepcopy(doc["items"][0])
    a["sources"][0]["ref"], b["sources"][0]["ref"] = "#9", "#10"
    assert sort_key(a, method, 1.0) < sort_key(b, method, 1.0)


def test_missing_method_key_raises(doc) -> None:
    del doc["ranking_method"]["blast_factors"]
    with pytest.raises(RankingError, match="blast_factors"):
        method_from(doc["ranking_method"])


def test_unknown_weight_key_raises(doc) -> None:
    method = method_from(doc["ranking_method"])
    doc["items"][0]["impact"] = "mystery"
    with pytest.raises(RankingError, match="mystery"):
        score(doc["items"][0], method)
