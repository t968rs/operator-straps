"""The ActionPlan models: the one definition of a plan's shape.

``ActionPlan.schema.json`` is generated from these classes (``schema_text``) and never edited by hand. The
models accept and reject the same plan documents as the hand-written draft-07 schema they replace, which is
why several choices look odd:

* a field the old schema required has no default; one it allowed to be absent but not null is a plain typed
  field with a default that is not ``None``; one it allowed to be null is ``Optional``;
* dates stay ``str`` (the old ``format: date`` was annotation only), ``pr`` is a strict int or str (an
  integral float such as ``1.0`` passes unchanged, as the JSON ``integer`` type allows), and patterns use the
  ``re`` engine, as ``jsonschema`` does;
* an object the old schema left open uses ``extra="allow"`` and one it closed uses ``extra="forbid"``;
  no model uses pydantic's default ``extra="ignore"``, which would drop a key and move the freeze digest.

A field marked ``Mutable`` is an execution field: ``plan.py record`` changes it after the freeze, so the
freeze digest leaves it out (``mutable_top`` and ``mutable_item``).

Two record rules live only in the models, since the generated schema cannot express them: a provenance's
commit agrees with its source (checked when ``plan.py`` loads the plan), and an item's status agrees with its
record's outcome (checked by ``plan.py check``). A plan breaking either one passes ``jsonschema`` alone.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, ClassVar, Dict, List, Literal, Optional, Tuple, Union

from pydantic import (BaseModel, ConfigDict, Field, PrivateAttr, StrictInt, StrictStr,
                      ValidatorFunctionWrapHandler, WrapValidator, model_validator)

from harness_lib.plan_enums import (ItemStatus, MarkdownSync, ModelName, OutcomeKind, Priority, RecordScheme,
                                    RecordSource, RedException)

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/ActionPlan.schema.json"
_OPEN = ConfigDict(extra="allow", regex_engine="python-re")
_CLOSED = ConfigDict(extra="forbid", regex_engine="python-re")
_DATE = {"format": "date"}
_SHA40 = r"^[0-9a-f]{40}$"
_SHA64 = r"^[0-9a-f]{64}$"


class Mutable:
    """Marker metadata: the field changes while a frozen plan executes."""


def _int_or_str(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    """One error, at ``pr`` itself, for anything but an int or a string (a union reports one per branch).

    A float with no fraction (``1.0``) passes unchanged, as the JSON schema ``integer`` type accepts it;
    keeping the float keeps the freeze digest of the file it came from.
    """
    if isinstance(value, float) and value.is_integer():
        return value
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("must be an integer or a string")
    return handler(value)


NonEmpty = Annotated[str, Field(min_length=1)]
PrNumber = Annotated[Union[StrictInt, StrictStr], WrapValidator(_int_or_str)]


class Anchor(BaseModel):
    model_config = _CLOSED

    at: str = Field(pattern=r"^[^:]+:[0-9]+(-[0-9]+)?$",
                    description="Repo-relative path and 1-based line or range: `src/x.py:12-18`.")
    expect: NonEmpty = Field(description="Text the range must contain; whitespace runs compare as one space.")


class Command(BaseModel):
    model_config = _CLOSED

    run: NonEmpty
    expect: NonEmpty = Field(description="The output that means the command passed.")
    writes: List[str] = Field(default_factory=list, description="Files a generation command writes, default "
                              "outputs and working-directory side effects included.")


class PlannedTest(BaseModel):
    model_config = _CLOSED

    node: str = Field(pattern=r"^[^:]+\.py(::[^:]+)+$")
    red: RedException = Field(description="The exception that fails the test before the item is implemented.")


class DecisionOption(BaseModel):
    model_config = _CLOSED

    id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    summary: NonEmpty


class Decision(BaseModel):
    model_config = _CLOSED

    id: str = Field(pattern=r"^D[0-9]+$")
    question: NonEmpty
    options: List[DecisionOption] = Field(min_length=2)
    chosen: Optional[str]
    rationale: Optional[str] = None


class Value(BaseModel):
    model_config = _CLOSED

    name: NonEmpty
    value: NonEmpty
    source: NonEmpty = Field(description="Where the value comes from: a spec section or a `path:line`.")
    assumes: List[str] = Field(default_factory=list, description="Option ids the value depends on.")


class PlanFormat(BaseModel):
    model_config = _CLOSED

    name: NonEmpty
    example: NonEmpty
    source: Anchor


class Sweep(BaseModel):
    model_config = _CLOSED

    id: str = Field(pattern=r"^S[0-9]+$")
    pattern: NonEmpty = Field(description="Extended regular expression run with `git grep -E` over tracked "
                              "and untracked files.")
    hits: Dict[str, NonEmpty] = Field(description="Repo-relative file -> classification.")


class DeferredTopic(BaseModel):
    model_config = _OPEN

    topic: str
    rationale: str
    affected_sites: List[str] = Field(default_factory=list)


class Context(BaseModel):
    model_config = _OPEN

    project: str = ""
    owner: str = ""
    deadline: Optional[str] = Field(default=None, json_schema_extra=_DATE)
    tags: List[str] = Field(default_factory=list)


class Frozen(BaseModel):
    model_config = _OPEN

    commit: str = Field(pattern=_SHA40)
    tree: str = Field(pattern=_SHA40)
    date: str = Field(json_schema_extra=_DATE)
    digest: str = Field(pattern=_SHA64)
    records: Optional[RecordScheme] = None

    @classmethod
    def at(cls, commit: str, tree: str, date: str, digest: str, records: Optional[RecordScheme]) -> "Frozen":
        """A freeze record; ``records`` is set only when given, so the dump writes no null key."""
        scheme: Dict[str, Any] = {} if records is None else {"records": records}
        return cls(commit=commit, tree=tree, date=date, digest=digest, **scheme)


class PrAttributes(BaseModel):
    """One PR associated with a plan; `pr` is an int, or a string for drafts without a number yet."""

    model_config = _OPEN

    pr: PrNumber
    review_doc: Optional[str] = Field(default=None, pattern=r"^docs/PR_REVIEWS/.+\.json$")
    branch: str
    base_branch: str
    pip_document: Optional[str] = Field(default=None, pattern=r"^docs/PLANS/.+_PIP\.md$")
    merged_at: Optional[str] = Field(default=None, json_schema_extra=_DATE)


class Provenance(BaseModel):
    """Where the recorded code came from: always a tree, a commit only when one existed.

    A commit source needs its commit and a staged source carries none; plan.py enforces that rule when it
    loads the plan, the JSON schema does not.
    """

    model_config = _CLOSED

    source: RecordSource
    tree: str = Field(pattern=_SHA40, description="The tree the tests ran on.")
    commit: Optional[str] = Field(default=None, pattern=_SHA40)

    @model_validator(mode="after")
    def _commit_matches_source(self) -> "Provenance":
        """A commit source names its commit; a staged source names none."""
        if self.source == RecordSource.commit and self.commit is None:
            raise ValueError("a commit provenance needs its commit")
        if self.source == RecordSource.staged and self.commit is not None:
            raise ValueError("a staged provenance carries no commit")
        return self

    @property
    def label(self) -> str:
        """``commit <c7>`` for a commit source, ``staged tree <t7>`` for a staged one."""
        if self.source == RecordSource.commit:
            return f"commit {(self.commit or '')[:7]}"
        return f"staged tree {self.tree[:7]}"

    @property
    def where(self) -> str:
        """How a message names the code: ``<c7>`` for a commit, ``the index (tree <t7>)`` for the index."""
        if self.source == RecordSource.commit:
            return (self.commit or "")[:7]
        return f"the index (tree {self.tree[:7]})"


class PassedTests(BaseModel):
    """The planned nodes that passed on a throwaway worktree at the provenance tree."""

    model_config = _CLOSED

    nodes: List[NonEmpty] = Field(min_length=1)
    command: NonEmpty = Field(description="The pytest command line as run.")

    @classmethod
    def of(cls, nodes: List[str], argv: List[str]) -> "PassedTests":
        """The passed ``nodes`` and the command that ran them (``python``, then ``argv`` past argv[0])."""
        return cls(nodes=list(nodes), command=" ".join(["python", *argv[1:]]))

    @property
    def summary(self) -> str:
        """``: <n> test node(s) passed``, the suffix of a COMPLETE item's evidence."""
        return f": {len(self.nodes)} test node(s) passed"


