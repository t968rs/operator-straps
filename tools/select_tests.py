"""Decide which CI work a diff needs: pytest files, ruff files and the plugin validation job.

Usage: select_tests.py (--full | --base REF [--head REF]) [--root DIR] [--out-dir DIR]

A test file is selected when any of these holds:

- it changed;
- its import closure holds a changed file. The closure starts at the test, ``tests/conftest.py`` and every
  ``.py`` file under ``plugins/`` or ``tools/`` whose basename the test spells out (a script loaded by
  path), and follows imports resolved against the ``pythonpath`` entries of ``pyproject.toml``, every
  ``tests/`` directory holding a ``_``-prefixed helper (reached through ``sys.path.insert``) and the
  importing file's own directory;
- its source names a changed or deleted file: the basename, or for a ``.py`` file the bare module name. This
  covers hooks and scripts that tests load by path instead of by import. A non-``.py`` basename that other
  files share (``SKILL.md``, ``README.md``) counts only with its anchor: the source must also name, as a
  whole word, the nearest folder above the file that no other file of that basename has at the same height
  (``pr-sum`` for ``plugins/harness/skills/pr-sum/SKILL.md``); for a shared name at the repo root, a line
  holding the basename must also name a root or repo (``REPO_ROOT / "README.md"``). When no folder tells the
  files apart, the basename alone counts;
- its code walks a tree (calls matching ``rglob(``, ``.glob(``, ``iglob(``, ``iterdir(``, ``.walk(`` other
  than ``ast.walk(``, ``copytree(``, ``scandir(`` or ``listdir(``; comments and docstrings do not count) and
  a changed or deleted path sits under one of the directories its module-level literal ``WALK_ROOTS``
  tuple lists (repo-relative; ``"."`` is the whole repo). ``WALK_ROOTS = ()`` marks a test that walks
  only temporary directories, which this rule never selects. Without a valid marker (a tuple of relative
  paths, no ``..``), any path outside ``docs/`` that changed or was deleted selects it.

A changed or deleted non-``.py`` file under ``plugins/`` or ``tools/`` also counts as a change to every
``.py`` file there whose code names its basename in a string literal (a module that reads the data file by
path); docstrings and comments do not count, since a module that only describes ``plugin.json`` would
otherwise pull every importer of it into the run. The same holds for a non-``.py`` file under ``tests/`` and
every ``_``-prefixed helper module under ``tests/``. A shared basename needs its anchor here too, except in a
module under the data file's own folder, which can reach the file through ``Path(__file__)``.

Anything the rules cannot judge selects everything: a shared file (conftest, pyproject, the workflow, this
script), a deleted ``.py`` file, a path with characters outside ``[A-Za-z0-9_./-]``, a test or helper that
does not parse, or a diff that cannot be read. Those escalations cost CI time, never coverage. Under-selection
remains possible: a test that reaches a file through a path built at runtime, without spelling the file name
(and, for a shared basename, its anchor) out, is skipped on the pull request, and only the full run on push
to ``main`` catches it after the merge.

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
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

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
TREE_WALK = re.compile(r"\brglob\(|\.glob\(|\biglob\(|\biterdir\(|(?<!\bast)\.walk\(|\bcopytree\("
                       r"|\bscandir\(|\blistdir\(")
WALK_MARKER = "WALK_ROOTS"
ROOT_NAME = re.compile(r"root|repo", re.IGNORECASE)
DEFAULT_PYTHONPATH = ("plugins/harness/lib", "tests", "plugins/arc-straps/skills/arc-meta/scripts")
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


def import_bases(root: Path) -> List[str]:
    """Where absolute imports resolve: the ``pythonpath`` entries plus every ``tests/`` directory holding a
    ``_``-prefixed helper, which tests reach through ``sys.path.insert`` (``tests/lib`` is not a pythonpath
    entry)."""
    bases = pythonpath_roots(root)
    helper_dirs = sorted({PurePosixPath(h).parent.as_posix() for h in helper_files(root)})
    return [*bases, *(d for d in helper_dirs if d not in bases)]


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


def basename_index(root: Path) -> Dict[str, List[str]]:
    """Basename to repo paths for every file of the tree outside ``SKIP_DIRS``."""
    index: Dict[str, List[str]] = {}
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_dir = Path(here).relative_to(root).as_posix()
        for name in files:
            index.setdefault(name, []).append(name if rel_dir == "." else f"{rel_dir}/{name}")
    return index


def name_anchor(path: str, index: Dict[str, List[str]]) -> Optional[str]:
    """What a source must name besides the basename of a non-``.py`` ``path`` other files share: the nearest
    folder name that no other file of that basename has at the same height, or ``""`` for a file at the
    repo root. None keeps the plain basename rule: a unique basename, or no folder tells the files apart."""
    *dirs, name = path.split("/")
    others = [p.split("/")[:-1] for p in index.get(name, []) if p != path]
    if name.endswith(".py") or not others:
        return None
    if not dirs:
        return ""
    for height in range(1, len(dirs) + 1):
        if all(len(o) < height or o[-height] != dirs[-height] for o in others):
            return dirs[-height]
    return None


def name_anchors(changed: Sequence[str], index: Dict[str, List[str]]) -> Dict[str, str]:
    """``name_anchor`` of each changed path that has one."""
    found = {c: name_anchor(c, index) for c in changed}
    return {c: a for c, a in found.items() if a is not None}


def _names_anchor(text: str, name: str, anchor: str) -> bool:
    """Whether ``text`` names the folder ``anchor`` as a whole word; for ``""``, whether a line holding
    ``name`` also names a root or repo (``REPO_ROOT / "README.md"``)."""
    if anchor:
        return re.search(rf"(?<![\w-]){re.escape(anchor)}(?![\w-])", text) is not None
    return any(ROOT_NAME.search(line.replace(name, "")) for line in text.splitlines() if name in line)


def mentions(text: str, path: str, anchor: Optional[str] = None) -> bool:
    """Whether a source names ``path``: its basename, or for ``.py`` the bare module name. With an
    ``anchor`` from ``name_anchor``, the basename counts only when ``_names_anchor`` holds as well."""
    name = path.rsplit("/", 1)[-1]
    if name in text:
        return anchor is None or _names_anchor(text, name, anchor)
    if name.endswith(".py"):
        return re.search(rf"(?<!\w){re.escape(name[:-3])}(?!\w)", text) is not None
    return False


def _why(rel: str, text: str, deps: Set[str], changed: Sequence[str], anchors: Dict[str, str],
         walk: Callable[[], Optional[str]]) -> Optional[str]:
    """The first rule that selects test ``rel``, else None; the walk rule runs last, only when needed."""
    if rel in changed:
        return "test changed"
    hit = next((c for c in changed if c in deps), None)
    if hit:
        return f"imports {hit}"
    hit = next((c for c in changed if mentions(text, c, anchors.get(c))), None)
    if hit:
        return f"names {hit}"
    return walk()


def walks(text: str) -> bool:
    """Whether a module's code matches ``TREE_WALK``; comments and docstrings are prose, not walks.
    A module that does not parse counts as walking."""
    if not TREE_WALK.search(text):
        return False
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return True
    prose = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and id(node.value) in prose:
            node.value = ast.Constant("")
    return TREE_WALK.search(ast.unparse(tree)) is not None


def _root_prefix(root: object) -> Optional[str]:
    """A ``WALK_ROOTS`` entry as a ``dir/`` prefix (``""`` for ``.``); None when it is not a relative
    POSIX path inside the repo."""
    if not isinstance(root, str) or not root or "\\" in root or ":" in root or root.startswith("/"):
        return None
    parts = [p for p in root.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None
    return "".join(f"{p}/" for p in parts)


def _marker_values(tree: ast.Module) -> List[ast.expr]:
    """Values assigned to ``WALK_ROOTS`` at module level."""
    found: List[ast.expr] = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        value = getattr(node, "value", None)
        if value is not None and any(isinstance(t, ast.Name) and t.id == WALK_MARKER for t in targets):
            found.append(value)
    return found


def walk_roots(text: str) -> Optional[Tuple[str, ...]]:
    """The module's literal ``WALK_ROOTS`` tuple as directory prefixes; None when absent or invalid."""
    try:
        values = _marker_values(ast.parse(text))
        roots = ast.literal_eval(values[0]) if len(values) == 1 else None
    except (SyntaxError, ValueError):
        return None
    if not isinstance(roots, tuple):
        return None
    prefixes = [_root_prefix(r) for r in roots]
    return None if any(p is None for p in prefixes) else tuple(str(p) for p in prefixes)


