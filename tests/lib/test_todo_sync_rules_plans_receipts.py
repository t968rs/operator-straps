"""Plan rules on a plan frozen with the receipts scheme.

Its JSON statuses stay PENDING for good and its PIP is HTML, so a leftover markdown PIP cannot drift from it:
P1 and P4 skip such a plan, while the same plan frozen as sealed is flagged. P3 pairs ``_PIP.html`` files
as it pairs ``_PIP.md``: a lone HTML PIP is warned.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import PIP, PIP_REL, PLAN_REL, build, rule_findings, todo_files  # noqa: E402

FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64}


def frozen_files(records: str):
    """The in-sync project frozen on ``records``, with PENDING SMP-2's only box checked (a P1 error)."""
    files = todo_files()
    files[PLAN_REL]["frozen"] = dict(FROZEN, records=records)
    files[PIP_REL] = PIP.replace("- [ ] open", "- [X] open")
    return files


@pytest.mark.parametrize("records, flagged", [("receipts", False), ("sealed", True)])
def test_p1_skips_a_receipts_plan(make_project, records: str, flagged: bool) -> None:
    found = rule_findings(build(make_project, frozen_files(records)), "P1")
    assert bool(found) is flagged


@pytest.mark.parametrize("records, flagged", [("receipts", False), ("sealed", True)])
def test_p4_skips_a_receipts_plan(make_project, records: str, flagged: bool) -> None:
    found = rule_findings(build(make_project, frozen_files(records)), "P4")
    assert bool(found) is flagged


def test_p3_warns_a_lone_html_pip(make_project) -> None:
    files = todo_files()
    files["docs/PLANS/0002_Lonely_PIP.html"] = "<!DOCTYPE html>\n"
    found = [(f.severity, f.file) for f in rule_findings(build(make_project, files), "P3")]
    assert found == [("warn", "docs/PLANS/0002_Lonely_PIP.html")]
