"""qa_review_json.py D follows ``review_merge.compute_verdict``; C2a sees past the snapshot evidence lead."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List

import pytest

_SHA = "3333333ccccccc"
_LEAD = f"{_SHA} (working-tree snapshot; developer commits) - "


@pytest.fixture(scope="module")
def qa(plugin_root: Path) -> ModuleType:
    target = plugin_root / "skills" / "pr-team" / "commands" / "qa_review_json.py"
    spec = importlib.util.spec_from_file_location("qa_review_json_d_c2a", target)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issue(issue_id: str) -> Dict[str, Any]:
    return {"id": issue_id, "name": "n", "file": "f.py", "summary": "s", "fix": ["f"]}


def _doc(verdict: str, resolutions: List[Dict[str, Any]], bubble_up: List[Dict[str, Any]]) -> Dict[str, Any]:
    issues = {"critical": [], "important": [_issue("I1")], "minor": [_issue("M1"), _issue("M2")]}
    return {"issues": issues, "post_review_resolutions": resolutions, "bubble_up": bubble_up,
            "verdict": verdict}


def _res(issue_id: str, status: str = "RESOLVED") -> Dict[str, Any]:
    return {"id": issue_id, "status": status, "date": "2026-10-02", "evidence": f"{_LEAD}done"}


def test_d_partial_closeout_with_bubbled_minor_is_ready(qa: ModuleType) -> None:
    bubbled = [{"id": "M2", "classification": "fixer_failed", "reason": "fixer FAIL: red"}]
    ok, msg = qa.check_d_verdict(_doc("READY TO MERGE - 2 of 3 findings resolved, 1 bubbled",
                                      [_res("I1"), _res("M1")], bubbled))
    assert ok, msg


def test_d_pending_minor_expects_not_ready(qa: ModuleType) -> None:
    resolutions = [_res("I1"), _res("M1")]
    pending = "NOT READY TO MERGE - minor findings pending Phase 5: M2"
    ok, msg = qa.check_d_verdict(_doc(pending, resolutions, []))
    assert ok, msg
    ok, msg = qa.check_d_verdict(_doc("READY TO MERGE - forced", resolutions, []))
    assert not ok and "NOT READY TO MERGE" in msg


def test_d_reads_latest_resolution(qa: ModuleType) -> None:
    resolutions = [_res("I1"), _res("M1"), _res("M2"), _res("I1", "DOWNGRADED_TO_MINOR")]
    ok, msg = qa.check_d_verdict(_doc("READY TO MERGE - stale", resolutions, []))
    assert not ok and "important: I1" in msg


@pytest.mark.parametrize("rationale", ["bubbled - out_of_scope", "classification: out_of_scope"])
def test_c2a_strips_snapshot_lead(qa: ModuleType, rationale: str) -> None:
    entry = {"id": "M2", "status": "CLOSED_NO_ACTION", "date": "2026-10-02",
             "evidence": f"{_LEAD}{rationale}"}
    ok, msg = qa.check_c2a_no_auto_closed_no_action({"post_review_resolutions": [entry]})
    assert not ok, msg
    entry["evidence"] = f"{_LEAD}developer closed: tracked in a follow-up PR"
    assert qa.check_c2a_no_auto_closed_no_action({"post_review_resolutions": [entry]})[0]
