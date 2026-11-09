"""The ``scripts/todo_sync.py`` driver: check, render, runner, retire, split, refresh and migrate-ids
subcommands, exit codes, output formats.

Each case runs the script as a subprocess against a ``make_project`` tree built by
``tests/lib/_todo_helpers.py``, which copies the ``TodoCatalog.min.json`` fixture (stable ids ID1-ID3) or
the ``TodoCatalog.legacy.json`` fixture (rank-tied TODO-001 to TODO-003) into the project.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import (CATALOG_REL, ID1, ID2, ID3, LEGACY_CATALOG, PIP, PIP_REL,  # noqa: E402
                           RESEARCH_REL, SNAP_DIR, SNAP_REL, STUB_REL, TODO_DIR, config, stub_text,
                           todo_files)
from conftest import GIT_ENV, PLUGIN_ROOT  # noqa: E402

SCRIPT = PLUGIN_ROOT / "scripts" / "todo_sync.py"
BETA_STUB = "docs/RESEARCH/Beta/_IMPL_TODO.md"
REPORT_SCHEMA = json.loads((PLUGIN_ROOT / "schemas" / "TodoSyncReport.schema.json").read_text("utf-8"))
REPORT_REL = Path(".claude") / "state" / "harness" / "todo-sync" / "report.json"
NEW_ID = r"todo-[2-9a-hjkmnp-z]{4}"


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
    assert f"| {ID1} Pipes \\| in the title " in lines[6]
    assert f"| [{ID2}](../../Alpha/_IMPL_TODO.md) Split the loader module " in lines[7]
    assert "](" not in lines[6] and "](" not in lines[8]
    assert lines[7].rstrip(" |").endswith("tracker #101") and lines[8].rstrip(" |").endswith("none")
    assert len({len(line) for line in lines[4:]}) == 1
    check = _run(["check", "--rules", "T2"], root)
    assert _report(root)["findings"] == [], check.stdout


def _cells(line: str) -> List[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]


def test_render_extra_stubs_and_escaping(make_project) -> None:
    files = todo_files()
    del files[SNAP_REL]
    files[BETA_STUB] = stub_text("beta-cache")
    item = files[CATALOG_REL]["items"][1]
    item["title"] = "a | [b](c)"
    item["sources"].append({"type": "impl_stub", "ref": BETA_STUB, "item": "Beta part"})
    root = make_project(config(), files=files)
    done = _run(["render", "--date", "2026-10-21"], root)
    assert done.returncode == 0, done.stderr
    row = (root / SNAP_DIR / "TODO_Snapshot_2026_1021.md").read_text(encoding="utf-8").splitlines()[7]
    cells = _cells(row)
    assert len(cells) == 7
    assert cells[1] == (f"[{ID2}](../../Alpha/_IMPL_TODO.md) a \\| \\[b\\]\\(c\\) "
                        "[2](../../Beta/_IMPL_TODO.md)")


def _render_rows(make_project, files: dict) -> List[str]:
    """Render ``files`` (snapshot removed) and return the three table rows."""
    del files[SNAP_REL]
    root = make_project(config(), files=files)
    done = _run(["render", "--date", "2026-10-21"], root)
    assert done.returncode == 0, done.stderr
    return (root / SNAP_DIR / "TODO_Snapshot_2026_1021.md").read_text(encoding="utf-8").splitlines()[6:9]


def test_render_keeps_code_spans_unescaped(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["items"][1]["title"] = "Split `load()` from [x](y) and ``a`b[c]``"
    cells = _cells(_render_rows(make_project, files)[1])
    assert cells[1] == (f"[{ID2}](../../Alpha/_IMPL_TODO.md) Split `load()` from \\[x\\]\\(y\\) "
                        "and ``a`b[c]``")


def test_render_stubless_title_is_unchanged(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["items"][2]["title"] = "Pick [x](y)"
    assert _cells(_render_rows(make_project, files)[2])[1] == f"{ID3} Pick [x](y)"


def test_render_without_a_research_catalog_scans_anchors(make_project) -> None:
    files = todo_files()
    del files[RESEARCH_REL]
    files[CATALOG_REL]["items"][1]["sources"] = []
    cell = _cells(_render_rows(make_project, files)[1])[1]
    assert cell == f"[{ID2}](../../Alpha/_IMPL_TODO.md) Split the loader module"


def test_render_links_rows_by_position_not_id(make_project) -> None:
    files = todo_files()
    files[BETA_STUB] = stub_text("beta-cache")
    items = files[CATALOG_REL]["items"]
    items[2].update(id=ID2, sources=[{"type": "impl_stub", "ref": BETA_STUB, "item": "Beta"}])
    rows = _render_rows(make_project, files)
    assert _cells(rows[1])[1] == f"[{ID2}](../../Alpha/_IMPL_TODO.md) Split the loader module"
    assert _cells(rows[2])[1] == f"[{ID2}](../../Beta/_IMPL_TODO.md) Choose a cache format"


def test_render_tolerates_malformed_link_fields(make_project) -> None:
    files = todo_files()
    items = files[CATALOG_REL]["items"]
    items[0].update(sources=5, catalog_entry_ids=5)
    items[1]["id"] = [ID2]
    rows = _render_rows(make_project, files)
    assert _cells(rows[0])[1] == f"{ID1} Parser drops the last row"
    assert "](" not in rows[1]


def test_render_with_null_stub_name(make_project) -> None:
    files = todo_files()
    del files[SNAP_REL]
    root = make_project(config({"folder": TODO_DIR, "stub_name": None}), files=files)
    done = _run(["render", "--date", "2026-10-21"], root)
    assert done.returncode == 0, done.stderr
    lines = (root / SNAP_DIR / "TODO_Snapshot_2026_1021.md").read_text(encoding="utf-8").splitlines()
    assert f"| [{ID2}](../../Alpha/_IMPL_TODO.md) Split the loader module " in lines[7]


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
RECORDS = ("docs/PLANS", "docs/PR_REVIEWS", "docs/_commit_messages")


@pytest.fixture()
def retiring(make_project) -> Path:
    """The clean project plus TODO ids in a stub, the research catalog, an unrelated note and dated
    records."""
    files = todo_files()
    files[STUB_REL] = stub_text() + f"\nRepoToDo tracks the rest as {ID2}.\n"
    files[RESEARCH_REL] = {"description": f"Loader work is {ID2}; it follows {ID1}.", **files[RESEARCH_REL]}
    files[NOTES_REL] = f"See {ID1}.\nAlso {ID2}.\n"
    files.update(_dated_records(*RECORDS))
    return make_project(config(), files=files)


def _dated_records(plans: str, reviews: str, commits: str) -> dict:
    """A plan PIP, a review and a commit message naming TODO ids, as dated records of finished work."""
    return {f"{plans}/0001_Old_PIP.md": f"Executed under {ID1} and {ID2}.\n",
            f"{reviews}/0001_Old.json": {"summary": f"Merged review naming {ID1} and {ID2}."},
            f"{commits}/0001_Old.txt": f"Lands {ID1} and {ID2}.\n"}


def _references(lines: List[str]) -> List[str]:
    return [line for line in lines if line.startswith("reference (not rewritten): ")]


def _catalog_ids(root: Path) -> List[str]:
    data = json.loads((root / CATALOG_REL).read_text(encoding="utf-8"))
    return [i["id"] for i in data["items"]]


def _bytes(root: Path, *rels: str) -> dict:
    return {rel: (root / rel).read_bytes() for rel in rels}


def test_retire_keeps_ids_and_lists_references(retiring: Path) -> None:
    before = _bytes(retiring, STUB_REL, RESEARCH_REL, NOTES_REL)
    done = _run(["retire", ID1[len("todo-"):].upper()], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == f"retired {ID1}; 2 item(s) remain"
    assert not any(line.startswith(("renumbered", "rewrote")) for line in lines)
    assert any(line.startswith("issue #11: ") for line in lines)
    assert f"dangling: {RESEARCH_REL}:2 names retired {ID1}" in lines
    assert _references(lines) == [f"reference (not rewritten): {NOTES_REL}:1:See {ID1}."]
    assert _catalog_ids(retiring) == [ID2, ID3]
    assert json.loads((retiring / CATALOG_REL).read_text(encoding="utf-8"))["retired_ids"] == [ID1]
    assert _bytes(retiring, *before) == before
    check = _run(["check", "--rules", "T1,T3,T4,T5,T6,T7,T8,T9,T10"], retiring)
    assert check.returncode == 0 and _report(retiring)["findings"] == []


def test_retire_skips_plan_review_and_commit_message_records(retiring: Path) -> None:
    lines = _run(["retire", ID1], retiring).stdout.splitlines()
    assert _references(lines) == [f"reference (not rewritten): {NOTES_REL}:1:See {ID1}."]


def test_retire_skips_the_configured_record_folders(make_project) -> None:
    files = {**todo_files(), NOTES_REL: f"See {ID1}.\n",
             **_dated_records("kept/plans", "kept/reviews", "kept/msgs"), **_dated_records(*RECORDS)}
    artifacts = {"plans": "kept/plans", "reviews": "kept/reviews", "commit_messages": "kept/msgs",
                 "planning_prefixes": []}
    root = make_project(config(artifacts=artifacts), files=files)
    lines = _run(["retire", ID1], root).stdout.splitlines()
    assert sorted(ref.split(":", 2)[1].strip() for ref in _references(lines)) == [
        "docs/PLANS/0001_Old_PIP.md", "docs/PR_REVIEWS/0001_Old.json", "docs/_commit_messages/0001_Old.txt",
        NOTES_REL]


def test_retire_keeps_the_catalog_style(retiring: Path) -> None:
    path = retiring / CATALOG_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_bytes((json.dumps(data, indent=4) + "\n").replace("\n", "\r\n").encode("utf-8"))
    assert _run(["retire", ID3], retiring).returncode == 0
    raw = path.read_bytes().decode("utf-8")
    assert raw.startswith('{\r\n    "$schema"') and raw.endswith("}\r\n")
    assert "\n" not in raw.replace("\r\n", "")


def test_retire_dry_run_writes_nothing(retiring: Path) -> None:
    before = _bytes(retiring, CATALOG_REL, STUB_REL, RESEARCH_REL)
    done = _run(["retire", "--dry-run", ID1], retiring)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(f"would retire {ID1}; 2 item(s) remain")
    assert _bytes(retiring, *before) == before


def test_retire_unknown_id_is_a_problem(clean: Path) -> None:
    done = _run(["retire", "9zzz"], clean)
    assert done.returncode == 2
    assert done.stderr.strip() == "problem: no such item(s) in the catalog: todo-9zzz"


def test_retire_needs_the_feature_on(make_project) -> None:
    done = _run(["retire", ID1], make_project({}))
    assert done.returncode == 2 and "retire needs todo.folder" in done.stderr


def _spec(root: Path, parts: list) -> Path:
    path = root / "split_spec.json"
    path.write_text(json.dumps({"parts": parts}), encoding="utf-8")
    return path


LOADER_PARTS = [{"title": "Split the loader reads", "loe": {"size": "XS", "reasoning": "One function."}},
                {"title": "Split the loader writes"}]


def test_split_retires_the_original_and_flags_prose(retiring: Path) -> None:
    before = _bytes(retiring, STUB_REL, RESEARCH_REL)
    done = _run(["split", ID2, "--spec", str(_spec(retiring, LOADER_PARTS))], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    head = re.fullmatch(rf"split {ID2} into ({NEW_ID}), ({NEW_ID}); 4 item\(s\) now", lines[0])
    assert head, lines[0]
    reads, writes = head.groups()
    parts = f"(parts {reads}, {writes})"
    assert f"dangling: {STUB_REL}:12 names split {ID2} {parts}" in lines
    assert f"dangling: {RESEARCH_REL}:2 names split {ID2} {parts}" in lines
    assert _references(lines) == [f"reference (not rewritten): {NOTES_REL}:2:Also {ID2}."]
    assert not any(line.startswith(("renumbered", "rewrote", "review:")) for line in lines)
    assert _catalog_ids(retiring) == [ID1, reads, writes, ID3]
    assert _bytes(retiring, *before) == before
    check = _run(["check", "--rules", "T1,T3,T4,T5,T6,T7,T8,T9,T10"], retiring)
    assert check.returncode == 0 and _report(retiring)["findings"] == []


def test_split_skips_plan_review_and_commit_message_records(retiring: Path) -> None:
    lines = _run(["split", ID2, "--spec", str(_spec(retiring, LOADER_PARTS))], retiring).stdout.splitlines()
    assert _references(lines) == [f"reference (not rewritten): {NOTES_REL}:2:Also {ID2}."]


def test_split_dry_run_writes_nothing(retiring: Path) -> None:
    before = _bytes(retiring, CATALOG_REL, STUB_REL, RESEARCH_REL)
    done = _run(["split", "--dry-run", ID2, "--spec", str(_spec(retiring, LOADER_PARTS))], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert re.fullmatch(rf"would split {ID2} into {NEW_ID}, {NEW_ID}; 4 item\(s\) now", lines[0])
    assert "note: new ids are drawn at random; the real run draws its own" in lines
    assert _bytes(retiring, *before) == before


def test_split_bad_spec_is_a_problem(clean: Path) -> None:
    done = _run(["split", ID2, "--spec", str(_spec(clean, [{"title": "alone"}]))], clean)
    assert done.returncode == 2
    assert done.stderr.strip() == "problem: a split needs at least two parts"


def test_refresh_reranks_after_a_hand_edit(retiring: Path) -> None:
    path = retiring / CATALOG_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][2].update(severity=5, impact="silent_wrong_output")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    stub = (retiring / STUB_REL).read_bytes()
    done = _run(["refresh"], retiring)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[:3] == ["refreshed 3 item(s)", f"rescored 1 item(s): {ID3}",
                         f"re-ranked 2 item(s): {ID3} 3->2, {ID2} 2->3"]
    assert _catalog_ids(retiring) == [ID1, ID3, ID2]
    assert (retiring / STUB_REL).read_bytes() == stub
    check = _run(["check", "--rules", "T1,T6,T7,T8,T9,T10"], retiring)
    assert check.returncode == 0 and _report(retiring)["findings"] == []


def test_refresh_of_a_ranked_catalog_writes_nothing(clean: Path) -> None:
    before = (clean / CATALOG_REL).read_bytes()
    done = _run(["refresh"], clean)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["refreshed 3 item(s)", "nothing changed"]
    assert (clean / CATALOG_REL).read_bytes() == before


@pytest.fixture()
def legacy(make_project) -> Path:
    """A project whose catalog still carries rank-tied ids, named in a stub, a note and dated records."""
    files = todo_files()
    files[CATALOG_REL] = copy.deepcopy(LEGACY_CATALOG)
    files[STUB_REL] = stub_text() + "\nRepoToDo tracks the rest as TODO-002.\n"
    files[NOTES_REL] = "See TODO-003.\n"
    files["vendor/copy.md"] = "Upstream TODO-001.\n"
    files["third_party/copy.md"] = "Upstream TODO-002.\n"
    for rel, body in _dated_records(*RECORDS).items():
        files[rel] = "Executed under TODO-001." if isinstance(body, str) else {"summary": "Names TODO-001."}
    return make_project(config(), files=files)


def test_operations_refuse_a_legacy_catalog(legacy: Path) -> None:
    before = (legacy / CATALOG_REL).read_bytes()
    add_spec = legacy / "add.json"
    add_spec.write_text(json.dumps({"items": [{}]}), encoding="utf-8")
    for args in (["retire", "1"], ["split", "2", "--spec", str(_spec(legacy, LOADER_PARTS))], ["refresh"],
                 ["add", "--spec", str(add_spec)]):
        done = _run(args, legacy)
        assert done.returncode == 2, args
        assert done.stderr.startswith(f"problem: {args[0]}: ") and "migrate-ids" in done.stderr, done.stderr
    assert (legacy / CATALOG_REL).read_bytes() == before
    _run(["check", "--rules", "T1,T6"], legacy)
    findings = _report(legacy)["findings"]
    assert [f["rule"] for f in findings] == ["T6"] and "migrate-ids" in findings[0]["message"]


def test_migrate_ids_dry_run_writes_nothing(legacy: Path) -> None:
    before = _bytes(legacy, CATALOG_REL, STUB_REL, NOTES_REL)
    done = _run(["migrate-ids", "--dry-run"], legacy)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "would migrate 3 item(s) to stable ids"
    assert f"would rewrite {STUB_REL} (1 reference(s))" in lines
    assert _bytes(legacy, *before) == before


def test_migrate_ids_rewrites_live_files_and_keeps_history(legacy: Path) -> None:
    kept = _bytes(legacy, "vendor/copy.md", "third_party/copy.md", *_dated_records(*RECORDS))
    done = _run(["migrate-ids", "--exclude", "vendor", "--exclude", "third_party"], legacy)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "migrated 3 item(s) to stable ids"
    catalog = json.loads((legacy / CATALOG_REL).read_text(encoding="utf-8"))
    mapping = catalog["legacy_ids"]["map"]
    assert list(mapping) == ["TODO-001", "TODO-002", "TODO-003"]
    assert [i["id"] for i in catalog["items"]] == list(mapping.values())
    assert (legacy / NOTES_REL).read_text(encoding="utf-8") == f"See {mapping['TODO-003']}.\n"
    assert f"tracks the rest as {mapping['TODO-002']}." in (legacy / STUB_REL).read_text(encoding="utf-8")
    assert _bytes(legacy, *kept) == kept
    assert lines[-1] == "next: todo_sync.py render, then todo_sync.py check"
    check = _run(["check", "--rules", "T1,T6,T7,T8,T9,T10"], legacy)
    assert check.returncode == 0 and _report(legacy)["findings"] == []
    again = _run(["migrate-ids", "--exclude", "vendor", "--exclude", "third_party"], legacy)
    assert again.returncode == 0, again.stderr
    assert again.stdout.splitlines()[0] == "migrated 0 item(s) to stable ids"
    assert _bytes(legacy, *kept) == kept
