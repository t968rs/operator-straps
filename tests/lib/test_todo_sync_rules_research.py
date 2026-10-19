"""Research rules S1-S6: catalog entries against their stubs and folders, red and green per rule."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import RESEARCH_REL, STUB_REL, build, config, rule_findings, stub_text, todo_files  # noqa: E402

RULES = ["S1", "S2", "S3", "S4", "S5", "S6"]


@pytest.mark.parametrize("rule", RULES)
def test_in_sync_project_is_clean(make_project, rule: str) -> None:
    assert rule_findings(build(make_project), rule) == []


def _entry(files, n: int = 0):
    return files[RESEARCH_REL]["entries"][n]


def test_s1_anchor_names_another_entry(make_project) -> None:
    files = todo_files()
    files[STUB_REL] = stub_text(entry_id="beta-cache")
    [f] = rule_findings(build(make_project, files), "S1")
    assert (f.severity, f.file, f.subject, f.line) == ("error", STUB_REL, "alpha-loader", 8)
    assert "#beta-cache" in f.message


def test_s1_stub_without_anchor_line(make_project) -> None:
    files = todo_files()
    files[STUB_REL] = "# stub\nstatus: PARTIALLY_IMPLEMENTED\nloe: M (1-3 days)\n"
    [f] = rule_findings(build(make_project, files), "S1")
    assert "anchor" in f.message


def test_s1_terminal_entry_with_missing_stub_file(make_project) -> None:
    files = todo_files()
    _entry(files, 1)["stub_path"] = "docs/RESEARCH/Beta/_IMPL_TODO.md"
    [f] = rule_findings(build(make_project, files), "S1")
    assert (f.file, f.subject) == (RESEARCH_REL, "beta-cache")
    assert "does not exist" in f.message


def test_s1_leaves_missing_non_terminal_stub_to_s3(make_project) -> None:
    files = todo_files()
    del files[STUB_REL]
    cfg = build(make_project, files)
    assert rule_findings(cfg, "S1") == []
    [f] = rule_findings(cfg, "S3")
    assert f.subject == "alpha-loader" and "does not exist" in f.message


def test_s2_orphan_stub(make_project) -> None:
    files = todo_files()
    files["docs/RESEARCH/Beta/Deep/_IMPL_TODO.md"] = stub_text(entry_id="beta-cache")
    [f] = rule_findings(build(make_project, files), "S2")
    assert (f.severity, f.file) == ("error", "docs/RESEARCH/Beta/Deep/_IMPL_TODO.md")


def test_s3_non_terminal_entry_without_stub_path(make_project) -> None:
    files = todo_files()
    _entry(files)["stub_path"] = None
    del files[STUB_REL]
    [f] = rule_findings(build(make_project, files), "S3")
    assert (f.severity, f.subject) == ("error", "alpha-loader")
    assert "stub_path is null" in f.message


@pytest.mark.parametrize("field,stub_kwargs,line", [
    ("status", {"status": "FULLY_IMPLEMENTED"}, 6),
    ("loe", {"loe": "L (1-2 weeks)"}, 7),
])
def test_s4_header_differs_from_entry(make_project, field: str, stub_kwargs, line: int) -> None:
    files = todo_files()
    files[STUB_REL] = stub_text(**stub_kwargs)
    [f] = rule_findings(build(make_project, files), "S4")
    assert (f.severity, f.file, f.line, f.subject) == ("error", STUB_REL, line, "alpha-loader")
    assert f"{field}:" in f.message


def test_s4_missing_header_line(make_project) -> None:
    files = todo_files()
    files[STUB_REL] = stub_text().replace("loe: M (1-3 days)\n", "")
    [f] = rule_findings(build(make_project, files), "S4")
    assert "no loe: line" in f.message


def test_s5_missing_research_folder(make_project) -> None:
    files = todo_files()
    _entry(files, 1)["research_folder"] = "docs/RESEARCH/Gone"
    findings = rule_findings(build(make_project, files), "S5")
    assert [(f.severity, f.subject) for f in findings] == [("error", "beta-cache")]


def test_s6_uncovered_folder_warns(make_project) -> None:
    files = todo_files()
    files["docs/RESEARCH/Gamma/notes.md"] = "g\n"
    [f] = rule_findings(build(make_project, files), "S6")
    assert (f.severity, f.file) == ("warn", "docs/RESEARCH/Gamma")


@pytest.mark.parametrize("ignore", ["Gamma", "docs/RESEARCH/Gamma"])
def test_s6_ignore_folders(make_project, ignore: str) -> None:
    files = todo_files()
    files["docs/RESEARCH/Gamma/notes.md"] = "g\n"
    cfg = config()
    cfg["todo"]["research"]["ignore_folders"] = [ignore]
    assert rule_findings(build(make_project, files, cfg), "S6") == []


def test_s6_catalog_and_snapshot_folders_are_excluded(make_project) -> None:
    files = todo_files()
    cfg = config()
    cfg["todo"]["snapshots"]["dir"] = "docs/RESEARCH/Snaps/dated"
    files["docs/RESEARCH/Snaps/dated/keep.md"] = "x\n"
    assert rule_findings(build(make_project, files, cfg), "S6") == []


def test_unreadable_research_catalog_is_one_finding(make_project) -> None:
    from harness_lib.todo_sync import check
    files = todo_files()
    files[RESEARCH_REL] = "{not json"
    report = check(build(make_project, files), rules=RULES + ["T3", "T4", "T5"])
    assert [(f.rule, f.file) for f in report.findings] == [("S1", RESEARCH_REL)]
    skipped = dict(report.rules_skipped)
    assert skipped["S2"] == skipped["T3"] == "research catalog unreadable"


@pytest.mark.parametrize("key,rules", [
    ("stub_name", ["S1", "S2", "S3", "S4"]),
    ("catalog", ["S1", "S2", "S3", "S4", "S5", "S6", "T3", "T4", "T5"]),
])
def test_null_keys_gate_rules(make_project, key: str, rules) -> None:
    from harness_lib.todo_sync import check
    cfg = config()
    cfg["todo"]["research"][key] = None
    report = check(build(make_project, cfg=cfg))
    skipped = dict(report.rules_skipped)
    assert all(skipped[r] == f"todo.research.{key} is null" for r in rules)
