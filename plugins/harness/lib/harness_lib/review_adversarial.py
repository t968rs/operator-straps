"""Pure planning for a pr-review ``--adversarial`` (``-a``) run: plan-path classification, the code
refuter's scope, the refuter slots, the Workflow args, the ``adversarial_check`` log entry, the pinned-schema
check and the agent count.

A plan path is a reviewable path under ``artifacts.plans`` (read from the active config inside each
function). Its state follows one table:

- ``<stem>_ActionPlan.json``: ``plan_doc.ledger_state``; frozen, locked and armed count frozen, unlocked
  and none unfrozen. A plan without a ledger is frozen when its legacy ``frozen`` field is set.
- ``<stem>_PIP.*``: as the plan ``<stem>_ActionPlan.json`` (full stem); without one, unfrozen.
- ``NNNN/**``: as the one plan numbered NNNN; zero or several such plans count unfrozen with a note.
- ``freezes/**`` and ``strap/*/fixtures/**``: excluded from the code refuter's scope.
- ``strap/<name>/**``: frozen when the skill's ``SkillSpec.json`` is frozen or ``strap_lock.is_locked``.
- anything else: unfrozen.

An unreadable state counts unfrozen with a note. A tree not at the PR head reads no state: every plan path
outside freezes/ and strap fixtures counts unfrozen, with one note. Notes carry no ``note:`` prefix, no
newline and no absolute path; capture prints them.

The driver's refuted-id helpers live here too: ``refuted_now`` (ids whose latest resolution is ``REFUTED``),
``refuted_problem`` (the one refusal text ``bubble``, ``closeout --resolved``, ``waves --ids`` and
``refute`` print for such an id, naming ``unrefute``) and ``with_overrule`` (the ``refuted_ids`` /
``unrefuted_ids`` update a developer ``refute`` or ``unrefute`` makes to a review's ``adversarial_check``).
"""
from __future__ import annotations

import copy
import json
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from harness_lib import freeze_ledger as fl
from harness_lib import plan_doc as pd
from harness_lib import review_models as rm
from harness_lib import review_plan as rp
from harness_lib.validation.id_handling import ADVERSARIAL_STATUSES, latest_statuses

REVIEWER_AGENT = "harness:pr-reviewer"
PLANS_BUCKET = "plans"
#: Code-refuter scope buckets, in slot order.
SCOPE_BUCKETS = (rp.PathBucket.RUNTIME.value, rp.PathBucket.TESTS.value, PLANS_BUCKET)
FROZEN_STATES = frozenset({fl.LedgerState.frozen, fl.LedgerState.locked, fl.LedgerState.armed})
STRAP_DIR = "strap"
FIXTURES_DIR = "fixtures"
OFF_HEAD_NOTE = ("tree is not at the PR head: plan state unread; every plan path outside freezes/ and strap "
                 "fixtures counts unfrozen")
_PLAN_NUMBER = re.compile(r"^\d{4}$")
_PIP = re.compile(r"^(?P<stem>.+)_PIP\.[^/]+$")

#: A plan path's state: (frozen, note or None).
_State = Tuple[bool, Optional[str]]


@dataclass(frozen=True)
class PlanPaths:
    """Plan paths by state; ``notes`` explains each unresolved state."""

    frozen: Tuple[str, ...] = ()
    unfrozen: Tuple[str, ...] = ()
    excluded: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()

    @property
    def classified(self) -> Tuple[str, ...]:
        """Every classified plan path."""
        return self.frozen + self.unfrozen + self.excluded


# --- plan-path classification -------------------------------------------------------------------------------


def _key(rel: str) -> str:
    """``rel`` as a comparison key: case-folded on Windows, whose file system ignores case."""
    return rel.lower() if os.name == "nt" else rel


def _plans() -> Tuple[str, Path]:
    """The plans folder as a normalized POSIX prefix ending in ``/`` and as an absolute path."""
    from harness_lib.config import active
    cfg = active()
    rel = posixpath.normpath(cfg.artifacts.plans.replace("\\", "/")).strip("/")
    return rel + "/", cfg.path(cfg.artifacts.plans)


