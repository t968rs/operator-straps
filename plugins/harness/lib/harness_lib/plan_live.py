"""``live.js``: the receipts and the DesignEvolution of a plan as one script the HTML PIP reloads.

The file is ``window.PLAN_LIVE = <PlanLive JSON>;``. It is derived, so ``write_live`` also keeps the plan
folder's ``.gitignore`` listing it (D9); no project has to add an ignore line. Being ignored, it never moves
with a worktree's work: ``sourced_plans`` names the plans a set of moved paths feeds and ``refresh_live``
rebuilds one the way ``plan.py render`` does, for the a-w attach.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from pydantic import BaseModel, ConfigDict

from harness_lib import evolution_doc as ed
from harness_lib import freeze_ledger as fl
from harness_lib import plan_doc as pd
from harness_lib import plan_receipts as prt
from harness_lib.evolution_models import DesignEvolution
from harness_lib.receipt_models import Receipt

LIVE_NAME = "live.js"
LIVE_HEAD = "window.PLAN_LIVE = "
# Paths under the plans folder that a plan's live.js derives from, or that make a plan a receipts plan.
_SOURCES = tuple(re.compile(pattern) for pattern in (
    rf"^(\d+)/{prt.RECEIPTS_DIR}/[^/]+\.json$",
    rf"^(\d+)/{re.escape(ed.CATALOG_NAME)}$",
    rf"^(\d+)_[^/]*{re.escape(pd.PLAN_SUFFIX)}$",
    rf"^{fl.FREEZES_DIR}/plan/(\d+)-[^/]+/[^/]+$",
))


class PlanLive(BaseModel):
    """The payload of ``live.js``: receipts sorted by item id, the catalog or None, and the UTC build time."""

    model_config = ConfigDict(extra="forbid")

    receipts: List[Receipt]
    evolution: Optional[DesignEvolution]
    built: str


def live_path(plans_dir: Path, plan_id: str) -> Path:
    """``<plans_dir>/<plan_id>/live.js``."""
    return plans_dir / plan_id / LIVE_NAME


def build_live(plans_dir: Path, plan_id: str) -> PlanLive:
    """The current payload: every receipt that loads, sorted by item id, and the catalog."""
    receipts = sorted(prt.load_receipts(plans_dir, plan_id).receipts.values(), key=lambda r: r.item)
    built = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return PlanLive(receipts=receipts, evolution=prt._catalog(plans_dir, plan_id), built=built)


def _ignore_live(folder: Path) -> None:
    """Keep ``folder/.gitignore`` listing ``live.js`` once; its other lines stay as they are."""
    path = folder / ".gitignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if LIVE_NAME in (line.strip() for line in lines):
        return
    path.write_text("\n".join([*lines, LIVE_NAME]) + "\n", encoding="utf-8")


def write_live(plans_dir: Path, plan_id: str) -> Path:
    """Write ``live.js`` for the plan and keep the plan folder ignoring it; the path written."""
    path = live_path(plans_dir, plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_live(plans_dir, plan_id).model_dump(mode="json"), ensure_ascii=False)
    path.write_text(f"{LIVE_HEAD}{payload};\n", encoding="utf-8")
    _ignore_live(path.parent)
    return path


def sourced_plans(paths: Iterable[str], plans_rel: str) -> List[str]:
    """The plan ids, sorted, whose ``live.js`` the repo-relative POSIX ``paths`` feed.

    A path counts when it is a receipt, the DesignEvolution catalog, the plan JSON or a ``plan/`` freeze
    ledger entry under ``plans_rel`` (the project's ``artifacts.plans``).
    """
    prefix = plans_rel.replace("\\", "/").strip("/") + "/"
    found = set()
    for path in paths:
        if not path.startswith(prefix):
            continue
        hit = next((m for m in (rx.match(path[len(prefix):]) for rx in _SOURCES) if m), None)
        if hit is not None:
            found.add(hit.group(1))
    return sorted(found)


def refresh_live(plans_dir: Path, plan_id: str) -> Optional[Path]:
    """Rebuild ``live.js`` when ``plan.py render`` would: a frozen receipts plan whose HTML page exists.

    None, and nothing written, for any other plan and for a plan whose file is gone; a plan file that does
    not load is the ``PlanError`` ``plan_doc.load_plan`` raises.
    """
    if not any(plans_dir.glob(f"{plan_id}_*{pd.PLAN_SUFFIX}")):
        return None
    plan_file = pd.find_plan(plans_dir, plan_id)
    plan = pd.load_plan(plan_file)
    if not prt.uses_receipts(plan) or not pd.pip_html_path(plan_file).is_file():
        return None
    return write_live(plans_dir, plan.plan_id)
