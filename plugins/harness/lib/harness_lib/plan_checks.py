"""Checks a plan's claims against the tree: anchors, lint over commands and decisions, sweeps.

Each function returns one problem line per defect, so a driver prints them all at once. Anchors and sweeps
read the working tree of ``root``; lint reads the plan plus the tree, to tell a test file from a folder and
to require each test node's file to exist in the tree or among the planned tests.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from harness_lib.plan_doc import planned_tests_dir
from harness_lib.plan_models import ActionPlan, Anchor, Decision

_AT = re.compile(r"^(?P<path>[^:]+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
# 7-40 hex characters with at least one letter: all-digit tokens (counts, run ids, dates) are not SHAs.
_SHA = re.compile(r"\b(?=[0-9]*[a-f])[0-9a-f]{7,40}\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_SHELL_STOPS = frozenset({"|", "||", "&&", ";", ">", ">>", "<", "2>", "&"})
# pytest options whose next token is a value, not a path.
_VALUE_OPTIONS = frozenset({"-k", "-m", "-p", "-c", "-o", "--deselect", "--ignore", "--rootdir",
                            "--basetemp", "--confcutdir", "--junitxml", "-W"})


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip()


# --- anchors ----------------------------------------------------------------------------------------------

def anchors_of(plan: ActionPlan) -> Iterator[Tuple[str, Anchor]]:
    """``(owner, anchor)`` for every item anchor and every format source."""
    for item in plan.items:
        for anchor in item.anchors:
            yield item.id, anchor
    for fmt in plan.formats:
        yield f"format {fmt.name}", fmt.source


def _lines(root: Path, rel: str) -> Optional[List[str]]:
    path = root / rel
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else None


def anchor_problem(root: Path, owner: str, anchor: Anchor) -> Optional[str]:
    """None when the anchor's text sits in its line range, else the problem."""
    at, expect = anchor.at, anchor.expect
    match = _AT.match(at)
    if not match:
        return f"anchor {owner} {at}: not a path:line or path:start-end"
    lines = _lines(root, match["path"])
    if lines is None:
        return f"anchor {owner} {at}: no such file"
    start, end = int(match["start"]), int(match["end"] or match["start"])
    if start < 1 or end < start or end > len(lines):
        return f"anchor {owner} {at}: the file has {len(lines)} lines"
    found = _squash(" ".join(lines[start - 1:end]))
    if _squash(expect) in found:
        return None
    where = f"line {start} reads" if start == end else f"lines {start}-{end} read"
    return f"anchor {owner} {at}: {expect!r} not found; {where} {found[:120]!r}"


def anchor_problems(plan: ActionPlan, root: Path) -> List[str]:
    return [p for owner, a in anchors_of(plan) if (p := anchor_problem(root, owner, a))]


# --- commands ---------------------------------------------------------------------------------------------

