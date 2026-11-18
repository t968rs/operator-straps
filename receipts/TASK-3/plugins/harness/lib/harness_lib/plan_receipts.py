"""The receipts of a plan: files under ``<plans>/<id>/receipts/``, the status view and the receipt problems.

No git runs here. A plan frozen with ``records == "receipts"`` keeps its items PENDING in the JSON for good;
each item's outcome lives in a sealed ``Receipt`` file named after the item. ``status_view`` lays the
receipts over a deep copy of the plan (D2: a receipt whose seal is broken still gives its status; ``check``,
``verify`` and the gates refuse that seal). ``receipt_problems`` lists what ``check`` reports, including each
cited DesignChange that is missing, does not name the item or changed after the receipt (D8). ``book_for``
gives each command one record book for the plan's scheme (D10): receipts, or the sealed records in the plan.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_lib import evolution_doc as ed
from harness_lib import plan_record as prc
from harness_lib.evolution_models import DesignEvolution
from harness_lib.plan_doc import PlanError, item_by_id, schema_lines
from harness_lib.plan_enums import ItemStatus, RecordScheme
from harness_lib.plan_models import ActionItem, ActionPlan, Completed
from harness_lib.receipt_models import Deviations, Receipt

RECEIPTS_DIR = "receipts"
_NODE_START = re.compile(r"^[^:=\[\]]+\.py::")


def receipts_dir(plans_dir: Path, plan_id: str) -> Path:
    """``<plans_dir>/<plan_id>/receipts``."""
    return plans_dir / plan_id / RECEIPTS_DIR


def receipt_path(plans_dir: Path, plan_id: str, item_id: str) -> Path:
    """``<plans_dir>/<plan_id>/receipts/<item_id>.json``."""
    return receipts_dir(plans_dir, plan_id) / f"{item_id}.json"


def write_receipt(plans_dir: Path, receipt: Receipt) -> Path:
    """Write ``receipt`` to its item's file, replacing any earlier receipt; the path written."""
    path = receipt_path(plans_dir, receipt.plan_id, receipt.item)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = receipt.model_dump(mode="json", exclude_none=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


class ReceiptSet(BaseModel):
    """The receipts of a plan keyed by item id, and one line per receipt file that could not be used."""

    model_config = ConfigDict(extra="forbid")

    receipts: Dict[str, Receipt] = Field(default_factory=dict)
    problems: List[str] = Field(default_factory=list)


def _read_receipt(path: Path, name: str) -> Tuple[Optional[Receipt], List[str]]:
    """The receipt in ``path``, or None and the lines that say why it cannot be used."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"receipt {name} does not parse: {exc}"]
    if not isinstance(data, dict):
        return None, [f"receipt {name} does not hold a JSON object"]
    try:
        receipt = Receipt.model_validate(data)
    except ValidationError as exc:
        return None, [f"receipt {name} does not validate: {line}" for line in schema_lines(exc)]
    if receipt.item != path.stem:
        return None, [f"receipt {name} is for item {receipt.item}, not {path.stem}"]
    return receipt, []


def load_receipts(plans_dir: Path, plan_id: str) -> ReceiptSet:
    """Every ``*.json`` in the plan's receipts folder, keyed by file stem; none when the folder is absent."""
    folder = receipts_dir(plans_dir, plan_id)
    found = ReceiptSet()
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        receipt, problems = _read_receipt(path, f"{plan_id}/{RECEIPTS_DIR}/{path.name}")
        found.problems.extend(problems)
        if receipt is not None:
            found.receipts[path.stem] = receipt
    return found


def uses_receipts(plan: ActionPlan) -> bool:
    """The plan is frozen with the receipts record scheme."""
    return plan.frozen is not None and plan.frozen.records == RecordScheme.receipts


def status_view(plan: ActionPlan, receipts: ReceiptSet) -> ActionPlan:
    """A deep copy of ``plan`` whose items take status and evidence from their receipts, PENDING without one.

    A receipt whose seal is broken still gives its status (D2). ``plan`` itself is left untouched.
    """
    view = plan.model_copy(deep=True)
    for item in view.items:
        receipt = receipts.receipts.get(item.id)
        if receipt is None:
            item.status = ItemStatus.PENDING
            continue
        item.status = receipt.status
        item.evidence = receipt.evidence
    return view


def _find_item(plan: ActionPlan, item_id: str) -> Optional[ActionItem]:
    return next((item for item in plan.items if item.id == item_id), None)


def receipt_holds(plan: ActionPlan, receipts: ReceiptSet, item_id: str) -> bool:
    """The item has a receipt whose seal matches the receipt and the item's planned files and tests."""
    receipt, item = receipts.receipts.get(item_id), _find_item(plan, item_id)
    return receipt is not None and item is not None and receipt.holds(plan.plan_id, item)


def _citation_problem(evolution: DesignEvolution, item_id: str, change_id: str, digest: str) -> Optional[str]:
    """The problem of one citation against the catalog, or None when the entry exists, names the item and
    still has the digest the receipt bound."""
    change = evolution.find(change_id)
    if change is None:
        return f"{item_id} cites {change_id}, which the DesignEvolution catalog does not have"
    if item_id not in change.items:
        return f"{item_id} cites {change_id}, whose items do not list {item_id}"
    if change.digest() != digest:
        command = prc.record_command(evolution.plan_id, item_id, ItemStatus.COMPLETE, again=True)
        return f"{item_id} cites {change_id}, which changed after its receipt; {command}"
    return None


def citation_problems(evolution: Optional[DesignEvolution], item_id: str,
                      deviations: Deviations) -> List[str]:
    """One line per change id the deviations cite that the catalog does not back, naming the id and item."""
    if evolution is None:
        return [f"{item_id} cites {change_id}, but the plan has no readable DesignEvolution catalog"
                for change_id in deviations.cited]
    lines = (_citation_problem(evolution, item_id, change_id, deviations.change_digests[change_id])
             for change_id in deviations.cited)
    return [line for line in lines if line is not None]


def _seal_line(plan: ActionPlan, receipt: Receipt) -> str:
    command = prc.record_command(plan.plan_id, receipt.item, receipt.status, again=True)
    return (f"{receipt.item} receipt does not match its seal (outcome, evidence, deviations, the item's "
            f"files or tests, or the receipt changed by hand); {command}")


def receipt_problems(plan: ActionPlan, receipts: ReceiptSet,
                     evolution: Optional[DesignEvolution]) -> List[str]:
    """The load problems, then per receipt: no such plan item, a broken seal, and its citation problems."""
    problems = list(receipts.problems)
    for item_id, receipt in receipts.receipts.items():
        item = _find_item(plan, item_id)
        if item is None:
            problems.append(f"receipt {item_id} names no item of plan {plan.plan_id}")
            continue
        if not receipt.holds(plan.plan_id, item):
            problems.append(_seal_line(plan, receipt))
        problems.extend(citation_problems(evolution, item_id, receipt.deviations))
    return problems


def split_substitution(value: str) -> Optional[Tuple[str, str]]:
    """``PLANNED=NODE`` split at the first ``=`` where a test file path begins; None when there is none."""
    for index, char in enumerate(value):
        if char == "=" and _NODE_START.match(value[index + 1:]):
            return value[:index], value[index + 1:]
    return None


class RecordBook(Protocol):
    """The record rules of one plan, read the same way under either record scheme."""

    def holds(self, item_id: str) -> bool: ...

    def status(self, item_id: str) -> ItemStatus: ...

    def nodes(self, item_id: str) -> List[str]: ...

    def problems(self) -> List[str]: ...

    def view(self) -> ActionPlan: ...


class SealedBook:
    """The record book of a plan whose records live in its items (sealed or legacy)."""

    def __init__(self, plan: ActionPlan) -> None:
        self.plan = plan

    def holds(self, item_id: str) -> bool:
        return prc.record_holds(self.plan, item_by_id(self.plan, item_id))

    def status(self, item_id: str) -> ItemStatus:
        return item_by_id(self.plan, item_id).status

    def nodes(self, item_id: str) -> List[str]:
        return prc.recorded_nodes(item_by_id(self.plan, item_id))

    def problems(self) -> List[str]:
        return prc.record_lines(self.plan)

    def view(self) -> ActionPlan:
        return self.plan


class ReceiptBook:
    """The record book of a receipts plan; the receipts and the catalog are loaded once."""

    def __init__(self, plan: ActionPlan, receipts: ReceiptSet, evolution: Optional[DesignEvolution]) -> None:
        self.plan, self.receipts, self.evolution = plan, receipts, evolution

    def holds(self, item_id: str) -> bool:
        return receipt_holds(self.plan, self.receipts, item_id)

    def status(self, item_id: str) -> ItemStatus:
        receipt = self.receipts.receipts.get(item_id)
        return ItemStatus.PENDING if receipt is None else receipt.status

    def nodes(self, item_id: str) -> List[str]:
        """The nodes a COMPLETE receipt passed; none without one."""
        receipt = self.receipts.receipts.get(item_id)
        outcome = receipt.outcome if receipt is not None else None
        tests = outcome.tests if isinstance(outcome, Completed) else None
        return list(tests.nodes) if tests is not None else []

    def problems(self) -> List[str]:
        return receipt_problems(self.plan, self.receipts, self.evolution)

    def view(self) -> ActionPlan:
        return status_view(self.plan, self.receipts)


def _catalog(plans_dir: Path, plan_id: str) -> Optional[DesignEvolution]:
    """The plan's catalog; None when absent or invalid (``check`` reports an invalid catalog itself)."""
    try:
        return ed.load_evolution(ed.catalog_path(plans_dir, plan_id))
    except PlanError:
        return None


def book_for(plans_dir: Path, plan: ActionPlan) -> RecordBook:
    """A ``ReceiptBook`` on a receipts plan, a ``SealedBook`` over the plan's own records otherwise."""
    if not uses_receipts(plan):
        return SealedBook(plan)
    receipts = load_receipts(plans_dir, plan.plan_id)
    return ReceiptBook(plan, receipts, _catalog(plans_dir, plan.plan_id))
