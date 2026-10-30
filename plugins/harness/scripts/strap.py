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
    prints ``open:`` for each judgment behavior short of scenarios.
``red <name>``
    Run the mechanical behaviors' planned tests on a throwaway tree; each must fail as planned.
``draw <name>``
    One seeded scenario per judgment behavior without a draw; final.
``run <name> <B> --arm baseline|green [--scenario SC]``
    Create (or re-print) a run, build its scenario tree and print the runner dispatch row.
``init <name> --run R``
    The runner's brief, ending with the exact ``record-run`` command.
``record-run <name> --run R``
    Store the reply read from stdin, evaluate the checks against the tree, then drop the tree.
``judge-row <name>``
    The judge dispatch row for every recorded run with an ungraded judged item (``--judge`` specs).
``scaffold <name>``
    Render the planned parts and record them in the spec.
``retest <name> <B>``
    After a failed green and a skill change, draw one fresh scenario of the behavior.
``freeze <name>``
    The final gate; stamps the skill hash and the grader.
``api <name>``
    Run stdin code with the public names of ``harness_lib.strap_api`` and ``name`` bound.

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

from harness_lib import plan_red as pr
from harness_lib import strap_api as sa
from harness_lib import strap_models as sm
from harness_lib import strap_runs as sr
from harness_lib.branch_capture import CaptureError, git, git_out
from harness_lib.config import active, activate, load_config
from harness_lib.project import project_root
from harness_lib.strap_lint import lint_python, lint_skill
from harness_lib.strap_models import (
    Arm, Behavior, BehaviorKind, BehaviorState, Draw, DrawReason, Frozen, Grader, GradeValue, Part, PartKind,
    Run, Scenario, SkillSpec, SpecMode,
)
from harness_lib.strap_scaffold import find_plugin_dir, planned_parts, render_parts

PROBLEMS = (CaptureError, ValueError, OSError)
PLUGIN_NAME = "harness"
RUNNER_AGENT = "harness:strap-scenario-runner"
JUDGE_AGENT = "harness:strap-judge"
AGENT_MODEL = "sonnet"
SESSION_ROLE = "session"
SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
TAMPERED = "driver-owned fields changed outside strap.py"
REPLY_TAG = "REPLY"
FIXTURE_IDENTITY = ("-c", "user.name=strap", "-c", "user.email=strap@localhost")
PLUGIN_VAR = "${CLAUDE_PLUGIN_ROOT}"
SKILL_DIR_VAR = "${CLAUDE_SKILL_DIR}"


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

def load(name: str, writable: bool = False) -> SkillSpec:
    """The stored spec; refused when missing, hand-edited in driver-owned fields, or frozen (``writable``)."""
    path = sa.spec_path(name)
    if not path.is_file():
        raise Refused([f"no spec for {name} at {_rel(path)}; run new first"])
    spec = sm.load_spec(path)
    if spec.driver_digest != sm.driver_digest(spec):
        raise Refused([TAMPERED])
    if writable and spec.frozen is not None:
        raise Refused([f"{name} is frozen"])
    return spec


def save(spec: SkillSpec) -> SkillSpec:
    """Re-validate ``spec`` from its dump, stamp a fresh driver digest and write it."""
    checked = SkillSpec.model_validate(spec.model_dump())
    stamped = checked.model_copy(update={"driver_digest": sm.driver_digest(checked)})
    path = sa.spec_path(stamped.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sm.dump_spec(stamped), encoding="utf-8", newline="\n")
    return stamped


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


def _require_skill_md(spec: SkillSpec) -> Part:
    part = _skill_md(spec)
    if part is None:
        raise Refused([f"{spec.name}: no skill_md part"])
    return part


def skill_hash(spec: SkillSpec) -> str:
    """Content hash of every part file, read from the project's working tree."""
    return sr.content_hash(_root(), [part.path for part in spec.parts])


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


