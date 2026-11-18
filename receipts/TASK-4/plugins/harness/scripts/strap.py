"""strap driver: the gate-owned transitions of a strap-skills ``SkillSpec``.

The spec lives at ``<artifacts.plans>/strap/<name>/SkillSpec.json``. Authored fields change through the API
(``api``); this script owns draws, runs, grades' prerequisites, behavior states and the freeze, and stamps
``driver_digest`` on every write so a hand edit of a driver-owned field is caught. Every refusal is one
``problem: ...`` line per defect on stderr with exit 1.

``new <name> [--edit [--base REF]] [--judge]``
    Create the spec, or resume an existing one. ``--edit`` records ``base`` (HEAD, or an ancestor REF) and
    the skill's existing files as parts.
``check <name>``
    Model, canonical form, driver digest, lint of the parts that exist, agent files of role scenarios;
    prints ``open:`` for each judgment behavior short of scenarios. Reconciles the ledger's commit tags
    (writes refs, never files) and prints ``untagged:``, ``off-history:``, ``drift:``, ``ledger:`` and
    ``legacy:`` warnings.
``red <name>``
    Run the mechanical behaviors' planned tests on a throwaway tree; each must fail as planned.
``draw <name>``
    One seeded scenario per judgment behavior without a draw; final.
``run <name> <B> --arm baseline|green [--scenario SC]``
    Create (or re-print) a run, build its scenario tree and print the runner dispatch row.
``init <name> --run R``
    The runner's brief, ending with the exact ``record-run`` command.
``record-run <name> --run R``
    Store the reply read from stdin (machine paths redacted), evaluate the checks against the tree and the
    unredacted reply, then drop the tree.
``judge-row <name>``
    The judge dispatch row for every recorded run with an ungraded judged item (``--judge`` specs).
``scaffold <name>``
    Render the planned parts and record them in the spec.
``retest <name> <B>``
    After a failed green and a skill change, draw one fresh scenario of the behavior.
``freeze <name> [--refreeze]``
    The final gate; stamps the skill hash and the grader. ``--refreeze`` runs every gate again on a frozen
    spec and stamps the current hash, whether or not the parts changed; on a spec never frozen it is a plain
    freeze. Every listed part file must exist. A frozen spec
    takes ``run --arm green``, ``record-run`` of a green run, and through ``api`` part edits and the grades
    of green runs, so the new hash can earn its greens; new behaviors come only after ``reopen``. Each
    freeze also writes a ``freeze`` ledger entry under ``<artifacts.plans>/freezes/skill/<name>/`` and tags
    its tree (a spec frozen before the ledger first gets history entries).
``lock <name>``
    Run only on the developer's explicit ask: a Frozen spec, not stale, whose planned and contract tests
    pass and whose last freeze's files are committed at HEAD and clean, becomes Locked (a ``lock`` entry and
    a tagged tree that adds ``SkillSpec.json``). A Locked spec refuses every writer until ``reopen``.
``reopen <name> [--base REF]``
    Start a new round on a frozen or locked spec: the stamp and the live behavior ids move into ``rounds``,
    ``frozen`` clears, the mode becomes edit and ``base`` moves to HEAD (or an ancestor REF). The new base
    must descend from the previous one and hold every part as the working tree has it. ``red`` then skips
    the mechanical behaviors frozen green in an earlier round; the next ``freeze`` gates every live
    behavior. Writes a ``reopen`` entry and tags the new base.
``relink <name> [--to REF]``
    After a rewrite, re-point a ``base`` no longer on HEAD's history at its patch-id match (or REF), write a
    ``relink`` entry and tag the new base.
``api <name>``
    Run stdin code with the public names of ``harness_lib.strap_api`` and ``name`` bound.

Tags are local: each command that creates one prints ``tag: <name> -> <sha7>`` and a ``push:`` line. Only
``check`` and the ledger writers (``new --edit``, ``freeze``, ``reopen``, ``lock``, ``relink``) reconcile the
ledger's commit tags; the other commands leave them to the next of those. Inside a scenario tree
(``freeze_git.SCENARIO_MARKER`` at the project root) no tag is created and nothing reconciled.

``--repo`` (default: the working directory) names a directory inside the project. Usage::

    strap.py [--repo DIR] <subcommand> <name> ...
"""
import argparse
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from pydantic import ValidationError

from harness_lib import freeze_git as fg
from harness_lib import plan_red as pr
from harness_lib import strap_api as sa
from harness_lib import strap_lock as sl
from harness_lib import strap_models as sm
from harness_lib import strap_runs as sr
from harness_lib.branch_capture import CaptureError, git, git_out
from harness_lib.config import active, activate, load_config
from harness_lib.freeze_ledger import LedgerError
from harness_lib.plan_enums import ItemStatus
from harness_lib.plan_enums import RedException as PlanRed
from harness_lib.plan_models import ActionItem, ActionPlan, PlannedTest
from harness_lib.project import project_root
from harness_lib.strap_lint import lint_project_skill, lint_python, lint_skill
from harness_lib.strap_models import (
    Arm, Behavior, BehaviorKind, BehaviorState, Draw, DrawReason, Frozen, Grader, GradeValue, Part, PartKind,
    Round, Run, Scenario, SkillSpec, SpecMode,
)
from harness_lib.strap_profile import Profile, new_fields, profile_of
from harness_lib.strap_scaffold import planned_parts, render_parts

PROBLEMS = (CaptureError, ValueError, OSError, LedgerError)
RUNNER_AGENT = "harness:strap-scenario-runner"
JUDGE_AGENT = "harness:strap-judge"
AGENT_MODEL = "sonnet"
DISPATCH_SKILL = "strap-skills"
SESSION_ROLE = "session"
SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
TAMPERED = "driver-owned fields changed outside strap.py"
REPLY_TAG = "REPLY"
FIXTURE_IDENTITY = ("-c", "user.name=strap", "-c", "user.email=strap@localhost")


