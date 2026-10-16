"""Behavioral tests for harness_lib.review_edit: per-field editors and the byte-stable load / save."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

from harness_lib import review_edit as red
from harness_lib.config import activate, load_config

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "review_edit"
_CORPUS = sorted(_FIXTURES.glob("*.json"))
_SHA = "3333333ccccccc"


@pytest.fixture
def project(make_project) -> Path:
    """An activated throwaway project (the plugin's schema governs)."""
    root = make_project(config={})
    activate(load_config(root))
    return root


@pytest.fixture
def doc() -> Dict[str, object]:
    return red.load_review(_FIXTURES / "open_review.json")


def test_corpus_mixes_line_endings() -> None:
    endings = {b"\r\n" in p.read_bytes() for p in _CORPUS}
    assert endings == {True, False}


@pytest.mark.parametrize("src", _CORPUS, ids=lambda p: p.name)
def test_round_trip_is_byte_identical(project: Path, tmp_path: Path, src: Path) -> None:
    target = tmp_path / src.name
    shutil.copyfile(src, target)
    red.save_review(target, red.load_review(target), project)
    assert target.read_bytes() == src.read_bytes()


def test_save_refuses_invalid_document(project: Path, tmp_path: Path, doc: Dict[str, object]) -> None:
    target = tmp_path / "r.json"
    shutil.copyfile(_FIXTURES / "open_review.json", target)
    bad = {**doc, "verdict": "READY TO MERGE - forced"}
    with pytest.raises(ValueError, match="issue counts"):
        red.save_review(target, bad, project)
    assert target.read_bytes() == (_FIXTURES / "open_review.json").read_bytes()


_NEW_ISSUE = {"name": "N", "file": "f.py", "summary": "s", "fix": ["f"]}

_EDITORS = [
    pytest.param(lambda d: red.set_schema(d, "x.json", "2.1.0"), id="set_schema"),
    pytest.param(lambda d: red.set_pr_meta(d, pr_title="New title"), id="set_pr_meta"),
    pytest.param(lambda d: red.set_shas(d, head_sha=_SHA), id="set_shas"),
    pytest.param(lambda d: red.set_review_date(d, "2026-10-05"), id="set_review_date"),
    pytest.param(lambda d: red.set_stats(d, 1, 2, 3), id="set_stats"),
    pytest.param(lambda d: red.set_verdict(d, "NOT READY TO MERGE - hold"), id="set_verdict"),
    pytest.param(red.recompute_verdict, id="recompute_verdict"),
    pytest.param(lambda d: red.add_reviewer(d, "x"), id="add_reviewer"),
    pytest.param(lambda d: red.remove_reviewer(d, "pr-reviewer-core"), id="remove_reviewer"),
    pytest.param(lambda d: red.set_scoped_files(d, ["a/b.py"]), id="set_scoped_files"),
    pytest.param(lambda d: red.add_bubble(d, "M1"), id="add_bubble"),
    pytest.param(lambda d: red.clear_bubble(red.add_bubble(d, "M1"), "M1"), id="clear_bubble"),
    pytest.param(lambda d: red.add_strength(d, "Good tests"), id="add_strength"),
    pytest.param(lambda d: red.set_strengths(d, ["a", "b"]), id="set_strengths"),
    pytest.param(lambda d: red.add_issue(d, "minor", _NEW_ISSUE), id="add_issue"),
    pytest.param(lambda d: red.regrade_issue(d, "M2", "important"), id="regrade_issue"),
    pytest.param(lambda d: red.merge_issue_ids(d, "M1", ["M2"]), id="merge_issue_ids"),
    pytest.param(lambda d: red.set_issue_field(d, "I1", "lines", "10-14"), id="set_issue_field"),
    pytest.param(lambda d: red.add_bubble_up(d, "I1", "out_of_scope", "later"), id="add_bubble_up"),
    pytest.param(lambda d: red.drop_bubble_up(red.add_bubble_up(d, "I1", "out_of_scope", "later"), "I1"),
                 id="drop_bubble_up"),
    pytest.param(lambda d: red.resolve(d, "M1", "RESOLVED", "done", "2026-10-02"), id="resolve"),
    pytest.param(lambda d: red.resolve_all(
        d, [{"id": "M1", "status": "RESOLVED", "evidence": "typo fixed", "date": "2026-10-02"}], _SHA),
        id="resolve_all"),
    pytest.param(lambda d: red.set_verification_phase(d, "dispatch_time", {"a": 1}),
                 id="set_verification_phase"),
    pytest.param(lambda d: red.set_verification_phase(
        red.set_verification_phase(d, "dispatch_time", {"a": 1}), "skipped", "catalog"),
        id="set_verification_phase_skipped"),
]


@pytest.mark.parametrize("editor", _EDITORS)
def test_editors_do_not_mutate(doc: Dict[str, object], editor) -> None:
    before = copy.deepcopy(doc)
    out = editor(doc)
    assert out is not doc
    assert doc == before


def test_set_schema(doc: Dict[str, object]) -> None:
    assert red.set_schema(doc, "x.json", "2.1.0")["schema_ref"] == "x.json"
    with pytest.raises(ValueError, match="unknown schema version"):
        red.set_schema(doc, "x.json", "9.9.9")


def test_set_pr_meta_keeps_unset(doc: Dict[str, object]) -> None:
    out = red.set_pr_meta(doc, pr_title="New title")
    assert (out["pr_title"], out["pr"], out["branch"]) == ("New title", 42, "feature/widget-cache")


def test_set_shas(doc: Dict[str, object]) -> None:
    assert red.set_shas(doc, head_sha=_SHA)["head_sha"] == _SHA
    assert red.set_shas(doc, base_sha="a" * 64)["base_sha"] == "a" * 64
    for bad in ("xyz1234", "abc", "A" * 40, "a" * 41):
        with pytest.raises(ValueError):
            red.set_shas(doc, base_sha=bad)


def test_set_review_date(doc: Dict[str, object]) -> None:
    assert red.set_review_date(doc, "2026-10-05")["review_date"] == "2026-10-05"
    for bad in ("10/05/2026", "2026-13-01"):
        with pytest.raises(ValueError):
            red.set_review_date(doc, bad)


def test_set_stats(doc: Dict[str, object]) -> None:
    assert red.set_stats(doc, 1, 2, 3)["stats"] == {"additions": 1, "deletions": 2, "files_changed": 3}
    with pytest.raises(ValueError):
        red.set_stats(doc, -1, 2, 3)
    with pytest.raises(ValueError):
        red.set_stats(doc, "1", 2, 3)


def test_verdict_refuses_ready_while_undispositioned(doc: Dict[str, object]) -> None:
    with pytest.raises(ValueError, match="I1, M1, M2"):
        red.set_verdict(doc, "READY TO MERGE - all good")
    with pytest.raises(ValueError):
        red.set_verdict(doc, "LGTM")
    assert red.set_verdict(doc, "NOT READY TO MERGE - hold")["verdict"] == "NOT READY TO MERGE - hold"
    assert red.recompute_verdict(doc)["verdict"] == "NOT READY TO MERGE - important: I1"


def test_verdict_refuses_ready_over_bubbled_important(doc: Dict[str, object]) -> None:
    out = red.add_bubble(doc, "I1")
    out = red.resolve(out, "M1", "RESOLVED", "typo fixed", "2026-10-02")
    out = red.resolve(out, "M2", "RESOLVED", "import dropped", "2026-10-02")
    with pytest.raises(ValueError, match="computed verdict: NOT READY TO MERGE - important: I1"):
        red.set_verdict(out, "READY TO MERGE - forced")


def test_reviewers(doc: Dict[str, object]) -> None:
    out = red.add_reviewer(red.add_reviewer(doc, "external"), "external")
    assert out["reviewers"] == ["pr-reviewer-core", "external"]
    assert red.remove_reviewer(out, "external")["reviewers"] == ["pr-reviewer-core"]
    with pytest.raises(ValueError):
        red.remove_reviewer(doc, "nobody")


def test_set_scoped_files(doc: Dict[str, object]) -> None:
    out = red.set_scoped_files(doc, ["a\\b.py", "a/b.py", "c.py"])
    assert out["scoped_review_files"] == ["a/b.py", "c.py"]


def test_bubbles(doc: Dict[str, object]) -> None:
    out = red.add_bubble(doc, "M1")
    assert out["bubbles"] == ["M1"]
    assert red.clear_bubble(out, "M1")["bubbles"] == []
    with pytest.raises(ValueError, match="no issue"):
        red.add_bubble(doc, "M9")
    with pytest.raises(ValueError):
        red.clear_bubble(doc, "M1")


def test_issue_editors(doc: Dict[str, object]) -> None:
    new = {"name": "N", "file": "f.py", "summary": "s", "fix": ["f"]}
    added = red.add_issue(doc, "minor", new)
    assert [i["id"] for i in added["issues"]["minor"]] == ["M1", "M2", "M3"]  # type: ignore[index]
    regraded = red.regrade_issue(doc, "M2", "important")
    assert [i["id"] for i in regraded["issues"]["important"]] == ["I1", "I2"]  # type: ignore[index]
    merged = red.merge_issue_ids(doc, "M1", ["M2"])
    assert [i["id"] for i in merged["issues"]["minor"]] == ["M1"]  # type: ignore[index]
    edited = red.set_issue_field(doc, "I1", "lines", "10-14")
    assert edited["issues"]["important"][0]["lines"] == "10-14"  # type: ignore[index]
    with pytest.raises(ValueError):
        red.set_issue_field(doc, "I1", "id", "I7")


def test_regrade_carries_dispositions(doc: Dict[str, object]) -> None:
    out = red.resolve(doc, "M1", "RESOLVED", "first", "2026-10-02")
    out = red.add_bubble(red.add_bubble_up(out, "M2", "out_of_scope", "later"), "M2")
    out = red.resolve(out, "M2", "DOWNGRADED_TO_MINOR", "minor after all", "2026-10-02")
    regraded = red.regrade_issue(out, "M2", "important")
    assert regraded["bubbles"] == ["I2"]
    assert [b["id"] for b in regraded["bubble_up"]] == ["I2"]  # type: ignore[union-attr]
    assert [e["id"] for e in regraded["post_review_resolutions"]] == ["M1", "I2"]  # type: ignore[union-attr]
    red.recompute_verdict(regraded)
    added = red.add_issue(regraded, "minor", {"name": "N", "file": "f.py", "summary": "s", "fix": ["f"]})
    assert [i["id"] for i in added["issues"]["minor"]] == ["M1", "M2"]  # type: ignore[index]


def test_merge_refuses_dispositioned_drop(doc: Dict[str, object]) -> None:
    out = red.resolve(doc, "M2", "RESOLVED", "done", "2026-10-02")
    with pytest.raises(ValueError, match="M2 carries a resolution or bubble"):
        red.merge_issue_ids(out, "M1", ["M2"])
    kept = red.merge_issue_ids(red.resolve(doc, "M1", "RESOLVED", "done", "2026-10-02"), "M1", ["M2"])
    assert [i["id"] for i in kept["issues"]["minor"]] == ["M1"]  # type: ignore[index]


def test_add_issue_skips_ids_named_by_dispositions(doc: Dict[str, object]) -> None:
    stale = red._with(doc, bubbles=["M5"])
    added = red.add_issue(stale, "minor", {"name": "N", "file": "f.py", "summary": "s", "fix": ["f"]})
    assert added["issues"]["minor"][-1]["id"] == "M6"  # type: ignore[index]


def test_strengths(doc: Dict[str, object]) -> None:
    out = red.add_strength(doc, "Good tests")
    assert out["strengths"][-1] == "Good tests"  # type: ignore[index]
    assert red.set_strengths(doc, ["a", "a", " ", "b"])["strengths"] == ["a", "b"]


def test_bubble_up(doc: Dict[str, object]) -> None:
    out = red.add_bubble_up(doc, "I1", "out_of_scope", "tracked   separately")
    entry = {"id": "I1", "classification": "out_of_scope", "reason": "tracked separately"}
    assert out["bubble_up"] == [entry]
    with pytest.raises(ValueError, match="already"):
        red.add_bubble_up(out, "I1", "out_of_scope", "again")
    with pytest.raises(ValueError, match="classification"):
        red.add_bubble_up(doc, "I1", "wontfix", "r")
    assert red.drop_bubble_up(out, "I1")["bubble_up"] == []


def test_resolve_appends_history(doc: Dict[str, object]) -> None:
    out = red.resolve(doc, "M1", "DOWNGRADED_TO_MINOR", "first", "2026-10-02")
    out = red.resolve(out, "M2", "RESOLVED", "other", "2026-10-02")
    out = red.resolve(out, "M1", "CLOSED_NO_ACTION", "not applicable", "2026-10-03")
    assert [(e["id"], e["status"]) for e in out["post_review_resolutions"]] == [  # type: ignore[union-attr]
        ("M1", "DOWNGRADED_TO_MINOR"), ("M2", "RESOLVED"), ("M1", "CLOSED_NO_ACTION")]
    assert red.recompute_verdict(out)["verdict"] == "NOT READY TO MERGE - important: I1"
    with pytest.raises(ValueError, match="rationale"):
        red.resolve(doc, "M1", "CLOSED_NO_ACTION", " ")
    with pytest.raises(ValueError, match="status"):
        red.resolve(doc, "M1", "FIXED", "x")


def test_resolve_all_is_all_or_nothing(doc: Dict[str, object]) -> None:
    entries = [{"id": "I1", "status": "RESOLVED", "evidence": "bound added", "date": "2026-10-02"},
               {"id": "M1", "status": "RESOLVED", "evidence": f"{_SHA} typo fixed", "date": "2026-10-02"},
               {"id": "M2", "status": "CLOSED_NO_ACTION", "evidence": "re-exported", "date": "2026-10-02"}]
    out = red.resolve_all(doc, entries, _SHA)
    evidence = [e["evidence"] for e in out["post_review_resolutions"]]  # type: ignore[union-attr]
    assert evidence[0] == red.snapshot_evidence(_SHA, "bound added")
    assert evidence[1] == f"{_SHA} typo fixed"
    assert out["verdict"] == "READY TO MERGE - 3 of 3 findings resolved, 0 bubbled"
    with pytest.raises(ValueError, match="entry 2 \\(M9\\)"):
        red.resolve_all(doc, [entries[0], {"id": "M9", "status": "RESOLVED", "evidence": "x"}])


def test_snapshot_evidence() -> None:
    assert red.snapshot_evidence(_SHA, "LRU bound added") == (
        f"{_SHA} (working-tree snapshot; developer commits) - LRU bound added")
    with pytest.raises(ValueError, match="blank"):
        red.snapshot_evidence(_SHA, " ")
    with pytest.raises(ValueError, match="7-40"):
        red.snapshot_evidence("a" * 64, "sha-256 ids miss the hook's evidence rule")


def test_set_verification_phase(doc: Dict[str, object]) -> None:
    out = red.set_verification_phase(doc, "dispatch_time", {"a": 1})
    assert out["verification_log"] == {"dispatch_time": {"a": 1}}
    out = red.set_verification_phase(out, "pre_fix_time", "pending - to be populated in Phase 4")
    assert set(out["verification_log"]) == {"dispatch_time", "pre_fix_time"}  # type: ignore[arg-type]
    skipped = red.set_verification_phase(out, "skipped", "catalog")
    assert skipped["verification_log"] == {"skipped": True, "reason": "catalog"}
    with pytest.raises(ValueError):
        red.set_verification_phase(doc, "post_fix_time", {})


def test_hand_closeout_flips_verdict_to_ready(project: Path, tmp_path: Path, doc: Dict[str, object]) -> None:
    out = red.resolve(doc, "I1", "RESOLVED", red.snapshot_evidence(_SHA, "LRU bound added"), "2026-10-02")
    out = red.resolve(out, "M1", "RESOLVED", red.snapshot_evidence(_SHA, "typo fixed"), "2026-10-02")
    out = red.resolve(out, "M2", "CLOSED_NO_ACTION", "import is re-exported", "2026-10-02")
    out = red.recompute_verdict(out)
    assert out["verdict"] == "READY TO MERGE - 3 of 3 findings resolved, 0 bubbled"
    target = tmp_path / "r.json"
    red.save_review(target, out, project)
    assert target.read_bytes() == red.dumps_review(out).encode("utf-8")


def _cli(script: str, target: Path, project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, script, str(target), "--repo", str(project), *args],
                          capture_output=True, text=True, timeout=60)


