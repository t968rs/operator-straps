"""TODO sync engine: rules S1-S6, P1-P4 and T1-T10 over a project's TODO, research and plan artifacts.

Public API (the driver ``scripts/todo_sync.py``, the SessionStart hook and tests call these):

- ``check(cfg, rules=None) -> Report``: run the rule catalog (or the selected ids).
- ``render_snapshot(cfg, date) -> Path``: bring the snapshot page T2 compares against, and its stamp, up to
  date, writing each only when its text changes; every run is recorded in ``render_record_path(cfg)``.
- ``write_runner(cfg) -> Path``: write the runner pointer the todo-watch mod executes.

Every path is project-relative through ``cfg``; nothing is written under the plugin root.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.project import main_worktree, plugin_root, run_git
from harness_lib.todo_sync.errors import TodoSyncError
from harness_lib.todo_sync import rules_plans as rp
from harness_lib.todo_sync import rules_research as rr
from harness_lib.todo_sync import rules_todo as rt
from harness_lib.todo_sync.report import Finding, Report, snapshot_header, write_atomic, write_report
from harness_lib.todo_sync.snapshot_html import (LIVE_NAME, PAGE_NAME, SnapshotPage, live_script, page_stamp,
                                                 render_page)
from harness_lib.todo_sync.sources import (JsonFile, Sources, parse_header, posix, ranked_items, read_json,
                                           rows_sha256)
from harness_lib.todo_sync.stub_links import item_stubs, link_target

__all__ = ["RULES", "RULE_IDS", "Report", "TodoSyncError", "check", "render_record_path", "render_snapshot",
           "report_path", "runner_path", "write_report", "write_runner"]

RuleFn = Callable[[Sources], List[Finding]]


@dataclass(frozen=True)
class RuleSpec:
    """One catalog rule: id, implementation and the inputs it needs."""

    id: str
    fn: RuleFn
    needs: Tuple[str, ...]


_R, _S, _T = ("research", "stub_name"), ("research",), ("todo",)
RULES: Tuple[RuleSpec, ...] = (
    RuleSpec("S1", rr.s1_stub_anchor, _R), RuleSpec("S2", rr.s2_orphan_stubs, _R),
    RuleSpec("S3", rr.s3_non_terminal_stub, _R), RuleSpec("S4", rr.s4_stub_header, _R),
    RuleSpec("S5", rr.s5_research_folder, _S), RuleSpec("S6", rr.s6_uncovered_folders, _S),
    RuleSpec("P1", rp.p1_checkboxes, ("plans",)), RuleSpec("P2", rp.p2_evidence_sha, ("plans",)),
    RuleSpec("P3", rp.p3_pair_files, ("plans",)), RuleSpec("P4", rp.p4_sync_claim, ("plans",)),
    RuleSpec("T1", rt.t1_schema, _T), RuleSpec("T2", rt.t2_snapshot, ("todo", "snapshots")),
    RuleSpec("T3", rt.t3_links_resolve, ("todo", "research")),
    RuleSpec("T4", rt.t4_entries_referenced, ("todo", "research")),
    RuleSpec("T5", rt.t5_live_entries, ("todo", "research")),
    RuleSpec("T6", rt.t6_ids_and_ranks, _T), RuleSpec("T7", rt.t7_dependencies, _T),
    RuleSpec("T8", rt.t8_trackers, _T), RuleSpec("T9", rt.t9_counts, _T), RuleSpec("T10", rt.t10_ranking, _T),
)
RULE_IDS: Tuple[str, ...] = tuple(r.id for r in RULES)
_LABELS = {"todo": "catalog", "research": "research catalog"}


def _config_gate(cfg: HarnessConfig, need: str) -> Optional[str]:
    """Why ``need`` is switched off in the configuration, or None."""
    todo = cfg.todo
    gates = {
        "todo": None if todo.catalog else "todo.folder is null",
        "research": None if todo.research.catalog else "no research catalog (todo.research.catalog)",
        "stub_name": None if todo.stub_name else "todo.stub_name is null",
        "plans": None if todo.plans_pairs else "todo.plans.pairs is false",
        "snapshots": None if todo.snapshots.dir else "todo.snapshots.dir is null",
    }
    return gates[need]


def _input(src: Sources, need: str) -> Optional[JsonFile]:
    return {"todo": lambda: src.todo, "research": lambda: src.research}.get(need, lambda: None)()


def _gate(spec: RuleSpec, src: Sources, selected: Optional[frozenset]) -> Tuple[Optional[str], List[Finding]]:
    """``(skip reason, findings)``: a skip reason, or the one finding reporting an unreadable input."""
    if not src.cfg.todo.enabled:
        return "todo.folder is null", []
    if selected is not None and spec.id not in selected:
        return "not selected", []
    if spec.id in src.cfg.todo.rules_disabled:
        return "disabled", []
    reason = next((r for r in (_config_gate(src.cfg, n) for n in spec.needs) if r), None)
    if reason:
        return reason, []
    for need in spec.needs:
        jf = _input(src, need)
        if jf is not None and not jf.ok:
            if not src.claim(jf.rel):
                return f"{_LABELS[need]} unreadable", []
            return None, [Finding(spec.id, "error", jf.rel, f"{_LABELS[need]} {jf.error}",
                                  fix="Repair the file, or fix its path in .claude/harness.json.")]
    return None, []


def _run(spec: RuleSpec, src: Sources) -> List[Finding]:
    """The rule's findings; a rule that fails on malformed input yields one error finding instead."""
    try:
        return spec.fn(src)
    except Exception as exc:  # noqa: BLE001 - a malformed input is a finding, never a traceback
        return [Finding(spec.id, "error", None, f"rule could not run: {type(exc).__name__}: {exc}")]


