"""Receipts: one sealed record per plan item, kept outside the frozen plan.

A receipt carries the outcome of an item, the evidence that outcome writes and the deviations from the plan
(an extra file, a substituted test node), each citing a DesignChange id. The seal covers every receipt field
but itself plus the item's planned files and tests as frozen, so a hand edit, a receipt copied to another
item or plan, or a refreeze that moves the item's files or tests breaks it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from harness_lib.evolution_models import _CHANGE_ID
from harness_lib.plan_enums import ItemStatus
from harness_lib.plan_models import _CLOSED, _DATE, _SHA64, SCHEMA_DIALECT, ActionItem, NonEmpty, Outcome

SCHEMA_ID = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/Receipt.schema.json"
_NODE_PATTERN = r"^[^:]+\.py(::[^:]+)+$"
ChangeId = Annotated[str, Field(pattern=_CHANGE_ID)]


class ExtraFile(BaseModel):
    """A file the item changed that its plan did not list."""

    model_config = _CLOSED

    path: NonEmpty
    change: ChangeId = Field(description="Id of the DesignChange that allows the file.")


class TestSubstitution(BaseModel):
    """A planned test node replaced by another node that proves the item."""

    __test__: ClassVar[bool] = False
    model_config = _CLOSED

    planned: str = Field(pattern=_NODE_PATTERN)
    node: str = Field(pattern=_NODE_PATTERN)
    change: ChangeId = Field(description="Id of the DesignChange that allows the substitution.")


class Deviations(BaseModel):
    """How the work departed from the plan; every cited change id carries the digest of that change."""

    model_config = _CLOSED

    extra_files: List[ExtraFile] = Field(default_factory=list)
    substitutions: List[TestSubstitution] = Field(default_factory=list)
    change_digests: Dict[ChangeId, Annotated[str, Field(pattern=_SHA64)]] = Field(
        default_factory=dict, description="Change id -> digest of that DesignChange, for each id cited.",
        json_schema_extra={"additionalProperties": False})

    @property
    def cited(self) -> List[str]:
        """The change ids the deviations cite, each once, in first-seen order."""
        ids = [entry.change for entry in (*self.extra_files, *self.substitutions)]
        return list(dict.fromkeys(ids))

    @model_validator(mode="after")
    def _digests_match_citations(self) -> "Deviations":
        """The keys of ``change_digests`` are exactly the cited change ids."""
        cited, held = set(self.cited), set(self.change_digests)
        if cited - held:
            raise ValueError(f"no change digest for cited change(s) {sorted(cited - held)}")
        if held - cited:
            raise ValueError(f"change digest for uncited change(s) {sorted(held - cited)}")
        return self


class Receipt(BaseModel):
    """The sealed outcome of one plan item."""

    model_config = _CLOSED

    plan_id: str = Field(pattern=r"^[0-9]{4}$")
    item: str = Field(pattern=r"^[A-Z]{2,4}-[0-9.]+$")
    outcome: Outcome
    evidence: str
    deviations: Deviations = Field(default_factory=Deviations)
    ref: Optional[str] = None
    date: str = Field(json_schema_extra=_DATE)
    seal: str = Field(pattern=_SHA64, description="SHA-256 of this receipt without its seal, plus the item's "
                      "planned files and tests.")

    @classmethod
    def sealed(cls, plan_id: str, item: ActionItem, *, outcome: Outcome, date: str,
               deviations: Optional[Deviations] = None, ref: Optional[str] = None) -> "Receipt":
        """A receipt of ``outcome`` for ``item`` in plan ``plan_id``, sealed over the item as it stands."""
        fields: Dict[str, Any] = {"plan_id": plan_id, "item": item.id, "outcome": outcome,
                                  "evidence": outcome.evidence(date), "date": date, "ref": ref,
                                  "deviations": deviations if deviations is not None else Deviations()}
        seal = _digest(cls.model_construct(**fields, seal=""), plan_id, item)
        return cls(**fields, seal=seal)

    def holds(self, plan_id: str, item: ActionItem) -> bool:
        """The receipt names this plan and item, and the seal matches it and the item's files and tests."""
        if self.plan_id != plan_id or self.item != item.id:
            return False
        return _digest(self, plan_id, item) == self.seal

    @property
    def status(self) -> ItemStatus:
        """The item status the outcome implies."""
        return self.outcome.status

    def nodes(self, item: ActionItem) -> List[str]:
        """The item's planned test nodes in plan order, each replaced by its substitute when one exists."""
        return substituted_nodes(item, self.deviations)


def substituted_nodes(item: ActionItem, deviations: Deviations) -> List[str]:
    """The item's planned test nodes in plan order, each replaced by its substitute when one exists."""
    swaps = {sub.planned: sub.node for sub in deviations.substitutions}
    return [swaps.get(test.node, test.node) for test in item.tests]


def _digest(receipt: Receipt, plan_id: str, item: ActionItem) -> str:
    """SHA-256 hex of the canonical JSON of the receipt without its seal, bound to ``plan_id`` and ``item``."""
    body = receipt.model_dump(mode="json", exclude_defaults=True, exclude={"seal"})
    body.update(plan_id=plan_id, item=item.id)
    payload = {"receipt": body, "files": list(item.files),
               "tests": [test.model_dump(mode="json") for test in item.tests]}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_dict() -> Dict[str, Any]:
    """The draft 2020-12 JSON schema of ``Receipt``, with ``$schema`` and ``$id`` first."""
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **Receipt.model_json_schema()}


def schema_text() -> str:
    """``schema_dict`` as the text committed to ``schemas/Receipt.schema.json``."""
    return json.dumps(schema_dict(), indent=2, ensure_ascii=False) + "\n"