def _edit_parts(root: Path, spec: SkillSpec, skill_rel: str) -> List[Part]:
    """The skill's tracked folder files, plus its models, API, driver and contract test when present."""
    folder = f"{spec.plugin_dir}/skills/{spec.name}"
    tracked = [p for p in git_out(root, "ls-files", "-z", "--", folder).split("\0") if p]
    parts = [Part(kind=PartKind.SKILL_MD if rel == skill_rel else PartKind.REFERENCE, path=rel)
             for rel in sorted(tracked)]
    snake = spec.name.replace("-", "_")
    extra = [(PartKind.MODELS, f"{spec.plugin_dir}/lib/harness_lib/{snake}_models.py"),
             (PartKind.API, f"{spec.plugin_dir}/lib/harness_lib/{snake}_api.py"),
             (PartKind.DRIVER, f"{spec.plugin_dir}/scripts/{snake}.py")]
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
    plugin_dir = _rel(find_plugin_dir(root, PLUGIN_NAME))
    skill_rel = f"{plugin_dir}/skills/{args.name}/SKILL.md"
    base: Optional[str] = None
    if args.edit:
        base = _edit_base(root, args.name, skill_rel, args.base)
    elif (root / skill_rel).is_file():
        raise Refused([f"{args.name} exists; use --edit"])
    spec = SkillSpec(name=args.name, mode=SpecMode.EDIT if args.edit else SpecMode.NEW, base=base,
                     judge=args.judge, plugin_dir=plugin_dir)
    if args.edit:
        spec = spec.model_copy(update={"parts": _edit_parts(root, spec, skill_rel)})
    spec = save(spec)
    detail = f"edit from {base[:12]} | {len(spec.parts)} parts" if base else "new"
    print(f"new [done] | {spec.name} | {detail} | judge {spec.judge} | {_rel(sa.spec_path(spec.name))}")
    return 0


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
            problems += lint_skill(root / spec.plugin_dir, spec.name)
        elif target.suffix == ".py":
            problems += lint_python(target)
    return problems