class Refused(Exception):
    """A refusal; ``problems`` holds one line per defect."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


# --- locations --------------------------------------------------------------------------------------------

def _root() -> Path:
    return active().project_root.resolve()


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(_root()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _strap_dir(name: str) -> Path:
    """``<artifacts.plans>/strap/<name>``: the spec, planned tests and fixtures of one skill."""
    return sa.spec_path(name).parent


def launcher() -> str:
    """The absolute ``hpy`` command that runs this script against the active project."""
    hpy = (SCRIPT_DIR / "hpy").as_posix()
    return f'sh "{hpy}" "{SCRIPT.as_posix()}" --repo "{_root().as_posix()}"'


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --- spec load and save -----------------------------------------------------------------------------------

def load(name: str, writable: bool = False, unlocked: bool = False) -> SkillSpec:
    """The stored spec; refused when missing, hand-edited in driver-owned fields or, once frozen, in authored
    fields, Locked (``writable`` or ``unlocked``), or frozen (``writable``)."""
    path = sa.spec_path(name)
    if not path.is_file():
        raise Refused([f"no spec for {name} at {_rel(path)}; run new first"])
    spec = sm.load_spec(path)
    if spec.driver_digest != sm.driver_digest(spec):
        raise Refused([TAMPERED])
    if sm.seal_broken(spec):
        raise Refused([sm.SEAL_BROKEN])
    if writable or unlocked:
        sl.refuse_locked(spec)
    if writable and spec.frozen is not None:
        raise Refused([f"{name} is frozen"])
    return spec


def save(spec: SkillSpec) -> SkillSpec:
    """Re-validate ``spec`` from its dump, seal a frozen spec, stamp a fresh driver digest and write it."""
    checked = sm.sealed(SkillSpec.model_validate(spec.model_dump()))
    stamped = checked.model_copy(update={"driver_digest": sm.driver_digest(checked)})
    path = sa.spec_path(stamped.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sm.dump_spec(stamped), encoding="utf-8", newline="\n")
    return stamped


def spec_bytes(name: str) -> Tuple[Path, bytes]:
    """The spec file and its bytes, for ``strap_lock.commit`` to put back when an entry write fails."""
    path = sa.spec_path(name)
    return path, path.read_bytes()


# --- lookups ----------------------------------------------------------------------------------------------

def _behavior(spec: SkillSpec, ident: str) -> Behavior:
    found = next((b for b in spec.behaviors if b.id == ident), None)
    if found is None:
        raise Refused([f"unknown behavior {ident}"])
    return found


def _judgment(spec: SkillSpec, ident: str) -> Behavior:
    """A judgment behavior that is not dropped."""
    behavior = _behavior(spec, ident)
    if behavior.kind != BehaviorKind.JUDGMENT:
        raise Refused([f"{ident} is mechanical; its gate is red and its planned tests"])
    if behavior.state == BehaviorState.DROPPED:
        raise Refused([f"{ident} is dropped"])
    return behavior


def _scenario(behavior: Behavior, ident: str) -> Scenario:
    found = next((s for s in behavior.scenarios if s.id == ident), None)
    if found is None:
        raise Refused([f"{behavior.id} has no scenario {ident}"])
    return found


def _run_of(spec: SkillSpec, ident: str) -> Run:
    found = next((r for r in spec.runs if r.id == ident), None)
    if found is None:
        raise Refused([f"unknown run {ident}"])
    return found


def _scenario_of_run(spec: SkillSpec, run: Run) -> Scenario:
    return _scenario(_behavior(spec, run.behavior), run.scenario)


def _runs(spec: SkillSpec, **match: Any) -> List[Run]:
    """Runs whose fields equal every keyword given, in recorded order."""
    return [run for run in spec.runs if all(getattr(run, key) == value for key, value in match.items())]


def _draws_of(spec: SkillSpec, behavior_id: str) -> List[Draw]:
    return [draw for draw in spec.draws if draw.behavior == behavior_id]


def _skill_md(spec: SkillSpec) -> Optional[Part]:
    return next((part for part in spec.parts if part.kind == PartKind.SKILL_MD), None)


def _refuse_frozen_baseline(spec: SkillSpec, arm: Arm) -> None:
    """A frozen spec takes green runs only, so a part change can be proven on the new hash."""
    if spec.frozen is not None and arm != Arm.GREEN:
        raise Refused([f"{spec.name} is frozen; it takes green runs only"])


def _require_skill_md(spec: SkillSpec) -> Part:
    part = _skill_md(spec)
    if part is None:
        raise Refused([f"{spec.name}: no skill_md part"])
    return part


def skill_hash(spec: SkillSpec) -> str:
    """Content hash of every part file, read from the project's working tree."""
    return sr.content_hash(_root(), [part.path for part in spec.parts])


def stale_line(spec: SkillSpec) -> Optional[str]:
    """The ``stale:`` line of a frozen spec whose parts no longer hash to the stamp, else None."""
    if spec.frozen is None:
        return None
    current = skill_hash(spec)
    if current == spec.frozen.skill_hash:
        return None
    return (f"stale: frozen at {spec.frozen.skill_hash[:12]}, parts now hash {current[:12]}; "
            "prove greens then freeze --refreeze")


def _with_states(spec: SkillSpec, ids: Set[str], state: BehaviorState) -> List[Behavior]:
    return [b.model_copy(update={"state": state}) if b.id in ids else b for b in spec.behaviors]


def _put_run(spec: SkillSpec, run: Run) -> SkillSpec:
    """``spec`` with ``run`` replacing the run of the same id, or appended."""
    runs = [run if existing.id == run.id else existing for existing in spec.runs]
    if not any(existing.id == run.id for existing in spec.runs):
        runs.append(run)
    return spec.model_copy(update={"runs": runs})


# --- new --------------------------------------------------------------------------------------------------

def _resume(args: argparse.Namespace) -> int:
    """An existing spec: print its state; ``--judge`` turns the judge on only before any grade."""
    spec = load(args.name)
    if args.judge and not spec.judge:
        if spec.grades or spec.frozen is not None:
            raise Refused([f"{spec.name} already has grades; --judge is fixed once grading starts"])
        spec = save(spec.model_copy(update={"judge": True}))
    mode = SpecMode(spec.mode).value
    stale = stale_line(spec)
    if stale:
        print(stale)
    print(f"resume | {spec.name} | {len(spec.behaviors)} behaviors | mode {mode} | judge {spec.judge} "
          f"| {_rel(sa.spec_path(spec.name))}")
    return 0