def walk_reason(text: str, changed: Sequence[str], non_docs: bool) -> Optional[str]:
    """Why a walking test runs: a change under one of its ``WALK_ROOTS``; without a valid marker, any
    change outside ``docs/``. ``WALK_ROOTS = ()`` (temporary directories only) never selects."""
    if not walks(text):
        return None
    roots = walk_roots(text)
    if roots is None:
        return "walks the tree" if non_docs else None
    hit = next(((r, c) for r in roots for c in changed if c.startswith(r)), None)
    return f"walks {hit[0] or './'}, holding {hit[1]}" if hit else None


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


def helper_files(root: Path) -> List[str]:
    """Repo paths of the ``_``-prefixed helper modules under ``tests/``, which test files import by name."""
    base = root / "tests"
    if not base.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("_*.py")
                  if not any(part in SKIP_DIRS for part in p.relative_to(base).parts))


def _docstrings(tree: ast.AST) -> Set[int]:
    """``id`` of every docstring constant: the first statement of a module, class or function body."""
    found: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def code_strings(text: str) -> str:
    """The string literals of a module's code, one per line; docstrings and comments are prose, not reads.
    A module that does not parse keeps its raw text, so it can only be over-selected."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    prose = _docstrings(tree)
    return "\n".join(n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in prose)


def _inside(rel: str, data: str) -> bool:
    """Whether module ``rel`` sits under the folder of ``data``: it can reach the file through
    ``Path(__file__)``, so the basename alone counts."""
    folder = data.rpartition("/")[0]
    return bool(folder) and rel.startswith(f"{folder}/")


def _readers_of(root: Path, data: Sequence[str], rels: Sequence[str], anchors: Dict[str, str]) -> List[str]:
    """The files in ``rels`` whose code names one of the changed ``data`` files in a string literal."""
    found: List[str] = []
    if not data:
        return found
    for rel in rels:
        text = code_strings((root / rel).read_text(encoding="utf-8", errors="replace"))
        if any(mentions(text, d, None if _inside(rel, d) else anchors.get(d)) for d in data):
            found.append(rel)
    return found


def data_readers(root: Path, changed: Sequence[str], index: Dict[str, List[str]],
                 anchors: Dict[str, str]) -> List[str]:
    """Indexed ``.py`` files whose source names a changed non-``.py`` file under ``plugins/``/``tools/``, and
    test helpers whose source names a changed non-``.py`` file under ``tests/``."""
    data = [c for c in changed if not c.endswith(".py")]
    script_data = [c for c in data if c.startswith(("plugins/", "tools/"))]
    helper_data = [c for c in data if c.startswith("tests/")]
    scripts = sorted(r for rels in index.values() for r in rels)
    return [*_readers_of(root, script_data, scripts, anchors),
            *_readers_of(root, helper_data, helper_files(root), anchors)]


def affected_tests(root: Path, changed: Sequence[str]) -> Tuple[List[str], List[str]]:
    """``(selected test files, one reason line each)``; raises Unresolvable when a file does not parse."""
    roots, cache, index = import_bases(root), {}, path_loadable(root)
    anchors = name_anchors(changed, basename_index(root))
    changed = [*changed, *data_readers(root, changed, index, anchors)]
    non_docs = any(not c.startswith("docs/") for c in changed)
    chosen: List[str] = []
    reasons: List[str] = []
    for rel in list_tests(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        deps = closure(root, [rel, CONFTEST, *named_scripts(text, index)], roots, cache)
        why = _why(rel, text, deps, changed, anchors, lambda: walk_reason(text, changed, non_docs))
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