def _ok(done: subprocess.CompletedProcess) -> None:
    assert done.returncode == 0, done.stderr


def test_cli_resolve_and_check(project: Path, plugin_root: Path) -> None:
    target = project / "review.json"
    shutil.copyfile(_FIXTURES / "open_review_crlf.json", target)
    script = str(plugin_root / "scripts" / "review_edit.py")

    _ok(_cli(script, target, project, "resolve", "I1", "RESOLVED", "bound added", "--sha", _SHA,
             "--date", "2026-10-02"))
    before = target.read_bytes()
    bad = _cli(script, target, project, "verdict", "--text", "READY TO MERGE - nope")
    assert bad.returncode == 1 and "problem: READY verdict refused" in bad.stderr
    assert target.read_bytes() == before
    _ok(_cli(script, target, project, "--recompute", "bubble-up", "M1", "needs_follow_up", "later"))
    assert b"\r\n" in target.read_bytes()
    assert b"\n" not in target.read_bytes().replace(b"\r\n", b"")
    doc = red.load_review(target)
    assert doc["verdict"] == "NOT READY TO MERGE - minor findings pending Phase 5: M2"
    _ok(_cli(script, target, project, "resolve", "M2", "RESOLVED", "x", "--sha", _SHA, "--recompute"))
    assert red.load_review(target)["verdict"] == "READY TO MERGE - 2 of 3 findings resolved, 1 bubbled"
    _ok(_cli(script, target, project, "check"))


