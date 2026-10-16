"""Decide which CI work a diff needs: pytest files, ruff files and the plugin validation job.

Usage: select_tests.py (--full | --base REF [--head REF]) [--root DIR] [--out-dir DIR]

A test file is selected when any of these holds:

- it changed;
- its import closure holds a changed file. The closure starts at the test, ``tests/conftest.py`` and every
  ``.py`` file under ``plugins/`` or ``tools/`` whose basename the test spells out (a script loaded by
  path), and follows imports resolved against the ``pythonpath`` entries of ``pyproject.toml`` plus the
  importing file's own directory;
- its source names a changed or deleted file: the basename, or for a ``.py`` file the bare module name. This
  covers hooks and scripts that tests load by path instead of by import;
- its source walks the tree (``rglob``, ``glob``, ``iterdir``, ``os.walk``) and any path outside ``docs/``
  changed or was deleted.

A changed or deleted non-``.py`` file under ``plugins/`` or ``tools/`` also counts as a change to every
``.py`` file there whose source names its basename (a module that reads the data file by path).

Anything the rules cannot judge selects everything: a shared file (conftest, pyproject, the workflow, this
script), a deleted ``.py`` file, a path with characters outside ``[A-Za-z0-9_./-]``, a test or helper that
does not parse, or a diff that cannot be read. Those escalations cost CI time, never coverage. Under-selection
remains possible: a test that reaches a file through a path built at runtime, without spelling the file name
out, is skipped on the pull request, and only the full run on push to ``main`` catches it after the merge.

Writes ``selected-tests.txt`` and ``ruff-files.txt`` (one path per line) under ``--out-dir`` (default
``<root>/.artifacts``), prints the plan as JSON and, when ``GITHUB_OUTPUT`` is set, appends
``pytest``, ``ruff`` and ``plugins`` for later workflow steps.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple

FULL_TRIGGERS = frozenset({
    "tests/conftest.py",
    "pyproject.toml",
    "requirements-dev.txt",
    ".github/workflows/ci.yml",
    "tools/select_tests.py",
})
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")
LINT_ROOTS = ("plugins/", "tests/", "tools/")
PLUGIN_PREFIXES = ("plugins/", ".claude-plugin/")
TREE_WALK = re.compile(r"\brglob\(|\.glob\(|\biterdir\(|\bos\.walk\(")
DEFAULT_PYTHONPATH = ("plugins/harness/lib", "tests")
CONFTEST = "tests/conftest.py"
SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".git", ".venv"})


class Unresolvable(Exception):
    """The static rules cannot judge this tree; the caller selects everything."""


@dataclass
class Plan:
    pytest: str = "none"
    tests: List[str] = field(default_factory=list)
    ruff: str = "none"
    ruff_files: List[str] = field(default_factory=list)
    plugins: bool = False
    reasons: List[str] = field(default_factory=list)


def list_tests(root: Path) -> List[str]:
    """Every ``tests/*/test_*.py`` file, the set CI runs, as repo-relative POSIX paths."""
    return sorted(p.relative_to(root).as_posix() for p in (root / "tests").glob("*/test_*.py"))