class _Outcome(BaseModel):
    """Shared shape of an outcome: closed, the status it implies, and the evidence it writes."""

    model_config = _CLOSED
    status: ClassVar[ItemStatus]

    def evidence(self, date: str) -> str:
        """The item evidence this outcome writes when recorded on ``date``."""
        raise NotImplementedError


class Completed(_Outcome):
    """The item is done: its code and, when it plans tests, the nodes that passed on it."""

    status: ClassVar[ItemStatus] = ItemStatus.COMPLETE

    kind: Literal[OutcomeKind.complete]
    provenance: Provenance
    tests: Optional[PassedTests] = None

    @classmethod
    def of(cls, provenance: Provenance, tests: Optional[PassedTests]) -> "Completed":
        """A completed outcome; ``tests`` is set only when given, so the dump writes no null key."""
        passed: Dict[str, Any] = {} if tests is None else {"tests": tests}
        return cls(kind=OutcomeKind.complete, provenance=provenance, **passed)

    def evidence(self, date: str) -> str:
        """The provenance label, then the passed node count when tests ran."""
        return self.provenance.label + (self.tests.summary if self.tests is not None else "")


class Started(_Outcome):
    """Work on the item has begun."""

    status: ClassVar[ItemStatus] = ItemStatus.IN_PROGRESS

    kind: Literal[OutcomeKind.started]

    def evidence(self, date: str) -> str:
        return f"started {date}"


