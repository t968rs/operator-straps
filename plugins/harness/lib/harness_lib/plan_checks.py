"""Checks a plan's claims against the tree: anchors, lint over commands and decisions, sweeps.

Each function returns one problem line per defect, so a driver prints them all at once. Anchors and sweeps
read the working tree of ``root``; lint reads the plan, plus the tree only to tell a test file from a folder.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from harness_lib.plan_doc import items_of, planned_tests_dir

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

def anchors_of(plan: Mapping[str, Any]) -> Iterator[Tuple[str, Mapping[str, Any]]]:
    """``(owner, anchor)`` for every item anchor and every format source."""
    for item in items_of(plan):
        for anchor in item.get("anchors") or []:
            yield str(item.get("id")), anchor
    for fmt in plan.get("formats") or []:
        if isinstance(fmt, dict) and isinstance(fmt.get("source"), dict):
            yield f"format {fmt.get('name')}", fmt["source"]


def _lines(root: Path, rel: str) -> Optional[List[str]]:
    path = root / rel
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else None


def anchor_problem(root: Path, owner: str, anchor: Mapping[str, Any]) -> Optional[str]:
    """None when the anchor's text sits in its line range, else the problem."""
    at, expect = str(anchor.get("at")), str(anchor.get("expect"))
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


def anchor_problems(plan: Mapping[str, Any], root: Path) -> List[str]:
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


def command_problems(plan: Mapping[str, Any], root: Path) -> List[str]:
    out: List[str] = []
    for item in items_of(plan):
        for cmd in item.get("commands") or []:
            run, owner = str(cmd.get("run", "")), str(item.get("id"))
            out.extend(p for p in (sha_problem(owner, run), pytest_problem(owner, run, root)) if p)
    return out


# --- items and tests --------------------------------------------------------------------------------------

def duplicate_problems(plan: Mapping[str, Any]) -> List[str]:
    ids = [str(i.get("id")) for i in items_of(plan)]
    return [f"item id {i} is used {ids.count(i)} times" for i in dict.fromkeys(ids) if ids.count(i) > 1]


def dependency_problems(plan: Mapping[str, Any]) -> List[str]:
    known = {str(i.get("id")) for i in items_of(plan)}
    out = [f"{i.get('id')} depends on unknown item {dep}"
           for i in items_of(plan) for dep in i.get("dependencies") or [] if dep not in known]
    cycle = _cycle_members(plan, known)
    return out + ([f"dependency cycle among {', '.join(cycle)}"] if cycle else [])


def _cycle_members(plan: Mapping[str, Any], known: Set[str]) -> List[str]:
    """Items left after repeatedly removing items whose known dependencies are all removed (Kahn)."""
    deps = {str(i.get("id")): {d for d in i.get("dependencies") or [] if d in known} for i in items_of(plan)}
    while True:
        free = [k for k, v in deps.items() if not v]
        if not free:
            return sorted(deps)
        for key in free:
            del deps[key]
        for pending in deps.values():
            pending.difference_update(free)


def planned_test_problems(plan: Mapping[str, Any], root: Path, plans_dir: Path) -> List[str]:
    """A test node's file exists in the tree or is planned under ``<plans_dir>/<plan_id>/tests/``."""
    planned = planned_tests_dir(plans_dir, str(plan.get("plan_id")))
    out: List[str] = []
    for item in items_of(plan):
        for test in item.get("tests") or []:
            node = str(test.get("node"))
            rel = node.split("::")[0]
            if not (root / rel).is_file() and not (planned / rel).is_file():
                where = (planned / rel).relative_to(root).as_posix() if planned.is_relative_to(root) else rel
                out.append(f"{item.get('id')} test {node}: {rel} is neither in the tree "
                           f"nor planned at {where}")
    return out


# --- decisions and values ---------------------------------------------------------------------------------

def _decisions(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [d for d in plan.get("decisions") or [] if isinstance(d, dict)]


def _option_owner(plan: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(o.get("id")): d for d in _decisions(plan) for o in d.get("options") or []}


def decision_problems(plan: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    seen: List[str] = [str(o.get("id")) for d in _decisions(plan) for o in d.get("options") or []]
    out.extend(f"option id {o} is used {seen.count(o)} times"
               for o in dict.fromkeys(seen) if seen.count(o) > 1)
    for d in _decisions(plan):
        own = {str(o.get("id")) for o in d.get("options") or []}
        if d.get("chosen") is not None and d.get("chosen") not in own:
            out.append(f"{d.get('id')} chose {d.get('chosen')}, which is not one of its options")
    return out


def value_problems(plan: Mapping[str, Any]) -> List[str]:
    owners = _option_owner(plan)
    out: List[str] = []
    for value in plan.get("values") or []:
        for option in value.get("assumes") or []:
            out.extend(_assumption_problem(str(value.get("name")), option, owners))
    return out


def _assumption_problem(name: str, option: str, owners: Mapping[str, Mapping[str, Any]]) -> List[str]:
    decision = owners.get(option)
    if decision is None:
        return [f"value {name} assumes unknown option {option}"]
    chosen = decision.get("chosen")
    if chosen is None or chosen == option:
        return []
    return [f"value {name} assumes {option}, which {decision.get('id')} rejected (chose {chosen}); "
            "recompute it or drop the assumption"]


def open_decisions(plan: Mapping[str, Any]) -> List[str]:
    return [f"{d.get('id')}: {d.get('question')}" for d in _decisions(plan) if d.get("chosen") is None]


def lint_problems(plan: Mapping[str, Any], root: Path, plans_dir: Path) -> List[str]:
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


def sweep_problems(plan: Mapping[str, Any], root: Path, plans_prefix: str) -> List[str]:
    """Hits the sweep does not classify, and classified files without a hit."""
    out: List[str] = []
    for sweep in plan.get("sweeps") or []:
        sid, classified = sweep.get("id"), set(sweep.get("hits") or {})
        hits, error = sweep_hits(root, str(sweep.get("pattern")), plans_prefix)
        if error:
            out.append(f"sweep {sid}: git grep failed: {error}")
            continue
        out.extend(f"sweep {sid}: {p} has hits but no classification" for p in sorted(hits - classified))
        out.extend(f"sweep {sid}: {p} is classified but has no hit" for p in sorted(classified - hits))
    return out
