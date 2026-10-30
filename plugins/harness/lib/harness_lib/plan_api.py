"""Authoring API for ActionPlan files, called from a heredoc: ``load`` a plan, change a copy, ``write`` it.

Both functions are driver entry points: they activate the project named by ``repo`` (default: the working
directory) themselves, since a heredoc has no driver to do it. ``load`` returns the validated ``ActionPlan``;
nested models built in the heredoc validate as they are constructed, and ``model_copy`` does not, so ``write``
validates the dump of the whole plan again before it touches a file.

``write`` saves to the file ``load`` read (a plan loaded from a linked worktree is written there, not into
the active project), and refuses (all problems at once, nothing written) an unknown plan id, a plan that was
not loaded or whose file changed since, a changed ``plan_id``, ``base_commit`` or ``frozen`` (``plan.py
new`` and ``freeze`` own them), an extra key at the plan or item level the file does not already carry (a
misspelled field), a duplicate item id and, on a frozen plan, any change to an execution field (only
``plan.py record`` sets those). Without pydantic 2 the import prints one ``problem:`` line and exits 1.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def _pydantic_missing() -> bool:
    """True when pydantic 2 does not import: the plan models need it."""
    try:
        import pydantic
    except ImportError:
        return True
    return not hasattr(pydantic, "model_validator")


if _pydantic_missing():
    print("problem: pydantic>=2 is not installed; plan_api needs it (pip install 'pydantic>=2')",
          file=sys.stderr)
    sys.exit(1)

from harness_lib import plan_checks as pc  # noqa: E402
from harness_lib import plan_doc as pd  # noqa: E402
from harness_lib import plan_models as pm  # noqa: E402
from harness_lib.config import activate, active, load_config  # noqa: E402
from harness_lib.plan_render import render_pip  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

PlanRef = Union[str, int, Path]
Repo = Optional[Union[str, Path]]
_OWNERS = {"base_commit": "plan.py new", "frozen": "plan.py freeze"}


def _activate(repo: Repo) -> None:
    activate(load_config(project_root(Path(repo) if repo is not None else None)))


def _plan_file(ref: PlanRef) -> Path:
    """The plan file named by ``ref``: an existing ``*_ActionPlan.json`` path (as given or under the
    project root), else a plan id; the same lookup as ``plan.py locate``."""
    text = str(ref)
    for candidate in (Path(text), active().project_root / text):
        if candidate.name.endswith(pd.PLAN_SUFFIX) and candidate.is_file():
            return candidate
    if not text.isdigit():
        raise pd.PlanError([f"{text} is neither a plan file nor a plan id"])
    return pd.find_plan(active().path(active().artifacts.plans), text)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(plan: PlanRef, repo: Repo = None) -> pm.ActionPlan:
    """The plan with id (padded or not) or file ``plan``, validated; ``write`` needs a plan loaded here."""
    _activate(repo)
    path = _plan_file(plan)
    loaded = pd.load_plan(path)
    loaded._loaded_hash = _hash(path)
    loaded._loaded_path = path.resolve()
    return loaded


def _target(plan: pm.ActionPlan) -> Path:
    """The file ``write`` saves: the plan id's file next to the loaded file, else in the active project."""
    loaded = plan._loaded_path
    plans_dir = loaded.parent if loaded is not None else active().path(active().artifacts.plans)
    return pd.find_plan(plans_dir, plan.plan_id).resolve()


# --- refusals ---------------------------------------------------------------------------------------------

def _stale_problems(plan: pm.ActionPlan, path: Path) -> List[str]:
    if plan._loaded_hash is None or plan._loaded_path is None:
        return ["plan was not loaded with plan_api.load; load it, change a copy and write that"]
    if plan._loaded_path != path:
        loaded_id = plan._loaded_path.name.split("_", 1)[0]
        return [f"plan_id differs from the loaded plan {loaded_id}; plan.py new owns it"]
    if plan._loaded_hash == _hash(path):
        return []
    return [f"plan {plan.plan_id} changed on disk since it was loaded; load it again and redo the change"]


def _owned_problems(raw: Dict[str, Any], disk: Dict[str, Any]) -> List[str]:
    return [f"{key} differs from the file on disk; {owner} owns it"
            for key, owner in _OWNERS.items() if raw.get(key) != disk.get(key)]


def _execution_problems(raw: Dict[str, Any], disk: Dict[str, Any]) -> List[str]:
    """On a frozen plan, each execution field that differs from the file: only ``record`` sets them."""
    if disk.get("frozen") is None:
        return []
    tail = "only plan.py record sets it on a frozen plan"
    top = [key for key in pd.MUTABLE_TOP if key != "frozen" and raw.get(key) != disk.get(key)]
    out = [f"plan {key}: {tail}" for key in top]
    kept = {item["id"]: item for item in disk["items"]}
    for item in raw["items"]:
        before = kept.get(item.get("id"))
        changed = [key for key in pd.MUTABLE_ITEM if before is not None and item.get(key) != before.get(key)]
        out += [f"{item['id']} {key}: {tail}" for key in changed]
    return out


def _extra_problems(raw: Dict[str, Any], disk: Dict[str, Any]) -> List[str]:
    """Keys outside the models that the file does not already carry: a misspelled field."""
    out = [f"unknown key {key} on the plan" for key in sorted(set(raw) - set(pm.ActionPlan.model_fields)
                                                              - set(disk))]
    kept = {item["id"]: item for item in disk["items"]}
    for item in raw["items"]:
        known = set(pm.ActionItem.model_fields) | set(kept.get(item.get("id"), {}))
        out += [f"unknown key {key} on item {item.get('id')}" for key in sorted(set(item) - known)]
    return out


# --- write ------------------------------------------------------------------------------------------------

def _problems(plan: pm.ActionPlan, path: Path, raw: Dict[str, Any]) -> List[str]:
    disk = pd.plan_dict(pd.load_plan(path))
    problems = _stale_problems(plan, path) + _owned_problems(raw, disk)
    problems += _execution_problems(raw, disk) + _extra_problems(raw, disk)
    return problems


def write(plan: pm.ActionPlan, repo: Repo = None) -> pm.ActionPlan:
    """Validate ``plan``, save its JSON and PIP and return it re-validated; else refuse with every problem."""
    _activate(repo)
    path = _target(plan)
    raw = pd.plan_dict(plan)
    problems = _problems(plan, path, raw)
    checked: Optional[pm.ActionPlan] = None
    try:
        checked = pd.validate_plan(raw)
    except pd.PlanError as exc:
        problems += exc.problems
    problems += pc.duplicate_problems(checked) if checked is not None else []
    if problems or checked is None:
        raise pd.PlanError(problems)
    pip_text = render_pip(checked, path.name)
    pd.save_plan(path, checked)
    pd.pip_path(path).write_text(pip_text, encoding="utf-8")
    checked._loaded_hash = _hash(path)
    checked._loaded_path = path
    return checked
