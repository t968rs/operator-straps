"""Plan rule P2 reads a sealed COMPLETE record as naming its revision, as it reads a SHA in the evidence."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import PLAN_REL, build, rule_findings, todo_files  # noqa: E402

RECORD = {"outcome": {"kind": "complete", "provenance": {"source": "staged", "tree": "c" * 40}},
          "date": "2026-11-05", "seal": "d" * 64}


def test_p2_accepts_a_complete_record_without_a_sha_in_the_evidence(make_project) -> None:
    files = todo_files()
    item = files[PLAN_REL]["items"][0]
    item["evidence"] = "staged tree 1234567"
    item["record"] = RECORD
    assert rule_findings(build(make_project, files), "P2") == []


def test_p2_still_flags_a_record_that_is_not_complete(make_project) -> None:
    files = todo_files()
    item = files[PLAN_REL]["items"][0]
    item["evidence"] = "Done."
    item["record"] = {**RECORD, "outcome": {"kind": "closed", "rationale": "superseded"}}
    [finding] = rule_findings(build(make_project, files), "P2")
    assert finding.subject == "SMP-1"


def test_p2_flags_a_complete_record_missing_its_seal(make_project) -> None:
    files = todo_files()
    item = files[PLAN_REL]["items"][0]
    item["evidence"] = "Done."
    item["record"] = {"outcome": RECORD["outcome"], "date": "2026-11-05"}
    [finding] = rule_findings(build(make_project, files), "P2")
    assert finding.subject == "SMP-1"