def test_cli_check_refuses_invalid_document(project: Path, plugin_root: Path) -> None:
    target = project / "review.json"
    forced = red._with(red.load_review(_FIXTURES / "open_review.json"), verdict="READY TO MERGE - forced")
    target.write_bytes(red.dumps_review(forced).encode("utf-8"))
    before = target.read_bytes()
    bad = _cli(str(plugin_root / "scripts" / "review_edit.py"), target, project, "check")
    assert bad.returncode == 1 and "problem: issue counts" in bad.stderr, bad.stderr
    assert target.read_bytes() == before


def test_cli_resolve_file_writes_once(project: Path, plugin_root: Path) -> None:
    target = project / "review.json"
    shutil.copyfile(_FIXTURES / "open_review.json", target)
    proposed = project / "proposed_resolutions.json"
    script = str(plugin_root / "scripts" / "review_edit.py")
    good = [{"id": "I1", "status": "RESOLVED", "evidence": "bound added", "date": "2026-10-02"},
            {"id": "M1", "status": "RESOLVED", "evidence": "typo fixed", "date": "2026-10-02"}]
    proposed.write_text(json.dumps([*good, {"id": "M9", "status": "RESOLVED", "evidence": "x"}]), "utf-8")
    bad = _cli(script, target, project, "resolve-file", str(proposed), "--sha", _SHA)
    assert bad.returncode == 1 and "problem: entry 3 (M9): no issue M9" in bad.stderr
    assert target.read_bytes() == (_FIXTURES / "open_review.json").read_bytes()
    proposed.write_text(json.dumps({"post_review_resolutions": good}), "utf-8")
    _ok(_cli(script, target, project, "resolve-file", str(proposed), "--sha", _SHA))
    doc = red.load_review(target)
    assert [e["id"] for e in doc["post_review_resolutions"]] == ["I1", "M1"]  # type: ignore[union-attr]
    assert doc["verdict"] == "NOT READY TO MERGE - minor findings pending Phase 5: M2"