def _reason(exc: BaseException) -> str:
    """A one-line cause of ``exc`` that names no absolute path: the ``strerror`` of the first ``OSError``
    along ``__cause__``, else the first line of ``problems[0]`` or of the message, else the type name."""
    cause: Optional[BaseException] = exc
    while cause is not None:
        if isinstance(cause, OSError):
            return cause.strerror or type(cause).__name__
        cause = cause.__cause__
    problems = getattr(exc, "problems", None)
    lines = str(problems[0] if problems else exc).splitlines()
    return lines[0].strip() if lines and lines[0].strip() else type(exc).__name__


def _plan_frozen(plan_file: Path, plans_dir: Path) -> bool:
    """True when the plan in ``plan_file`` counts frozen; raises when its state cannot be read, a ledger
    without entries included."""
    plan = pd.parse_plan(plan_file.read_text(encoding="utf-8"), plan_file.name)
    state = pd.ledger_state(plan, plans_dir)
    if state is None:
        return plan.frozen is not None
    if state is fl.LedgerState.none:
        raise pd.PlanError([f"ledger {plan.ledger} holds no entries"])
    return state in FROZEN_STATES


def _plan_state(name: str, plans_dir: Path) -> _State:
    """The state of the plan file ``name`` (a ``<stem>_ActionPlan.json`` in ``plans_dir``)."""
    plan_file = plans_dir / name
    if not plan_file.is_file():
        return False, None
    try:
        return _plan_frozen(plan_file, plans_dir), None
    except (pd.PlanError, OSError, ValueError) as exc:
        stem = name[: -len(pd.PLAN_SUFFIX)]
        return False, f"plan {stem}: state unreadable ({_reason(exc)}); its paths count unfrozen"


def _numbered_state(number: str, plans_dir: Path, cache: Dict[Tuple[str, str], _State]) -> _State:
    """The state of the one plan numbered ``number``, through ``cache``; zero or several such plans count
    unfrozen."""
    hits = sorted(p.name for p in plans_dir.glob(f"{number}_*{pd.PLAN_SUFFIX}"))
    if len(hits) == 1:
        return _state(("plan", hits[0]), plans_dir, cache)
    found = "no plan" if not hits else f"{len(hits)} plans"
    return False, f"plan folder {number}/: {found} numbered {number}; its paths count unfrozen"


def _strap_state(name: str, plans_dir: Path) -> _State:
    """The state of the strap skill ``name``: frozen when its spec is frozen or its round is Locked, the
    ledger read under ``plans_dir``; a skill folder without a spec is unfrozen."""
    from harness_lib import strap_lock
    from harness_lib.strap_models import SPEC_FILE, load_spec
    spec_file = plans_dir / STRAP_DIR / name / SPEC_FILE
    if not spec_file.is_file():
        return False, None
    try:
        spec = load_spec(spec_file)
        found = fl.load_entries(fl.ledger_dir(plans_dir, fl.skill_stem(name)))
        return spec.frozen is not None or strap_lock.is_locked(spec, found), None
    except (OSError, ValueError, fl.LedgerError) as exc:
        return False, f"strap skill {name}: state unreadable ({_reason(exc)}); its paths count unfrozen"


def _subject(rel: str) -> Optional[Tuple[str, str]]:
    """``(kind, key)`` naming whose state a plan-relative path follows; ``("excluded", "")`` for ledger and
    fixture data; None for a path that is never frozen."""
    parts = rel.split("/")
    if parts[0] == fl.FREEZES_DIR and len(parts) > 1:
        return "excluded", ""
    if parts[0] == STRAP_DIR and len(parts) > 2:
        return ("excluded", "") if parts[2] == FIXTURES_DIR and len(parts) > 3 else ("strap", parts[1])
    if len(parts) > 1 and _PLAN_NUMBER.match(parts[0]):
        return "number", parts[0]
    if len(parts) == 1 and rel.endswith(pd.PLAN_SUFFIX):
        return "plan", rel
    pip = _PIP.match(rel) if len(parts) == 1 else None
    return ("plan", pip.group("stem") + pd.PLAN_SUFFIX) if pip else None


