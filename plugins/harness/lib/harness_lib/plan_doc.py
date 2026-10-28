"""Plan documents owned by the ``plan.py`` driver: file names, plan ids, schema validation, freeze digest.

A plan is ``<artifacts.plans>/<plan_id>_<Title>_ActionPlan.json`` validated by ``ActionPlan.schema.json``; its
PIP (``<plan_id>_<Title>_PIP.md``) is rendered from it, and the test files it plans live under
``<artifacts.plans>/<plan_id>/tests/<repo-relative path>``. The plan is handled as parsed JSON (plain dicts),
so the schema is the one definition of its shape.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

PLAN_SUFFIX = "_ActionPlan.json"
PIP_SUFFIX = "_PIP.md"
SCHEMA = "ActionPlan.schema.json"
DONE = frozenset({"COMPLETE", "CLOSED_NO_ACTION"})
# Fields that change while the plan executes; everything else is fixed once the plan is frozen.
MUTABLE_TOP = ("completed", "frozen", "markdown_sync_status", "markdown_last_updated")
MUTABLE_ITEM = ("status", "evidence", "verification_references")
_ID_PREFIX = re.compile(r"^(\d{4})_")


class PlanError(Exception):
    """A defect in a plan or a request about one; ``problems`` holds one line per defect."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def title_slug(title: str) -> str:
    """The title as a file-name part: runs of other characters become one underscore."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")
    if not slug:
        raise PlanError([f"title {title!r} has no letters or digits"])
    return slug


def next_plan_id(plans_dir: Path) -> str:
    """One past the highest four-digit prefix among the folder's files, zero-padded."""
    found = [int(m.group(1)) for p in plans_dir.glob("*") if (m := _ID_PREFIX.match(p.name))]
    return f"{max(found, default=0) + 1:04d}"


def plan_path(plans_dir: Path, plan_id: str, slug: str) -> Path:
    return plans_dir / f"{plan_id}_{slug}{PLAN_SUFFIX}"


def pip_path(plan_file: Path) -> Path:
    """The PIP beside a plan file; a problem when the file name lacks the plan suffix."""
    if not plan_file.name.endswith(PLAN_SUFFIX):
        raise PlanError([f"{plan_file.name} does not end with {PLAN_SUFFIX}"])
    return plan_file.with_name(plan_file.name[: -len(PLAN_SUFFIX)] + PIP_SUFFIX)


def planned_tests_dir(plans_dir: Path, plan_id: str) -> Path:
    return plans_dir / plan_id / "tests"


def find_plan(plans_dir: Path, plan_id: str) -> Path:
    """The plan file of ``plan_id`` (padding optional); a problem when none or several match."""
    padded = f"{int(plan_id):04d}" if plan_id.isdigit() else plan_id
    hits = sorted(plans_dir.glob(f"{padded}_*{PLAN_SUFFIX}"))
    if len(hits) != 1:
        found = "no plan" if not hits else f"{len(hits)} plans"
        raise PlanError([f"{found} {padded} in {plans_dir.as_posix()}"])
    return hits[0]


def parse_plan(text: str, name: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PlanError([f"{name} is not JSON: {exc}"]) from exc
    if not isinstance(data, dict):
        raise PlanError([f"{name} does not hold a JSON object"])
    return data


def load_plan(path: Path) -> Dict[str, Any]:
    try:
        return parse_plan(path.read_text(encoding="utf-8"), path.name)
    except OSError as exc:
        raise PlanError([f"cannot read {path.as_posix()}: {exc}"]) from exc


def dump_plan(plan: Mapping[str, Any]) -> str:
    return json.dumps(plan, indent=2, ensure_ascii=False) + "\n"


def save_plan(path: Path, plan: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_plan(plan), encoding="utf-8")


def schema_problems(plan: Mapping[str, Any], cfg: HarnessConfig) -> List[str]:
    """One ``schema: <json path>: <message>`` line per violation of the ActionPlan schema."""
    import jsonschema

    from harness_lib.validation.schema_registry import load_schema, schema_registry

    schema = load_schema(SCHEMA, cfg)
    validator = jsonschema.validators.validator_for(schema)(schema, registry=schema_registry(cfg))
    errors = sorted(validator.iter_errors(plan), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"schema: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}"
            for e in errors]


def frozen_digest(plan: Mapping[str, Any]) -> str:
    """SHA-256 of the plan without MUTABLE_TOP at the top level and MUTABLE_ITEM in each item."""
    fixed = {k: v for k, v in plan.items() if k not in MUTABLE_TOP}
    items = fixed.get("items")
    if isinstance(items, list):
        fixed["items"] = [{k: v for k, v in i.items() if k not in MUTABLE_ITEM} if isinstance(i, dict) else i
                          for i in items]
    canonical = json.dumps(fixed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def items_of(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [i for i in plan.get("items") or [] if isinstance(i, dict)]


def item_by_id(plan: Mapping[str, Any], item_id: str) -> Dict[str, Any]:
    for item in items_of(plan):
        if item.get("id") == item_id:
            return item
    raise PlanError([f"no item {item_id} in plan {plan.get('plan_id')}"])