class Blocked(_Outcome):
    """The item waits on something outside it."""

    status: ClassVar[ItemStatus] = ItemStatus.BLOCKED

    kind: Literal[OutcomeKind.blocked]
    reason: NonEmpty

    def evidence(self, date: str) -> str:
        return self.reason


class Closed(_Outcome):
    """The item is closed without action."""

    status: ClassVar[ItemStatus] = ItemStatus.CLOSED_NO_ACTION

    kind: Literal[OutcomeKind.closed]
    rationale: NonEmpty

    def evidence(self, date: str) -> str:
        return self.rationale


Outcome = Annotated[Union[Completed, Started, Blocked, Closed], Field(discriminator="kind")]


class SealedFields(BaseModel):
    """The payload an item seal covers: the plan id, the item fields the record vouches for, the record."""

    model_config = _CLOSED

    plan_id: str
    id: str
    status: ItemStatus
    evidence: str
    files: List[str]
    tests: List[PlannedTest]
    outcome: Outcome
    date: str

    @classmethod
    def of(cls, plan_id: str, item: "ActionItem", outcome: Outcome, date: str) -> "SealedFields":
        """The sealed payload of ``item`` in plan ``plan_id`` under ``outcome`` recorded on ``date``."""
        return cls(plan_id=plan_id, id=item.id, status=item.status, evidence=item.evidence,
                   files=list(item.files), tests=list(item.tests), outcome=outcome, date=date)

    def digest(self) -> str:
        """SHA-256 hex of the canonical JSON; defaulted fields are left out, so a later default keeps it."""
        payload = self.model_dump(mode="json", exclude_defaults=True)
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ItemRecord(BaseModel):
    """What `plan.py record` wrote for one item, and the seal that proves it wrote it.

    The item's status must be the one the outcome implies; `plan.py check` enforces that agreement, the JSON
    schema does not.
    """

    model_config = _CLOSED

    outcome: Outcome
    date: str = Field(json_schema_extra=_DATE)
    seal: str = Field(pattern=_SHA64, description="SHA-256 of the plan id, the item's id, status, evidence, "
                      "files and tests, and this record without the seal.")

    @classmethod
    def sealed(cls, plan_id: str, item: "ActionItem", outcome: Outcome, date: str) -> "ItemRecord":
        """A record of ``outcome`` for ``item``, sealed over the item as it stands now."""
        seal = SealedFields.of(plan_id, item, outcome, date).digest()
        return cls(outcome=outcome, date=date, seal=seal)

    def holds(self, plan_id: str, item: "ActionItem") -> bool:
        """The seal matches the item as it stands, and the item's status is the one the outcome implies."""
        expected = SealedFields.of(plan_id, item, self.outcome, self.date).digest()
        return expected == self.seal and item.status == self.outcome.status


class ActionItem(BaseModel):
    model_config = _OPEN

    id: str = Field(pattern=r"^[A-Z]{2,4}-[0-9.]+$",
                    description="Item id: 2-4 uppercase letters, a dash, digits and periods (`TASK-3.2`).")
    priority: Optional[Priority] = None
    category: Optional[str] = None
    worktree: Optional[str] = None
    title: str
    action: str = Field(description="Execution-ready implementation steps; the checklist source of truth.")
    files: List[str] = Field(default_factory=list, description="Paths of the files the item changes.")
    dependencies: Optional[List[str]] = Field(default=None, description="Item ids that finish first.")
    status: Annotated[ItemStatus, Mutable()]
    evidence: Annotated[str, Mutable()]
    verification_references: Annotated[List[str], Mutable()] = Field(default_factory=list)
    record: Annotated[Optional[ItemRecord], Mutable()] = None
    markdown_section: Optional[str] = None
    notes: Optional[str] = None
    model: ModelName = Field(default=ModelName.sonnet, description="Model that implements the item.")
    anchors: List[Anchor] = Field(default_factory=list)
    commands: List[Command] = Field(default_factory=list)
    tests: List[PlannedTest] = Field(default_factory=list, description=(
        "Pytest node ids that prove the item, each with the exception that fails it before the item is "
        "implemented. A planned test file lives at `<plans dir>/<plan_id>/tests/<repo-relative path>`."))

    def stamp(self, plan_id: str, outcome: Outcome, date: str) -> None:
        """Move the item to ``outcome``: status, evidence, cleared legacy references, the sealed record."""
        self.status = outcome.status
        self.evidence = outcome.evidence(date)
        self.verification_references = []
        self.record = ItemRecord.sealed(plan_id, self, outcome, date)


