"""A consuming project in sync with every todo_sync rule, for tests to mutate one input at a time.

``todo_files()`` returns the project files (repo-relative path -> text or JSON-able data); a test edits
the dict, then ``build(make_project, files)`` writes the project and returns its config. The TODO catalog
is the shared ``TodoCatalog.min.json`` fixture.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from conftest import FIXTURES
from harness_lib.config import HarnessConfig, load_config

CATALOG_REL = "docs/RESEARCH/TODO/TodoCatalog.json"
SNAP_DIR = "docs/RESEARCH/TODO"
SNAP_REL = f"{SNAP_DIR}/TODO_Snapshot_2026_1019.md"
RESEARCH_REL = "docs/RESEARCH/ResearchCatalog.json"
STUB_REL = "docs/RESEARCH/Alpha/_IMPL_TODO.md"
PLAN_REL = "docs/PLANS/0001_Sample_ActionPlan.json"
PIP_REL = "docs/PLANS/0001_Sample_PIP.md"
MIN_CATALOG = json.loads((FIXTURES / "todo_sync" / "TodoCatalog.min.json").read_text(encoding="utf-8"))

TODO_BLOCK = {
    "catalog": CATALOG_REL,
    "snapshots": {"dir": SNAP_DIR},
    "research": {"catalog": RESEARCH_REL, "stub_name": "_IMPL_TODO.md"},
}

RESEARCH = {"entries": [
    {"id": "alpha-loader", "status": "PARTIALLY_IMPLEMENTED", "loe": "M (1-3 days)", "stub_path": STUB_REL,
     "research_folder": "docs/RESEARCH/Alpha", "issues": ["102"]},
    {"id": "beta-cache", "status": "FULLY_IMPLEMENTED", "loe": "S", "stub_path": None,
     "research_folder": "docs/RESEARCH/Beta", "issues": []},
]}


def stub_text(entry_id: str = "alpha-loader", status: str = "PARTIALLY_IMPLEMENTED",
              loe: str = "M (1-3 days)") -> str:
    """A stub header naming ``entry_id`` with the given status and loe."""
    return ("# TODO_IMPL_STUB\n\n<!-- grep_anchor: TODO_IMPL_STUB -->\n\ntopic: Alpha loader\n"
            f"status: {status}\nloe: {loe}\ncatalog_entry: {RESEARCH_REL}#{entry_id}\n\n"
            "## What needs to be done\n")


PLAN = {
    "plan_id": "0001", "documentation": PIP_REL, "markdown_sync_status": "in_sync",
    "items": [
        {"id": "SMP-1", "status": "COMPLETE", "evidence": "Commit abc1234 landed it.",
         "markdown_section": "SMP-1"},
        {"id": "SMP-2", "status": "PENDING", "evidence": None, "markdown_section": "#smp-2"},
        {"id": "SMP-3", "status": "BLOCKED", "evidence": None, "markdown_section": None},
    ],
}

PIP = """# 0001 Sample

## SMP-1: first

- [x] done
- [x] verified

## SMP-2: second

- [ ] open
"""


def snapshot_text(catalog: Dict[str, Any], top_n: int = 10) -> str:
    """A snapshot whose header matches ``catalog``'s top rows."""
    from harness_lib.todo_sync.sources import rows_sha256
    sha = rows_sha256(catalog["items"], top_n)
    return (f"<!-- todo-snapshot source={CATALOG_REL} top={top_n} rows_sha256={sha} "
            "rendered=2026-10-19 -->\n\n# TODO Snapshot\n")


def todo_files() -> Dict[str, Any]:
    """Every file of the in-sync project, deep-copied so tests can mutate freely."""
    catalog = copy.deepcopy(MIN_CATALOG)
    return {
        CATALOG_REL: catalog,
        SNAP_REL: snapshot_text(catalog),
        RESEARCH_REL: copy.deepcopy(RESEARCH),
        STUB_REL: stub_text(),
        "docs/RESEARCH/Beta/notes.md": "beta\n",
        PLAN_REL: copy.deepcopy(PLAN),
        PIP_REL: PIP,
    }


def config(todo: Optional[Dict[str, Any]] = None, **extra: Any) -> Dict[str, Any]:
    """A harness.json body with the test ``todo`` block (or ``todo``) plus ``extra`` top-level keys."""
    return {"todo": copy.deepcopy(TODO_BLOCK if todo is None else todo), **extra}


def build(make_project, files: Optional[Dict[str, Any]] = None,
          cfg: Optional[Dict[str, Any]] = None) -> HarnessConfig:
    """Write the project and return its loaded configuration."""
    body = config() if cfg is None else cfg
    root = make_project(body, files=todo_files() if files is None else files)
    return load_config(root)


def rule_findings(cfg: HarnessConfig, rule: str) -> List[Any]:
    """Findings of one rule id, run alone."""
    from harness_lib.todo_sync import check
    report = check(cfg, rules=[rule])
    assert rule in report.rules_run, report.rules_skipped
    return [f for f in report.findings if f.rule == rule]
