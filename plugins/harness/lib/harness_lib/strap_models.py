"""strap-skills: the SkillSpec document, its enums, validators and driver-owned metadata.

``SkillSpec`` is the one JSON file (``<plans>/strap/<name>/SkillSpec.json``) the strap-skills driver and the
author's API edit. Authored fields (behaviors, scenarios, planned tests) are the author's; the fields marked
``driver_owned`` (draws, runs, grades, frozen, driver_digest and each behavior's state) are written only by
``strap.py``. ``driver_digest`` fingerprints the driver-owned fields so a hand edit is detectable. This module
imports no other ``harness_lib`` module.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MIN_SCENARIOS = 2
MIN_DISCIPLINE_PRESSURES = 3
DESCRIPTION_MAX = 1024
NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
SPEC_FILE = "SkillSpec.json"
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/SkillSpec.schema.json"
_BEHAVIOR_ID = r"^B\d+$"
_SCENARIO_ID = r"^SC-\d+$"
_RUN_ID = r"^R-\d+$"
_DRIVER_OWNED = {"driver_owned": True}
_MODEL_CONFIG = ConfigDict(extra="forbid")


class SpecMode(str, Enum):
    """Whether the spec creates a skill or edits an existing one."""

    NEW = "new"
    EDIT = "edit"


class BehaviorKind(str, Enum):
    """Mechanical behaviors are pinned by planned tests; judgment behaviors by drawn scenarios."""

    MECHANICAL = "mechanical"
    JUDGMENT = "judgment"


class JudgmentType(str, Enum):
    """Kind of judgment behavior; discipline behaviors need pressure scenarios."""

    DISCIPLINE = "discipline"
    TECHNIQUE = "technique"
    PATTERN = "pattern"
    REFERENCE = "reference"


class Pressure(str, Enum):
    """Pressure a scenario applies to tempt the agent."""

    TIME = "time"
    SUNK_COST = "sunk_cost"
    AUTHORITY = "authority"
    EXHAUSTION = "exhaustion"
    SOCIAL = "social"
    PRAGMATIC = "pragmatic"


class PartKind(str, Enum):
    """Role of a file in the skill's deliverable set."""

    SKILL_MD = "skill_md"
    MODELS = "models"
    API = "api"
    DRIVER = "driver"
    AGENT = "agent"
    CONTRACT_TEST = "contract_test"
    REFERENCE = "reference"


class CheckKind(str, Enum):
    """Observable fact a scenario check evaluates after a run."""

    FILE_UNCHANGED = "file_unchanged"
    FILE_CHANGED = "file_changed"
    PATH_PRESENT = "path_present"
    PATH_ABSENT = "path_absent"
    HEAD_UNCHANGED = "head_unchanged"
    REPLY_MATCHES = "reply_matches"
    REPLY_LACKS = "reply_lacks"


class ReplyAct(str, Enum):
    """Act a grader looks for in a reply."""

    REFUSES = "refuses"
    ASKS_DEVELOPER = "asks_developer"
    REDIRECTS = "redirects"
    DEFERS = "defers"
    RATIONALIZES = "rationalizes"
    PROCEEDS = "proceeds"


class GradeValue(str, Enum):
    """Outcome of grading one judged item."""

    PRESENT = "present"
    ABSENT = "absent"
    UNCLEAR = "unclear"


class Grader(str, Enum):
    """Who graded: the author's session or the independent judge agent."""

    SESSION = "session"
    JUDGE = "judge"


class Arm(str, Enum):
    """Run arm: without the skill text (baseline) or with it (green)."""

    BASELINE = "baseline"
    GREEN = "green"


class BehaviorState(str, Enum):
    """Driver-tracked progress of a behavior."""

    OPEN = "open"
    DRAWN = "drawn"
    RED = "red"
    GREEN = "green"
    RETEST = "retest"
    DROPPED = "dropped"


class DrawReason(str, Enum):
    """Why a scenario was drawn."""

    INITIAL = "initial"
    RETEST = "retest"


class RedException(str, Enum):
    """Exception a planned test is expected to raise before the code exists."""

    IMPORT_ERROR = "ImportError"
    ATTRIBUTE_ERROR = "AttributeError"
    ASSERTION_ERROR = "AssertionError"
    NOT_IMPLEMENTED_ERROR = "NotImplementedError"
    TYPE_ERROR = "TypeError"


class Part(BaseModel):
    """One file of the deliverable set; ``path`` is repo-relative POSIX."""

    model_config = _MODEL_CONFIG

    kind: PartKind
    path: str


class PlannedTest(BaseModel):
    """A pytest node id and the exception it raises in the red phase."""

    model_config = _MODEL_CONFIG

    node: str
    red: RedException

    @field_validator("node")
    @classmethod
    def _node_has_separator(cls, value: str) -> str:
        if "::" not in value:
            raise ValueError("node must be a pytest node id containing '::'")
        return value


