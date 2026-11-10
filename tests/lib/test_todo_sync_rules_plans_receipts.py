"""Plan rules on a plan frozen with the receipts scheme.

Its JSON statuses stay PENDING for good and its PIP is HTML, so a leftover markdown PIP cannot drift from it:
P1 and P4 skip such a plan. P3 pairs ``_PIP.html`` files as it pairs ``_PIP.md``: a lone HTML PIP is warned.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import PIP, PIP_REL, PLAN_REL, build, rule_findings, todo_files  # noqa: E402

FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64}


def receipts_files(records: str = "receipts"):
    files = todo_files()
    files[PLAN_REL]["frozen"] = dict(FROZEN, records=records)
    files[PLAN_REL]["items"][1]["status"] = "PENDING"
    files[PIP_REL] = PIP.replace("- [ ] open", "- [X] open")
    return files


def test_p1_skips_a_receipts_plan(make_project) -> None:
    assert rule_findings(build(make_project, receipts_files()), "P1") == []


def test_p4_skips_a_receipts_plan(make_project) -> None:
    files = receipts_files()
    files[PLAN_REL]["markdown_sync_status"] = "in_sync"
    assert rule_findings(build(make_project, files), "P4") == []


def test_p3_warns_a_lone_html_pip(make_project) -> None:
    files = todo_files()
    files["docs/PLANS/0002_Lonely_PIP.html"] = "<!DOCTYPE html>\n"
    found = [(f.severity, f.file) for f in rule_findings(build(make_project, files), "P3")]
    assert found == [("warn", "docs/PLANS/0002_Lonely_PIP.html")]