def _selection(rules: Optional[Iterable[str]]) -> Optional[frozenset]:
    if rules is None:
        return None
    chosen = frozenset(r.strip().upper() for r in rules if r.strip())
    unknown = sorted(chosen - set(RULE_IDS))
    if unknown:
        raise TodoSyncError(f"unknown rule id(s): {', '.join(unknown)} (known: {', '.join(RULE_IDS)})")
    return chosen


def check(cfg: HarnessConfig, rules: Optional[Iterable[str]] = None) -> Report:
    """Run the rule catalog (or ``rules``) over the project ``cfg`` describes."""
    start = time.perf_counter()
    selected, src = _selection(rules), Sources(cfg)
    run: List[str] = []
    skipped: List[Tuple[str, str]] = []
    findings: List[Finding] = []
    for spec in RULES:
        reason, reported = _gate(spec, src, selected)
        if reason:
            skipped.append((spec.id, reason))
            continue
        run.append(spec.id)
        findings.extend(reported or _run(spec, src))
    return Report(_utc_now(), (time.perf_counter() - start) * 1000, tuple(run), tuple(skipped),
                  tuple(findings), cfg.todo.rules_warn_counts, None, RULE_IDS)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def report_path(cfg: HarnessConfig) -> Path:
    """Default report location: ``<state_dir>/todo-sync/report.json``."""
    return cfg.path(cfg.state_dir) / "todo-sync" / "report.json"


def runner_path(cfg: HarnessConfig) -> Path:
    """Runner pointer location: ``<state_dir>/todo-sync/runner.json``."""
    return cfg.path(cfg.state_dir) / "todo-sync" / "runner.json"


def repo_name(cfg: HarnessConfig) -> str:
    """The name part of ``todo.gh.repo`` (``owner/name``), else the name in the ``origin`` remote URL, else
    the main checkout's folder name.

    The remote comes before the folder because every clone shares it, while the folder name is set per
    machine: a tracked page drawn from the folder name would differ between clones in differently named
    folders, and each render on the other machine would rewrite it.
    """
    repo = cfg.todo.gh_repo
    if isinstance(repo, str) and repo.strip("/"):
        return repo.strip("/").rsplit("/", 1)[-1]
    return _origin_name(cfg.project_root) or main_worktree(cfg.project_root).name


def _origin_name(root: Path) -> Optional[str]:
    """The last path part of the ``origin`` remote URL, any ``.git`` dropped; None without a usable one."""
    try:
        done = run_git(["git", "-C", str(root), "remote", "get-url", "origin"])
    except OSError:
        return None
    url = done.stdout.strip().rstrip("/\\") if done.returncode == 0 else ""
    name = re.split(r"[/:\\]", url)[-1]
    return name.removesuffix(".git") or None


def render_record_path(cfg: HarnessConfig) -> Path:
    """Render record location: ``<state_dir>/todo-sync/render.json``, beside the report."""
    return cfg.path(cfg.state_dir) / "todo-sync" / "render.json"


