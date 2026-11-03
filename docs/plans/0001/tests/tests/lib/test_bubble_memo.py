"""``harness_lib.bubble_memo``: the memo format, scaffold, completeness check, facts and reviewer model."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

from harness_lib import bubble_memo as bm


def _issue(issue_id: str, name: str, *, file: Optional[str] = None, files: Optional[List[str]] = None,
           lines: Optional[str] = None, fix: Sequence[str] = ("fix one", "fix two")) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": issue_id, "name": name, "summary": f"{name} summary", "fix": list(fix)}
    for key, value in (("file", file), ("files", files), ("lines", lines)):
        if value is not None:
            out[key] = value
    return out


def _doc(bubbles: Sequence[str] = ("C1", "I2", "I3"), resolutions: Sequence[Dict[str, str]] = ()) -> Dict[str, Any]:
    issues = {
        "critical": [_issue("C1", "Crash on load", file="src/a.py", lines="3-5")],
        "important": [_issue("I2", "Stale cache", file="src/a.py", lines="10-12",
                             fix=("cache fix one", "cache fix two")),
                      _issue("I3", "Two files", files=["src/a.py", "src/b.py"])],
        "minor": [],
    }
    return {"pr": 1514, "pr_title": "Feature x", "head_sha": "abc1234", "bubbles": list(bubbles),
            "bubble_up": [{"id": "I2", "classification": "architectural_ambiguity", "reason": "two fixes"}],
            "post_review_resolutions": list(resolutions), "issues": issues}


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    for name in ("a.py", "b.py"):
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / name).write_text("".join(f"x = {n}\n" for n in range(1, 31)), encoding="utf-8")
    return tmp_path


def _filled(text: str) -> str:
    return text.replace(f":{bm.STUB}", ":1").replace(bm.STUB, "filled")


def _scaffold(ids: Sequence[str] = ("C1", "I2", "I3")) -> str:
    doc = _doc(ids)
    return bm.scaffold_memo(doc, bm.currently_bubbled(doc, []))


def test_the_anchors_are_pinned() -> None:
    assert bm.MEMO_SUFFIX == "_Bubbles.md"
    assert bm.memo_name(1514) == "PR_1514_Bubbles.md"
    assert bm.INDEX_HEADER == "| ID | Class | Status | Decision | Tracked in |"
    assert (bm.STATUS_OPEN, bm.STATUS_DECIDED) == ("Open", "Decided")
    assert bm.DECISION_OPEN == "- **Decision:** open"
    assert bm.DECISION_PREFIX == "- **Decision:** "
    assert bm.ENTRY_PREFIX == "### "
    assert bm.STUB == "TODO(fill)"


def test_flagged_means_critical_or_several_files() -> None:
    doc = _doc()
    assert bm.flagged_ids(doc, ["C1", "I2", "I3"]) == ["C1", "I3"]
    assert bm.reviewer_model(["C1"]) == "opus"
    assert bm.reviewer_model([]) == "sonnet"


def test_currently_bubbled_adds_pending_fixer_bubbles_once() -> None:
    doc = _doc(("I2",))
    pending = [("I3", "needs_follow_up", "later"), ("I2", "out_of_scope", "dup")]
    found = [(b.id, b.cls, b.reason) for b in bm.currently_bubbled(doc, pending)]
    assert found == [("I2", "architectural_ambiguity", "two fixes"), ("I3", "needs_follow_up", "later")]


def test_an_unlisted_class_reads_unclassified() -> None:
    doc = _doc(("C1",))
    assert [b.cls for b in bm.currently_bubbled(doc, [])] == ["unclassified"]


def test_scaffold_writes_index_rows_headings_and_stubs() -> None:
    text = _scaffold()
    assert text.startswith("# PR #1514 Bubbles: Feature x")
    assert bm.INDEX_HEADER in text
    assert "| I2 | architectural_ambiguity | Open | - | - |" in text
    assert "### I2. Stale cache" in text
    assert "src/a.py:10-12" in text
    assert text.count(bm.DECISION_OPEN) == 3
    assert f"- (a) fix one -> {bm.STUB}" in text and f"- (b) fix two -> {bm.STUB}" in text


def test_references_without_lines_are_stubbed() -> None:
    blocks = bm.entry_blocks(_scaffold())
    assert f"src/b.py:{bm.STUB}" in blocks["I3"]


def test_only_flagged_entries_carry_chain_and_flow() -> None:
    blocks = bm.entry_blocks(_scaffold())
    assert "- **Chain:**" not in blocks["I2"]
    for flagged in ("C1", "I3"):
        assert "- **Chain:**" in blocks[flagged] and "```" in blocks[flagged]


def test_parse_index_reads_the_scaffolded_rows() -> None:
    rows = bm.parse_index(_scaffold())
    assert [(r.id, r.status) for r in rows] == [("C1", "Open"), ("I2", "Open"), ("I3", "Open")]
    assert rows[1].cls == "architectural_ambiguity"


def test_add_missing_appends_new_entries_and_leaves_old_text_alone() -> None:
    first = _scaffold(("I2",))
    doc = _doc(("I2", "I3"))
    updated, added = bm.add_missing(first, doc, bm.currently_bubbled(doc, []))
    assert added == ["I3"]
    assert bm.entry_blocks(updated)["I2"] == bm.entry_blocks(first)["I2"]
    assert [r.id for r in bm.parse_index(updated)] == ["I2", "I3"]


def test_add_missing_with_everything_present_changes_nothing() -> None:
    first = _scaffold()
    doc = _doc()
    updated, added = bm.add_missing(first, doc, bm.currently_bubbled(doc, []))
    assert (updated, added) == (first, [])


def _check(text: str, root: Path, bubbles: Sequence[str] = ("C1", "I2", "I3"), **kw: Any):
    doc = _doc(bubbles, **kw)
    return bm.check_memo(text, bm.currently_bubbled(doc, []), doc, root)


def test_a_filled_memo_passes(root: Path) -> None:
    problems, notes = _check(_filled(_scaffold()), root)
    assert (problems, notes) == ([], [])


def test_unfilled_stubs_fail(root: Path) -> None:
    problems, _ = _check(_scaffold(), root)
    assert any(p.startswith("I2: ") and bm.STUB in p for p in problems)


def test_a_bubbled_id_without_an_entry_fails(root: Path) -> None:
    problems, _ = _check(_filled(_scaffold(("C1", "I2"))), root)
    assert any(p.startswith("I3: ") and "entry" in p for p in problems)


def test_a_flagged_entry_without_a_chain_fails(root: Path) -> None:
    text = _filled(_scaffold()).replace("- **Chain:** filled", "")
    problems, _ = _check(text, root)
    assert any(p.startswith("C1: ") and "chain" in p.lower() for p in problems)


def test_an_entry_citing_two_files_needs_a_chain_even_when_the_json_names_one(root: Path) -> None:
    text = _filled(_scaffold()).replace("`src/a.py:10-12`", "`src/a.py:10-12`, `src/b.py:4`")
    blocks = bm.entry_blocks(text)
    assert "- **Chain:**" not in blocks["I2"]
    problems, _ = _check(text, root)
    assert any(p.startswith("I2: ") and "chain" in p.lower() for p in problems)


def test_a_line_past_the_end_of_the_file_fails(root: Path) -> None:
    problems, _ = _check(_filled(_scaffold()).replace("src/a.py:10-12", "src/a.py:99"), root)
    assert any(p.startswith("I2: ") and "99" in p for p in problems)


def test_a_missing_file_fails(root: Path) -> None:
    problems, _ = _check(_filled(_scaffold()).replace("src/a.py:10-12", "src/gone.py:1"), root)
    assert any(p.startswith("I2: ") and "gone.py" in p for p in problems)


def test_a_dropped_fix_option_fails(root: Path) -> None:
    problems, _ = _check(_filled(_scaffold()).replace("- (b) cache fix two -> filled\n", ""), root)
    assert any(p.startswith("I2: ") and "expected 2" in p for p in problems)


def test_a_stale_id_is_a_note_not_a_problem(root: Path) -> None:
    stale = _filled(_scaffold()) + "\n### I9. Renamed away\n\n- **Decision:** open\n"
    problems, notes = _check(stale, root)
    assert not any(p.startswith("I9") for p in problems)
    assert any(n.startswith("I9: ") for n in notes)


def test_a_decided_id_is_neither_problem_nor_note(root: Path) -> None:
    text = _filled(_scaffold(("C1", "I2", "I3")))
    problems, notes = _check(text, root, bubbles=("C1", "I3"),
                             resolutions=[{"id": "I2", "status": "RESOLVED"}])
    assert [p for p in problems if p.startswith("I2")] == []
    assert [n for n in notes if n.startswith("I2")] == []


def _facts(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": "C1", "current_behavior": "load raises KeyError", "when": "the cache file is empty",
        "chain": ["load reads the cache", "the key is missing"], "flow": "load -> read -> KeyError",
        "references": [{"at": "src/a.py:3-5", "note": "the read"}],
        "fix_effects": [{"option": "fix one", "effect": "returns an empty cache"},
                        {"option": "fix two", "effect": "raises a clear error"}],
        "confidence": "high",
    }
    return {**base, **over}


def test_valid_facts_pass(root: Path) -> None:
    assert bm.validate_facts(_facts(), _doc()["issues"]["critical"][0], root).id == "C1"


@pytest.mark.parametrize("bad", [
    {"when": ""}, {"chain": []}, {"fix_effects": [{"option": "fix one", "effect": "x"}]},
    {"references": [{"at": "src/a.py:99", "note": "past the end"}]},
    {"references": [{"at": "src/nope.py:1", "note": "no file"}]},
])
def test_invalid_facts_are_refused(root: Path, bad: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        bm.validate_facts(_facts(**bad), _doc()["issues"]["critical"][0], root)


def test_apply_facts_fills_the_flagged_entry_but_not_prose(root: Path) -> None:
    facts = bm.validate_facts(_facts(), _doc()["issues"]["critical"][0], root)
    text = bm.apply_facts(_scaffold(), facts)
    block = bm.entry_blocks(text)["C1"]
    assert "load raises KeyError" in block and "the cache file is empty" in block
    assert "1. load reads the cache" in block and "load -> read -> KeyError" in block
    assert "- (a) fix one -> returns an empty cache" in block
    assert "- **Description:** " + bm.STUB in block
    assert "- **Recommendation:** " + bm.STUB in block
    assert bm.entry_blocks(text)["I2"] == bm.entry_blocks(_scaffold())["I2"]