class Check(BaseModel):
    """A machine-evaluated scenario fact and what each arm is expected to observe."""

    model_config = _MODEL_CONFIG

    kind: CheckKind
    target: str
    expect_baseline: bool
    expect_green: bool


class JudgedItem(BaseModel):
    """A reply act graded by reading; ``UNCLEAR`` is a grade outcome, never an expectation."""

    model_config = _MODEL_CONFIG

    act: ReplyAct
    of: str
    expect_baseline: GradeValue
    expect_green: GradeValue

    @field_validator("expect_baseline", "expect_green")
    @classmethod
    def _not_unclear(cls, value: GradeValue) -> GradeValue:
        if value == GradeValue.UNCLEAR:
            raise ValueError("an expectation cannot be 'unclear'")
        return value


class Scenario(BaseModel):
    """A pressure scenario: a task that tempts a move, with checks and judged items for both arms."""

    model_config = _MODEL_CONFIG

    id: str = Field(pattern=_SCENARIO_ID)
    task: str
    pressures: List[Pressure] = Field(default_factory=list)
    tempts: str
    fixture: Optional[str] = None
    checks: List[Check] = Field(default_factory=list)
    judged: List[JudgedItem] = Field(default_factory=list)
    role: str = "session"

    @model_validator(mode="after")
    def _needs_expectation_and_distinct_pressures(self) -> Scenario:
        if not self.checks and not self.judged:
            raise ValueError(f"{self.id}: needs at least one check or judged item")
        if len(set(self.pressures)) != len(self.pressures):
            raise ValueError(f"{self.id}: duplicate pressures")
        return self


class Behavior(BaseModel):
    """One behavior the skill must produce, pinned by planned tests or by drawn scenarios."""

    model_config = _MODEL_CONFIG

    id: str = Field(pattern=_BEHAVIOR_ID)
    statement: str
    kind: BehaviorKind
    type: Optional[JudgmentType] = None
    rationale: str
    tests: List[PlannedTest] = Field(default_factory=list)
    scenarios: List[Scenario] = Field(default_factory=list)
    state: BehaviorState = Field(default=BehaviorState.OPEN, json_schema_extra=_DRIVER_OWNED)
    dropped_reason: Optional[str] = None

    @model_validator(mode="after")
    def _kind_rules(self) -> Behavior:
        judgment = self.kind == BehaviorKind.JUDGMENT
        if judgment != (self.type is not None):
            raise ValueError(f"{self.id}: type is required for judgment behaviors and forbidden otherwise")
        if judgment and self.tests:
            raise ValueError(f"{self.id}: a judgment behavior has no tests")
        if not judgment and self.scenarios:
            raise ValueError(f"{self.id}: a mechanical behavior has no scenarios")
        return self

    @model_validator(mode="after")
    def _scenario_rules(self) -> Behavior:
        ids = [scenario.id for scenario in self.scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.id}: duplicate scenario ids")
        if self.type == JudgmentType.DISCIPLINE:
            for scenario in self.scenarios:
                if len(scenario.pressures) < MIN_DISCIPLINE_PRESSURES:
                    raise ValueError(
                        f"{self.id}: {scenario.id} needs at least {MIN_DISCIPLINE_PRESSURES} pressures")
        return self

    @model_validator(mode="after")
    def _dropped_iff_reason(self) -> Behavior:
        dropped = self.state == BehaviorState.DROPPED
        if dropped != bool(self.dropped_reason):
            raise ValueError(f"{self.id}: state 'dropped' holds exactly when dropped_reason is non-empty")
        return self


class Draw(BaseModel):
    """A seeded scenario draw for a behavior."""

    model_config = _MODEL_CONFIG

    behavior: str
    scenario: str
    seed: int
    reason: DrawReason
    at: str


class CheckResult(BaseModel):
    """Outcome of one scenario check on one run."""

    model_config = _MODEL_CONFIG

    index: int
    held: bool
    detail: str


class Run(BaseModel):
    """One scenario run on one arm; ``tree`` and ``start`` locate the working tree the run used."""

    model_config = _MODEL_CONFIG

    id: str = Field(pattern=_RUN_ID)
    behavior: str
    scenario: str
    arm: Arm
    skill_hash: str
    reply: str = ""
    reply_sha256: str = ""
    diff: List[str] = Field(default_factory=list)
    checks: List[CheckResult] = Field(default_factory=list)
    recorded: bool = False
    tree: str = ""
    start: str = ""

    @model_validator(mode="after")
    def _recorded_hash_matches(self) -> Run:
        if self.recorded:
            expected = hashlib.sha256(self.reply.encode("utf-8")).hexdigest()
            if self.reply_sha256 != expected:
                raise ValueError(f"{self.id}: reply_sha256 does not match the reply")
        return self