def _edit_base(root: Path, name: str, skill_rel: str, ref: Optional[str]) -> str:
    """Full SHA of the edit's base: HEAD, or ``ref`` when it is an ancestor of HEAD."""
    if git(root, "cat-file", "-e", f"HEAD:{skill_rel}").returncode != 0:
        raise Refused([f"{name} has no SKILL.md to edit"])
    if ref is None:
        return git_out(root, "rev-parse", "HEAD").strip()
    done = git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if done.returncode != 0:
        raise Refused([f"--base {ref} does not name a commit"])
    sha = done.stdout.strip()
    if git(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0:
        raise Refused([f"--base {ref} is not an ancestor of HEAD"])
    return sha


def _edit_parts(root: Path, spec: SkillSpec) -> List[Part]:
    """The skill's tracked folder files, plus its models, API, driver and contract test when present.

    A tracked file at the profile's models, API or driver path takes that kind (a project skill keeps them in
    its folder's ``scripts/``); every other folder file is a reference."""
    profile = profile_of(spec)
    special = {profile.skill_md: PartKind.SKILL_MD, profile.models: PartKind.MODELS,
               profile.api: PartKind.API, profile.driver: PartKind.DRIVER}
    tracked = [p for p in git_out(root, "ls-files", "-z", "--", profile.skill_folder).split("\0") if p]
    parts = [Part(kind=special.get(rel, PartKind.REFERENCE), path=rel) for rel in sorted(tracked)]
    extra = [(kind, rel) for rel, kind in special.items() if kind != PartKind.SKILL_MD]
    extra += [(p.kind, p.path) for p in planned_parts(spec) if p.kind == PartKind.CONTRACT_TEST]
    listed = {part.path for part in parts}
    parts += [Part(kind=kind, path=rel) for kind, rel in extra
              if rel not in listed and (root / rel).is_file()]
    return parts


def cmd_new(args: argparse.Namespace) -> int:
    if sa.spec_path(args.name).is_file():
        return _resume(args)
    if args.base and not args.edit:
        raise Refused(["--base needs --edit"])
    root = _root()
    fields = new_fields(active(), root)
    skill_rel = profile_of(SkillSpec(name=args.name, mode=SpecMode.NEW, **fields)).skill_md
    base: Optional[str] = None
    if args.edit:
        base = _edit_base(root, args.name, skill_rel, args.base)
    elif (root / skill_rel).is_file():
        raise Refused([f"{args.name} exists; use --edit"])
    spec = SkillSpec(name=args.name, mode=SpecMode.EDIT if args.edit else SpecMode.NEW, base=base,
                     judge=args.judge, **fields)
    if args.edit:
        spec = spec.model_copy(update={"parts": _edit_parts(root, spec)})
    pending = sl.base_pending(args.name, base) if base else None
    if pending is not None:
        sl.preflight(root, pending)
    spec = save(spec)
    detail = f"edit from {base[:12]} | {len(spec.parts)} parts" if base else "new"
    print(f"new [done] | {spec.name} | {detail} | judge {spec.judge} | {_rel(sa.spec_path(spec.name))}")
    _print_lines(sl.commit(root, pending) if pending is not None else [])
    return 0


def _print_lines(lines: Sequence[str]) -> None:
    """Print the ledger's ``tag:``, ``push:`` and ``warn:`` lines, one per line, after the status line."""
    for line in lines:
        print(line)


# --- check ------------------------------------------------------------------------------------------------

def _lint_problems(spec: SkillSpec) -> List[str]:
    """Lint of every part file that exists: the skill's SKILL.md and each Python part."""
    root = _root()
    problems: List[str] = []
    for part in spec.parts:
        target = root / part.path
        if not target.is_file():
            continue
        if part.kind == PartKind.SKILL_MD:
            problems += _lint_skill_md(root, profile_of(spec), spec.name)
        elif target.suffix == ".py":
            problems += lint_python(target)
    return problems


def _lint_skill_md(root: Path, profile: Profile, name: str) -> List[str]:
    """The harness house lint for a harness skill, the generic project lint for a project skill."""
    if profile.plugin_dir is not None:
        return lint_skill(root / profile.plugin_dir, name)
    return lint_project_skill(root / profile.skill_folder, name)


def _role_problems(spec: SkillSpec) -> List[str]:
    profile = profile_of(spec)
    agents = _root() / profile.agents_dir
    return [f"{sc.id}: role {sc.role} has no {profile.agents_dir}/{sc.role}.md"
            for behavior in spec.behaviors for sc in behavior.scenarios
            if sc.role != SESSION_ROLE and not (agents / f"{sc.role}.md").is_file()]


def spec_problems(name: str) -> Tuple[Optional[SkillSpec], List[str]]:
    """The spec (None when it does not load) and every defect ``check`` reports."""
    path = sa.spec_path(name)
    if not path.is_file():
        return None, [f"no spec for {name} at {_rel(path)}; run new first"]
    try:
        spec = sm.load_spec(path)
    except ValidationError as exc:
        return None, [f"{_rel(path)}: {line}" for line in _validation_lines(exc)]
    problems: List[str] = []
    if path.read_text(encoding="utf-8") != sm.dump_spec(spec):
        problems.append(f"{_rel(path)} is not in the canonical form strap.py writes")
    if spec.driver_digest != sm.driver_digest(spec):
        problems.append(TAMPERED)
    if sm.seal_broken(spec):
        problems.append(sm.SEAL_BROKEN)
    return spec, problems + _lint_problems(spec) + _role_problems(spec)


def cmd_check(args: argparse.Namespace) -> int:
    """Report the spec's defects and warnings; reconcile writes tag refs, never files."""
    spec, problems = spec_problems(args.name)
    if spec is None or problems:
        raise Refused(problems)
    short = [b for b in spec.behaviors if b.kind == BehaviorKind.JUDGMENT
             and b.state != BehaviorState.DROPPED and len(b.scenarios) < sm.MIN_SCENARIOS]
    for behavior in short:
        print(f"open: {behavior.id} | {len(behavior.scenarios)} of {sm.MIN_SCENARIOS} scenarios")
    stale = stale_line(spec)
    if stale:
        print(stale)
    _print_lines(sl.check_lines(_root(), spec))
    print(f"check [ok] | {spec.name} | {len(spec.behaviors)} behaviors | {len(short)} open")
    return 0


# --- red --------------------------------------------------------------------------------------------------

def _start_commit(spec: SkillSpec) -> str:
    """The commit runs and red start from: an edit's base, else HEAD."""
    return spec.base or git_out(_root(), "rev-parse", "HEAD").strip()


def _red_item(behavior: Behavior) -> ActionItem:
    """One mechanical behavior as a PENDING plan item holding its planned tests."""
    tests = [PlannedTest.model_construct(node=t.node, red=PlanRed(sm.RedException(t.red).value))
             for t in behavior.tests]
    return ActionItem.model_construct(id=behavior.id, status=ItemStatus.PENDING, tests=tests)


def _red_plan(spec: SkillSpec) -> ActionPlan:
    """The mechanical behaviors as the ``ActionPlan`` ``plan_red`` reads; ``plan_id`` is the skill name.

    Built with ``model_construct``: a skill name fails the plan id pattern and a behavior id the item id
    pattern, and ``plan_red`` reads only ``plan_id`` and each item's id, status and tests. A behavior in
    state ``green`` was frozen in an earlier round, so its code exists at the new base and it is skipped.
    """
    done = (BehaviorState.DROPPED, BehaviorState.GREEN)
    items = [_red_item(b) for b in spec.behaviors
             if b.kind == BehaviorKind.MECHANICAL and b.state not in done and b.tests]
    return ActionPlan.model_construct(plan_id=spec.name, items=items)


def red_results(spec: SkillSpec) -> List[pr.RedResult]:
    """Planned nodes run on a throwaway tree at the start commit, planned test files laid over it."""
    plan = _red_plan(spec)
    if not plan.items:
        return []
    root = _root()
    tree = pr.make_tree(root, _start_commit(spec), active().resolve_worktree_root())
    try:
        _mark_scenario(tree)
        pr.overlay(pr.test_sources(plan, _strap_dir(spec.name).parent), tree)
        return pr.run_red(plan, tree, sys.executable)
    finally:
        pr.drop_tree(root, tree)


def cmd_red(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    results = red_results(spec)
    problems = pr.red_problems(results)
    if problems:
        raise Refused(problems)
    if not results:
        print(f"red [ok] | {spec.name} | no planned tests")
        return 0
    ids = {result.item for result in results}
    save(spec.model_copy(update={"behaviors": _with_states(spec, ids, BehaviorState.RED)}))
    rows = [f"{r.item} {r.node}: {r.got} (planned {r.expected})" for r in results]
    print("\n".join([f"red [ok] | {spec.name} | {len(results)} nodes fail as planned", *rows]))
    return 0


# --- draw -------------------------------------------------------------------------------------------------

def cmd_draw(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    drawn = {draw.behavior for draw in spec.draws}
    pending = [b for b in spec.behaviors if b.kind == BehaviorKind.JUDGMENT
               and b.state != BehaviorState.DROPPED and b.id not in drawn]
    short = [f"{b.id}: fewer than {sm.MIN_SCENARIOS} scenarios" for b in pending
             if len(b.scenarios) < sm.MIN_SCENARIOS]
    if short:
        raise Refused(short)
    if not pending:
        print(f"draw [done] | {spec.name} | nothing to draw")
        return 0
    draws = list(spec.draws)
    for behavior in pending:
        seed = sr.new_seed()
        picked = sr.draw_scenario(behavior, (), seed)
        draws.append(Draw(behavior=behavior.id, scenario=picked, seed=seed, reason=DrawReason.INITIAL,
                          at=_now()))
    states = _with_states(spec, {b.id for b in pending}, BehaviorState.DRAWN)
    save(spec.model_copy(update={"draws": draws, "behaviors": states}))
    print("\n".join(f"draw | {d.behavior} -> {d.scenario}" for d in draws[len(spec.draws):]))
    return 0


# --- run: which scenario ----------------------------------------------------------------------------------

def _needs(spec: SkillSpec, behavior: Behavior, arm: Arm, current: str, scenario: str) -> bool:
    """A baseline is needed once per scenario; a green once per scenario and skill hash."""
    if arm == Arm.BASELINE:
        return not _runs(spec, behavior=behavior.id, scenario=scenario, arm=arm, recorded=True)
    return not _runs(spec, behavior=behavior.id, scenario=scenario, arm=arm, recorded=True,
                     skill_hash=current)


def _candidates(spec: SkillSpec, behavior: Behavior) -> List[str]:
    """The must-pass scenarios, then the latest draw."""
    pool = sr.must_pass(spec, behavior.id)
    latest = _draws_of(spec, behavior.id)[-1].scenario
    return pool + ([latest] if latest not in pool else [])


def _target(spec: SkillSpec, behavior: Behavior, arm: Arm, current: str, chosen: Optional[str]) -> str:
    """The scenario this run covers: ``chosen`` (a drawn one) or the first candidate still needing ``arm``."""
    if chosen is not None:
        if chosen not in {draw.scenario for draw in _draws_of(spec, behavior.id)}:
            raise Refused([f"{behavior.id}: {chosen} is not a drawn scenario"])
        if not _needs(spec, behavior, arm, current, chosen):
            where = "" if arm == Arm.BASELINE else " on this hash"
            raise Refused([f"{behavior.id}: {chosen} {arm.value} already recorded{where}"])
        target = chosen
    else:
        target = next((sc for sc in _candidates(spec, behavior) if _needs(spec, behavior, arm, current, sc)),
                      None)
        if target is None:
            raise Refused([f"{behavior.id}: no scenario needs a {arm.value} run on hash {current[:12]}"])
    if arm == Arm.GREEN and not _runs(spec, behavior=behavior.id, scenario=target, arm=Arm.BASELINE,
                                      recorded=True):
        raise Refused([f"{behavior.id}: {target} has no recorded baseline; run --arm baseline first"])
    return target


# --- run: the scenario tree -------------------------------------------------------------------------------

def _fixture_dir(spec: SkillSpec, scenario: Scenario) -> Optional[Path]:
    """``<plans>/strap/<name>/fixtures/<fixture or SC>/`` when present; a named fixture must exist."""
    folder = _strap_dir(spec.name) / "fixtures" / (scenario.fixture or scenario.id)
    if folder.is_dir():
        return folder
    if scenario.fixture:
        raise Refused([f"{scenario.id}: fixture {_rel(folder)} does not exist"])
    return None


def _lay_fixture(tree: Path, folder: Path) -> str:
    """Overlay ``folder`` on ``tree`` and commit it there, so the run's diff shows only the agent's work."""
    sources = {p.relative_to(folder).as_posix(): p for p in sorted(folder.rglob("*")) if p.is_file()}
    pr.overlay(sources, tree)
    git_out(tree, "add", "-A")
    snapshot = git_out(tree, "write-tree").strip()
    commit = git_out(tree, *FIXTURE_IDENTITY, "commit-tree", snapshot, "-p", "HEAD", "-m", "strap fixture")
    git_out(tree, "update-ref", "--no-deref", "HEAD", commit.strip())
    return commit.strip()


def _mark_scenario(tree: Path) -> None:
    """Write ``freeze_git.SCENARIO_MARKER`` at the root of a throwaway tree, so a driver run inside it
    creates no tags. Written after any fixture commit and ignored through ``info/exclude``, so the runner's
    ``git status`` stays clean and ``git add -A`` skips it; ``changed_paths`` also leaves it out, so it is
    never committed, hashed or seen by a run's checks."""
    (tree / fg.SCENARIO_MARKER).write_text("strap scenario tree\n", encoding="utf-8", newline="\n")
    _exclude_marker(tree)


def _exclude_marker(tree: Path) -> None:
    """Name the root marker in the ``info/exclude`` git reads for ``tree`` (the repository's shared one for
    a linked worktree), once; the anchored pattern matches only a worktree root."""
    found = Path(git_out(tree, "rev-parse", "--git-path", "info/exclude").strip())
    path = found if found.is_absolute() else tree / found
    line = f"/{fg.SCENARIO_MARKER}"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if line in text.splitlines():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lead = "\n" if text and not text.endswith("\n") else ""
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{lead}{line}\n")


def build_tree(start: str, fixture: Optional[Path]) -> Tuple[Path, str]:
    """A throwaway tree at ``start`` with ``fixture`` laid over it; returns the tree and its commit."""
    root = _root()
    tree = pr.make_tree(root, start, active().resolve_worktree_root())
    try:
        commit = _lay_fixture(tree, fixture) if fixture is not None else start
        _mark_scenario(tree)
    except Exception:
        pr.drop_tree(root, tree)
        raise
    return tree.resolve(), commit


def _tree(run: Run) -> Path:
    """The run's working tree as an absolute resolved path; ``Run.tree`` holds it relative to the
    worktree root, so the tracked spec names no machine path."""
    tree = sa.run_tree(run)
    if tree is None:
        raise Refused([f"{run.id} has no working tree"])
    return tree.resolve()


def _live_tree(run: Run) -> Optional[Path]:
    """The run's working tree when it exists on disk, else None."""
    tree = sa.run_tree(run)
    return tree.resolve() if tree is not None and tree.is_dir() else None


def _place(spec: SkillSpec, run: Run, scenario: Scenario) -> Tuple[SkillSpec, Run]:
    """Save ``run`` with a live tree: kept when present, rebuilt at its start, or built fresh."""
    if _live_tree(run) is not None:
        return spec, run
    if run.start:
        tree, start = build_tree(run.start, None)
    else:
        tree, start = build_tree(_start_commit(spec), _fixture_dir(spec, scenario))
    try:
        placed = run.model_copy(update={"tree": sa.tree_name(tree), "start": start})
        return save(_put_run(spec, placed)), placed
    except Exception:
        pr.drop_tree(_root(), tree)
        raise


def runner_lines(name: str, run_id: str, tree: str, init: str) -> List[str]:
    """Header lines of a runner row: the dispatching skill, then the skill under test as TARGET."""
    return [f"agent={RUNNER_AGENT} model={AGENT_MODEL}", f"SKILL: {DISPATCH_SKILL}", f"TARGET: {name}",
            f"RUN: {run_id}", f"TREE: {tree}", f"INIT: {init}"]


def judge_lines(name: str, runs: List[str], spec_path: str) -> List[str]:
    """Header lines of a judge row, in the same order as the runner row."""
    return [f"agent={JUDGE_AGENT} model={AGENT_MODEL}", f"SKILL: {DISPATCH_SKILL}", f"TARGET: {name}",
            f"RUNS: {','.join(runs)}", f"SPEC: {spec_path}"]


def recorded_block(name: str, run_id: str) -> str:
    """The column-1 return block printed by record-run."""
    return "\n".join(["---", "SIGNAL: recorded", f"RUN: {run_id}", f"TARGET: {name}", "---"])


def runner_row(spec: SkillSpec, run: Run) -> str:
    init = f"{launcher()} init {spec.name} --run {run.id}"
    return "\n".join(runner_lines(spec.name, run.id, _tree(run).as_posix(), init))


def _next_run_id(spec: SkillSpec) -> str:
    numbers = [int(run.id[2:]) for run in spec.runs]
    return f"R-{max(numbers, default=0) + 1}"


def cmd_run(args: argparse.Namespace) -> int:
    spec = load(args.name, unlocked=True)
    arm = Arm(args.arm)
    _refuse_frozen_baseline(spec, arm)
    _require_skill_md(spec)
    behavior = _judgment(spec, args.behavior)
    if not _draws_of(spec, behavior.id):
        raise Refused([f"{behavior.id}: never drawn; run draw first"])
    current = skill_hash(spec)
    target = _target(spec, behavior, arm, current, args.scenario)
    open_runs = _runs(spec, behavior=behavior.id, scenario=target, arm=arm, skill_hash=current,
                      recorded=False)
    run = open_runs[-1] if open_runs else Run(id=_next_run_id(spec), behavior=behavior.id, scenario=target,
                                              arm=arm, skill_hash=current)
    spec, run = _place(spec, run, _scenario(behavior, target))
    print(f"run [ready] | {spec.name} | {behavior.id} {target} | {arm.value} | {run.id} "
          f"| hash {current[:12]}")
    print(runner_row(spec, run))
    return 0


# --- init -------------------------------------------------------------------------------------------------

def _rewrite(text: str, source: Path, spec: SkillSpec, run: Run) -> str:
    """``text`` with the skill's variables pointing at ``source`` (and a project skill's
    ``${CLAUDE_PROJECT_DIR}`` at the run tree, where the scenario's writes must land)."""
    return profile_of(spec).rewrite(text, source, _tree(run))


def _skill_text(spec: SkillSpec, run: Run) -> Optional[str]:
    """Green: the working tree's SKILL.md. An edit's baseline: SKILL.md at ``base``. Else none."""
    part = _require_skill_md(spec)
    root = _root()
    if run.arm == Arm.GREEN:
        path = root / part.path
        if not path.is_file():
            raise Refused([f"{run.id}: green needs {part.path}, which does not exist"])
        return _rewrite(path.read_text(encoding="utf-8"), root, spec, run)
    if SpecMode(spec.mode) != SpecMode.EDIT:
        return None
    done = git(root, "show", f"{spec.base}:{part.path}")
    return _rewrite(done.stdout, _tree(run), spec, run) if done.returncode == 0 else None


def _agent_text(spec: SkillSpec, run: Run, scenario: Scenario) -> Optional[str]:
    """The role agent's file: the working tree's for green, the run tree's for baseline.

    A project skill's file gets the same variable rewrite as its SKILL.md.
    """
    if scenario.role == SESSION_ROLE:
        return None
    source = _root() if run.arm == Arm.GREEN else _tree(run)
    profile = profile_of(spec)
    path = source / profile.agents_dir / f"{scenario.role}.md"
    if not path.is_file():
        return (f"{profile.agents_dir}/{scenario.role}.md is absent at the start commit; "
                "play the role from the task alone.")
    text = path.read_text(encoding="utf-8")
    return text if profile.plugin_dir is not None else profile.rewrite(text, source, _tree(run))


def brief(spec: SkillSpec, run: Run, scenario: Scenario) -> str:
    lines = [f"# Scenario run {run.id} | {spec.name} | {run.behavior} {run.scenario} | {run.arm.value}", "",
             f"Working tree: {_tree(run).as_posix()}", "Work only inside the working tree.", "",
             "## Task", "", scenario.task.rstrip(), ""]
    skill = _skill_text(spec, run) if scenario.skill_in_brief else None
    if skill is not None:
        lines += ["## Skill", "", skill.rstrip(), ""]
    agent = _agent_text(spec, run, scenario)
    if agent is not None:
        lines += [f"## Role: {scenario.role}", "", agent.rstrip(), ""]
    lines += ["## Record", "", "Finish with exactly this command; the reply goes on the lines after it, "
              f"closed by a line holding only {REPLY_TAG}.", "",
              f"{launcher()} record-run {spec.name} --run {run.id} <<'{REPLY_TAG}'"]
    return "\n".join(lines)


def _live_run(spec: SkillSpec, run_id: str) -> Run:
    """An unrecorded run whose tree still exists."""
    run = _run_of(spec, run_id)
    if run.recorded:
        raise Refused([f"{run.id} already recorded"])
    if _live_tree(run) is None:
        raise Refused([f"{run.id}: its tree is gone; run `run {spec.name} {run.behavior} --arm "
                       f"{run.arm.value}` to rebuild it"])
    return run


def cmd_init(args: argparse.Namespace) -> int:
    spec = load(args.name)
    run = _live_run(spec, args.run)
    print(brief(spec, run, _scenario_of_run(spec, run)))
    return 0


# --- record-run -------------------------------------------------------------------------------------------

def changed_paths(tree: Path) -> List[str]:
    """Paths ``git status`` reports in ``tree``, untracked files listed one by one; the scenario marker is
    left out."""
    entries = git_out(tree, "status", "--porcelain", "-z", "--untracked-files=all").split("\0")
    paths: List[str] = []
    skip = False
    for entry in entries:
        if skip or len(entry) < 4:
            skip = False
            continue
        paths.append(entry[3:])
        skip = entry[0] in "RC"
    return sorted(set(paths) - {fg.SCENARIO_MARKER})


def _refuse_twin(spec: SkillSpec, run: Run) -> None:
    twins = _runs(spec, behavior=run.behavior, scenario=run.scenario, arm=run.arm, skill_hash=run.skill_hash,
                  recorded=True)
    if twins:
        raise Refused([f"{twins[0].id}: {run.scenario} {run.arm.value} already recorded on this hash"])


def _refuse_frozen_open_run(spec: SkillSpec, run: Run) -> None:
    """A non-green run left open at freeze: drop its tree, since nothing can record it, then refuse."""
    if spec.frozen is None or run.arm == Arm.GREEN:
        return
    tree = _live_tree(run)
    if not run.recorded and tree is not None:
        pr.drop_tree(_root(), tree)
    _refuse_frozen_baseline(spec, run.arm)


def cmd_record_run(args: argparse.Namespace) -> int:
    spec = load(args.name, unlocked=True)
    _refuse_frozen_open_run(spec, _run_of(spec, args.run))
    run = _live_run(spec, args.run)
    _refuse_twin(spec, run)
    tree = _tree(run)
    reply = sys.stdin.read()
    changed = changed_paths(tree)
    head_moved = git_out(tree, "rev-parse", "HEAD").strip() != run.start
    sa.record_run(spec.name, run.id, reply)
    spec = load(args.name)
    recorded = _run_of(spec, run.id)
    checks = sr.evaluate_checks(_scenario_of_run(spec, recorded).checks, recorded.arm, changed,
                                lambda target: (tree / target).exists(), head_moved, reply)
    save(_put_run(spec, recorded.model_copy(update={"diff": changed, "checks": checks})))
    pr.drop_tree(_root(), tree)
    print(recorded_block(spec.name, run.id))
    return 0


# --- judge-row --------------------------------------------------------------------------------------------

def _ungraded(spec: SkillSpec, run: Run) -> List[int]:
    graded = {grade.item for grade in spec.grades if grade.run == run.id}
    return [i for i in range(len(_scenario_of_run(spec, run).judged)) if i not in graded]


def cmd_judge_row(args: argparse.Namespace) -> int:
    spec = load(args.name)
    if not spec.judge:
        raise Refused([f"{spec.name} is not a --judge spec; the session grades it"])
    pending = [run.id for run in spec.runs if run.recorded and _ungraded(spec, run)]
    if not pending:
        raise Refused([f"{spec.name}: no recorded run has an ungraded judged item"])
    print("\n".join(judge_lines(spec.name, pending, sa.spec_path(spec.name).as_posix())))
    return 0


# --- scaffold ---------------------------------------------------------------------------------------------

def cmd_scaffold(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    written = render_parts(spec, _root())
    spec = save(spec.model_copy(update={"parts": planned_parts(spec)}))
    print(f"scaffold [done] | {spec.name} | {len(written)} written | {len(spec.parts)} parts")
    for path in written:
        print(f"wrote: {_rel(path)}")
    bump = profile_of(spec).bump
    if bump is not None:
        print(f"bump: {bump}")
    return 0


# --- retest -----------------------------------------------------------------------------------------------

def _void_retest(spec: SkillSpec, behavior: Behavior) -> bool:
    """True when the latest retest draw has recorded baselines and none of them failed."""
    retests = [d for d in _draws_of(spec, behavior.id) if d.reason == DrawReason.RETEST]
    if not retests:
        return False
    scenario = _scenario(behavior, retests[-1].scenario)
    baselines = _runs(spec, behavior=behavior.id, scenario=scenario.id, arm=Arm.BASELINE, recorded=True)
    return bool(baselines) and not any(sr.baseline_failed(scenario, r, spec.grades) for r in baselines)


def cmd_retest(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    behavior = _judgment(spec, args.behavior)
    failed = [r for r in _runs(spec, behavior=behavior.id, arm=Arm.GREEN, recorded=True)
              if not sr.green_passed(_scenario(behavior, r.scenario), r, spec.grades)]
    if not failed:
        raise Refused([f"{behavior.id}: no failed green"])
    current = skill_hash(spec)
    if failed[-1].skill_hash == current and not _void_retest(spec, behavior):
        raise Refused([f"{behavior.id}: skill unchanged since the failed green (hash {current[:12]})"])
    seed = sr.new_seed()
    try:
        picked = sr.draw_scenario(behavior, [d.scenario for d in _draws_of(spec, behavior.id)], seed)
    except ValueError as exc:
        raise Refused([f"{exc}; add one with add_scenario"]) from None
    draw = Draw(behavior=behavior.id, scenario=picked, seed=seed, reason=DrawReason.RETEST, at=_now())
    states = _with_states(spec, {behavior.id}, BehaviorState.RETEST)
    spec = save(spec.model_copy(update={"draws": [*spec.draws, draw], "behaviors": states}))
    print(f"retest | {behavior.id} -> {picked} | must pass: {', '.join(sr.must_pass(spec, behavior.id))}")
    return 0


# --- freeze -----------------------------------------------------------------------------------------------

def _grade_problems(spec: SkillSpec, behavior: Behavior) -> List[str]:
    """An unclear grade or an ungraded judged item on any recorded run of the behavior."""
    problems: List[str] = []
    for run in _runs(spec, behavior=behavior.id, recorded=True):
        values = [grade.value for grade in spec.grades if grade.run == run.id]
        if GradeValue.UNCLEAR in values:
            problems.append(f"{behavior.id}: unclear grade on {run.id}")
        if _ungraded(spec, run):
            problems.append(f"{behavior.id}: ungraded judged item on {run.id}")
    return problems


def _passed_greens(spec: SkillSpec, behavior: Behavior, current: str) -> Set[str]:
    runs = _runs(spec, behavior=behavior.id, arm=Arm.GREEN, recorded=True, skill_hash=current)
    return {r.scenario for r in runs if sr.green_passed(_scenario(behavior, r.scenario), r, spec.grades)}


def _judgment_gate(spec: SkillSpec, behavior: Behavior, current: str) -> List[str]:
    ident = behavior.id
    if len(behavior.scenarios) < sm.MIN_SCENARIOS:
        return [f"{ident}: fewer than {sm.MIN_SCENARIOS} scenarios"]
    if not _draws_of(spec, ident):
        return [f"{ident}: never drawn"]
    problems = _grade_problems(spec, behavior)
    baselines = _runs(spec, behavior=ident, arm=Arm.BASELINE, recorded=True)
    failed = {r.scenario for r in baselines
              if sr.baseline_failed(_scenario(behavior, r.scenario), r, spec.grades)}
    passed = _passed_greens(spec, behavior, current)
    if not baselines:
        problems.append(f"{ident}: no recorded baseline")
    elif not failed:
        problems.append(f"{ident}: baseline did not fail")
    elif not passed & failed:
        problems.append(f"{ident}: no passing green on the current hash")
    problems += [f"{ident}: {sc} failed green and has not passed on the current hash"
                 for sc in sr.must_pass(spec, ident) if sc not in passed]
    return problems


def _planned_tests_pass(behavior: Behavior) -> bool:
    """Each planned node passes on the working tree, one pytest process per node."""
    root = _root()
    return all(pr.run_pytest([sys.executable, *pr.PYTEST_ARGS, test.node], root).returncode == 0
               for test in behavior.tests)


def _mechanical_gate(behavior: Behavior) -> List[str]:
    if behavior.state not in (BehaviorState.RED, BehaviorState.GREEN):
        return [f"{behavior.id}: red not recorded"]
    if not _planned_tests_pass(behavior):
        return [f"{behavior.id}: planned tests fail"]
    return []


def freeze_problems(spec: SkillSpec, current: str) -> List[str]:
    problems = [] if _skill_md(spec) is not None else [f"{spec.name}: no skill_md part"]
    root = _root()
    problems += [f"{part.path}: part file missing" for part in spec.parts if not (root / part.path).is_file()]
    for behavior in spec.behaviors:
        if behavior.state == BehaviorState.DROPPED:
            continue
        if behavior.kind == BehaviorKind.JUDGMENT:
            problems += _judgment_gate(spec, behavior, current)
        else:
            problems += _mechanical_gate(behavior)
    return problems


def cmd_freeze(args: argparse.Namespace) -> int:
    spec, problems = spec_problems(args.name)
    if spec is None:
        raise Refused(problems)
    sl.refuse_locked(spec)
    if spec.frozen is not None and not args.refreeze:
        raise Refused(["already frozen; after a part change, rerun freeze with --refreeze"])
    previous = spec.frozen or (spec.rounds[-1].frozen if spec.rounds else None)
    current = skill_hash(spec)
    problems += freeze_problems(spec, current)
    if problems:
        raise Refused(problems)
    grader = Grader.JUDGE if spec.judge else Grader.SESSION
    live = {b.id for b in spec.behaviors if b.state != BehaviorState.DROPPED}
    frozen = Frozen(skill_hash=current, grader=grader, at=_now())
    root = _root()
    pending = sl.freeze_pending(root, spec, frozen)
    sl.preflight(root, pending)
    before = spec_bytes(spec.name)
    save(spec.model_copy(update={"frozen": frozen,
                                 "behaviors": _with_states(spec, live, BehaviorState.GREEN)}))
    lines = sl.commit(root, pending, before)
    was = f" | was {previous.skill_hash[:12]}" if previous is not None else ""
    print(f"freeze [done] | {spec.name} | {current[:12]} | grader {grader.value}{was}")
    _print_lines(lines)
    return 0


# --- reopen -----------------------------------------------------------------------------------------------

def _reopen_base_problems(root: Path, spec: SkillSpec, base: str) -> List[str]:
    """The new base must descend from the previous one and hold every part as the working tree has it."""
    problems = []
    if spec.base and git(root, "merge-base", "--is-ancestor", spec.base, base).returncode != 0:
        problems.append(f"base {base[:12]} does not descend from the previous base {spec.base[:12]}")
    paths = [part.path for part in spec.parts]
    missing = [p for p in paths if git(root, "cat-file", "-e", f"{base}:{p}").returncode != 0]
    problems += [f"{p}: not committed at base {base[:12]}; commit the frozen round first" for p in missing]
    present = [p for p in paths if p not in missing]
    if present and git(root, "diff", "--quiet", base, "--", *present).returncode != 0:
        problems.append(f"parts differ from base {base[:12]}; commit the frozen round first")
    return problems


def cmd_reopen(args: argparse.Namespace) -> int:
    """A new round on a frozen or locked spec: the stamp moves into ``rounds``, ``base`` moves to the new
    start, a ``reopen`` entry is written and the new base tagged."""
    spec = load(args.name)
    if spec.frozen is None:
        raise Refused([f"{spec.name} is not frozen; nothing to reopen"])
    root = _root()
    base = _edit_base(root, spec.name, profile_of(spec).skill_md, args.base)
    problems = _reopen_base_problems(root, spec, base)
    if problems:
        raise Refused(problems)
    pending = sl.reopen_pending(root, spec, base)
    sl.preflight(root, pending)
    live = [b.id for b in spec.behaviors if b.state != BehaviorState.DROPPED]
    rounds = [*spec.rounds, Round(base=spec.base, frozen=spec.frozen, behaviors=live)]
    was = spec.frozen.skill_hash
    before = spec_bytes(spec.name)
    spec = save(spec.model_copy(update={"rounds": rounds, "frozen": None, "mode": SpecMode.EDIT,
                                        "base": base}))
    lines = sl.commit(root, pending, before)
    print(f"reopen [done] | {spec.name} | round {len(rounds) + 1} | base {base[:12]} | was {was[:12]}")
    _print_lines(lines)
    return 0


# --- lock and relink --------------------------------------------------------------------------------------

def _contract_tests_pass(spec: SkillSpec) -> bool:
    """Each ``contract_test`` part passes on the working tree, one pytest process per part."""
    root = _root()
    return all(pr.run_pytest([sys.executable, *pr.PYTEST_ARGS, part.path], root).returncode == 0
               for part in spec.parts if part.kind == PartKind.CONTRACT_TEST)


def lock_gate(spec: SkillSpec) -> List[str]:
    """Frozen, not stale, planned and contract tests passing, and the ledger's last freeze at HEAD."""
    if spec.frozen is None:
        return [f"{spec.name} is not frozen; freeze it before lock"]
    stale = stale_line(spec)
    if stale:
        return [stale]
    problems = [f"{b.id}: planned tests fail" for b in spec.behaviors
                if b.kind == BehaviorKind.MECHANICAL and b.state != BehaviorState.DROPPED
                and not _planned_tests_pass(b)]
    if not _contract_tests_pass(spec):
        problems.append(f"{spec.name}: a contract_test part fails")
    return problems + sl.lock_problems(_root(), spec)


def cmd_lock(args: argparse.Namespace) -> int:
    """Lock a Frozen spec on the developer's explicit ask: a ``lock`` entry and its tagged tree."""
    spec = load(args.name)
    problems = lock_gate(spec)
    if problems:
        raise Refused(problems)
    root = _root()
    pending = sl.lock_pending(root, spec)
    sl.preflight(root, pending)
    lines = sl.commit(root, pending)
    entry = pending.entries[-1]
    print(f"lock [done] | {spec.name} | r{entry.round}.{entry.seq} | tree {(entry.tree or '')[:12]}")
    _print_lines(lines)
    return 0


def cmd_relink(args: argparse.Namespace) -> int:
    """Re-point a base lost to a rewrite at its patch-id match (or ``--to``), with a ``relink`` entry."""
    spec = load(args.name)
    root = _root()
    new_base, match = sl.relink_target(root, spec, args.to)
    pending = sl.relink_pending(root, spec, new_base, match)
    sl.preflight(root, pending)
    old = spec.base or ""
    before = spec_bytes(spec.name)
    save(spec.model_copy(update={"base": new_base}))
    try:
        pending = sl.relinked(root, spec, pending)
    except sl.LockRefused:
        before[0].write_bytes(before[1])
        raise
    lines = sl.commit(root, pending, before)
    print(f"relink [done] | {spec.name} | base {old[:12]} -> {new_base[:12]} | {match}")
    _print_lines(lines)
    return 0


# --- api --------------------------------------------------------------------------------------------------

def _skill_api() -> ModuleType:
    """The sibling ``skill_api.py`` launcher, imported by path."""
    spec = importlib.util.spec_from_file_location("strap_skill_api", SCRIPT_DIR / "skill_api.py")
    if spec is None or spec.loader is None:
        raise Refused([f"cannot load {(SCRIPT_DIR / 'skill_api.py').as_posix()}"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_api(args: argparse.Namespace) -> int:
    sa.spec_path(args.name)
    return int(_skill_api().main(["--repo", str(_root()), "strap_api", args.name]))


# --- CLI --------------------------------------------------------------------------------------------------

def _validation_lines(exc: ValidationError) -> List[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or 'spec'}: {err['msg']}" for err in exc.errors()]


def _problem_lines(exc: BaseException) -> List[str]:
    if isinstance(exc, ValidationError):
        lines = _validation_lines(exc)
    else:
        lines = list(getattr(exc, "problems", None) or [str(exc)])
    return [" ".join(line.split()) for line in lines]


def _named(sub: Any, command: str, text: str) -> argparse.ArgumentParser:
    parser = sub.add_parser(command, help=text)
    parser.add_argument("name", help="Skill name (lower-case, hyphenated).")
    return parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="strap.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help="Directory inside the project (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    new = _named(sub, "new", "Create the spec, or resume an existing one.")
    new.add_argument("--edit", action="store_true", help="Edit an existing skill.")
    new.add_argument("--base", help="Ancestor of HEAD the edit starts from (default: HEAD).")
    new.add_argument("--judge", action="store_true", help="Grade through the judge agent.")
    for command, text in (("check", "Validate the spec and lint its parts."),
                          ("red", "Run the mechanical planned tests red."), ("draw", "Draw scenarios."),
                          ("judge-row", "Print the judge dispatch row."), ("scaffold", "Render the parts."),
                          ("api", "Run stdin against strap_api.")):
        _named(sub, command, text)
    freeze = _named(sub, "freeze", "Apply the final gate.")
    freeze.add_argument("--refreeze", action="store_true",
                        help="Freeze a frozen spec again after a part change; every gate runs again.")
    reopen = _named(sub, "reopen", "Start a new round of behaviors on a frozen or locked spec.")
    reopen.add_argument("--base", help="Ancestor of HEAD the new round starts from (default: HEAD).")
    _named(sub, "lock", "Lock a frozen spec (only on the developer's explicit ask).")
    relink = _named(sub, "relink", "Re-point a base lost to a rewrite.")
    relink.add_argument("--to", help="The commit to re-point at (default: the patch-id match on HEAD).")
    run = _named(sub, "run", "Create a scenario run and print the runner row.")
    run.add_argument("behavior", help="Behavior id, such as B1.")
    run.add_argument("--arm", required=True, choices=[arm.value for arm in Arm])
    run.add_argument("--scenario", help="A drawn scenario id (default: the next one that needs the arm).")
    for command, text in (("init", "Print the runner's brief."), ("record-run", "Record a reply (stdin).")):
        _named(sub, command, text).add_argument("--run", required=True, help="Run id, such as R-1.")
    _named(sub, "retest", "Draw a fresh scenario after a failed green.").add_argument("behavior")
    return parser


COMMANDS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "new": cmd_new, "check": cmd_check, "red": cmd_red, "draw": cmd_draw, "run": cmd_run, "init": cmd_init,
    "record-run": cmd_record_run, "judge-row": cmd_judge_row, "scaffold": cmd_scaffold,
    "retest": cmd_retest, "freeze": cmd_freeze, "reopen": cmd_reopen, "lock": cmd_lock,
    "relink": cmd_relink, "api": cmd_api,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a problem."""
    for stream in (sys.stdout, sys.stdin):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        activate(load_config(project_root(args.repo)))
        return COMMANDS[args.command](args)
    except (Refused, *PROBLEMS) as exc:
        sys.stderr.write("".join(f"problem: {line}\n" for line in _problem_lines(exc)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
