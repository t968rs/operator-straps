"""Plan rules P1-P4: ActionPlan items against their PIP sections, red and green per rule."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import PIP, PIP_REL, PLAN_REL, build, config, rule_findings, todo_files  # noqa: E402

RULES = ["P1", "P2", "P3", "P4"]


@pytest.mark.parametrize("rule", RULES)
def test_in_sync_project_is_clean(make_project, rule: str) -> None:
    assert rule_findings(build(make_project), rule) == []


def _item(files, n: int):
    return files[PLAN_REL]["items"][n]


def test_p1_complete_item_with_open_box(make_project) -> None:
    files = todo_files()
    files[PIP_REL] = PIP.replace("- [x] verified", "- [ ] verified")
    [f] = rule_findings(build(make_project, files), "P1")
    assert (f.severity, f.file, f.subject, f.line) == ("error", PIP_REL, "SMP-1", 6)
    assert "1 unchecked" in f.message


def test_p1_closed_no_action_counts_as_done(make_project) -> None:
    files = todo_files()
    _item(files, 0)["status"] = "CLOSED_NO_ACTION"
    files[PIP_REL] = PIP.replace("- [x] done", "- [ ] done")
    [f] = rule_findings(build(make_project, files), "P1")
    assert f.subject == "SMP-1"


@pytest.mark.parametrize("status", ["PENDING", "IN_PROGRESS"])
def test_p1_open_item_with_every_box_checked(make_project, status: str) -> None:
    files = todo_files()
    _item(files, 1)["status"] = status
    files[PIP_REL] = PIP.replace("- [ ] open", "- [X] open")
    [f] = rule_findings(build(make_project, files), "P1")
    assert (f.subject, f.line) == ("SMP-2", 8)


def test_p1_blocked_and_boxless_sections_are_out_of_scope(make_project) -> None:
    files = todo_files()
    _item(files, 2)["markdown_section"] = "SMP-2"
    files[PIP_REL] = PIP + "\n## SMP-4: prose only\n\nNothing to tick.\n"
    files[PLAN_REL]["items"].append({"id": "SMP-4", "status": "COMPLETE", "evidence": "abc1234",
                                     "markdown_section": "SMP-4"})
    assert rule_findings(build(make_project, files), "P1") == []


def test_p1_unknown_section_warns(make_project) -> None:
    files = todo_files()
    _item(files, 1)["markdown_section"] = "docs/PLANS/0001_Sample_PIP.md#smp-9"
    [f] = rule_findings(build(make_project, files), "P1")
    assert (f.severity, f.subject) == ("warn", "SMP-2")
    assert "section not found" in f.message


def test_unparseable_plan_is_one_p_error(make_project) -> None:
    from harness_lib.todo_sync import check
    files = todo_files()
    files[PLAN_REL] = "{broken"
    report = check(build(make_project, files), rules=RULES)
    assert [(f.rule, f.file, f.severity) for f in report.findings] == [("P1", PLAN_REL, "error")]


@pytest.mark.parametrize("evidence", [None, "Done in PR #12.", "see ab12"])
def test_p2_complete_without_sha(make_project, evidence) -> None:
    files = todo_files()
    _item(files, 0)["evidence"] = evidence
    [f] = rule_findings(build(make_project, files), "P2")
    assert (f.severity, f.file, f.subject) == ("error", PLAN_REL, "SMP-1")


def test_p2_accepts_a_sha_in_verification_references(make_project) -> None:
    files = todo_files()
    _item(files, 0)["evidence"] = "Done in PR #12."
    _item(files, 0)["verification_references"] = ["CI run 42", "commit 0a1b2c3d"]
    assert rule_findings(build(make_project, files), "P2") == []


def test_p2_ignores_non_string_references(make_project) -> None:
    files = todo_files()
    _item(files, 0)["evidence"] = "Done."
    _item(files, 0)["verification_references"] = [None, 7]
    [f] = rule_findings(build(make_project, files), "P2")
    assert f.subject == "SMP-1"


def test_p3_missing_documentation(make_project) -> None:
    files = todo_files()
    files[PLAN_REL]["documentation"] = "docs/PLANS/missing_PIP.md"
    [f] = rule_findings(build(make_project, files), "P3")
    assert (f.severity, f.file) == ("warn", PLAN_REL)


def test_p3_pip_without_plan(make_project) -> None:
    files = todo_files()
    files["docs/PLANS/0002_Lonely_PIP.md"] = "# lonely\n"
    [f] = rule_findings(build(make_project, files), "P3")
    assert (f.severity, f.file) == ("warn", "docs/PLANS/0002_Lonely_PIP.md")


def test_p3_ignores_nested_folders(make_project) -> None:
    files = todo_files()
    files["docs/PLANS/Sub/0003_Deep_PIP.md"] = "# deep\n"
    assert rule_findings(build(make_project, files), "P3") == []


def test_p4_in_sync_claim_with_p1_error(make_project) -> None:
    files = todo_files()
    files[PIP_REL] = PIP.replace("- [x] verified", "- [ ] verified")
    cfg = build(make_project, files)
    [f] = rule_findings(cfg, "P4")
    assert (f.severity, f.file) == ("error", PLAN_REL)


def test_p4_pending_sync_status_is_honest(make_project) -> None:
    files = todo_files()
    files[PIP_REL] = PIP.replace("- [x] verified", "- [ ] verified")
    files[PLAN_REL]["markdown_sync_status"] = "pending_markdown_sync"
    assert rule_findings(build(make_project, files), "P4") == []


def test_pairs_false_gates_the_group(make_project) -> None:
    from harness_lib.todo_sync import check
    cfg = config()
    cfg["todo"]["plans"] = {"pairs": False}
    skipped = dict(check(build(make_project, cfg=cfg)).rules_skipped)
    assert all(skipped[r] == "todo.plans.pairs is false" for r in RULES)
