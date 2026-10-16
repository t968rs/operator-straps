"""Behavioral tests for harness_lib.review_edit: per-field editors and the byte-stable load / save."""
from __future__ import annotations

import copy
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
    bad = red._with(doc, verdict="READY TO MERGE - forced")
    with pytest.raises(ValueError, match="issue counts"):
        red.save_review(target, bad, project)
    assert target.read_bytes() == (_FIXTURES / "open_review.json").read_bytes()


def test_editors_do_not_mutate(doc: Dict[str, object]) -> None:
    before = copy.deepcopy(doc)
    red.add_reviewer(doc, "x")
    red.resolve(doc, "M1", "RESOLVED", "done", "2026-10-02")
    red.set_issue_field(doc, "M1", "lines", "4")
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


def test_verdict_refuses_ready_while_undispositioned(doc: Dict[str, object]) -> None:
    with pytest.raises(ValueError, match="I1, M1, M2"):
        red.set_verdict(doc, "READY TO MERGE - all good")
    with pytest.raises(ValueError):
        red.set_verdict(doc, "LGTM")
    assert red.set_verdict(doc, "NOT READY TO MERGE - hold")["verdict"] == "NOT READY TO MERGE - hold"
    assert red.recompute_verdict(doc)["verdict"] == "NOT READY TO MERGE - important: I1"


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


def test_resolve_replaces_same_id_only(doc: Dict[str, object]) -> None:
    out = red.resolve(doc, "M1", "RESOLVED", "first", "2026-10-02")
    out = red.resolve(out, "M2", "RESOLVED", "other", "2026-10-02")
    out = red.resolve(out, "M1", "CLOSED_NO_ACTION", "not applicable", "2026-10-03")
    assert [(e["id"], e["status"]) for e in out["post_review_resolutions"]] == [  # type: ignore[union-attr]
        ("M1", "CLOSED_NO_ACTION"), ("M2", "RESOLVED")]
    with pytest.raises(ValueError, match="rationale"):
        red.resolve(doc, "M1", "CLOSED_NO_ACTION", " ")
    with pytest.raises(ValueError, match="status"):
        red.resolve(doc, "M1", "FIXED", "x")


def test_snapshot_evidence() -> None:
    assert red.snapshot_evidence(_SHA, "LRU bound added") == (
        f"{_SHA} (working-tree snapshot; developer commits) - LRU bound added")


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
    assert red.load_review(target) == out


def test_cli_resolve_and_check(project: Path, plugin_root: Path) -> None:
    target = project / "review.json"
    shutil.copyfile(_FIXTURES / "open_review_crlf.json", target)
    script = str(plugin_root / "scripts" / "review_edit.py")

    def cli(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, script, str(target), "--repo", str(project), *args],
                              capture_output=True, text=True)

    done = cli("resolve", "I1", "RESOLVED", "bound added", "--sha", _SHA, "--date", "2026-10-02")
    assert done.returncode == 0, done.stderr
    bad = cli("verdict", "--text", "READY TO MERGE - nope")
    assert bad.returncode == 1 and "problem: READY verdict refused" in bad.stderr
    assert cli("--recompute", "bubble-up", "M1", "needs_follow_up", "later").returncode == 0
    assert b"\r\n" in target.read_bytes()
    doc = red.load_review(target)
    assert doc["verdict"] == "NOT READY TO MERGE - minor findings pending Phase 5: M2"
    assert cli("check").returncode == 0