def _state(subject: Optional[Tuple[str, str]], plans_dir: Path,
           cache: Dict[Tuple[str, str], _State]) -> _State:
    """The state of ``subject``, read once per subject (a plan named by its file and by its ``NNNN/``
    folder shares one entry)."""
    if subject is None:
        return False, None
    if subject not in cache:
        kind, key = subject
        if kind == "number":
            cache[subject] = _numbered_state(key, plans_dir, cache)
        else:
            cache[subject] = (_plan_state if kind == "plan" else _strap_state)(key, plans_dir)
    return cache[subject]


def _plan_rel(path: str, prefix: str) -> Optional[str]:
    """``path`` relative to the plans folder (POSIX separators), or None when it lies outside."""
    posix = path.replace("\\", "/")
    return posix[len(prefix):] if _key(posix).startswith(_key(prefix)) else None


def classify_plan_paths(paths: Sequence[str], at_head: bool) -> PlanPaths:
    """Sort the plan paths among ``paths`` into frozen, unfrozen and excluded; other paths are left out.

    With ``at_head`` False no state is read: every plan path outside freezes/ and strap fixtures counts
    unfrozen, with one note when any of them has a state to read. The rows keep the paths as given.
    """
    prefix, plans_dir = _plans()
    rows: Dict[str, List[str]] = {"frozen": [], "unfrozen": [], "excluded": []}
    notes: List[str] = []
    cache: Dict[Tuple[str, str], _State] = {}
    for path in dict.fromkeys(paths):
        rel = _plan_rel(path, prefix)
        if rel is None:
            continue
        subject = _subject(rel)
        if subject is not None and subject[0] == "excluded":
            rows["excluded"].append(path)
            continue
        if not at_head:
            frozen, note = False, (OFF_HEAD_NOTE if subject is not None else None)
        else:
            frozen, note = _state(subject, plans_dir, cache)
        rows["frozen" if frozen else "unfrozen"].append(path)
        notes += [note] if note else []
    return PlanPaths(*(tuple(rows[k]) for k in ("frozen", "unfrozen", "excluded")),
                     notes=tuple(dict.fromkeys(notes)))


# --- code scope and refuter slots ---------------------------------------------------------------------------


def code_scope(buckets: Mapping[str, Sequence[str]], plan_paths: PlanPaths) -> Dict[str, Tuple[str, ...]]:
    """The code refuter's scope: the runtime and tests buckets without any plan path (the plan rule overrides
    the bucket), plus the unfrozen plan paths as ``plans``. Empty buckets are dropped."""
    taken = set(plan_paths.classified)
    scope = {name: tuple(plan_paths.unfrozen) if name == PLANS_BUCKET
             else tuple(p for p in buckets.get(name, ()) if p not in taken) for name in SCOPE_BUCKETS}
    return {name: paths for name, paths in scope.items() if paths}


@dataclass(frozen=True)
class CodeSlot:
    """One code refuter: slot id, scope paths and model."""

    id: str
    paths: Tuple[str, ...]
    model: str = rm.REFUTER_MODEL

    def record(self) -> Dict[str, object]:
        return {"id": self.id, "paths": list(self.paths), "model": self.model}


@dataclass(frozen=True)
class RefuteSlot:
    """One findings refuter: slot id, the reviewer or code-refuter slot it checks, and model."""

    id: str
    target: str
    model: str = rm.REFUTER_MODEL

    def record(self) -> Dict[str, object]:
        return {"id": self.id, "target": self.target, "model": self.model}


@dataclass(frozen=True)
class RefuterPlan:
    """The refuter slots of an adversarial run: code refuters, then findings refuters."""

    code: Tuple[CodeSlot, ...] = ()
    refute: Tuple[RefuteSlot, ...] = ()

    def record(self) -> Dict[str, List[Dict[str, object]]]:
        """The ``plan.json["adversarial"]`` entry."""
        return {"code": [s.record() for s in self.code], "refute": [s.record() for s in self.refute]}


