"""Run an action plan's planned tests red: overlaid on a commit, each must fail as planned.

A planned test file lives beside the plan at ``<plans_dir>/<plan_id>/tests/<repo-relative path>``. The
red run copies those files into a detached worktree at a commit (``make_tree``, ``overlay``; the ``plan.py``
driver passes HEAD, so items already recorded are part of the tree),
runs every test node of each open item there, one pytest process per node (``run_red``), and compares the
exception that failed the node with the item's planned ``red`` reason (``red_problems``).

One process per node keeps the nodes independent: pytest aborts a whole session on a collection error, so
an expected module-level ``ImportError`` in one file would otherwise hide every other node of the run.
Each run imports the code of the tree, not of the main checkout: the tree is the working directory, and a
src-layout root goes first on ``PYTHONPATH`` (``tree_env``), ahead of an editable install.

``classify`` reads pytest's ``--tb=auto`` output; ``run_red`` passes that option last, so it overrides a
project's ``addopts``. Under ``--tb=short`` a bare ``E   assert`` line still counts as ``AssertionError``.
``ModuleNotFoundError`` counts as
``ImportError``, its base class, since a planned red names the import failing rather than its cause. A
collection error counts as ``ImportError`` when pytest reports it as an ``ImportError while importing test
module`` (a test file importing what the task has yet to write), else as ``COLLECTION``.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from harness_lib.branch_capture import CaptureError, git
from harness_lib.plan_lanes import node_file, open_items
from harness_lib.plan_models import ActionPlan

PASSED, COLLECTION, MISSING, FAILED = "PASSED", "COLLECTION", "MISSING", "FAILED"
NOT_RED = (PASSED, COLLECTION, MISSING)
# ``--tb=auto`` pins the traceback style ``classify`` reads, whatever the project's ``addopts`` say.
PYTEST_ARGS = ("-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=auto")
ALIASES = {"ModuleNotFoundError": "ImportError"}

_HEADER = re.compile(r"^_{2,} (.+?) _{2,}$")
_LOCATION = re.compile(r"^\S.*:\d+: (\w+)$", re.MULTILINE)
_E_LINE = re.compile(r"^E\s+(\w+):", re.MULTILINE)
_E_ASSERT = re.compile(r"^E\s+assert\b", re.MULTILINE)
_COUNT_PASSED = re.compile(r"^.*\b\d+ passed\b.*$", re.MULTILINE)
_NOT_FOUND = re.compile(r"^ERROR: (?:file or directory )?not found: (.+?)\s*$", re.MULTILINE)
_COLLECTING = "ERROR collecting "
_CONFTEST = "while loading conftest"
_IMPORT_COLLECT = "ImportError while importing test module"


@dataclass(frozen=True)
class RedResult:
    """One planned test node: its item, the planned red reason and what the run gave."""

    item: str
    node: str
    expected: str
    got: str


# --- planned sources --------------------------------------------------------------------------------------

def test_sources(plan: ActionPlan, plans_dir: Path) -> Dict[str, Path]:
    """Repo-relative test file -> planned source, for each open item's node that has a planned source."""
    folder = plans_dir / plan.plan_id / "tests"
    found: Dict[str, Path] = {}
    for item in open_items(plan):
        for test in item.tests:
            rel = node_file(test.node)
            if rel not in found and (folder / rel).is_file():
                found[rel] = folder / rel
    return found


def overlay(sources: Mapping[str, Path], tree: Path) -> List[str]:
    """Copy each source into ``tree`` at its repo-relative path; return the paths written, in order."""
    for rel, source in sources.items():
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return list(sources)


# --- classification ---------------------------------------------------------------------------------------

def _sections(output: str) -> Dict[str, str]:
    """Text of each ``____ name ____`` section of pytest output, keyed by the name."""
    sections: Dict[str, List[str]] = {}
    current: Optional[List[str]] = None
    for line in output.splitlines():
        header = _HEADER.match(line)
        if header:
            current = sections.setdefault(header.group(1), [])
        elif line.startswith("==="):
            current = None
        elif current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _same_file(printed: str, rel: str) -> bool:
    """True when a path pytest printed (relative to its rootdir) names the repo-relative ``rel``."""
    printed = printed.replace("\\", "/")
    return printed == rel or rel.endswith("/" + printed) or printed.endswith("/" + rel)


def _collect_error(sections: Mapping[str, str], node: str) -> Optional[str]:
    """``ImportError`` or ``COLLECTION`` when the node's file failed to collect, else None."""
    for name, text in sections.items():
        if name.startswith(_COLLECTING) and _same_file(name[len(_COLLECTING):], node_file(node)):
            return "ImportError" if _IMPORT_COLLECT in text else COLLECTION
    return None


