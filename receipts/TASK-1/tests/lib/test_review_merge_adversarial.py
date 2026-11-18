"""``review_merge`` and ``review_edit`` under ``--adversarial``: the REFUTED (closing), BUBBLED and
NOT_RESOLVED (non-closing) statuses, the Layer 2 exemption, ``merge_findings_traced``, ``merge_adversarial``,
the ``refuted`` key on a draft issue (``refuted_resolutions``, ``strip_refuted``, ``merge_ids``,
``review_document``) and the developer overrule (``issue_info``, ``apply_refute``, ``apply_unrefute``)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

import pytest

from harness_lib import review_edit as red
from harness_lib import review_merge as rmg
from harness_lib import review_models as rm
from harness_lib.config import activate, load_config

_CTX = {"root": "/repo"}
_TODAY = "2026-11-12"
_EVIDENCE = "src/a.py:3 is guarded by the length check at :2"


@pytest.fixture
def project(make_project) -> Path:
    """An activated throwaway project without a pinned schema copy (the plugin's schema governs)."""
    root = make_project(config={})
    activate(load_config(root))
    return root


def _finding(name: str, lines: str, **extra: object) -> Dict[str, object]:
    """A finding mapping on ``src/a.py``; ``extra`` replaces or adds keys."""
    base: Dict[str, object] = {"severity": "minor", "name": name, "summary": f"{name} summary", "fix": ["f"],
                               "file": "src/a.py", "lines": lines, "fix_kind": "mechanical"}
    base.update(extra)
    return base


def _report(slot: str, *findings: Mapping[str, object]) -> rm.ReviewerReport:
    return rm.ReviewerReport.model_validate({"reviewer": slot, "findings": list(findings)}, context=_CTX)


def _attack_report(slot: str, *findings: Mapping[str, object]) -> rm.ReviewerReport:
    data = {"reviewer": slot, "findings": list(findings)}
    return rm.CodeRefuterReport.model_validate(data, context=_CTX)


def _evidence(finding: rm.Finding) -> str:
    return f"{finding.file}:{finding.lines} disproves {finding.name}"


def _refute(report: rm.ReviewerReport, *verdicts: str) -> rm.RefutationReport:
    """The findings refuter's report over ``report``: one verdict per finding, in order."""
    entries = tuple(rm.Refutation(key=rm.finding_key(f), verdict=v, evidence=_evidence(f))
                    for f, v in zip(report.findings, verdicts))
    return rm.RefutationReport(refuter=f"adv_refute_{report.reviewer}", target=report.reviewer,
                               report_digest=rm.report_digest(report), refutations=entries)


def _by_name(issues: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    return {str(i["name"]): i for i in issues}


def _issue(issue_id: str, refuted: Optional[str] = None, **extra: object) -> Dict[str, object]:
    """A schema issue dict, carrying ``refuted`` evidence when given."""
    out: Dict[str, object] = {"id": issue_id, "name": f"n {issue_id}", "file": "src/a.py",
                              "reviewer": "runtime", "fix_kind": "mechanical", "summary": f"s {issue_id}",
                              "fix": ["f"], **extra}
    if refuted is not None:
        out["refuted"] = refuted
    return out


def _refusal(call: Callable[[], object]) -> str:
    """Message of the ValueError ``call`` raises; AssertionError when ``call`` accepts its input."""
    try:
        call()
    except ValueError as exc:
        return str(exc)
    raise AssertionError("call accepted input it must refuse")


# --- TASK-1: statuses, version, pending rule -----------------------------------------------------------


_OVERRULE_STATUSES = {"REFUTED", "BUBBLED", "NOT_RESOLVED"}


def test_refuted_is_the_only_new_closed_status() -> None:
    assert set(rmg.CLOSED_STATUSES) == {"RESOLVED", "CLOSED_NO_ACTION", "REFUTED"}
    assert not _OVERRULE_STATUSES & set(red.RESOLUTION_STATUSES)
    assert "status must be one of" in _refusal(lambda: red.resolve(_review(), "I1", "REFUTED", _EVIDENCE,
                                                                    _TODAY))


def _version(text: str) -> tuple:
    return tuple(int(part) for part in text.split("."))


def test_schema_version_is_at_least_2_3_0() -> None:
    assert _version(rmg.SCHEMA_VERSION) >= (2, 3, 0)


def test_compute_verdict_settles_a_refuted_id() -> None:
    issues = {"critical": [], "important": [{"id": "I1"}], "minor": []}
    verdict = rmg.compute_verdict(issues, [{"id": "I1", "status": "REFUTED"}], [], [])
    assert verdict.startswith("READY TO MERGE")


def test_not_resolved_latest_status_is_no_disposition() -> None:
    history = [{"id": "I1", "status": "REFUTED"}, {"id": "I1", "status": "NOT_RESOLVED"}]
    doc = {"issues": {"critical": [], "important": [{"id": "I1"}], "minor": []},
           "post_review_resolutions": history}
    assert rmg.undispositioned_ids(doc) == ["I1"]
    assert rmg.compute_verdict(doc["issues"], history, [], []) == "NOT READY TO MERGE - important: I1"


def test_not_resolved_latest_status_is_open_despite_a_bubble_entry() -> None:
    history = [{"id": "M1", "status": "REFUTED"}, {"id": "M1", "status": "NOT_RESOLVED"}]
    ledger = [{"id": "M1", "classification": "needs_follow_up", "reason": "follow-up"}]
    assert "M1" not in rmg._settled_ids(history, ["M1"], ledger)
    issues = {"critical": [], "important": [], "minor": [{"id": "M1"}]}
    verdict = rmg.compute_verdict(issues, history, [], ledger)
    assert verdict == "NOT READY TO MERGE - minor findings pending Phase 5: M1"


def test_entry_ids_keep_the_orphan_guard_and_the_merge_refusal() -> None:
    history = [{"id": "M2", "status": "REFUTED"}, {"id": "M2", "status": "NOT_RESOLVED"}]
    assert rmg._entry_ids(history) == {"M2"}
    issues = {"critical": [], "important": [], "minor": [{"id": "M1"}]}
    assert "orphan" in _refusal(lambda: rmg.compute_verdict(issues, history, [], []))
    doc = {"verdict": "v", "bubbles": [], "bubble_up": [], "post_review_resolutions": history,
           "issues": {"critical": [], "important": [], "minor": [_issue("M1"), _issue("M2")]}}
    assert "M2" in _refusal(lambda: red.merge_issue_ids(doc, "M1", ["M2"]))


def _pending_doc(verdict: str, *resolutions: Dict[str, str]) -> Dict[str, object]:
    return {"verdict": verdict, "verification_log": {"pre_fix_time": rmg.PENDING},
            "post_review_resolutions": list(resolutions)}


_NOT_READY = "NOT READY TO MERGE - minor findings pending Phase 5: M2"
_REFUTED_M1 = {"id": "M1", "status": "REFUTED"}


@pytest.mark.parametrize("status", ["REFUTED", "BUBBLED", "NOT_RESOLVED"])
def test_pending_rule_exempts_overrule_statuses(status: str) -> None:
    entries = (_REFUTED_M1, {"id": "M1", "status": status})
    assert rmg._pending_problems(_pending_doc(_NOT_READY, *entries)) == []


def test_pending_rule_still_refuses_other_resolutions() -> None:
    assert rmg._pending_problems(_pending_doc(_NOT_READY, _REFUTED_M1)) == []
    resolved = {"id": "M2", "status": "RESOLVED"}
    assert rmg._pending_problems(_pending_doc(_NOT_READY, _REFUTED_M1, resolved))


def test_pending_rule_still_refuses_a_ready_verdict() -> None:
    assert rmg._pending_problems(_pending_doc(_NOT_READY, _REFUTED_M1)) == []
    assert rmg._pending_problems(_pending_doc("READY TO MERGE - 1 of 1 findings resolved", _REFUTED_M1))


# --- TASK-4: verdict text, provenance and merge_adversarial --------------------------------------------


def test_ready_verdict_counts_refuted_ids_apart() -> None:
    issues = {"critical": [], "important": [{"id": "I1"}], "minor": []}
    verdict = rmg.compute_verdict(issues, [{"id": "I1", "status": "REFUTED"}], [], [])
    assert verdict.endswith(", 1 refuted") and "0 of 1 findings resolved" in verdict, verdict
    resolved = rmg.compute_verdict(issues, [{"id": "I1", "status": "RESOLVED"}], [], [])
    assert resolved == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"


def test_merge_findings_traced_maps_each_issue_to_its_findings() -> None:
    runtime = _report("runtime", _finding("a", "3"), _finding("b", "40"))
    overall = _report("overall", _finding("a", "3"))
    issues, trace = rmg.merge_findings_traced([runtime, overall])
    assert issues == rmg.merge_findings([runtime, overall])
    ids = {str(i["name"]): str(i["id"]) for i in issues}
    key_a, key_b = (rm.finding_key(f) for f in runtime.findings)
    assert {tuple(t) for t in trace[ids["a"]]} == {("runtime", key_a), ("overall", key_a)}
    assert {tuple(t) for t in trace[ids["b"]]} == {("runtime", key_b)}


def test_merge_adversarial_marks_a_fully_refuted_issue() -> None:
    runtime = _report("runtime", _finding("a", "3"), _finding("b", "40"))
    issues, _ = rmg.merge_adversarial([runtime], {"runtime": _refute(runtime, "refuted", "upheld")})
    named = _by_name(issues)
    assert _evidence(runtime.findings[0]) in str(named["a"]["refuted"])
    assert "refuted" not in named["b"]


def test_merge_adversarial_keeps_an_issue_with_one_upheld_finding() -> None:
    runtime, overall = _report("runtime", _finding("a", "3")), _report("overall", _finding("a", "3"))
    refutations = {"runtime": _refute(runtime, "refuted"), "overall": _refute(overall, "upheld")}
    issues, _ = rmg.merge_adversarial([runtime, overall], refutations)
    assert len(issues) == 1 and "refuted" not in issues[0]


def test_merge_adversarial_mixed_group_takes_its_shape_from_upheld_findings() -> None:
    crash = _finding("Crash on empty input", "3", severity="critical", fix_kind="judgment",
                     summary="Crashes when the list is empty.", also=["docs/x.md"])
    typo = _finding("Typo in error message", "4", summary="The message misspells received.")
    runtime, overall = _report("runtime", crash), _report("overall", typo)
    refutations = {"runtime": _refute(runtime, "refuted"), "overall": _refute(overall, "upheld")}
    issues, notes = rmg.merge_adversarial([runtime, overall], refutations)
    assert len(issues) == 1
    issue = issues[0]
    assert (issue["id"], issue["name"], issue["fix_kind"]) == ("M1", "Typo in error message", "mechanical")
    assert str(issue["summary"]).startswith("The message misspells") and "Crashes" not in issue["summary"]
    assert "refuted" not in issue
    assert issue == {"id": "M1", "name": "Typo in error message", "file": "src/a.py", "lines": "4",
                     "reviewer": "overall", "fix_kind": "mechanical",
                     "summary": "The message misspells received.", "fix": ["f"]}
    assert _evidence(runtime.findings[0]) in repr(notes)


def test_merge_adversarial_folds_the_attack_into_the_summary() -> None:
    code = _attack_report("adv_code", _finding("a", "3", attack="f(-1) returns 0"))
    issues, _ = rmg.merge_adversarial([code], {"adv_code": _refute(code, "upheld")})
    assert "Attack: f(-1) returns 0" in str(issues[0]["summary"])


def test_merge_adversarial_counts_a_source_without_refutations_as_upheld() -> None:
    runtime, folded = _report("runtime", _finding("a", "3")), _report("fold_notes", _finding("a", "3"))
    issues, _ = rmg.merge_adversarial([runtime, folded], {"runtime": _refute(runtime, "refuted")})
    assert len(issues) == 1 and "refuted" not in issues[0]


def test_merge_adversarial_without_refutations_equals_merge_findings() -> None:
    runtime = _report("runtime", _finding("a", "3"), _finding("b", "40"))
    overall = _report("overall", _finding("a", "4"))
    expected = rmg.merge_findings([runtime, overall])
    assert rmg.merge_adversarial([runtime, overall], {})[0] == expected
    upheld = {"runtime": _refute(runtime, "upheld", "upheld"), "overall": _refute(overall, "upheld")}
    assert rmg.merge_adversarial([runtime, overall], upheld)[0] == expected


# --- TASK-4: the refuted key on draft issues -----------------------------------------------------------


def test_refuted_resolutions_build_one_entry_per_refuted_issue() -> None:
    issues = [_issue("I1", refuted="e1"), _issue("M1"), _issue("M2", refuted="e2")]
    assert rmg.refuted_resolutions(issues, _TODAY) == [
        {"id": "I1", "status": "REFUTED", "date": _TODAY, "evidence": "e1"},
        {"id": "M2", "status": "REFUTED", "date": _TODAY, "evidence": "e2"},
    ]


def test_strip_refuted_drops_only_the_key_and_copies() -> None:
    issues = [_issue("I1", refuted="e1"), _issue("M1")]
    before = copy.deepcopy(issues)
    assert rmg.strip_refuted(issues) == [_issue("I1"), _issue("M1")]
    assert issues == before


def test_merge_ids_keeps_refuted_only_when_every_issue_is() -> None:
    both = rmg.merge_ids([_issue("M1", refuted="a"), _issue("M2", refuted="b")], "M1", ["M2"])
    assert both[0].get("refuted") == "a\n\nb"
    mixed = rmg.merge_ids([_issue("M1", refuted="a"), _issue("M2")], "M1", ["M2"])
    assert "refuted" not in mixed[0]


def test_merge_ids_mixed_group_takes_its_shape_from_upheld_issues() -> None:
    refuted = _issue("M1", refuted="src/a.py:3 is guarded", name="Wrong guard", summary="The guard is wrong.")
    upheld = _issue("M2", name="Typo in message", summary="The message misspells received.")
    merged = rmg.merge_ids([refuted, upheld], "M1", ["M2"])
    assert len(merged) == 1
    issue = merged[0]
    assert issue["id"] == "M1" and issue["name"] == "Typo in message", issue
    assert str(issue["summary"]).startswith("The message misspells"), issue["summary"]
    assert "refuted" not in issue


def _meta() -> Dict[str, object]:
    return {"pr": 1558, "pr_title": "t", "branch": "b", "base_branch": "main", "base_sha": "765e698eb",
            "head_sha": "a9630b78d", "review_date": _TODAY,
            "stats": {"additions": 1, "deletions": 0, "files_changed": 1}}


def _dispatch_time() -> Dict[str, object]:
    return {"pr_metadata_check": {"command": "gh pr view 1558", "stdout": "{\"state\":\"OPEN\"}",
                                  "result": "OK (state=OPEN)"},
            "structural_guards_check": {"applies": False, "command": "", "stdout_tail": "",
                                        "result": "SKIPPED (no CICD/test-infra paths in PR)"}}


def _draft(*issues: Dict[str, object]) -> Dict[str, object]:
    return {"issues": list(issues), "strengths": ["clean seams"], "reviewers": ["runtime (opus)"]}


def _all_issues(doc: Mapping[str, object]) -> List[Dict[str, object]]:
    return [i for tier in doc["issues"].values() for i in tier]  # type: ignore[attr-defined]


def test_review_document_writes_refuted_resolutions_and_strips_the_key() -> None:
    draft = _draft(_issue("I1", refuted=_EVIDENCE), _issue("M1"))
    doc = rmg.review_document(_meta(), draft, _dispatch_time())
    entries = doc.get("post_review_resolutions") or []
    assert [(e["id"], e["status"], e["evidence"]) for e in entries] == [("I1", "REFUTED", _EVIDENCE)]
    assert all("refuted" not in i for i in _all_issues(doc))
    assert doc["verdict"] == "NOT READY TO MERGE - minor findings pending Phase 5: M1"


def test_review_document_all_refuted_is_held_and_validates(project: Path) -> None:
    draft = _draft(_issue("I1", refuted=_EVIDENCE), _issue("M1", refuted=_EVIDENCE))
    held = red.recompute_verdict(rmg.review_document(_meta(), draft, _dispatch_time()))
    assert held["verdict"] == red.PHASE4_HOLD.format(reason="pre_fix_time pending")
    assert rmg.validate_review(held, project) == []


# --- TASK-4: the developer overrule (issue_info, apply_refute, apply_unrefute) -----------------------------


def _review(*resolutions: Dict[str, str]) -> Dict[str, object]:
    return {"verdict": "NOT READY TO MERGE - important: I1",
            "issues": {"critical": [], "important": [_issue("I1")], "minor": []},
            "bubbles": [], "bubble_up": [], "post_review_resolutions": list(resolutions)}


def _entry(status: str, evidence: str = _EVIDENCE) -> Dict[str, str]:
    return {"id": "I1", "status": status, "date": _TODAY, "evidence": evidence}


def test_issue_info_returns_the_issue_and_refuses_an_unknown_id() -> None:
    info = red.issue_info(_review(), "I1")
    assert (info["id"], info["name"], info["file"]) == ("I1", "n I1", "src/a.py")
    _refusal(lambda: red.issue_info(_review(), "M9"))


@pytest.mark.parametrize("history", [
    pytest.param((), id="open"),
    pytest.param((_entry("REFUTED"), _entry("NOT_RESOLVED", "overruled")), id="after-fix-overrule"),
    pytest.param((_entry("REFUTED"), _entry("BUBBLED", "overruled")), id="after-bubble-overrule"),
])
def test_apply_refute_appends_a_refuted_entry(history: tuple) -> None:
    doc = _review(*history)
    out = red.apply_refute(doc, "I1", "src/a.py:3 is guarded", _TODAY)
    assert out["post_review_resolutions"] == [*history, _entry("REFUTED", "src/a.py:3 is guarded")]
    assert doc == _review(*history)


@pytest.mark.parametrize("issue_id, history", [
    pytest.param("I1", (_entry("RESOLVED", "a9630b7 fixed"),), id="resolved"),
    pytest.param("I1", (_entry("CLOSED_NO_ACTION", "a9630b7 n/a"),), id="closed-no-action"),
    pytest.param("I1", (_entry("REFUTED"),), id="already-refuted"),
    pytest.param("M9", (), id="unknown-id"),
])
def test_apply_refute_refuses_a_closed_or_unknown_id(issue_id: str, history: tuple) -> None:
    _refusal(lambda: red.apply_refute(_review(*history), issue_id, "e", _TODAY))


def test_apply_unrefute_bubble_appends_bubbled_and_bubbles_the_id() -> None:
    doc = _review(_entry("REFUTED"))
    out = red.apply_unrefute(doc, "I1", "bubble", "the guard at :2 is dead code", _TODAY)
    assert out["post_review_resolutions"] == [
        _entry("REFUTED"), _entry("BUBBLED", "the guard at :2 is dead code")]
    assert "I1" in out["bubbles"]
    assert doc == _review(_entry("REFUTED"))


def test_apply_unrefute_fix_appends_not_resolved_and_reopens_the_id() -> None:
    out = red.apply_unrefute(_review(_entry("REFUTED")), "I1", "fix", "refutation overruled", _TODAY)
    resolutions = out["post_review_resolutions"]
    assert resolutions == [_entry("REFUTED"), _entry("NOT_RESOLVED", "refutation overruled")]
    assert "I1" not in rmg._closed_ids(resolutions)
    assert rmg.undispositioned_ids(out) == ["I1"]


def _bubbled_review(*resolutions: Dict[str, str]) -> Dict[str, object]:
    """``_review`` with I1 in the transient ``bubbles`` list and the ``bubble_up`` ledger."""
    doc = _review(*resolutions)
    doc["bubbles"] = ["I1"]
    doc["bubble_up"] = [{"id": "I1", "classification": "needs_follow_up", "reason": "follow-up"}]
    return doc


def test_bubble_refute_then_unrefute_fix_leaves_the_id_undispositioned() -> None:
    refuted = red.apply_refute(_bubbled_review(), "I1", "src/a.py:3 is guarded", _TODAY)
    assert refuted["bubbles"] == []
    out = red.apply_unrefute(refuted, "I1", "fix", "refutation overruled", _TODAY)
    assert out["bubbles"] == [] and out["bubble_up"] == _bubbled_review()["bubble_up"]
    assert rmg.undispositioned_ids(out) == ["I1"]


def test_apply_unrefute_fix_drops_the_id_from_bubbles_and_keeps_bubble_up() -> None:
    doc = _bubbled_review(_entry("REFUTED"))
    out = red.apply_unrefute(doc, "I1", "fix", "refutation overruled", _TODAY)
    assert out["bubbles"] == [] and out["bubble_up"] == doc["bubble_up"]
    assert rmg.undispositioned_ids(out) == ["I1"]


@pytest.mark.parametrize("issue_id, mode, history", [
    pytest.param("I1", "fix", (), id="never-refuted"),
    pytest.param("I1", "fix", (_entry("REFUTED"), _entry("NOT_RESOLVED", "r")), id="already-fix"),
    pytest.param("I1", "bubble", (_entry("REFUTED"), _entry("BUBBLED", "r")), id="already-bubbled"),
    pytest.param("I1", "fix", (_entry("RESOLVED", "a9630b7 fixed"),), id="resolved"),
    pytest.param("I1", "drop", (_entry("REFUTED"),), id="unknown-mode"),
    pytest.param("M9", "fix", (_entry("REFUTED"),), id="unknown-id"),
])
def test_apply_unrefute_refuses(issue_id: str, mode: str, history: tuple) -> None:
    _refusal(lambda: red.apply_unrefute(_review(*history), issue_id, mode, "reason", _TODAY))
