"""Plan documents owned by the ``plan.py`` driver: file names, plan ids, loading, dumping, freeze digest.

A plan is ``<artifacts.plans>/<plan_id>_<Title>_ActionPlan.json`` holding an ``ActionPlan``
(``harness_lib.plan_models``, the one definition of its shape); its PIP (``<plan_id>_<Title>_PIP.md``) is
rendered from it, and the test files it plans live under ``<artifacts.plans>/<plan_id>/tests/<repo-relative
path>``. Loading validates through the models and reports defects as ``schema: <json path>: <message>`` lines.
Dumping writes a field when it was set or differs from its default, so a plan file keeps its keys and the
freeze digest of a plan on disk survives a load and a dump.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

from pydantic import BaseModel, ValidationError

from harness_lib import plan_models as pm

PLAN_SUFFIX = "_ActionPlan.json"
PIP_SUFFIX = "_PIP.md"
# Fields that change while the plan executes; everything else is fixed once the plan is frozen.
MUTABLE_TOP = pm.mutable_top()
MUTABLE_ITEM = pm.mutable_item()
_ID_PREFIX = re.compile(r"^(\d{4})_")
_MESSAGE_LIMIT = 200


class PlanError(Exception):
    """A defect in a plan or a request about one; ``problems`` holds one line per defect."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("\n".join(problems))
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


# --- validation -------------------------------------------------------------------------------------------

def schema_lines(exc: ValidationError) -> List[str]:
    """One ``schema: <json path>: <message>`` line per failing path; messages of one path are joined."""
    by_path: Dict[str, List[str]] = {}
    for error in sorted(exc.errors(), key=lambda e: [str(p) for p in e["loc"]]):
        path = "/".join(str(part) for part in error["loc"]) or "<root>"
        messages = by_path.setdefault(path, [])
        if error["msg"] not in messages:
            messages.append(error["msg"])
    return [f"schema: {path}: {'; '.join(messages)[:_MESSAGE_LIMIT]}" for path, messages in by_path.items()]


def validate_plan(raw: Mapping[str, Any]) -> pm.ActionPlan:
    """The plan a raw dict holds; a ``PlanError`` of ``schema:`` lines when it is not a valid plan."""
    try:
        return pm.ActionPlan.model_validate(dict(raw))
    except ValidationError as exc:
        raise PlanError(schema_lines(exc)) from exc


def schema_problems(raw: Mapping[str, Any]) -> List[str]:
    """The ``schema:`` lines of a raw plan dict; empty when it is a valid plan."""
    try:
        validate_plan(raw)
    except PlanError as exc:
        return exc.problems
    return []


def parse_plan(text: str, name: str) -> pm.ActionPlan:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PlanError([f"{name} is not JSON: {exc}"]) from exc
    if not isinstance(data, dict):
        raise PlanError([f"{name} does not hold a JSON object"])
    return validate_plan(data)


def load_plan(path: Path) -> pm.ActionPlan:
    try:
        return parse_plan(path.read_text(encoding="utf-8"), path.name)
    except OSError as exc:
        raise PlanError([f"cannot read {path.as_posix()}: {exc}"]) from exc


# --- dumping ----------------------------------------------------------------------------------------------

def _mark_changed(node: Any) -> None:
    """Mark every field that holds a value other than its default as set, in the whole tree."""
    if isinstance(node, BaseModel):
        for name, field in type(node).model_fields.items():
            value = getattr(node, name)
            if name not in node.model_fields_set and value != field.get_default(call_default_factory=True):
                node.model_fields_set.add(name)
            _mark_changed(value)
    elif isinstance(node, list):
        for member in node:
            _mark_changed(member)
    elif isinstance(node, dict):
        for member in node.values():
            _mark_changed(member)


def plan_dict(plan: pm.ActionPlan) -> Dict[str, Any]:
    """The JSON form of a plan: a field is written when it was set or differs from its default."""
    copy = plan.model_copy(deep=True)
    _mark_changed(copy)
    return copy.model_dump(mode="json", exclude_unset=True, warnings=False)


def dump_plan(plan: pm.ActionPlan) -> str:
    return json.dumps(plan_dict(plan), indent=2, ensure_ascii=False) + "\n"


def save_plan(path: Path, plan: pm.ActionPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_plan(plan), encoding="utf-8")


def frozen_digest(plan: pm.ActionPlan) -> str:
    """SHA-256 of the plan without MUTABLE_TOP at the top level and MUTABLE_ITEM in each item."""
    fixed = {k: v for k, v in plan_dict(plan).items() if k not in MUTABLE_TOP}
    fixed["items"] = [{k: v for k, v in item.items() if k not in MUTABLE_ITEM} for item in fixed["items"]]
    canonical = json.dumps(fixed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- items ------------------------------------------------------------------------------------------------

def item_by_id(plan: pm.ActionPlan, item_id: str) -> pm.ActionItem:
    for item in plan.items:
        if item.id == item_id:
            return item
    raise PlanError([f"no item {item_id} in plan {plan.plan_id}"])
