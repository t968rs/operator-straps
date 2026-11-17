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


def _doc(bubbles: Sequence[str] = ("C1", "I2", "I3"),
         resolutions: Sequence[Dict[str, str]] = ()) -> Dict[str, Any]:
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


def test_apply_facts_replaces_the_prefilled_references(root: Path) -> None:
    prefilled = bm.entry_blocks(_scaffold())["C1"]
    assert "`src/a.py:3-5`" in prefilled
    refs = [{"at": "src/a.py:10-12", "note": "moved by the fix wave"}]
    facts = bm.validate_facts(_facts(references=refs), _doc()["issues"]["critical"][0], root)
    block = bm.entry_blocks(bm.apply_facts(_scaffold(), facts))["C1"]
    assert "`src/a.py:10-12` (moved by the fix wave)" in block and "`src/a.py:3-5`" not in block


def test_a_second_apply_keeps_hand_corrected_references(root: Path) -> None:
    facts = bm.validate_facts(_facts(), _doc()["issues"]["critical"][0], root)
    first = bm.apply_facts(_scaffold(), facts)
    edited = first.replace("`src/a.py:3-5` (the read)", "`src/a.py:4` (corrected by hand)")
    assert edited != first
    assert bm.apply_facts(edited, facts) == edited


def test_an_apply_that_changes_nothing_keeps_crlf_text(root: Path) -> None:
    facts = bm.validate_facts(_facts(), _doc()["issues"]["critical"][0], root)
    applied = bm.apply_facts(_scaffold(), facts).replace("\n", "\r\n")
    assert bm.apply_facts(applied, facts) is applied


def test_reference_files_reads_only_the_references_field() -> None:
    block = bm.entry_blocks(_scaffold())["I2"]
    cited = block.replace(f"- **Current behavior:** {bm.STUB}", "- **Current behavior:** see `src/b.py:2`")
    assert bm.reference_files(cited) == ["src/a.py"]


# ---------------------------------------------------------------- review follow-ups

_FLOW = "  ```\n  filled\n  ```"


def test_an_indented_rule_inside_a_flow_block_does_not_end_the_entry(root: Path) -> None:
    text = _filled(_scaffold()).replace(_FLOW, "  ```\n  a\n  ---\n  b\n  ```")
    assert bm.DECISION_OPEN in bm.entry_blocks(text)["C1"]
    assert _check(text, root) == ([], [])


def test_an_unindented_rule_ends_the_entry() -> None:
    text = _filled(_scaffold()).replace(bm.DECISION_OPEN, "---\n" + bm.DECISION_OPEN, 1)
    assert bm.DECISION_OPEN not in bm.entry_blocks(text)["C1"]


def test_a_flagged_entry_needs_a_parsed_reference(root: Path) -> None:
    text = _filled(_scaffold()).replace("`src/a.py:3-5`", "see above")
    problems, _ = _check(text, root)
    assert any(p.startswith("C1: ") and "path:line" in p for p in problems)


def test_a_flagged_entry_needs_a_flow_line(root: Path) -> None:
    text = _filled(_scaffold()).replace(_FLOW, "  ```\n  ```")
    problems, _ = _check(text, root)
    assert any(p.startswith("C1: ") and "flow" in p for p in problems)


def test_other_code_spans_are_prose_and_paths_are_normalised(root: Path) -> None:
    prose = _filled(_scaffold()).replace("`src/a.py:10-12`", "`src/a.py:10-12`, `load()`")
    assert _check(prose, root) == ([], [])
    same = _filled(_scaffold()).replace("`src/a.py:10-12`", "`./src/a.py:2`, `src/a.py:1`")
    assert _check(same, root) == ([], [])


