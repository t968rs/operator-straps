"""``live.js``: the receipts and the DesignEvolution of a plan as one script the HTML PIP reloads.

The file is ``window.PLAN_LIVE = <PlanLive JSON>;``. It is derived, so ``write_live`` also keeps the plan
folder's ``.gitignore`` listing it (D9); no project has to add an ignore line.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from harness_lib import evolution_doc as ed
from harness_lib import plan_receipts as prt
from harness_lib.evolution_models import DesignEvolution
from harness_lib.plan_doc import PlanError
from harness_lib.receipt_models import Receipt

LIVE_NAME = "live.js"
LIVE_HEAD = "window.PLAN_LIVE = "


class PlanLive(BaseModel):
    """The payload of ``live.js``: receipts sorted by item id, the catalog or None, and the UTC build time."""

    model_config = ConfigDict(extra="forbid")

    receipts: List[Receipt]
    evolution: Optional[DesignEvolution]
    built: str


def live_path(plans_dir: Path, plan_id: str) -> Path:
    """``<plans_dir>/<plan_id>/live.js``."""
    return plans_dir / plan_id / LIVE_NAME


def _catalog(plans_dir: Path, plan_id: str) -> Optional[DesignEvolution]:
    """The plan's catalog; None when absent or invalid, so a hand-broken catalog never blocks the page."""
    try:
        return ed.load_evolution(ed.catalog_path(plans_dir, plan_id))
    except PlanError:
        return None


def build_live(plans_dir: Path, plan_id: str) -> PlanLive:
    """The current payload: every receipt that loads, sorted by item id, and the catalog."""
    receipts = sorted(prt.load_receipts(plans_dir, plan_id).receipts.values(), key=lambda r: r.item)
    built = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return PlanLive(receipts=receipts, evolution=_catalog(plans_dir, plan_id), built=built)


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
