"""The keyword guesser and the one-time keyword migration (plan 2028).

``guess_keyword`` answers only with high confidence: a one-word title prefix (``merge-commit-msg: ...``), else
the one file stem that dominates the item's ``files`` (test prefixes and suffixes folded in, generic stems
such as ``SKILL`` or ``README`` skipped), else None. ``fill_keywords`` writes a guess into every item that
has no keyword and leaves the rest without one; ``apply_keywords`` does it to the project catalog.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, ID1, ID2, ID3, MIN_CATALOG, build, rule_findings, todo_files  # noqa: E402


def _keywords():
    from harness_lib.todo_sync import keywords
    return keywords


def _guess(title: str, files: Optional[List[str]] = None) -> Optional[str]:
    return _keywords().guess_keyword({"title": title, "files": files or []})


@pytest.mark.parametrize("title, files, expected", [
    ("merge-commit-msg: fall back to local git", [], "merge-commit-msg"),
    ("pr-sum: add --level 0", ["plugins/harness/scripts/pr_sum.py"], "pr-sum"),
    ("Speed up the Stop hook", ["plugins/harness/hooks/stop_gates.py", "tests/hooks/test_stop_gates.py",
                                "plugins/harness/skills/pr-review/SKILL.md"], "stop_gates"),
    ("Line widget", ["plugins/working-refs/hooks/line.ts", "plugins/working-refs/hooks/line.test.ts"], "line"),
    ("Relink checks", ["lib/plan.py", "tests/test_plan.py", "lib/plan_lock.py"], "plan"),
    ("One module", ["src/config.py", "src/tracker.py"], "tracker"),
], ids=["prefix", "prefix-over-files", "single-stem", "ts-test-suffix", "dominant-stem", "generic-skipped"])
def test_a_confident_guess(title: str, files: List[str], expected: str) -> None:
    assert _guess(title, files) == expected


@pytest.mark.parametrize("title, files", [
    ("Docs: tidy the README", []),
    ("Working refs: clear another branch", ["plugins/harness/skills/working/SKILL.md"]),
    ("Two modules", ["src/one.py", "src/two.py"]),
    ("No files at all", []),
    ("Only generic files", ["README.md", "plugins/x/SKILL.md", "plugins/x/config/defaults.json"]),
    ("A long stem", [f"src/{'a' * 40}.py"]),
], ids=["kind-prefix", "multiword-prefix", "tie", "nothing", "generic-only", "too-long"])
def test_no_guess_without_confidence(title: str, files: List[str]) -> None:
    assert _guess(title, files) is None


def _catalog(**files_by_id: List[str]) -> Dict[str, Any]:
    data = copy.deepcopy(MIN_CATALOG)
    for item in data["items"]:
        item["files"] = files_by_id.get(item["id"].replace("-", "_"), [])
    return data


def test_fill_sets_confident_guesses_and_leaves_the_rest_without_a_keyword() -> None:
    data = _catalog(todo_p4rs=["src/parser.py", "tests/test_parser.py"])
    out = _keywords().fill_keywords(data)
    items = {i["id"]: i for i in out.catalog["items"]}
    assert items[ID1]["keyword"] == "parser"
    assert "keyword" not in items[ID2] and "keyword" not in items[ID3]
    assert out.set == ((ID1, "parser"),) and out.left == (ID2, ID3)
    assert "keyword" not in data["items"][0], "the input catalog is not changed"


def test_fill_keeps_an_existing_keyword_and_places_a_new_one_after_the_title() -> None:
    data = _catalog(todo_p4rs=["src/parser.py"], todo_sp7t=["src/loader.py"])
    data["items"][0]["keyword"] = "rows"
    out = _keywords().fill_keywords(data)
    items = {i["id"]: i for i in out.catalog["items"]}
    assert items[ID1]["keyword"] == "rows" and ID1 not in dict(out.set)
    keys = list(items[ID2])
    assert keys[keys.index("title") + 1] == "keyword"


def test_apply_writes_the_catalog_and_dry_run_does_not(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["items"][0]["files"] = ["src/parser.py"]
    cfg = build(make_project, files)
    path = cfg.path(CATALOG_REL)
    before = path.read_bytes()
    dry = _keywords().apply_keywords(cfg, dry_run=True)
    assert dry.set == ((ID1, "parser"),) and path.read_bytes() == before
    _keywords().apply_keywords(cfg)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["items"][0]["keyword"] == "parser"
    assert rule_findings(cfg, "T1") == []


def test_keyword_lines_name_each_set_and_count_the_rest() -> None:
    out = _keywords().fill_keywords(_catalog(todo_p4rs=["src/parser.py"]))
    lines = _keywords().keyword_lines(out, dry_run=False)
    assert lines[0] == "keywords: set 1, left 2 without one"
    assert f"set {ID1}: parser" in lines