def _role_problems(spec: SkillSpec) -> List[str]:
    agents = _root() / spec.plugin_dir / "agents"
    return [f"{sc.id}: role {sc.role} has no agents/{sc.role}.md"
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
    return spec, problems + _lint_problems(spec) + _role_problems(spec)


def cmd_check(args: argparse.Namespace) -> int:
    spec, problems = spec_problems(args.name)
    if spec is None or problems:
        raise Refused(problems)
    short = [b for b in spec.behaviors if b.kind == BehaviorKind.JUDGMENT
             and b.state != BehaviorState.DROPPED and len(b.scenarios) < sm.MIN_SCENARIOS]
    for behavior in short:
        print(f"open: {behavior.id} | {len(behavior.scenarios)} of {sm.MIN_SCENARIOS} scenarios")
    print(f"check [ok] | {spec.name} | {len(spec.behaviors)} behaviors | {len(short)} open")
    return 0


# --- red --------------------------------------------------------------------------------------------------

def _start_commit(spec: SkillSpec) -> str:
    """The commit runs and red start from: an edit's base, else HEAD."""
    return spec.base or git_out(_root(), "rev-parse", "HEAD").strip()


def _red_plan(spec: SkillSpec) -> Dict[str, Any]:
    """The mechanical behaviors in the item shape ``plan_red`` reads; ``plan_id`` is the skill name."""
    items = [{"id": b.id, "status": "PENDING",
              "tests": [{"node": t.node, "red": sm.RedException(t.red).value} for t in b.tests]}
             for b in spec.behaviors
             if b.kind == BehaviorKind.MECHANICAL and b.state != BehaviorState.DROPPED and b.tests]
    return {"plan_id": spec.name, "items": items}


def red_results(spec: SkillSpec) -> List[pr.RedResult]:
    """Planned nodes run on a throwaway tree at the start commit, planned test files laid over it."""
    plan = _red_plan(spec)
    if not plan["items"]:
        return []
    root = _root()
    tree = pr.make_tree(root, _start_commit(spec), active().resolve_worktree_root())
    try:
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


def build_tree(start: str, fixture: Optional[Path]) -> Tuple[Path, str]:
    """A throwaway tree at ``start`` with ``fixture`` laid over it; returns the tree and its commit."""
    root = _root()
    tree = pr.make_tree(root, start, active().resolve_worktree_root())
    try:
        commit = _lay_fixture(tree, fixture) if fixture is not None else start
    except Exception:
        pr.drop_tree(root, tree)
        raise
    return tree.resolve(), commit


def _place(spec: SkillSpec, run: Run, scenario: Scenario) -> Tuple[SkillSpec, Run]:
    """Save ``run`` with a live tree: kept when present, rebuilt at its start, or built fresh."""
    if run.tree and Path(run.tree).is_dir():
        return spec, run
    if run.start:
        tree, start = build_tree(run.start, None)
    else:
        tree, start = build_tree(_start_commit(spec), _fixture_dir(spec, scenario))
    placed = run.model_copy(update={"tree": tree.as_posix(), "start": start})
    try:
        return save(_put_run(spec, placed)), placed
    except Exception:
        pr.drop_tree(_root(), tree)
        raise


def runner_row(spec: SkillSpec, run: Run) -> str:
    return "\n".join([f"agent={RUNNER_AGENT} model={AGENT_MODEL}", f"SKILL: {spec.name}", f"RUN: {run.id}",
                      f"TREE: {run.tree}", f"INIT: {launcher()} init {spec.name} --run {run.id}"])


def _next_run_id(spec: SkillSpec) -> str:
    numbers = [int(run.id[2:]) for run in spec.runs]
    return f"R-{max(numbers, default=0) + 1}"


def cmd_run(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    _require_skill_md(spec)
    behavior = _judgment(spec, args.behavior)
    if not _draws_of(spec, behavior.id):
        raise Refused([f"{behavior.id}: never drawn; run draw first"])
    arm, current = Arm(args.arm), skill_hash(spec)
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

def _rewrite(text: str, source: Path, spec: SkillSpec, skill_rel: str) -> str:
    """``text`` with the plugin and skill-dir variables pointing at ``source``'s copy of the plugin."""
    plugin = (source / spec.plugin_dir).as_posix()
    skill_dir = (source / skill_rel).parent.as_posix()
    return text.replace(PLUGIN_VAR, plugin).replace(SKILL_DIR_VAR, skill_dir)


def _skill_text(spec: SkillSpec, run: Run) -> Optional[str]:
    """Green: the working tree's SKILL.md. An edit's baseline: SKILL.md at ``base``. Else none."""
    part = _require_skill_md(spec)
    root = _root()
    if run.arm == Arm.GREEN:
        path = root / part.path
        if not path.is_file():
            raise Refused([f"{run.id}: green needs {part.path}, which does not exist"])
        return _rewrite(path.read_text(encoding="utf-8"), root, spec, part.path)
    if SpecMode(spec.mode) != SpecMode.EDIT:
        return None
    done = git(root, "show", f"{spec.base}:{part.path}")
    return _rewrite(done.stdout, Path(run.tree), spec, part.path) if done.returncode == 0 else None


def _agent_text(spec: SkillSpec, run: Run, scenario: Scenario) -> Optional[str]:
    """The role agent's file: the working tree's for green, the run tree's for baseline."""
    if scenario.role == SESSION_ROLE:
        return None
    source = _root() if run.arm == Arm.GREEN else Path(run.tree)
    path = source / spec.plugin_dir / "agents" / f"{scenario.role}.md"
    if not path.is_file():
        return f"agents/{scenario.role}.md is absent at the start commit; play the role from the task alone."
    return path.read_text(encoding="utf-8")


def brief(spec: SkillSpec, run: Run, scenario: Scenario) -> str:
    lines = [f"# Scenario run {run.id} | {spec.name} | {run.behavior} {run.scenario} | {run.arm.value}", "",
             f"Working tree: {run.tree}", "Work only inside the working tree.", "", "## Task", "",
             scenario.task.rstrip(), ""]
    skill = _skill_text(spec, run)
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
    if not run.tree or not Path(run.tree).is_dir():
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
    """Paths ``git status`` reports in ``tree``, untracked files listed one by one."""
    entries = git_out(tree, "status", "--porcelain", "-z", "--untracked-files=all").split("\0")
    paths: List[str] = []
    skip = False
    for entry in entries:
        if skip or len(entry) < 4:
            skip = False
            continue
        paths.append(entry[3:])
        skip = entry[0] in "RC"
    return sorted(set(paths))


def _refuse_twin(spec: SkillSpec, run: Run) -> None:
    twins = _runs(spec, behavior=run.behavior, scenario=run.scenario, arm=run.arm, skill_hash=run.skill_hash,
                  recorded=True)
    if twins:
        raise Refused([f"{twins[0].id}: {run.scenario} {run.arm.value} already recorded on this hash"])


def cmd_record_run(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    run = _live_run(spec, args.run)
    _refuse_twin(spec, run)
    tree = Path(run.tree)
    reply = sys.stdin.read()
    changed = changed_paths(tree)
    head_moved = git_out(tree, "rev-parse", "HEAD").strip() != run.start
    sa.record_run(spec.name, run.id, reply)
    spec = load(args.name, writable=True)
    recorded = _run_of(spec, run.id)
    checks = sr.evaluate_checks(_scenario_of_run(spec, recorded).checks, recorded.arm, changed,
                                lambda target: (tree / target).exists(), head_moved, recorded.reply)
    save(_put_run(spec, recorded.model_copy(update={"diff": changed, "checks": checks})))
    pr.drop_tree(_root(), tree)
    print("\n".join(["```text", "SIGNAL: recorded", f"RUN: {run.id}", f"SKILL: {spec.name}", "```"]))
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
    print("\n".join([f"agent={JUDGE_AGENT} model={AGENT_MODEL}", f"SKILL: {spec.name}",
                     f"RUNS: {','.join(pending)}", f"SPEC: {sa.spec_path(spec.name).as_posix()}"]))
    return 0


# --- scaffold ---------------------------------------------------------------------------------------------

def cmd_scaffold(args: argparse.Namespace) -> int:
    spec = load(args.name, writable=True)
    written = render_parts(spec, _root())
    spec = save(spec.model_copy(update={"parts": planned_parts(spec)}))
    print(f"scaffold [done] | {spec.name} | {len(written)} written | {len(spec.parts)} parts")
    for path in written:
        print(f"wrote: {_rel(path)}")
    print(f"bump: {spec.plugin_dir}/.claude-plugin/plugin.json")
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
    if spec.frozen is not None:
        raise Refused(["already frozen"])
    current = skill_hash(spec)
    problems += freeze_problems(spec, current)
    if problems:
        raise Refused(problems)
    grader = Grader.JUDGE if spec.judge else Grader.SESSION
    live = {b.id for b in spec.behaviors if b.state != BehaviorState.DROPPED}
    frozen = Frozen(skill_hash=current, grader=grader, at=_now())
    save(spec.model_copy(update={"frozen": frozen,
                                 "behaviors": _with_states(spec, live, BehaviorState.GREEN)}))
    print(f"freeze [done] | {spec.name} | {current[:12]} | grader {grader.value}")
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
                          ("freeze", "Apply the final gate."), ("api", "Run stdin against strap_api.")):
        _named(sub, command, text)
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
    "retest": cmd_retest, "freeze": cmd_freeze, "api": cmd_api,
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