def pythonpath_roots(root: Path) -> List[str]:
    """The ``pythonpath`` entries of pyproject.toml's pytest options, else the repo defaults."""
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return list(data["tool"]["pytest"]["ini_options"]["pythonpath"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return list(DEFAULT_PYTHONPATH)


def _raw_imports(path: Path) -> List[Tuple[str, Tuple[str, ...], int]]:
    """``(module, imported names, relative level)`` for every import statement, nested ones included."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        raise Unresolvable(f"{path.as_posix()} does not parse: {exc}") from exc
    found: List[Tuple[str, Tuple[str, ...], int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, (), 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", tuple(a.name for a in node.names), node.level))
    return found


def _module_files(root: Path, bases: Sequence[PurePosixPath], dotted: str) -> List[str]:
    """Repo files a dotted name loads: the module and each parent package ``__init__`` under any base."""
    parts = [p for p in dotted.split(".") if p]
    found: List[str] = []
    for base in bases:
        for end in range(1, len(parts) + 1):
            stem = base.joinpath(*parts[:end])
            for cand in (stem.with_name(stem.name + ".py"), stem / "__init__.py"):
                if (root / cand).is_file():
                    found.append(cand.as_posix())
    return found


def _direct_deps(root: Path, rel: str, roots: Sequence[str]) -> Set[str]:
    """Repo files ``rel`` imports directly."""
    here = PurePosixPath(rel).parent
    deps: Set[str] = set()
    for module, names, level in _raw_imports(root / rel):
        if level:
            up = here
            for _ in range(level - 1):
                up = up.parent
            bases = [up]
        else:
            bases = [PurePosixPath(r) for r in roots] + [here]
        deps.update(_module_files(root, bases, module))
        deps.update(f for n in names for f in _module_files(root, bases, f"{module}.{n}" if module else n))
    deps.discard(rel)
    return deps


def closure(root: Path, starts: Sequence[str], roots: Sequence[str],
            cache: Dict[str, Set[str]]) -> Set[str]:
    """``starts`` plus every repo file reachable through imports."""
    seen: Set[str] = set()
    todo = [s for s in starts if (root / s).is_file()]
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        if rel not in cache:
            cache[rel] = _direct_deps(root, rel, roots)
        todo.extend(cache[rel] - seen)
    return seen


def mentions(text: str, path: str) -> bool:
    """Whether a test's source names ``path``: its basename, or for ``.py`` the bare module name."""
    name = path.rsplit("/", 1)[-1]
    if name in text:
        return True
    if name.endswith(".py"):
        return re.search(rf"(?<!\w){re.escape(name[:-3])}(?!\w)", text) is not None
    return False


def _why(rel: str, text: str, deps: Set[str], changed: Sequence[str], walk_hit: bool) -> Optional[str]:
    """The first rule that selects test ``rel``, else None."""
    if rel in changed:
        return "test changed"
    hit = next((c for c in changed if c in deps), None)
    if hit:
        return f"imports {hit}"
    hit = next((c for c in changed if mentions(text, c)), None)
    if hit:
        return f"names {hit}"
    return "walks the tree" if walk_hit else None


def path_loadable(root: Path) -> Dict[str, List[str]]:
    """Basename to repo paths for the ``.py`` files under ``plugins/`` and ``tools/``: the hooks and
    scripts a test may load by path."""
    index: Dict[str, List[str]] = {}
    for top in ("plugins", "tools"):
        for here, dirs, files in os.walk(root / top):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if name.endswith(".py"):
                    rel = (Path(here) / name).relative_to(root).as_posix()
                    index.setdefault(name, []).append(rel)
    return index


def named_scripts(text: str, index: Dict[str, List[str]]) -> List[str]:
    """Repo ``.py`` files whose basename (with extension) the test source spells out."""
    return [rel for name, rels in index.items() if name in text for rel in rels]


def data_readers(root: Path, changed: Sequence[str], index: Dict[str, List[str]]) -> List[str]:
    """Indexed ``.py`` files whose source names a changed non-``.py`` file under ``plugins/``/``tools/``."""
    data = [c for c in changed if not c.endswith(".py") and c.startswith(("plugins/", "tools/"))]
    if not data:
        return []
    readers: List[str] = []
    for rel in sorted(r for rels in index.values() for r in rels):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if any(mentions(text, d) for d in data):
            readers.append(rel)
    return readers


def affected_tests(root: Path, changed: Sequence[str]) -> Tuple[List[str], List[str]]:
    """``(selected test files, one reason line each)``; raises Unresolvable when a file does not parse."""
    roots, cache, index = pythonpath_roots(root), {}, path_loadable(root)
    changed = [*changed, *data_readers(root, changed, index)]
    non_docs = any(not c.startswith("docs/") for c in changed)
    chosen: List[str] = []
    reasons: List[str] = []
    for rel in list_tests(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        deps = closure(root, [rel, CONFTEST, *named_scripts(text, index)], roots, cache)
        why = _why(rel, text, deps, changed, bool(TREE_WALK.search(text)) and non_docs)
        if why:
            chosen.append(rel)
            reasons.append(f"{rel}: {why}")
    return chosen, reasons


def _full_reason(paths: Sequence[str], deleted: Sequence[str]) -> Optional[str]:
    """Why the whole suite must run for ``paths``, else None."""
    shared = sorted(FULL_TRIGGERS.intersection(paths))
    if shared:
        return f"shared file changed: {', '.join(shared)}"
    gone = [d for d in deleted if d.endswith(".py")]
    if gone:
        return f"python file deleted: {gone[0]}"
    odd = [p for p in paths if not SAFE_PATH.match(p)]
    return f"unsafe path characters: {odd[0]}" if odd else None


def _ruff(root: Path, changed: Sequence[str]) -> Tuple[str, List[str]]:
    files = sorted(c for c in changed if c.endswith(".py") and c.startswith(LINT_ROOTS)
                   and (root / c).is_file())
    return ("subset", files) if files else ("none", [])


def plan(root: Path, changed: Sequence[str], deleted: Sequence[str]) -> Plan:
    """The CI work for a diff: ``changed`` holds added, modified and type-changed paths."""
    paths = sorted(set(changed) | set(deleted))
    reason = _full_reason(paths, deleted)
    if reason is None:
        try:
            tests, why = affected_tests(root, paths)
        except Unresolvable as exc:
            reason = str(exc)
    if reason is not None:
        return _full_plan(root, reason)
    ruff, ruff_files = _ruff(root, changed)
    kind = "subset" if tests else "none"
    plugins = any(p.startswith(PLUGIN_PREFIXES) for p in paths)
    return Plan(kind, tests, ruff, ruff_files, plugins, why)


def changed_files(root: Path, base: str, head: str) -> Tuple[List[str], List[str]]:
    """``(changed, deleted)`` paths between the merge base of ``base`` and ``head`` and ``head``."""
    done = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-status", "--no-renames", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    )
    changed: List[str] = []
    deleted: List[str] = []
    for line in done.stdout.splitlines():
        status, _, path = line.partition("\t")
        (deleted if status.startswith("D") else changed).append(path)
    return sorted(changed), sorted(deleted)


def _write_outputs(out_dir: Path, result: Plan) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, items in (("selected-tests.txt", result.tests), ("ruff-files.txt", result.ruff_files)):
        (out_dir / name).write_text("".join(f"{i}\n" for i in items), encoding="utf-8", newline="\n")
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"pytest={result.pytest}\nruff={result.ruff}\nplugins={str(result.plugins).lower()}\n")


def _full_plan(root: Path, reason: str) -> Plan:
    return Plan("full", list_tests(root), "full", [], True, [reason])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--base", help="ref the diff is taken against (merge-base form: BASE...HEAD)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--full", action="store_true", help="select everything without reading a diff")
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.full:
        result = _full_plan(root, "full run requested")
    elif not args.base:
        ap.error("--base is required unless --full is given")
    else:
        try:
            result = plan(root, *changed_files(root, args.base, args.head))
        except subprocess.CalledProcessError as exc:
            result = _full_plan(root, f"diff unreadable, running everything: {exc}")
        except OSError as exc:
            result = _full_plan(root, f"selection failed, running everything: {exc}")
    _write_outputs(args.out_dir or root / ".artifacts", result)
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