def render_snapshot(cfg: HarnessConfig, date: dt.date) -> Path:
    """Bring the snapshot page ``TODO_Snapshot.html`` in ``todo.snapshots.dir`` and its ``todo_live.js``
    stamp up to date, record the run in ``render_record_path``, and return the page's path.

    A page on disk that rendering again with its own date reproduces is kept, date included, and the stamp
    file is written only when its text differs, so a render that would draw the same page leaves both files
    as they are. Only a change to what the page draws (the TODO catalog, the research catalog or its stub
    files, configuration, or page code), or a hand-edited or missing page, rewrites the page, dated
    ``date``; a missing or differing stamp file is restored on its own, and one written beside a kept page
    carries the kept page's date. The page goes first, so an open page that reads a new stamp reloads into
    the new page.
    """
    todo = cfg.todo
    if not todo.catalog or not todo.snapshots.dir:
        raise TodoSyncError("render needs todo.folder and a non-null todo.snapshots.dir")
    build = _page_builder(cfg)
    folder = cfg.path(todo.snapshots.dir)
    path, live_path = folder / PAGE_NAME, folder / LIVE_NAME
    kept = _kept_page(path, build)
    rendered, text = kept if kept is not None else (date.isoformat(), build(date.isoformat()))
    stamp = page_stamp(text)
    if stamp is None:
        raise TodoSyncError(f"{PAGE_NAME}: rendered page carries no readable stamp; nothing written")
    live = live_script(stamp, rendered)
    wrote: List[str] = []
    if kept is None:
        write_atomic(path, text)
        wrote.append(PAGE_NAME)
    if _read_text(live_path) != live:
        write_atomic(live_path, live)
        wrote.append(LIVE_NAME)
    record = {"schema_version": 1, "run_date": date.isoformat(),
              "page": f"{posix(todo.snapshots.dir)}/{PAGE_NAME}", "page_date": rendered, "stamp": stamp,
              "wrote": wrote, "written_at": _utc_now()}
    write_atomic(render_record_path(cfg), json.dumps(record, indent=2) + "\n")
    return path


def _page_builder(cfg: HarnessConfig) -> Callable[[str], str]:
    """The page text for a render date; the catalog is read and its stub links resolved once."""
    todo = cfg.todo
    catalog = read_json(cfg.project_root, todo.catalog)
    if not catalog.ok:
        raise TodoSyncError(f"{catalog.rel}: {catalog.error}")
    raw = catalog.data.get("items")
    items = [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []
    source, cut, sha = posix(todo.catalog), todo.top_n, rows_sha256(items, todo.top_n)
    ranked = ranked_items(items)
    links = _stub_links(cfg, ranked)
    repo = repo_name(cfg)

    def build(rendered: str) -> str:
        return render_page(SnapshotPage(
            header=snapshot_header(source, cut, sha, rendered), catalog=catalog.data, top=ranked[:cut],
            top_n=cut, rendered=rendered, source=source, links=links[:cut], gh_repo=todo.gh_repo, repo=repo,
            rest=ranked[cut:], rest_links=links[cut:]))
    return build


def _read_text(path: Path) -> Optional[str]:
    """The text at ``path`` read with universal newlines (CRLF and lone CR become LF), so a checkout that
    converted line ends compares equal to the text ``write_atomic`` wrote."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _universal_newlines(text: str) -> str:
    """``text`` with CRLF and lone CR turned into LF, the translation a universal-newline read applies."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _kept_page(path: Path, build: Callable[[str], str]) -> Optional[Tuple[str, str]]:
    """The render date and the built text of the page at ``path`` when ``build`` with that date reproduces
    it under universal-newline translation, else None."""
    old = _read_text(path)
    header = parse_header(old.split("\n", 1)[0]) if old else None
    if header is None:
        return None
    built = build(header.rendered)
    if _universal_newlines(built) != old:
        return None
    return header.rendered, built


def _stub_links(cfg: HarnessConfig, rows: List[Dict[str, Any]]) -> List[List[str]]:
    """Stub link targets per item of ``rows`` (relative to ``todo.snapshots.dir``), from one ``Sources`` so
    the research tree is walked once; an item whose id is not a string gets none."""
    src = Sources(cfg)
    return [[link_target(s, cfg.todo.snapshots.dir) for s in item_stubs(src, item)]
            if isinstance(item.get("id"), str) else [] for item in rows]


def write_runner(cfg: HarnessConfig) -> Path:
    """Write the runner pointer: interpreter, driver script, project and report paths."""
    pointer = {
        "schema_version": 1, "python": sys.executable,
        "script": str(plugin_root() / "scripts" / "todo_sync.py"),
        "project": cfg.project_root.as_posix(), "report": report_path(cfg).as_posix(),
        "written_at": _utc_now(),
    }
    return write_atomic(runner_path(cfg), json.dumps(pointer, indent=2) + "\n")