def test_facts_models_refuse_unknown_keys_and_mismatched_options(root: Path) -> None:
    issue = _doc()["issues"]["critical"][0]
    effects = [{"option": "fix one", "effect": "x"}, {"option": "fix two", "effect": "y"}]
    bads = [{"extra": 1},
            {"fix_effects": [{**effects[0], "more": 1}, effects[1]]},
            {"fix_effects": [{"option": " ", "effect": "x"}, effects[1]]},
            {"fix_effects": [effects[1], effects[0]]}]
    for bad in bads:
        with pytest.raises(ValueError):
            bm.validate_facts(_facts(**bad), issue, root)
    spaced = [{"option": "fix   one", "effect": "x"}, effects[1]]
    assert bm.validate_facts(_facts(fix_effects=spaced), issue, root).id == "C1"


def test_only_plain_line_ranges_are_prefilled() -> None:
    for lines in ("~189-190", "10-12, 40"):
        doc = _doc()
        doc["issues"]["important"][0]["lines"] = lines
        blocks = bm.entry_blocks(bm.scaffold_memo(doc, bm.currently_bubbled(doc, [])))
        assert f"`src/a.py:{bm.STUB}`" in blocks["I2"]


def test_reference_problem_survives_bad_paths_and_counts_lines_by_newline(root: Path) -> None:
    assert "absolute" in (bm.reference_problem(f"{root.as_posix()}/src/a.py:1", root) or "")
    assert bm.reference_problem("a" * 5000 + ".py:1", root) is not None
    (root / "src" / "c.py").write_bytes(b"a\nb\nc\n")
    (root / "src" / "d.py").write_text("a\u2028b\n", encoding="utf-8")
    assert bm.reference_problem("src/c.py:3", root) is None
    assert bm.reference_problem("src/c.py:4", root) is not None
    assert bm.reference_problem("src/d.py:2", root) is not None


def test_crlf_text_is_read_as_lf(root: Path) -> None:
    crlf = _filled(_scaffold()).replace("\n", "\r\n")
    assert _check(crlf, root) == ([], [])
    assert [r.id for r in bm.parse_index(crlf)] == ["C1", "I2", "I3"]
    assert set(bm.entry_blocks(crlf)) == {"C1", "I2", "I3"}
    doc = _doc(("C1", "I2", "I3"))
    first = _scaffold(("I2",)).replace("\n", "\r\n")
    updated, added = bm.add_missing(first, doc, bm.currently_bubbled(doc, []))
    assert added == ["C1", "I3"] and "\r" not in updated
    facts = bm.validate_facts(_facts(), doc["issues"]["critical"][0], root)
    assert "\r" not in bm.apply_facts(_scaffold().replace("\n", "\r\n"), facts)


def test_a_malformed_index_row_is_a_problem_and_never_duplicated(root: Path) -> None:
    row = "| I2 | architectural_ambiguity | Open | - | - |"
    text = _filled(_scaffold()).replace(row, "| I2 | architectural_ambiguity | Open | a|b | - |")
    problems, _ = _check(text, root)
    assert "I2: malformed index row" in problems
    assert not any(p.startswith("I2: no index row") for p in problems)
    doc = _doc()
    assert bm.add_missing(text, doc, bm.currently_bubbled(doc, [])) == (text, [])


def test_add_missing_refuses_a_memo_without_an_index() -> None:
    doc = _doc(("I2",))
    with pytest.raises(ValueError):
        bm.add_missing("# PR #1 Bubbles: x\n", doc, bm.currently_bubbled(doc, []))


def test_a_prose_heading_is_not_an_entry() -> None:
    text = _scaffold() + "\n### Note. The above is draft\n\nprose\n"
    assert set(bm.entry_blocks(text)) == {"C1", "I2", "I3"}
    assert "prose" not in bm.entry_blocks(text)["I3"]


def test_scaffold_scope_names_the_review_file() -> None:
    doc = _doc()
    text = bm.scaffold_memo(doc, bm.currently_bubbled(doc, []), review_file="1514_Feature_x.json")
    scope = next(ln for ln in text.splitlines() if ln.startswith("- **Scope:**"))
    assert "1514_Feature_x.json" in scope and "#1514" in scope and "abc1234" in scope
