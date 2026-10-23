"""Adding drafted items to the TODO catalog, on copies of ``TodoCatalog.min.json``.

TODO-001 unblocks TODO-002; issue 11 is TODO-001's source, 101 a tracker with child 103, 102 a close
candidate.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, MIN_CATALOG, build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, check  # noqa: E402
from harness_lib.todo_sync.ranking import method_from, score  # noqa: E402
from harness_lib.todo_sync.reshape import add_items, apply_add, read_spec, summary_lines  # noqa: E402

CATALOG_RULES = ["T1", "T6", "T7", "T8", "T9", "T10"]


def _spec(issue: int = 9, **over: Any) -> Dict[str, Any]:
    """A full spec item: the scoring fields of TODO-001 with severity 5, so it outranks TODO-001."""
    base = {"issue": issue, "url": f"https://github.com/example/widgets/issues/{issue}",
            "title": f"New problem {issue}", "kind": "bug", "summary": "The parser skips a row.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}, "why_ranked": "Computed from ranking_method."}
    return {**base, **over}


def _catalog() -> Dict[str, Any]:
    return copy.deepcopy(MIN_CATALOG)


def test_new_item_outranks_and_shifts_the_rest() -> None:
    out = add_items(_catalog(), [_spec()])
    items = {i["id"]: i for i in out.catalog["items"]}
    assert out.added == (("TODO-001", 9),)
    assert out.renames == {"TODO-001": "TODO-002", "TODO-002": "TODO-003", "TODO-003": "TODO-004"}
    assert items["TODO-001"]["gh_issues"] == [9]
    assert items["TODO-001"]["sources"] == [{"type": "gh_issue", "ref": "#9",
                                             "url": "https://github.com/example/widgets/issues/9"}]
    assert items["TODO-002"]["unblocks"] == ["TODO-003"]
    assert items["TODO-003"]["depends_on"] == ["TODO-002"]
    assert out.catalog["trackers"][0]["child_todo_ids"] == ["TODO-003"]


def test_low_value_item_lands_last() -> None:
    low = _spec(severity=1, impact="docs_tooling", loe={"size": "XL", "reasoning": "Large."},
                blast_radius={"level": "XL", "reasoning": "Everything.", "consumers": []})
    out = add_items(_catalog(), [low])
    assert out.added == (("TODO-004", 9),)
    assert out.renames == {}


def test_counts_follow_the_new_items() -> None:
    out = add_items(_catalog(), [_spec(9), _spec(12)])
    assert out.catalog["counts"]["items"] == 5
    assert out.catalog["counts"]["sources_absorbed"]["gh_issue"] == 3
    assert all(new not in out.rescored for new, _ in out.added)


def test_priority_is_computed_not_taken() -> None:
    out = add_items(_catalog(), [_spec()])
    item = out.catalog["items"][0]
    value, _ = score(item, method_from(out.catalog["ranking_method"]))
    assert item["priority"]["score"] == value


CASES: Dict[str, Callable[[], List[Any]]] = {
    "missing why_ranked": lambda: [{k: v for k, v in _spec().items() if k != "why_ranked"}],
    "sets rank": lambda: [_spec(rank=1)],
    "sets depends_on": lambda: [_spec(depends_on=["TODO-001"])],
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
    "bad issue": "positive integer", "empty": "at least one", "unscoreable": "cannot score"}


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
    "unknown loe size": ({"loe": {"size": "Q", "reasoning": "x"}}, "cannot score"),
    "unknown blast level": ({"blast_radius": {"level": "Z", "reasoning": "x", "consumers": []}},
                            "cannot score"),
}


@pytest.mark.parametrize("case", list(TYPE_CASES))
def test_wrong_value_types_are_refused_not_crashes(case: str) -> None:
    over, fragment = TYPE_CASES[case]
    with pytest.raises(TodoSyncError, match=fragment):
        add_items(_catalog(), [_spec(**over)])


def test_apply_add_writes_the_catalog_and_dry_run_does_not(make_project) -> None:
    cfg = build(make_project)
    catalog_path = cfg.project_root / CATALOG_REL
    spec = cfg.project_root / "add.json"
    spec.write_text(json.dumps({"items": [_spec()]}), encoding="utf-8")
    before = catalog_path.read_bytes()
    dry = apply_add(cfg, spec, dry_run=True)
    assert catalog_path.read_bytes() == before
    assert summary_lines(dry, True)[0].startswith("would add TODO-001 (#9);")
    done = apply_add(cfg, spec)
    written = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert [i["id"] for i in written["items"]] == ["TODO-001", "TODO-002", "TODO-003", "TODO-004"]
    assert summary_lines(done, False)[0] == "added TODO-001 (#9); 4 item(s) now"
    assert summary_lines(done, False)[-1] == "next: todo_sync.py render, then todo_sync.py check"
    report = check(cfg, rules=CATALOG_RULES)
    assert report.findings == ()


def test_read_spec_names_its_key(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"parts": []}), encoding="utf-8")
    with pytest.raises(TodoSyncError, match="'items'"):
        read_spec(path, "items")
    assert read_spec(path) == []
