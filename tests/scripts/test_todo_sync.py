"""The ``scripts/todo_sync.py`` driver: check, render and runner subcommands, exit codes, output formats.

Each case runs the script as a subprocess against a ``make_project`` tree built by
``tests/lib/_todo_helpers.py``, which copies the ``TodoCatalog.min.json`` fixture into the project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import (CATALOG_REL, PIP, PIP_REL, RESEARCH_REL, SNAP_DIR, SNAP_REL, STUB_REL,  # noqa: E402
                           config, stub_text, todo_files)
from conftest import GIT_ENV, PLUGIN_ROOT  # noqa: E402

SCRIPT = PLUGIN_ROOT / "scripts" / "todo_sync.py"
REPORT_SCHEMA = json.loads((PLUGIN_ROOT / "schemas" / "TodoSyncReport.schema.json").read_text("utf-8"))
REPORT_REL = Path(".claude") / "state" / "harness" / "todo-sync" / "report.json"


def _run(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=120)


def _report(root: Path) -> dict:
    doc = json.loads((root / REPORT_REL).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(REPORT_SCHEMA, format_checker=jsonschema.FormatChecker()).validate(doc)
    return doc


@pytest.fixture()
def clean(make_project) -> Path:
    return make_project(config(), files=todo_files())


@pytest.fixture()
def drifting(make_project) -> Path:
    files = todo_files()
    files[PIP_REL] = PIP.replace("- [x] verified", "- [ ] verified")
    return make_project(config(), files=files)


def test_check_summary_and_report(clean: Path) -> None:
    done = _run(["check"], clean)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("todo-sync drift=0 error=0 warn=0 rules=20 elapsed_ms=")
    assert _report(clean)["drift"] == 0


def test_check_json_format_matches_the_report(drifting: Path) -> None:
    done = _run(["check", "--format", "json"], drifting)
    assert json.loads(done.stdout) == _report(drifting)


def test_check_markdown_format(drifting: Path) -> None:
    done = _run(["--project", str(drifting), "check", "--format", "markdown"], drifting.parent)
    assert done.stdout.startswith("# TODO sync report")
    assert f"| P1 | error | {PIP_REL}:6 | SMP-1 |" in done.stdout


@pytest.mark.parametrize("fail_on,code", [(None, 0), ("error", 1)])
def test_fail_on_error(drifting: Path, fail_on, code: int) -> None:
    args = ["check"] + (["--fail-on", fail_on] if fail_on else [])
    assert _run(args, drifting).returncode == code


def test_fail_on_error_passes_a_clean_tree(clean: Path) -> None:
    assert _run(["check", "--fail-on", "error"], clean).returncode == 0


@pytest.fixture()
def warning(make_project) -> Path:
    files = todo_files()
    files[SNAP_REL] = "# TODO Snapshot\n\nhand-written, no header\n"
    return make_project(config(), files=files)


@pytest.mark.parametrize("fail_on,code", [(None, 0), ("error", 0), ("warn", 1)])
def test_fail_on_warn_trips_on_a_warn_only_report(warning: Path, fail_on, code: int) -> None:
    args = ["check"] + (["--fail-on", fail_on] if fail_on else [])
    assert _run(args, warning).returncode == code
    assert _report(warning)["counts"] == {"error": 0, "warn": 1}


def test_fail_on_warn_also_trips_on_an_error(drifting: Path) -> None:
    assert _run(["check", "--fail-on", "warn"], drifting).returncode == 1


def test_fail_on_warn_passes_a_clean_tree(clean: Path) -> None:
    assert _run(["check", "--fail-on", "warn"], clean).returncode == 0


def test_rules_and_out(drifting: Path, tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    done = _run(["check", "--rules", "S1,T10", "--out", str(out)], drifting)
    assert done.returncode == 0, done.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["rules_run"] == ["S1", "T10"]


def test_unknown_rule_is_a_problem(clean: Path) -> None:
    done = _run(["check", "--rules", "S1,X9"], clean)
    assert done.returncode == 2 and done.stderr.startswith("problem: unknown rule id(s): X9")


def test_inactive_project_writes_nothing(make_project) -> None:
    root = make_project({})
    done = _run(["check"], root)
    assert (done.returncode, done.stdout.strip()) == (0, "todo sync inactive (todo.folder is null)")
    assert not (root / ".claude" / "state").exists()


def test_config_error_exits_2(make_project) -> None:
    root = make_project({"todo": {"top_n": 0}})
    done = _run(["check"], root)
    assert done.returncode == 2
    assert done.stderr.startswith("problem: ") and len(done.stderr.strip().splitlines()) == 1


def test_alternate_config(make_project, tmp_path: Path) -> None:
    root = make_project({}, files=todo_files())
    alt = tmp_path / "alt.json"
    alt.write_text(json.dumps(config()), encoding="utf-8")
    done = _run(["--config", str(alt), "check"], root)
    assert done.returncode == 0 and done.stdout.startswith("todo-sync drift=0"), done.stderr


def test_render_then_t2_is_clean(make_project) -> None:
    files = todo_files()
    del files[SNAP_REL]
    files[CATALOG_REL]["items"][0]["title"] = "Pipes | in the title"
    root = make_project(config(), files=files)
    done = _run(["render", "--date", "2026-10-21"], root)
    assert done.returncode == 0, done.stderr
    written = root / SNAP_DIR / "TODO_Snapshot_2026_1021.md"
    assert Path(done.stdout.strip()) == written
    lines = written.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith(f"<!-- todo-snapshot source={CATALOG_REL} top=10 rows_sha256=")
    assert lines[0].endswith(" rendered=2026-10-21 -->")
    assert lines[2] == "# TODO Snapshot: Top 10 (2026-10-21)"
    assert lines[4].startswith("| Rank | Item")
    assert "| TODO-001 Pipes \\| in the title " in lines[6]
    assert lines[7].rstrip(" |").endswith("tracker #101") and lines[8].rstrip(" |").endswith("none")
    assert len({len(line) for line in lines[4:]}) == 1
    check = _run(["check", "--rules", "T2"], root)
    assert _report(root)["findings"] == [], check.stdout


def test_render_creates_the_default_snapshots_folder(make_project) -> None:
    files = todo_files()
    del files[SNAP_REL]
    root = make_project(config(), files=files)
    done = _run(["render", "--date", "2026-10-21"], root)
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()) == root / SNAP_DIR / "TODO_Snapshot_2026_1021.md"
    assert _run(["check", "--rules", "T2"], root).returncode == 0 and _report(root)["findings"] == []


def test_render_refuses_a_name_the_pattern_rejects(make_project) -> None:
    cfg = config()
    cfg["todo"]["snapshots"] = {"name_pattern": r"Snap_(?P<date>\d{8})\.md"}
    done = _run(["render", "--date", "2026-10-21"], make_project(cfg, files=todo_files()))
    assert done.returncode == 2 and "does not match" in done.stderr


def test_runner_pointer(clean: Path) -> None:
    done = _run(["runner"], clean)
    assert done.returncode == 0, done.stderr
    pointer_path = Path(done.stdout.strip())
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert set(pointer) == {"schema_version", "python", "script", "project", "report", "written_at"}
    assert pointer["schema_version"] == 1 and Path(pointer["script"]) == SCRIPT
    assert pointer["project"] == clean.resolve().as_posix()
    assert pointer["report"] == (clean.resolve() / ".claude/state/harness/todo-sync/report.json").as_posix()
    assert pointer_path.resolve().is_relative_to(clean.resolve())


NOTES_REL = "docs/notes.md"


@pytest.fixture()
def retiring(make_project) -> Path:
    """The clean project plus TODO ids in a stub, the research catalog and an unrelated note."""
    files = todo_files()
    files[STUB_REL] = stub_text() + "\nRepoToDo tracks the rest as TODO-003.\n"
    files[RESEARCH_REL] = {"description": "Loader work is TODO-002.", **files[RESEARCH_REL]}
    files[NOTES_REL] = "See TODO-003.\n"
    return make_project(config(), files=files)


def _catalog_ids(root: Path) -> List[str]:
    data = json.loads((root / CATALOG_REL).read_text(encoding="utf-8"))
    return [i["id"] for i in data["items"]]


def test_retire_renumbers_and_rewrites_companions(retiring: Path) -> None:
    done = _run(["retire", "1"], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "retired TODO-001; 2 item(s) remain"
    assert lines[1] == "renumbered 2 item(s): TODO-002->TODO-001, TODO-003->TODO-002"
    assert f"rewrote ids in {RESEARCH_REL}" in lines and f"rewrote ids in {STUB_REL}" in lines
    assert any(line.startswith("issue #11: ") for line in lines)
    assert f"reference (not rewritten): {NOTES_REL}:1:See TODO-003." in lines
    assert _catalog_ids(retiring) == ["TODO-001", "TODO-002"]
    assert "tracks the rest as TODO-002." in (retiring / STUB_REL).read_text(encoding="utf-8")
    research = json.loads((retiring / RESEARCH_REL).read_text(encoding="utf-8"))
    assert research["description"] == "Loader work is TODO-001."
    assert (retiring / NOTES_REL).read_text(encoding="utf-8") == "See TODO-003.\n"
    check = _run(["check", "--rules", "T1,T3,T4,T5,T6,T7,T8,T9,T10"], retiring)
    assert check.returncode == 0 and _report(retiring)["findings"] == []


def test_retire_keeps_the_catalog_style(retiring: Path) -> None:
    path = retiring / CATALOG_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_bytes((json.dumps(data, indent=4) + "\n").replace("\n", "\r\n").encode("utf-8"))
    assert _run(["retire", "TODO-003"], retiring).returncode == 0
    raw = path.read_bytes().decode("utf-8")
    assert raw.startswith('{\r\n    "$schema"') and raw.endswith("}\r\n")
    assert "\n" not in raw.replace("\r\n", "")


def test_retire_dry_run_writes_nothing(retiring: Path) -> None:
    before = {rel: (retiring / rel).read_bytes() for rel in (CATALOG_REL, STUB_REL, RESEARCH_REL)}
    done = _run(["retire", "--dry-run", "TODO-001"], retiring)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("would retire TODO-001; 2 item(s) remain")
    assert {rel: (retiring / rel).read_bytes() for rel in before} == before


def test_retire_unknown_id_is_a_problem(clean: Path) -> None:
    done = _run(["retire", "9"], clean)
    assert done.returncode == 2
    assert done.stderr.strip() == "problem: no such item(s) in the catalog: TODO-009"


def test_retire_needs_the_feature_on(make_project) -> None:
    done = _run(["retire", "1"], make_project({}))
    assert done.returncode == 2 and "retire needs todo.folder" in done.stderr


def _spec(root: Path, parts: list) -> Path:
    path = root / "split_spec.json"
    path.write_text(json.dumps({"parts": parts}), encoding="utf-8")
    return path


LOADER_PARTS = [{"title": "Split the loader reads", "loe": {"size": "XS", "reasoning": "One function."}},
                {"title": "Split the loader writes"}]


def test_split_renumbers_rewrites_companions_and_flags_prose(retiring: Path) -> None:
    done = _run(["split", "2", "--spec", str(_spec(retiring, LOADER_PARTS))], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "split TODO-002 into TODO-002, TODO-003; 4 item(s) now"
    assert "renumbered 1 item(s): TODO-003->TODO-004" in lines
    assert f"rewrote ids in {STUB_REL}" in lines
    assert f"review: {RESEARCH_REL}:2 names split TODO-002, now TODO-002 (first part)" in lines
    assert f"reference (not rewritten): {NOTES_REL}:1:See TODO-003." in lines
    assert _catalog_ids(retiring) == ["TODO-001", "TODO-002", "TODO-003", "TODO-004"]
    assert "tracks the rest as TODO-004." in (retiring / STUB_REL).read_text(encoding="utf-8")
    check = _run(["check", "--rules", "T1,T3,T4,T5,T6,T7,T8,T9,T10"], retiring)
    assert check.returncode == 0 and _report(retiring)["findings"] == []


def test_split_dry_run_writes_nothing(retiring: Path) -> None:
    before = {rel: (retiring / rel).read_bytes() for rel in (CATALOG_REL, STUB_REL, RESEARCH_REL)}
    done = _run(["split", "--dry-run", "2", "--spec", str(_spec(retiring, LOADER_PARTS))], retiring)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("would split TODO-002 into TODO-002, TODO-003; 4 item(s) now")
    assert {rel: (retiring / rel).read_bytes() for rel in before} == before


def test_split_bad_spec_is_a_problem(clean: Path) -> None:
    done = _run(["split", "2", "--spec", str(_spec(clean, [{"title": "alone"}]))], clean)
    assert done.returncode == 2
    assert done.stderr.strip() == "problem: a split needs at least two parts"


def test_refresh_reorders_after_a_hand_edit(retiring: Path) -> None:
    path = retiring / CATALOG_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][2].update(severity=5, impact="silent_wrong_output")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    done = _run(["refresh"], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[:3] == ["refreshed 3 item(s)", "rescored 1 item(s): TODO-002",
                         "renumbered 2 item(s): TODO-002->TODO-003, TODO-003->TODO-002"]
    assert "tracks the rest as TODO-002." in (retiring / STUB_REL).read_text(encoding="utf-8")
    check = _run(["check", "--rules", "T1,T6,T7,T8,T9,T10"], retiring)
    assert check.returncode == 0 and _report(retiring)["findings"] == []


def test_refresh_of_a_ranked_catalog_writes_nothing(clean: Path) -> None:
    before = (clean / CATALOG_REL).read_bytes()
    done = _run(["refresh"], clean)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["refreshed 3 item(s)", "nothing changed"]
    assert (clean / CATALOG_REL).read_bytes() == before
