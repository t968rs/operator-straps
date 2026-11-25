"""Adding drafted items to the TODO catalog, on copies of ``TodoCatalog.min.json``.

ID1 unblocks ID2; issue 11 is ID1's source, 101 a tracker with child 103, 102 a close candidate. A new item
gets a new stable id; every other id stays and only ranks move.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, ID1, ID2, ID3, MIN_CATALOG, Scripted, build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, check  # noqa: E402
from harness_lib.todo_sync.ids import is_id  # noqa: E402
from harness_lib.todo_sync.ranking import method_from, score  # noqa: E402
from harness_lib.todo_sync.reshape import add_items, apply_add, read_spec, summary_lines  # noqa: E402

CATALOG_RULES = ["T1", "T6", "T7", "T8", "T9", "T10"]


def _spec(issue: int = 9, **over: Any) -> Dict[str, Any]:
    """A full spec item: the scoring fields of ID1 with severity 5, so it outranks ID1."""
    base = {"issue": issue, "url": f"https://github.com/example/widgets/issues/{issue}",
            "title": f"New problem {issue}", "kind": "bug", "summary": "The parser skips a row.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}, "why_ranked": "Computed from ranking_method."}
    return {**base, **over}


def _catalog() -> Dict[str, Any]:
    return copy.deepcopy(MIN_CATALOG)


def test_added_items_get_new_ids_and_every_other_id_stays() -> None:
    out = add_items(_catalog(), [_spec()])
    [(new, issue)] = out.added
    assert issue == 9 and is_id(new) and new not in {ID1, ID2, ID3}
    assert [(i["id"], i["rank"]) for i in out.catalog["items"]] == [(new, 1), (ID1, 2), (ID2, 3), (ID3, 4)]
    assert out.reranked == ((ID1, 1, 2), (ID2, 2, 3), (ID3, 3, 4))
    items = {i["id"]: i for i in out.catalog["items"]}
    assert items[new]["gh_issues"] == [9]
    assert items[new]["sources"] == [{"type": "gh_issue", "ref": "#9",
                                      "url": "https://github.com/example/widgets/issues/9"}]
    assert items[ID1]["unblocks"] == [ID2]
    assert items[ID2]["depends_on"] == [ID1]
    assert out.catalog["trackers"][0]["child_todo_ids"] == [ID2]
    assert not hasattr(out, "renames")


def test_low_value_item_lands_last() -> None:
    low = _spec(severity=1, impact="docs_tooling", loe={"size": "XL", "reasoning": "Large."},
                blast_radius={"level": "XL", "reasoning": "Everything.", "consumers": []})
    out = add_items(_catalog(), [low])
    assert out.catalog["items"][-1]["id"] == out.added[0][0]
    assert out.reranked == ()


def test_add_never_draws_a_retired_id() -> None:
    catalog = _catalog()
    catalog["retired_ids"] = ["todo-2a2a"]
    out = add_items(catalog, [_spec()], rng=Scripted("2a2a" + "p4rs" + "k7qf"))
    assert out.added == (("todo-k7qf", 9),)
    assert out.catalog["retired_ids"] == ["todo-2a2a"]


def test_counts_follow_the_new_items() -> None:
    out = add_items(_catalog(), [_spec(9), _spec(12)])
    assert out.catalog["counts"]["items"] == 5
    assert out.catalog["counts"]["sources_absorbed"]["gh_issue"] == 3
    assert all(new not in out.rescored for new, _ in out.added)
    assert len({new for new, _ in out.added}) == 2


def test_an_issue_only_cross_referenced_by_an_item_gets_its_own_item() -> None:
    catalog = _catalog()
    catalog["items"][0]["related_gh_issues"] = [400]
    out = add_items(catalog, [_spec(400)])
    assert [n for _, n in out.added] == [400]


def test_priority_is_computed_not_taken() -> None:
    out = add_items(_catalog(), [_spec()])
    item = out.catalog["items"][0]
    value, _ = score(item, method_from(out.catalog["ranking_method"]))
    assert item["priority"]["score"] == value


CASES: Dict[str, Callable[[], List[Any]]] = {
    "missing why_ranked": lambda: [{k: v for k, v in _spec().items() if k != "why_ranked"}],
    "sets rank": lambda: [_spec(rank=1)],
    "sets depends_on": lambda: [_spec(depends_on=[ID1])],
    "sets sources": lambda: [_spec(sources=[])],
    "item source": lambda: [_spec(11)],
    "tracker": lambda: [_spec(101)],
    "tracker child": lambda: [_spec(103)],
    "close candidate": lambda: [_spec(102)],
    "same issue twice": lambda: [_spec(9), _spec(9)],
    "not an object": lambda: ["text"],
    "bad issue": lambda: [_spec(0)],
    "empty": lambda: [],
    "unscoreable": lambda: [_spec(impact="nonsense")],
}
FRAGMENTS = {
    "missing why_ranked": "why_ranked", "sets rank": "sets rank", "sets depends_on": "sets depends_on",
    "sets sources": "sets sources", "item source": "#11", "tracker": "#101", "tracker child": "#103",
    "close candidate": "#102", "same issue twice": "appears twice", "not an object": "not an object",
    "bad issue": "positive integer", "empty": "at least one", "unscoreable": "item 1: impact"}


@pytest.mark.parametrize("case", list(CASES))
def test_refusals(case: str) -> None:
    with pytest.raises(TodoSyncError, match=FRAGMENTS[case]):
        add_items(_catalog(), CASES[case]())


TYPE_CASES = {
    "loe as a string": ({"loe": "S"}, "loe"),
    "blast_radius as a string": ({"blast_radius": "S"}, "blast_radius"),
    "blast_radius without consumers": ({"blast_radius": {"level": "S", "reasoning": "x"}}, "blast_radius"),
    "severity as a string": ({"severity": "5"}, "severity"),
    "severity null": ({"severity": None}, "severity"),
    "severity out of range": ({"severity": 6}, "severity"),
    "severity a bool": ({"severity": True}, "severity"),
    "files as a string": ({"files": "src/a.py"}, "files"),
    "related_gh_issues as a number": ({"related_gh_issues": 12}, "related_gh_issues"),
    "needs_decision as a string": ({"needs_decision": "yes"}, "needs_decision"),
    "empty title": ({"title": ""}, "title"),
    "unknown status": ({"status": "DONE"}, "status"),
    "unknown loe size": ({"loe": {"size": "Q", "reasoning": "x"}}, "item 1: loe/size"),
    "unknown blast level": ({"blast_radius": {"level": "Z", "reasoning": "x", "consumers": []}},
                            "item 1: blast_radius/level"),
    "unknown kind": ({"kind": "chore"}, "item 1: kind"),
    "url not https": ({"url": "http://example.com/9"}, "item 1: sources/0/url"),
    "snippet without a path:line header": ({"code_snippet": "x = 1\n"}, "item 1: code_snippet"),
    "files listed twice": ({"files": ["src/a.py", "src/a.py"]}, "item 1: files"),
    "extra loe key": ({"loe": {"size": "S", "reasoning": "x", "points": 2}}, "item 1: loe"),
    "decision without a question": ({"needs_decision": True}, "item 1: decision_question"),
    "question without a decision": ({"decision_question": "Which?"}, "item 1: decision_question"),
    "NEEDS_DECISION status without the flag": ({"status": "NEEDS_DECISION"}, "item 1: needs_decision"),
}


@pytest.mark.parametrize("case", list(TYPE_CASES))
def test_wrong_value_types_are_refused_not_crashes(case: str) -> None:
    over, fragment = TYPE_CASES[case]
    with pytest.raises(TodoSyncError, match=fragment):
        add_items(_catalog(), [_spec(**over)])


def test_dry_run_says_its_ids_are_provisional(make_project) -> None:
    cfg = build(make_project)
    spec = cfg.project_root / "add.json"
    spec.write_text(json.dumps({"items": [_spec()]}), encoding="utf-8")
    lines = summary_lines(apply_add(cfg, spec, dry_run=True), True)
    assert re.fullmatch(r"would add todo-[2-9a-hjkmnp-z]{4} \(#9\); 4 item\(s\) now", lines[0])
    assert "note: new ids are drawn at random; the real run draws its own" in lines


def test_apply_add_writes_the_catalog_and_dry_run_does_not(make_project) -> None:
    cfg = build(make_project)
    catalog_path = cfg.project_root / CATALOG_REL
    spec = cfg.project_root / "add.json"
    spec.write_text(json.dumps({"items": [_spec()]}), encoding="utf-8")
    before = catalog_path.read_bytes()
    apply_add(cfg, spec, dry_run=True)
    assert catalog_path.read_bytes() == before
    done = apply_add(cfg, spec)
    new = done.reshape.added[0][0]
    written = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert [i["id"] for i in written["items"]] == [new, ID1, ID2, ID3]
    lines = summary_lines(done, False)
    assert lines[0] == f"added {new} (#9); 4 item(s) now"
    assert f"re-ranked 3 item(s): {ID1} 1->2, {ID2} 2->3, {ID3} 3->4" in lines
    assert not any(line.startswith("note: new ids") for line in lines)
    assert lines[-1] == "next: todo_sync.py render, then todo_sync.py check"
    report = check(cfg, rules=CATALOG_RULES)
    assert report.findings == ()


def test_apply_add_refusal_leaves_the_catalog_untouched(make_project) -> None:
    cfg = build(make_project)
    catalog_path = cfg.project_root / CATALOG_REL
    spec = cfg.project_root / "add.json"
    spec.write_text(json.dumps({"items": [_spec(9), _spec(11)]}), encoding="utf-8")
    before = catalog_path.read_bytes()
    with pytest.raises(TodoSyncError, match="#11"):
        apply_add(cfg, spec)
    assert catalog_path.read_bytes() == before


def test_read_spec_names_its_key(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"parts": []}), encoding="utf-8")
    with pytest.raises(TodoSyncError, match="'items'"):
        read_spec(path, "items")
    assert read_spec(path) == []
