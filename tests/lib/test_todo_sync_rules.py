"""The todo_sync rule runner: catalog order, gates, drift counting and the report contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import PIP, PIP_REL, SNAP_REL, build, config, todo_files  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib.todo_sync import RULE_IDS, TodoSyncError, check  # noqa: E402
from harness_lib.todo_sync.report import format_markdown, format_summary, write_report  # noqa: E402

REPORT_SCHEMA_PATH = PLUGIN_ROOT / "schemas" / "TodoSyncReport.schema.json"
REPORT_SCHEMA = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(doc) -> None:
    jsonschema.Draft202012Validator(REPORT_SCHEMA, format_checker=jsonschema.FormatChecker()).validate(doc)


def test_catalog_order_and_clean_run(make_project) -> None:
    report = check(build(make_project))
    assert report.rules_run == RULE_IDS
    assert RULE_IDS == ("S1", "S2", "S3", "S4", "S5", "S6", "P1", "P2", "P3", "P4", "T1", "T2", "T3", "T4",
                        "T5", "T6", "T7", "T8", "T9", "T10")
    assert (report.findings, report.drift) == ((), 0)
    _validate(report.to_dict())


def test_disabled_and_not_selected(make_project) -> None:
    cfg = config()
    cfg["todo"]["rules"] = {"disabled": ["S2"]}
    report = check(build(make_project, cfg=cfg), rules=["s1", "S2"])
    assert report.rules_run == ("S1",)
    skipped = dict(report.rules_skipped)
    assert (skipped["S2"], skipped["T10"]) == ("disabled", "not selected")


def test_unknown_rule_id_raises(make_project) -> None:
    with pytest.raises(TodoSyncError, match="X9"):
        check(build(make_project), rules=["S1", "X9"])


def test_snapshots_dir_null_gates_t2(make_project) -> None:
    cfg = config()
    cfg["todo"]["snapshots"] = {"dir": None}
    assert dict(check(build(make_project, cfg=cfg)).rules_skipped)["T2"] == "todo.snapshots.dir is null"


def _drifting_files():
    files = todo_files()
    files[PIP_REL] = PIP.replace("- [x] verified", "- [ ] verified")
    files[SNAP_REL] = "# no header\n"
    return files


@pytest.mark.parametrize("warn_counts,drift", [(False, 2), (True, 3)])
def test_drift_counts_errors_and_optionally_warns(make_project, warn_counts: bool, drift: int) -> None:
    cfg = config()
    cfg["todo"]["rules"] = {"warn_counts": warn_counts}
    report = check(build(make_project, _drifting_files(), cfg))
    doc = report.to_dict()
    assert (doc["drift"], doc["counts"]) == (drift, {"error": 2, "warn": 1})
    assert sum(doc["by_rule"].values()) == drift
    assert [f["severity"] for f in doc["findings"]] == ["error", "error", "warn"]
    _validate(doc)


def test_report_writer_is_atomic_and_valid(make_project, tmp_path: Path) -> None:
    report = check(build(make_project, _drifting_files()))
    out = write_report(report, tmp_path / "deep" / "report.json")
    _validate(json.loads(out.read_text(encoding="utf-8")))
    assert [p.name for p in out.parent.iterdir()] == ["report.json"]


def test_text_formats(make_project) -> None:
    report = check(build(make_project, _drifting_files()))
    assert format_summary(report).startswith("todo-sync drift=2 error=2 warn=1 rules=20 elapsed_ms=")
    table = format_markdown(report)
    assert "| Rule | Severity | File:line | Subject | Message | Fix |" in table
    assert f"| P1 | error | {PIP_REL}:6 | SMP-1 |" in table


def test_inactive_project_skips_everything(make_project) -> None:
    report = check(build(make_project, cfg={}))
    assert report.rules_run == () and len(report.rules_skipped) == len(RULE_IDS)
