"""A plan's planned registry entries: plan data, applied by ``red`` and per item, never committed ahead.

A project whose pytest refuses an unregistered test file needs each planned test's registry entry before
``red`` can run it. The entry lives beside the planned tests, at
``<plans dir>/<plan_id>/registry_entries.json`` (``{"plan": <id>, "entries": [<registry entry dump>, ...]}``,
each entry with a ``file``), so the live registry never lists a file that does not exist yet, and the plan's
freeze tree carries the entries with the tests.

The registry format stays the project's: the configured ``tests.planned_registry`` argv upserts a list of
entries, with ``{entries}`` replaced by a JSON file holding that list and ``{registry}`` by the registry's
absolute path. ``registered`` reads only the ``file`` of each ``tests`` row, the shape pr-review reads.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from harness_lib.plan_doc import PlanError
from harness_lib.plan_lanes import node_file
from harness_lib.plan_models import ActionPlan

ENTRIES_NAME = "registry_entries.json"
TIMEOUT_SECONDS = 600
TAIL_LINES = 10


class PlannedEntries(BaseModel):
    """The entries file of one plan: its id and the registry entries of its planned tests."""

    model_config = ConfigDict(extra="forbid")

    plan: str
    entries: List[Dict[str, Any]]

    @field_validator("entries")
    @classmethod
    def _one_file_each(cls, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        files = [entry.get("file") for entry in entries]
        bad = [i for i, f in enumerate(files) if not isinstance(f, str) or not f]
        if bad:
            raise ValueError(f"entries {bad} have no file")
        twice = sorted({f for f in files if files.count(f) > 1})
        if twice:
            raise ValueError(f"{', '.join(twice)} listed twice")
        return entries

    def files(self) -> List[str]:
        return [str(entry["file"]) for entry in self.entries]


def entries_path(plans_dir: Path, plan_id: str) -> Path:
    return plans_dir / plan_id / ENTRIES_NAME


def _detail(exc: Exception) -> str:
    """Each validation error as ``<field location>: <message>``; any other error as its text."""
    if not isinstance(exc, ValidationError):
        return str(exc)
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in exc.errors())


def load_entries(plans_dir: Path, plan_id: str) -> Optional[PlannedEntries]:
    """The plan's planned entries, or None without a file; PlanError for a file that does not hold them."""
    path, where = entries_path(plans_dir, plan_id), f"{plan_id}/{ENTRIES_NAME}"
    if not path.is_file():
        return None
    try:
        loaded = PlannedEntries.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        detail = _detail(exc)
        raise PlanError([f"registry: {where}: {detail}"]) from None
    if loaded.plan != plan_id:
        raise PlanError([f"registry: {where} names plan {loaded.plan}"])
    return loaded


# --- the registry -----------------------------------------------------------------------------------------

def registered(registry: Path) -> Set[str]:
    """The ``file`` of every ``tests`` row of ``registry``; empty when it is missing or unreadable."""
    try:
        rows = json.loads(registry.read_text(encoding="utf-8")).get("tests") or []
    except (OSError, ValueError, AttributeError):
        return set()
    return {str(row["file"]) for row in rows if isinstance(row, dict) and "file" in row}


def pending(planned: PlannedEntries, files: Iterable[str], registry: Path) -> List[Dict[str, Any]]:
    """The planned entries of ``files``, in that order, that ``registry`` does not list yet."""
    known, by_file = registered(registry), dict(zip(planned.files(), planned.entries))
    return [by_file[f] for f in dict.fromkeys(files) if f in by_file and f not in known]


def planned_files(plan: ActionPlan, plans_dir: Path) -> List[str]:
    """Each test file the plan's nodes name that has a planned source under ``<plan_id>/tests/``."""
    folder = plans_dir / plan.plan_id / "tests"
    files = (node_file(t.node) for item in plan.items for t in item.tests)
    return [f for f in dict.fromkeys(files) if (folder / f).is_file()]


# --- the upsert command -----------------------------------------------------------------------------------

def command_argv(command: Sequence[str], registry: Path, entries: Path) -> List[str]:
    """``command`` with ``{registry}`` and ``{entries}`` replaced by the two paths."""
    return [arg.replace("{registry}", str(registry)).replace("{entries}", str(entries)) for arg in command]


def _program(program: str, cwd: Path) -> str:
    """A relative program path joins ``cwd``; a bare name searches PATH (``.cmd`` shims included)."""
    if os.sep in program or (os.altsep and os.altsep in program):
        target = Path(program)
        return str(target if target.is_absolute() else cwd / target)
    return shutil.which(program) or program


def _run(argv: List[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    """Run ``argv`` in ``cwd``; the timeout kills only the launched process, not its process tree."""
    return subprocess.run([_program(argv[0], cwd), *argv[1:]], cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                          errors="replace", timeout=TIMEOUT_SECONDS)


def upsert(command: Sequence[str], registry: Path, entries: Sequence[Dict[str, Any]], cwd: Path) -> None:
    """Run the configured upsert in ``cwd`` on ``entries``; PlanError with the output tail when it fails."""
    with tempfile.TemporaryDirectory(prefix="plan-registry-") as scratch:
        listed = Path(scratch) / "entries.json"
        listed.write_text(json.dumps(list(entries), indent=2), encoding="utf-8")
        argv = command_argv(command, registry, listed)
        try:
            done = _run(argv, cwd)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PlanError([f"tests.planned_registry: {' '.join(command)}: {exc}"]) from None
    if done.returncode != 0:
        tail = done.stdout.strip().splitlines()[-TAIL_LINES:]
        raise PlanError([f"tests.planned_registry: {' '.join(command)} (exit {done.returncode})",
                         *(f"  {line}" for line in tail)])
    _confirm(registry, entries)


def _confirm(registry: Path, entries: Sequence[Dict[str, Any]]) -> None:
    """PlanError naming each entry's file that ``registry`` still does not list after the upsert."""
    known = registered(registry)
    missing = [str(e["file"]) for e in entries if str(e["file"]) not in known]
    if missing:
        raise PlanError([f"{f}: tests.planned_registry exited 0 but the registry does not list it"
                         for f in missing])


# --- lint -------------------------------------------------------------------------------------------------

def lint_problems(plan: ActionPlan, plans_dir: Path, repo: Path, registry: Optional[str],
                  keyed: bool) -> List[str]:
    """The entries file's own problems, an entry naming no planned or present file, and, when
    ``tests.planned_registry`` is set (``keyed``), a planned test file with no entry and no live row."""
    try:
        planned = load_entries(plans_dir, plan.plan_id)
    except PlanError as exc:
        return exc.problems
    where, files = f"{plan.plan_id}/{ENTRIES_NAME}", planned_files(plan, plans_dir)
    entered = planned.files() if planned else []
    problems = [f"registry: entry {f} in {where} names no planned or present file"
                for f in entered if f not in files and not (repo / f).is_file()]
    if keyed and registry:
        known = registered(repo / registry)
        problems += [f"registry: {f} is planned with no entry in {where}"
                     for f in files if f not in entered and f not in known]
    return problems