def _tokens(command: str) -> List[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _pytest_args(tokens: Sequence[str]) -> Optional[List[str]]:
    """Positional arguments after ``pytest`` up to a shell operator, or None when pytest is not run."""
    names = ("pytest", "/pytest", "\\pytest")
    start = next((n for n, t in enumerate(tokens) if t.endswith(names)), None)
    if start is None:
        return None
    args: List[str] = []
    skip = False
    for token in tokens[start + 1:]:
        if token in _SHELL_STOPS:
            break
        if skip or token.startswith("-"):
            skip = not skip and token in _VALUE_OPTIONS
            continue
        args.append(token)
    return args


def pytest_problem(owner: str, command: str, root: Path) -> Optional[str]:
    args = _pytest_args(_tokens(command))
    if args is None:
        return None
    if not args:
        return f"{owner} command runs pytest without naming a test file"
    folders = [a for a in args if (root / a.split("::")[0]).is_dir()]
    if folders:
        return f"{owner} command runs pytest on directory {', '.join(folders)}; name test files"
    return None


def sha_problem(owner: str, command: str) -> Optional[str]:
    hits = _SHA.findall(command)
    if not hits:
        return None
    return f"{owner} command names commit {', '.join(hits)}; use {{base}} or git merge-base"


def command_problems(plan: ActionPlan, root: Path) -> List[str]:
    out: List[str] = []
    for item in plan.items:
        for cmd in item.commands:
            found = (sha_problem(item.id, cmd.run), pytest_problem(item.id, cmd.run, root))
            out.extend(p for p in found if p)
    return out


# --- items and tests --------------------------------------------------------------------------------------

def duplicate_problems(plan: ActionPlan) -> List[str]:
    ids = [i.id for i in plan.items]
    return [f"item id {i} is used {ids.count(i)} times" for i in dict.fromkeys(ids) if ids.count(i) > 1]


def dependency_problems(plan: ActionPlan) -> List[str]:
    known = {i.id for i in plan.items}
    out = [f"{i.id} depends on unknown item {dep}"
           for i in plan.items for dep in i.dependencies or [] if dep not in known]
    cycle = _cycle_members(plan, known)
    return out + ([f"dependency cycle among {', '.join(cycle)}"] if cycle else [])


def _cycle_members(plan: ActionPlan, known: Set[str]) -> List[str]:
    """Items on a dependency cycle: the Kahn leftovers that reach themselves, not those merely behind one."""
    left = _kahn_leftovers(plan, known)
    return [key for key in sorted(left) if key in _reachable(left, key)]


def _kahn_leftovers(plan: ActionPlan, known: Set[str]) -> Dict[str, Set[str]]:
    """Items left after repeatedly removing items whose known dependencies are all removed (Kahn)."""
    deps = {i.id: {d for d in i.dependencies or [] if d in known} for i in plan.items}
    while True:
        free = [k for k, v in deps.items() if not v]
        if not free:
            return deps
        for key in free:
            del deps[key]
        for pending in deps.values():
            pending.difference_update(free)


def _reachable(deps: Dict[str, Set[str]], start: str) -> Set[str]:
    """Every item reachable from ``start`` by following dependencies, one step or more."""
    seen: Set[str] = set()
    stack = list(deps.get(start, ()))
    while stack:
        key = stack.pop()
        if key not in seen:
            seen.add(key)
            stack.extend(deps.get(key, ()))
    return seen


def planned_test_problems(plan: ActionPlan, root: Path, plans_dir: Path) -> List[str]:
    """A test node's file exists in the tree or is planned under ``<plans_dir>/<plan_id>/tests/``."""
    planned = planned_tests_dir(plans_dir, plan.plan_id)
    out: List[str] = []
    for item in plan.items:
        for test in item.tests:
            rel = test.node.split("::")[0]
            if not (root / rel).is_file() and not (planned / rel).is_file():
                where = (planned / rel).relative_to(root).as_posix() if planned.is_relative_to(root) else rel
                out.append(f"{item.id} test {test.node}: {rel} is neither in the tree "
                           f"nor planned at {where}")
    return out


# --- decisions and values ---------------------------------------------------------------------------------

def _option_owner(plan: ActionPlan) -> Dict[str, Decision]:
    return {o.id: d for d in plan.decisions for o in d.options}


def decision_problems(plan: ActionPlan) -> List[str]:
    out: List[str] = []
    seen: List[str] = [o.id for d in plan.decisions for o in d.options]
    out.extend(f"option id {o} is used {seen.count(o)} times"
               for o in dict.fromkeys(seen) if seen.count(o) > 1)
    for d in plan.decisions:
        if d.chosen is not None and d.chosen not in {o.id for o in d.options}:
            out.append(f"{d.id} chose {d.chosen}, which is not one of its options")
    return out


def value_problems(plan: ActionPlan) -> List[str]:
    owners = _option_owner(plan)
    out: List[str] = []
    for value in plan.values:
        for option in value.assumes:
            out.extend(_assumption_problem(value.name, option, owners))
    return out


def _assumption_problem(name: str, option: str, owners: Dict[str, Decision]) -> List[str]:
    decision = owners.get(option)
    if decision is None:
        return [f"value {name} assumes unknown option {option}"]
    if decision.chosen is None or decision.chosen == option:
        return []
    return [f"value {name} assumes {option}, which {decision.id} rejected (chose {decision.chosen}); "
            "recompute it or drop the assumption"]


def open_decisions(plan: ActionPlan) -> List[str]:
    return [f"{d.id}: {d.question}" for d in plan.decisions if d.chosen is None]


def lint_problems(plan: ActionPlan, root: Path, plans_dir: Path) -> List[str]:
    """Every plan-internal defect, plus commands and test files checked against the tree."""
    return (duplicate_problems(plan) + dependency_problems(plan) + decision_problems(plan)
            + value_problems(plan) + command_problems(plan, root)
            + planned_test_problems(plan, root, plans_dir))


# --- sweeps -----------------------------------------------------------------------------------------------

def sweep_hits(root: Path, pattern: str, skip_prefix: str) -> Tuple[Set[str], Optional[str]]:
    """Files (tracked or untracked, not ignored) matching ``pattern``, minus ``skip_prefix``; or an error."""
    done = subprocess.run(["git", "grep", "-z", "-l", "-I", "-E", "--untracked", "-e", pattern], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode not in (0, 1):
        return set(), done.stderr.strip() or f"exit {done.returncode}"
    prefix = skip_prefix.rstrip("/") + "/"
    return {p for p in done.stdout.split("\0") if p and not p.startswith(prefix)}, None


def sweep_problems(plan: ActionPlan, root: Path, plans_prefix: str) -> List[str]:
    """Hits the sweep does not classify, and classified files without a hit."""
    out: List[str] = []
    for sweep in plan.sweeps:
        sid, classified = sweep.id, set(sweep.hits)
        hits, error = sweep_hits(root, sweep.pattern, plans_prefix)
        if error:
            out.append(f"sweep {sid}: git grep failed: {error}")
            continue
        out.extend(f"sweep {sid}: {p} has hits but no classification" for p in sorted(hits - classified))
        out.extend(f"sweep {sid}: {p} is classified but has no hit" for p in sorted(classified - hits))
    return out
