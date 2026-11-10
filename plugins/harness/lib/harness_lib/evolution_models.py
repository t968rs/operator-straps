"""The DesignEvolution models: the one definition of a plan-bound catalog of design changes.

``DesignEvolutionCatalog.schema.json`` is generated from these classes (``schema_text``). Every model is
closed (``extra="forbid"``) and every nested shape is its own class. Rules the generated schema cannot
express live in ``DesignEvolution``'s validator: unique change ids, a ``doc`` key found in
``primary_documents``, a ``plan`` document, and a summary finding that names a change. The tallies the old
schema stored (``by_phase`` and the like) are computed by ``DesignEvolution.counts``, so no ``category_enums``
block exists to drift.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date as _date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_lib.evolution_enums import ChangePhase, IssueCategory, OutcomeCategory

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = ("https://github.com/t968rs/operator-straps/plugins/harness/schemas/catalogs/"
             "DesignEvolutionCatalog.schema.json")
_CLOSED = ConfigDict(extra="forbid", regex_engine="python-re")
_CHANGE_ID = r"^(S|PR|P|EX|CX)[0-9]+$"


def _today() -> str:
    return _date.today().isoformat()


class ChangeOriginal(BaseModel):
    model_config = _CLOSED

    doc: str = Field(description="Key of a document in primary_documents (spec, plan, primer, ...).")
    location: str = Field(description="Section, line or paragraph reference within the document.")
    indicated: str = Field(description="The exact or paraphrased text or intent from the source document.")


class ChangeIssue(BaseModel):
    model_config = _CLOSED

    category: IssueCategory = Field(description="Problem category.")
    why_categorical: str = Field(description="Brief categorical label or reason.")
    why_free_form: str = Field(description="Detailed explanation of the problem.")


class NewOutcome(BaseModel):
    model_config = _CLOSED

    doc: str = Field(description="Key of the document in primary_documents being updated.")
    indicated: str = Field(description="The new or corrected text or direction.")


class WhyNewOutcome(BaseModel):
    model_config = _CLOSED

    category: OutcomeCategory = Field(description="Outcome category.")
    free_form: str = Field(description="Detailed explanation of why the new outcome is better or necessary.")


class DesignChange(BaseModel):
    """One design change, traced from the original intent through the issue found to the new outcome."""

    model_config = _CLOSED

    id: str = Field(pattern=_CHANGE_ID, description=(
        "Change ID: S=spec-review, PR=pr-bot-review, P=plan-review, EX=post-exec-start (self-sweep), "
        "CX=post-exec-start (external review), followed by a sequence number."))
    discovered_by: str = Field(description="Name or role of the reviewer who discovered this change.")
    phase: ChangePhase = Field(description="Lifecycle phase in which this change was discovered.")
    items: List[str] = Field(default_factory=list, description="Ids of the plan items the change touches.")
    original: ChangeOriginal
    issue: ChangeIssue
    new_outcome: NewOutcome
    why_new_outcome: WhyNewOutcome
    date: str = Field(default_factory=_today, description="Day the change was cataloged, `YYYY-MM-DD`.")

    def digest(self) -> str:
        """SHA-256 hex of the canonical JSON of this change (sorted keys, compact separators)."""
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FindingRef(BaseModel):
    model_config = _CLOSED

    id: str = Field(pattern=_CHANGE_ID, description="ID of the change entry; must match a change id.")
    rationale: str = Field(description="Why this change is the finding.")


class EvolutionSummary(BaseModel):
    model_config = _CLOSED

    highest_impact_finding: Optional[FindingRef] = Field(
        default=None, description="The most critical or widely-consequential change.")
    most_embarrassing_finding: Optional[FindingRef] = Field(
        default=None, description="The most obviously wrong or ridiculous mistake found.")
    lessons: List[str] = Field(default_factory=list, description="Key insights from the catalog.")


class IdConventions(BaseModel):
    model_config = _CLOSED

    comment: Optional[str] = Field(default=None, description=(
        "Narrative on the prefix mapping, sparse numbering and any phase-overlap rules."))
    prefixes: Dict[str, str] = Field(default_factory=dict, description=(
        "Per-prefix description of what an ID with that prefix represents."))


class EvolutionCounts(BaseModel):
    """Tallies of a catalog's changes, keyed by the value strings of the enums."""

    model_config = _CLOSED

    by_phase: Dict[str, int]
    by_issue: Dict[str, int]
    by_outcome: Dict[str, int]


def _tally(values: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


class DesignEvolution(BaseModel):
    """A plan-bound catalog of design changes across a feature's lifecycle."""

    model_config = _CLOSED

    plan_id: str = Field(pattern=r"^[0-9]{4}$", description="The 4-digit id of the catalog's plan.")
    feature: str = Field(description="Feature name or title.")
    issue: Optional[int] = Field(default=None, description="GitHub issue number.")
    pr: Optional[int] = Field(default=None, description="GitHub PR number.")
    branch_lineage: str = Field(description="Branch ancestry chain: [base]-->[parent]-->[child].")
    primary_documents: Dict[str, str] = Field(description=(
        "Links to key design documents (spec, plan, primer, research notes); `plan` is always present."))
    id_conventions: Optional[IdConventions] = None
    changes: List[DesignChange] = Field(default_factory=list, description=(
        "Design change entries, each tracing an issue from discovery through resolution."))
    summary: Optional[EvolutionSummary] = None

    @model_validator(mode="after")
    def _consistent(self) -> "DesignEvolution":
        """Unique change ids, a plan document, known doc keys and summary findings that name a change."""
        problems = _duplicate_ids(self) + _document_problems(self) + _finding_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def counts(self) -> EvolutionCounts:
        """Changes per phase, issue category and outcome category, keyed by the enum value strings."""
        return EvolutionCounts(
            by_phase=_tally([str(c.phase) for c in self.changes]),
            by_issue=_tally([str(c.issue.category) for c in self.changes]),
            by_outcome=_tally([str(c.why_new_outcome.category) for c in self.changes]))

    def find(self, change_id: str) -> Optional[DesignChange]:
        """The change with this id, or None."""
        return next((c for c in self.changes if c.id == change_id), None)


def _duplicate_ids(evo: DesignEvolution) -> List[str]:
    seen: Dict[str, int] = _tally([c.id for c in evo.changes])
    return [f"change id {ident} appears {n} times" for ident, n in seen.items() if n > 1]


def _document_problems(evo: DesignEvolution) -> List[str]:
    problems: List[str] = []
    if "plan" not in evo.primary_documents:
        problems.append("primary_documents needs a 'plan' key")
    for change in evo.changes:
        for key in (change.original.doc, change.new_outcome.doc):
            if key not in evo.primary_documents:
                problems.append(f"change {change.id} names document '{key}' outside primary_documents")
    return problems


def _finding_problems(evo: DesignEvolution) -> List[str]:
    if evo.summary is None:
        return []
    refs = (evo.summary.highest_impact_finding, evo.summary.most_embarrassing_finding)
    return [f"summary finding {ref.id} names no change" for ref in refs
            if ref is not None and evo.find(ref.id) is None]


def schema_dict() -> Dict[str, Any]:
    """The draft 2020-12 JSON schema of ``DesignEvolution``, with ``$schema`` and ``$id`` first."""
    body = DesignEvolution.model_json_schema()
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **body}


def schema_text() -> str:
    """``schema_dict`` as the text committed to ``schemas/catalogs/DesignEvolutionCatalog.schema.json``."""
    return json.dumps(schema_dict(), indent=2, ensure_ascii=False) + "\n"
