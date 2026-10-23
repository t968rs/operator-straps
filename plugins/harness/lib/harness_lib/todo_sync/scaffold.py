"""The starter TODO catalog ``todo_sync.py init`` writes: an empty, schema-valid ``RepoToDo.json`` and the first
snapshot, so a project that has just set ``todo.folder`` has something every sync rule can read.

``init_catalog`` never overwrites an existing catalog. The ranking tables are the defaults a new catalog starts
from; a project edits them in the catalog and ``todo_sync.py refresh`` rescores every item.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError, render_snapshot
from harness_lib.todo_sync.report import write_atomic
from harness_lib.todo_sync.sources import posix

LOE_SIZES = ("XS", "S", "M", "L", "XL")
STARTER_RANKING: Dict[str, Any] = {
    "value": "severity * impact_weight",
    "cost": "loe_points * blast_factor",
    "score": "value / sqrt(cost), multiplied by (1 + unblock_bonus) when the item unblocks at least one item",
    "impact_weights": {"silent_wrong_output": 1.5, "data_correctness": 1.4, "runtime_failure": 1.3,
                       "dev_velocity": 1.0, "maintainability": 0.8, "docs_tooling": 0.6},
    "loe_points": {"XS": 1, "S": 2, "M": 4, "L": 8, "XL": 16},
    "blast_factors": {"S": 1.0, "M": 1.2, "L": 1.5, "XL": 2.0},
    "unblock_bonus": 0.15,
    "tie_breakers": [
        "higher severity",
        "lower LoE points",
        "primary source type, where the primary source is sources[0]: gh_issue, then impl_stub, then "
        "research_folder",
        "primary source ref: issue number ascending for gh_issue, otherwise the ref path in code-point order",
        "primary source item text in code-point order (absent item sorts first)",
        "title in code-point order"],
    "impact_definitions": {
        "silent_wrong_output": "A shipped path completes without error or warning and publishes a value or "
                               "feature that is wrong under an established rule.",
        "data_correctness": "Output or reference data can be wrong or ungoverned, but the correct value still "
                            "needs a rule or decision to define it, a guard is missing, or the wrong value "
                            "already surfaces with a warning or error.",
        "runtime_failure": "A path raises or aborts on an input it accepts.",
        "dev_velocity": "Tests, CI or developer tooling are slower, noisier or less trustworthy than they "
                        "need to be; no output changes.",
        "maintainability": "Structure, duplication, dead code, missing tests or latent defects that no "
                           "current production path reaches; no output changes.",
        "docs_tooling": "Documentation, research records, configuration or agent tooling outside the "
                        "shipped paths."},
    "severity_scale": {
        "1": "Cosmetic or hygiene: renames, dead code, stale docs, a test gap for working or accepted "
             "behavior.",
        "2": "Debt with a concrete cost, a latent defect that no current path reaches, a missing guard, or a "
             "defect that needs a rare or optional input.",
        "3": "A wrong or failing result on a supported but uncommon input, or a defect a warning already "
             "surfaces.",
        "4": "Wrong published output on a common input of a production path, or a failure that blocks a "
             "supported workflow.",
        "5": "Crashes or corrupts a production path on its normal inputs."},
    "notes": "Each item's severity, impact, LoE and blast radius come from its source's triage. Ranking "
             "compares scores rounded to 4 decimals; the tie breakers apply in order, so ids and ranks are "
             "reproducible from the item fields alone.",
}
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class InitResult:
    """The files ``init_catalog`` wrote; ``snapshot`` is None when ``todo.snapshots.dir`` is null."""

    catalog: Path
    snapshot: Optional[Path]


def starter_catalog(head_sha: str, today: dt.date) -> Dict[str, Any]:
    """An empty catalog dated ``today`` and verified against ``head_sha``."""
    return {
        "generated": today.isoformat(),
        "generated_from": {"description": "Empty catalog written by todo_sync.py init.", "head_sha": head_sha},
        "ranking_method": copy.deepcopy(STARTER_RANKING),
        "counts": {"items": 0, "needs_decision": 0, "trackers": 0, "close_candidates": 0, "by_status": {},
                   "by_impact": {}, "by_loe": {size: 0 for size in LOE_SIZES},
                   "sources_absorbed": {"gh_issue": 0, "impl_stub": 0, "research_folder": 0},
                   "merged_items": 0},
        "items": [], "trackers": [], "close_candidates": [],
    }


def _head_sha(root: Path) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError:
        done = None
    sha = done.stdout.strip() if done is not None and done.returncode == 0 else ""
    if not _SHA.match(sha):
        raise TodoSyncError("init records the current commit in generated_from.head_sha; make a git commit "
                            "first")
    return sha


def init_catalog(cfg: HarnessConfig, today: Optional[dt.date] = None) -> InitResult:
    """Write the starter catalog and, when ``todo.snapshots.dir`` is set, the first snapshot."""
    if not cfg.todo.enabled or not cfg.todo.catalog:
        raise TodoSyncError("init needs todo.folder")
    path = cfg.path(cfg.todo.catalog)
    if path.exists():
        raise TodoSyncError(f"{posix(cfg.todo.catalog)} already exists; init never overwrites a catalog")
    day = today or dt.date.today()
    catalog = starter_catalog(_head_sha(cfg.project_root), day)
    write_atomic(path, json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    snapshot = render_snapshot(cfg, day) if cfg.todo.snapshots.dir else None
    return InitResult(path, snapshot)