def _code_slots(scope: Mapping[str, Sequence[str]], reviewable_count: int) -> Tuple[CodeSlot, ...]:
    """One pooled ``adv_code`` slot below ``SMALL_PR_FILES``, else one ``adv_code_<bucket>`` per bucket."""
    buckets = [(name, tuple(scope[name])) for name in SCOPE_BUCKETS if scope.get(name)]
    if not buckets:
        return ()
    prefix = rm.CODE_REFUTER_PREFIX
    if reviewable_count < rp.SMALL_PR_FILES:
        pooled = tuple(dict.fromkeys(p for _, paths in buckets for p in paths))
        return (CodeSlot(prefix, pooled),)
    return tuple(CodeSlot(f"{prefix}_{name}", paths) for name, paths in buckets)


def refuter_slots(reviewer_ids: Sequence[str], scope: Mapping[str, Sequence[str]],
                  reviewable_count: int) -> RefuterPlan:
    """The code refuters over ``scope`` and one findings refuter per reviewer slot, then per code refuter."""
    code = _code_slots(scope, reviewable_count)
    targets = [*reviewer_ids, *(slot.id for slot in code)]
    refute = tuple(RefuteSlot(f"{rm.FINDINGS_REFUTER_PREFIX}{t}", t) for t in targets)
    return RefuterPlan(code, refute)


# --- workflow args and the adversarial_check entry ----------------------------------------------------------


def workflow_args(run_key: str, run_id: str, reviewers: Sequence[Mapping[str, object]], plan: RefuterPlan,
                  prompts: Mapping[str, str]) -> Dict[str, object]:
    """The Workflow ``args`` object; ``guidance`` is None, the one field the session may set."""
    agent = rm.ADVERSARIAL_AGENT
    return {
        "run_key": run_key, "run_id": run_id, "guidance": None,
        "reviewers": [{"id": r["id"], "agentType": REVIEWER_AGENT, "model": r["model"], "prompt": r["prompt"]}
                      for r in reviewers],
        "code": [{"id": s.id, "agentType": agent, "model": s.model, "prompt": prompts[s.id]}
                 for s in plan.code],
        "refute": [{"id": s.id, "target": s.target, "agentType": agent, "model": s.model,
                    "prompt": prompts[s.id]} for s in plan.refute],
    }


def adversarial_check(plan: RefuterPlan) -> Dict[str, object]:
    """The capture-time ``verification_log.dispatch_time.adversarial_check`` entry."""
    return {"applies": True, "workflow": rm.ADVERSARIAL_WORKFLOW,
            "code_slots": [s.id for s in plan.code], "refute_slots": [s.id for s in plan.refute],
            "result": f"PENDING ({len(plan.code)} code refuters, {len(plan.refute)} findings refuters)"}


def complete_check(check: Mapping[str, object], checked: int, refuted: int, code_findings: int,
                   refuted_ids: Sequence[str]) -> Dict[str, object]:
    """A copy of ``check`` completed at build with the counts, ``refuted_ids`` and an ``OK`` result.

    Pure: ``checked`` and ``refuted`` count verdict entries (all, and the refuted ones), so ``refuted`` is at
    most ``checked``; ``refuted_ids`` are issue ids, a different unit. Nothing is checked.
    """
    counts = {"findings_checked": checked, "findings_refuted": refuted,
              "findings_upheld": checked - refuted, "code_findings": code_findings}
    return {**check, "counts": counts, "refuted_ids": list(refuted_ids), "unrefuted_ids": [],
            "result": f"OK ({checked} checked, {refuted} refuted, {code_findings} code findings)"}


# --- pinned schema and agent count --------------------------------------------------------------------------


