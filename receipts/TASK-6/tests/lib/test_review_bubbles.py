"""``harness_lib.review_bubbles``: the pending-fixer-bubble helpers shared by ``pr_review.py`` and ``bubble_memo.py``."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from harness_lib.review_bubbles import closed_ids, fixer_bubbles, pending_bubbles


def _write_report(run: Path, fixer: str, bubbles: List[Dict[str, str]]) -> None:
    (run / "fixes").mkdir(parents=True, exist_ok=True)
    body = {"fixer": fixer, "fixed": [], "bubbled": bubbles}
    (run / "fixes" / f"{fixer}.json").write_text(json.dumps(body), encoding="utf-8")


def _bubble(issue_id: str, classification: str = "architectural_ambiguity") -> Dict[str, str]:
    return {"id": issue_id, "classification": classification, "reason": f"{issue_id} needs a decision"}


def _doc(**fields: Any) -> Dict[str, Any]:
    return {"bubbles": [], "bubble_up": [], "post_review_resolutions": [], **fields}


def test_closed_ids_follow_the_latest_resolution() -> None:
    doc = _doc(post_review_resolutions=[
        {"id": "I1", "status": "RESOLVED"},
        {"id": "I2", "status": "CLOSED_NO_ACTION"},
        {"id": "I3", "status": "DOWNGRADED_TO_MINOR"},
        {"id": "I4", "status": "RESOLVED"},
        {"id": "I4", "status": "DOWNGRADED_TO_MINOR"},
    ])
    assert closed_ids(doc) == {"I1", "I2"}


def test_fixer_bubbles_pair_each_bubble_with_its_fixer(tmp_path: Path) -> None:
    _write_report(tmp_path, "fixer_a", [_bubble("I2")])
    _write_report(tmp_path, "fixer_b", [_bubble("C1", "needs_follow_up")])
    found = [(fixer, b.id, b.classification.value) for fixer, b in fixer_bubbles(tmp_path)]
    assert found == [("fixer_a", "I2", "architectural_ambiguity"), ("fixer_b", "C1", "needs_follow_up")]


def test_fixer_bubbles_of_a_run_without_reports_are_empty(tmp_path: Path) -> None:
    assert fixer_bubbles(tmp_path) == []


def test_pending_bubbles_skip_ids_the_review_already_holds(tmp_path: Path) -> None:
    _write_report(tmp_path, "fixer_a", [_bubble("I2"), _bubble("I3"), _bubble("I4"), _bubble("I5")])
    doc = _doc(
        bubbles=["I2"],
        bubble_up=[{"id": "I3", "classification": "out_of_scope", "reason": "later"}],
        post_review_resolutions=[{"id": "I4", "status": "CLOSED_NO_ACTION"}],
    )
    assert [b.id for _, b in pending_bubbles(doc, tmp_path)] == ["I5"]