def _no_default(schema: Dict[str, Any]) -> None:
    """Drop ``default`` from a generated property whose default fails its own pattern."""
    schema.pop("default", None)


class ActionPlan(BaseModel):
    """A unified execution plan: JSON is the source of truth for items, evidence and verification."""

    model_config = _OPEN

    plan_id: str = Field(pattern=r"^[0-9]{4}$", description=(
        "Zero-padded 4-digit sequential plan number, also the filename prefix: "
        "`{plan_id}_{Title}_ActionPlan.json` and `{plan_id}_{Title}_PIP.md`."))
    plan_created: str = Field(json_schema_extra=_DATE)
    completed: Annotated[Optional[str], Mutable()] = Field(default=None, json_schema_extra=_DATE)
    source_document: Optional[str] = None
    documentation: Optional[str] = None
    branch: Optional[str] = None
    base_branch: Optional[str] = None
    execution_model: str
    markdown_sync_status: Annotated[Optional[MarkdownSync], Mutable()] = None
    markdown_last_updated: Annotated[Optional[str], Mutable()] = Field(default=None, json_schema_extra=_DATE)
    context: Context = Field(default_factory=Context)
    pr_attributes: List[PrAttributes] = Field(default_factory=list)
    items: List[ActionItem]
    # The model default only marks the field absent (``plan.py new`` records it); the schema omits it, since
    # an empty string fails the pattern.
    base_commit: str = Field(default="", pattern=_SHA40, json_schema_extra=_no_default, description=(
        "Commit the plan was written against: the merge base of the base branch and HEAD, recorded by "
        "`plan.py new`. Commands name `{base}` instead of a SHA."))
    frozen: Annotated[Optional[Frozen], Mutable()] = Field(default=None, description=(
        "Set by `plan.py freeze`: the commit and tree the plan was frozen at and a digest of every field "
        "except item status, evidence, verification_references and record, and the top-level completed, "
        "frozen, markdown_sync_status and markdown_last_updated; a set `records` scheme is folded into the "
        "digest. `plan.py check` reports any later edit outside those fields."))
    decisions: List[Decision] = Field(default_factory=list, description=(
        "Design questions the plan settles. `chosen` null means open, which blocks `plan.py freeze`. "
        "Every option not chosen counts as rejected."))
    values: List[Value] = Field(default_factory=list, description=(
        "Thresholds, counts and bands the plan copies from the spec or the code, with the options each "
        "assumes. A value assuming a rejected option fails `plan.py check`."))
    formats: List[PlanFormat] = Field(default_factory=list)
    sweeps: List[Sweep] = Field(default_factory=list, description=(
        "Searches the plan relies on (old names, moved paths). `plan.py check` runs each pattern over "
        "tracked and untracked files and fails on a file with hits that `hits` does not classify, or a "
        "classified file with none. The plans folder and the plan's own `source_document` are skipped on "
        "both sides."))
    deferred_to_future_plans: List[DeferredTopic] = Field(default_factory=list)

    # Hash and resolved path of the file this plan was loaded from; ``plan_api.write`` saves to that file
    # and refuses a stale copy.
    _loaded_hash: Optional[str] = PrivateAttr(default=None)
    _loaded_path: Optional[Path] = PrivateAttr(default=None)


def _mutable(model: type) -> Tuple[str, ...]:
    return tuple(name for name, field in model.model_fields.items()
                 if any(isinstance(m, Mutable) for m in field.metadata))


def mutable_top() -> Tuple[str, ...]:
    """Plan-level fields that change while the plan executes, in declaration order."""
    return _mutable(ActionPlan)


def mutable_item() -> Tuple[str, ...]:
    """Item-level fields that change while the plan executes, in declaration order."""
    return _mutable(ActionItem)


def schema_dict() -> Dict[str, Any]:
    """The draft 2020-12 JSON schema of ``ActionPlan``, with ``$schema`` and ``$id`` first."""
    body = ActionPlan.model_json_schema()
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **body}


def schema_text() -> str:
    """``schema_dict`` as the text committed to ``schemas/ActionPlan.schema.json``."""
    return json.dumps(schema_dict(), indent=2, ensure_ascii=False) + "\n"