def schema_problem(path: Path) -> Optional[str]:
    """None when the schema at ``path`` lists every adversarial status in ``post_review_resolution.status``,
    else a problem naming the file and each missing status. An unreadable file or an enum that is missing
    or not a list lacks all three."""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
        enum = body["definitions"]["post_review_resolution"]["properties"]["status"]["enum"]
    except (OSError, ValueError, KeyError, TypeError):
        enum = None
    statuses = enum if isinstance(enum, list) else []
    missing = [status for status in ADVERSARIAL_STATUSES if status not in statuses]
    if not missing:
        return None
    return (f"{Path(path).as_posix()}: post_review_resolution.status lacks {', '.join(missing)}; "
            "update the schema before an --adversarial run")


def agent_count(reviewers: int, code_refuters: int) -> int:
    """Agents an adversarial run dispatches: each reviewer and code refuter plus one findings refuter each."""
    return 2 * (reviewers + code_refuters)


def worst_case_agents(project_lenses: int) -> int:
    """The most agents a run can dispatch: every bucket, lens and scope slot, ``project_lenses`` project
    lenses and one code refuter per scope bucket."""
    reviewers = len(rp.PathBucket.slotted()) + len(rp.Lens) + len(rp.ScopeLens) + project_lenses
    return agent_count(reviewers, len(SCOPE_BUCKETS))


# --- build counts and the developer overrule ----------------------------------------------------------------


def build_counts(refutations: Sequence[rm.RefutationReport],
                 code_reports: Sequence[rm.ReviewerReport]) -> Tuple[int, int, int]:
    """(findings checked, findings refuted, code findings): the verdict entries across ``refutations``, the
    refuted ones among them, and the findings across the code refuters' ``code_reports``."""
    checked = sum(len(r.refutations) for r in refutations)
    refuted = sum(r.counts()[rm.RefutationVerdict.refuted] for r in refutations)
    return checked, refuted, sum(len(r.findings) for r in code_reports)


def refuted_now(doc: Mapping[str, object]) -> List[str]:
    """Ids of a review whose latest resolution is ``REFUTED``, in first-resolution order (the position of
    each id's first resolution entry)."""
    latest = latest_statuses(doc.get("post_review_resolutions") or [])  # type: ignore[arg-type]
    return [str(i) for i, status in latest.items() if status == "REFUTED"]


def refuted_problem(issue_id: str, unchanged: Optional[str] = None) -> str:
    """The one refusal of a command on ``issue_id`` while its latest resolution is ``REFUTED``, naming the
    ``unrefute`` overrule; ``unchanged`` (a review path) adds ``; <unchanged> unchanged``."""
    text = (f"{issue_id}: latest resolution is REFUTED (closed by a refutation); refused until the "
            f"refutation is overruled with unrefute {issue_id} --fix (or --bubble)")
    return f"{text}; {unchanged} unchanged" if unchanged else text


def _moved(ids: Sequence[str], add: Sequence[str], drop: Sequence[str]) -> List[str]:
    """``ids`` without ``drop``, then each id of ``add`` not yet present."""
    kept = [i for i in ids if i not in drop]
    return list(dict.fromkeys([*kept, *add]))


def with_overrule(doc: Mapping[str, object], refuted: Sequence[str] = (),
                  unrefuted: Sequence[str] = ()) -> Dict[str, object]:
    """A copy of ``doc`` whose ``adversarial_check`` holds the current overrule state: ``refuted`` ids join
    ``refuted_ids`` and leave ``unrefuted_ids``, ``unrefuted`` ids the reverse. A review without the check
    (no ``-a``) comes back unchanged. ``counts`` and ``result`` stay the build-time figures: only the two id
    lists track the developer's overrules."""
    out = copy.deepcopy(dict(doc))
    log = out.get("verification_log")
    check = log.get("dispatch_time", {}).get("adversarial_check") if isinstance(log, dict) else None
    if not isinstance(check, dict):
        return out
    check["refuted_ids"] = _moved(check.get("refuted_ids") or [], refuted, unrefuted)
    check["unrefuted_ids"] = _moved(check.get("unrefuted_ids") or [], unrefuted, refuted)
    return out