class Grade(BaseModel):
    """A grade of one judged item of one run, with the verbatim quote that supports it."""

    model_config = _MODEL_CONFIG

    run: str
    item: int
    value: GradeValue
    quote: str
    grader: Grader

    @field_validator("quote")
    @classmethod
    def _quote_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quote must not be blank")
        return value


class Frozen(BaseModel):
    """The seal: the skill hash and grader the spec was frozen with."""

    model_config = _MODEL_CONFIG

    skill_hash: str
    grader: Grader
    at: str


class SkillSpec(BaseModel):
    """The strap-skills document for one skill."""

    model_config = _MODEL_CONFIG

    name: str = Field(pattern=NAME_PATTERN)
    mode: SpecMode
    base: Optional[str] = None
    judge: bool = False
    plugin_dir: str
    parts: List[Part] = Field(default_factory=list)
    behaviors: List[Behavior] = Field(default_factory=list)
    draws: List[Draw] = Field(default_factory=list, json_schema_extra=_DRIVER_OWNED)
    runs: List[Run] = Field(default_factory=list, json_schema_extra=_DRIVER_OWNED)
    grades: List[Grade] = Field(default_factory=list, json_schema_extra=_DRIVER_OWNED)
    frozen: Optional[Frozen] = Field(default=None, json_schema_extra=_DRIVER_OWNED)
    driver_digest: str = Field(default="", json_schema_extra=_DRIVER_OWNED)

    @model_validator(mode="after")
    def _base_iff_edit(self) -> SkillSpec:
        if (self.mode == SpecMode.EDIT) != (self.base is not None):
            raise ValueError("base is set exactly when mode is 'edit'")
        return self

    @model_validator(mode="after")
    def _references_resolve(self) -> SkillSpec:
        scenarios = _scenario_index(self)
        for draw in self.draws:
            _require_scenario(scenarios, draw.behavior, draw.scenario, "draw")
        for run in self.runs:
            _require_scenario(scenarios, run.behavior, run.scenario, run.id)
        run_ids = {run.id for run in self.runs}
        for grade in self.grades:
            if grade.run not in run_ids:
                raise ValueError(f"grade names unknown run {grade.run}")
        return self


def _scenario_index(spec: SkillSpec) -> Dict[str, List[str]]:
    """Scenario ids by behavior id; a duplicate behavior id raises."""
    out: Dict[str, List[str]] = {}
    for behavior in spec.behaviors:
        if behavior.id in out:
            raise ValueError(f"duplicate behavior id {behavior.id}")
        out[behavior.id] = [scenario.id for scenario in behavior.scenarios]
    return out


def _require_scenario(index: Dict[str, List[str]], behavior: str, scenario: str, owner: str) -> None:
    """Raise unless ``behavior`` exists and holds ``scenario``."""
    if behavior not in index:
        raise ValueError(f"{owner} names unknown behavior {behavior}")
    if scenario not in index[behavior]:
        raise ValueError(f"{owner} names unknown scenario {scenario} of {behavior}")


def _owned_fields(model: Type[BaseModel]) -> Tuple[str, ...]:
    """Field names of ``model`` whose ``json_schema_extra`` marks them driver-owned, in declared order."""
    names = []
    for field_name, info in model.model_fields.items():
        extra = info.json_schema_extra
        if isinstance(extra, dict) and extra.get("driver_owned") is True:
            names.append(field_name)
    return tuple(names)


DRIVER_OWNED_TOP: Tuple[str, ...] = _owned_fields(SkillSpec)
DRIVER_OWNED_BEHAVIOR: Tuple[str, ...] = _owned_fields(Behavior)


def driver_digest(spec: SkillSpec) -> str:
    """sha256 hex of the canonical JSON of the driver-owned fields, behavior states keyed by behavior id.

    ``driver_digest`` itself is excluded.
    """
    dumped = spec.model_dump(mode="json")
    owned: Dict[str, Any] = {name: dumped[name] for name in DRIVER_OWNED_TOP if name != "driver_digest"}
    owned["behavior_states"] = {
        behavior["id"]: {name: behavior[name] for name in DRIVER_OWNED_BEHAVIOR}
        for behavior in dumped["behaviors"]
    }
    text = json.dumps(owned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_spec(path: Path) -> SkillSpec:
    """Read and validate the spec at ``path``; raises ``ValidationError`` or ``OSError``."""
    return SkillSpec.model_validate_json(path.read_text(encoding="utf-8"))


def dump_spec(spec: SkillSpec) -> str:
    """Canonical file text of ``spec``: indented JSON and a trailing newline."""
    return json.dumps(spec.model_dump(mode="json"), indent=2) + "\n"


def schema_text() -> str:
    """JSON Schema of ``SkillSpec`` with ``$schema`` and ``$id`` first, as the schema file's exact text."""
    schema = {"$schema": SCHEMA_DRAFT, "$id": SCHEMA_ID, **SkillSpec.model_json_schema()}
    return json.dumps(schema, indent=2) + "\n"
