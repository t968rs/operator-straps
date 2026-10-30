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
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple, Union

from pydantic import (BaseModel, ConfigDict, Field, PrivateAttr, StrictInt, StrictStr,
                      ValidatorFunctionWrapHandler, WrapValidator)

from harness_lib.plan_enums import ItemStatus, MarkdownSync, ModelName, Priority, RedException

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/ActionPlan.schema.json"
_OPEN = ConfigDict(extra="allow", regex_engine="python-re")
_CLOSED = ConfigDict(extra="forbid", regex_engine="python-re")
_DATE = {"format": "date"}
_SHA40 = r"^[0-9a-f]{40}$"


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
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PrAttributes(BaseModel):
    """One PR associated with a plan; `pr` is an int, or a string for drafts without a number yet."""

    model_config = _OPEN

    pr: PrNumber
    review_doc: Optional[str] = Field(default=None, pattern=r"^docs/PR_REVIEWS/.+\.json$")
    branch: str
    base_branch: str
    pip_document: Optional[str] = Field(default=None, pattern=r"^docs/PLANS/.+_PIP\.md$")
    merged_at: Optional[str] = Field(default=None, json_schema_extra=_DATE)


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
    markdown_section: Optional[str] = None
    notes: Optional[str] = None
    model: ModelName = Field(default=ModelName.sonnet, description="Model that implements the item.")
    anchors: List[Anchor] = Field(default_factory=list)
    commands: List[Command] = Field(default_factory=list)
    tests: List[PlannedTest] = Field(default_factory=list, description=(
        "Pytest node ids that prove the item, each with the exception that fails it before the item is "
        "implemented. A planned test file lives at `<plans dir>/<plan_id>/tests/<repo-relative path>`."))


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
        "except item status, evidence and verification_references, and the top-level completed, frozen, "
        "markdown_sync_status and markdown_last_updated. `plan.py check` reports any later edit outside "
        "those fields."))
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
        "classified file with none."))
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