def _failure_text(sections: Mapping[str, str], node: str, passed: bool) -> Optional[str]:
    """The node's failure section; the only section of a run without passes when the names differ."""
    name = ".".join(node.split("::")[1:])
    for key in (name, f"ERROR at setup of {name}", f"ERROR at teardown of {name}"):
        if key in sections:
            return sections[key]
    failures = [text for key, text in sections.items() if not key.startswith(_COLLECTING)]
    return failures[0] if len(failures) == 1 and not passed else None


def _exception_name(text: str) -> str:
    """The class that failed a section: its crash location line, else its last ``E   Name:`` line.
    A bare ``E   assert`` line (a rewritten assertion under ``--tb=short``) counts as ``AssertionError``."""
    found = _LOCATION.findall(text) or _E_LINE.findall(text)
    if not found and _E_ASSERT.search(text):
        found = ["AssertionError"]
    name = found[-1] if found else FAILED
    return ALIASES.get(name, name)


def _not_found(output: str, node: str) -> bool:
    return any(_same_file(path, node) for path in _NOT_FOUND.findall(output))


def classify(output: str, node: str) -> str:
    """What pytest ``output`` says about ``node``: the failing exception class, or a NOT_RED marker.

    ``PASSED`` when the node ran and passed, ``COLLECTION`` for a collection error (a syntax error, a
    conftest that fails to load), ``MISSING`` when the node was not found or never ran.
    """
    if _CONFTEST in output:
        return COLLECTION
    sections = _sections(output)
    collected = _collect_error(sections, node)
    if collected:
        return collected
    passed = bool(_COUNT_PASSED.search(output))
    failure = _failure_text(sections, node, passed)
    if failure is not None:
        return _exception_name(failure)
    if _not_found(output, node):
        return MISSING
    return PASSED if passed else MISSING


# --- running ----------------------------------------------------------------------------------------------

def tree_env(tree: Path) -> Dict[str, str]:
    """The environment for a run in ``tree``: a src-layout root (``src/`` without ``__init__.py``) goes
    first on ``PYTHONPATH``, ahead of an editable install that resolves the package to the main checkout.
    The working directory already leads ``sys.path`` under ``python -m``; other source roots resolve
    wherever the environment installs them."""
    env = dict(os.environ)
    src = tree / "src"
    if src.is_dir() and not (src / "__init__.py").is_file():
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(src), env.get("PYTHONPATH")]))
    return env


def run_pytest(args: Sequence[str], tree: Path) -> "subprocess.CompletedProcess[str]":
    """One pytest run in ``tree`` with ``tree_env``; stdout holds stdout and stderr combined."""
    return subprocess.run(list(args), cwd=tree, env=tree_env(tree), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")


def pytest_output(args: Sequence[str], cwd: Path) -> str:
    """Combined stdout and stderr of one pytest run (stderr carries ``ERROR: not found``)."""
    return run_pytest(args, cwd).stdout


def run_red(plan: ActionPlan, tree: Path, python: str) -> List[RedResult]:
    """Run each open item's test nodes in ``tree``, one pytest process per node, and classify each."""
    results: List[RedResult] = []
    for item in open_items(plan):
        for test in item.tests:
            output = pytest_output([python, *PYTEST_ARGS, test.node], tree)
            results.append(RedResult(item.id, test.node, test.red.value, classify(output, test.node)))
    return results


def red_problems(results: Sequence[RedResult]) -> List[str]:
    """One line per node that did not fail as planned; PASSED, COLLECTION and MISSING always count."""
    return [
        f"{r.item} {r.node}: expected {r.expected}, got {r.got}"
        for r in results if r.got != r.expected or r.got in NOT_RED
    ]


# --- worktree lifecycle -----------------------------------------------------------------------------------

def _free_path(root: Path, base: str) -> Path:
    path, number = root / f"plan-red-{base[:7]}", 2
    while path.exists():
        path, number = root / f"plan-red-{base[:7]}-{number}", number + 1
    return path


def make_tree(repo: Path, base: str, root: Path) -> Path:
    """A detached worktree of ``repo`` at ``base`` under ``root``; raise ``CaptureError`` on failure."""
    root.mkdir(parents=True, exist_ok=True)
    path = _free_path(root, base)
    done = git(repo, "worktree", "add", "--detach", path.as_posix(), base)
    if done.returncode != 0:
        raise CaptureError([f"git worktree add at {base} failed: {done.stderr.strip()}"])
    return path


def drop_tree(repo: Path, tree: Path) -> None:
    """Remove a worktree made by ``make_tree``, overlaid files and all; raise ``CaptureError`` on failure."""
    done = git(repo, "worktree", "remove", "--force", tree.as_posix())
    if done.returncode != 0:
        raise CaptureError([f"git worktree remove {tree.as_posix()} failed: {done.stderr.strip()}"])
