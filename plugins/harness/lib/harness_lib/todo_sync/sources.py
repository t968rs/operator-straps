"""Lazy loaders for everything the sync rules read: the TODO catalog, the research catalog and its stubs,
plan pairs and snapshots.

Each input loads on first use and is cached for the run. A missing or unparseable file loads as a record
with ``error`` set (never an exception), and the rules turn that into a finding or a skip reason.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync.pip_sections import PipDoc, parse_pip

TERMINAL_RESEARCH = frozenset({"FULLY_IMPLEMENTED", "NOT_APPLICABLE"})
PLAN_SUFFIX = "_ActionPlan.json"
PIP_SUFFIX = "_PIP.md"
HEADER = re.compile(r"^<!-- todo-snapshot source=(?P<source>\S+) top=(?P<top>\d+) "
                    r"rows_sha256=(?P<sha>[0-9a-f]{64}) rendered=(?P<rendered>\d{4}-\d{2}-\d{2}) -->$")
_STATUS = re.compile(r"^status:(.*)$")
_LOE = re.compile(r"^loe:(.*)$")


@dataclass(frozen=True)
class JsonFile:
    """A JSON input: ``data`` when it parsed, else ``error``."""

    rel: str
    data: Any
    error: Optional[str]

    @property
    def ok(self) -> bool:
        """True when the file read and parsed."""
        return self.error is None


@dataclass(frozen=True)
class StubLine:
    """A stub header value and its 1-based line."""

    value: str
    line: int


@dataclass(frozen=True)
class Stub:
    """One research stub: its anchor id and its ``status:`` / ``loe:`` header lines."""

    rel: str
    exists: bool
    error: Optional[str]
    anchor: Optional[StubLine]
    status: Optional[StubLine]
    loe: Optional[StubLine]


@dataclass(frozen=True)
class PlanPair:
    """An ``<prefix>_ActionPlan.json`` and ``<prefix>_PIP.md`` pair; either side may be absent."""

    prefix: str
    plan: Optional[JsonFile]
    pip_rel: Optional[str]
    pip: Optional[PipDoc]


@dataclass(frozen=True)
class SnapshotHeader:
    """The parsed ``<!-- todo-snapshot ... -->`` first line of a snapshot."""

    source: str
    top: int
    rows_sha256: str
    rendered: str


@dataclass(frozen=True)
class Snapshot:
    """The newest snapshot file and its header (None when absent or unparseable)."""

    rel: str
    header: Optional[SnapshotHeader]


def posix(rel: str) -> str:
    """``rel`` with forward slashes and no leading ``./``."""
    out = rel.replace("\\", "/")
    return out[2:] if out.startswith("./") else out


def read_json(root: Path, rel: str) -> JsonFile:
    """Load ``root/rel`` as JSON; a read or parse failure lands in ``error``."""
    path = root / rel
    if not path.is_file():
        return JsonFile(posix(rel), None, "file not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JsonFile(posix(rel), None, f"unparseable: {exc}")
    if not isinstance(data, dict):
        return JsonFile(posix(rel), None, "top level is not an object")
    return JsonFile(posix(rel), data, None)


def _first(pattern: re.Pattern, lines: List[str], group: Any = 1) -> Optional[StubLine]:
    for n, line in enumerate(lines, 1):
        match = pattern.match(line)
        if match:
            return StubLine(match.group(group).strip(), n)
    return None


def read_stub(root: Path, rel: str, anchor: re.Pattern) -> Stub:
    """Parse a stub's anchor, ``status:`` and ``loe:`` lines (first match of each)."""
    path = root / rel
    if not path.is_file():
        return Stub(posix(rel), False, None, None, None, None)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return Stub(posix(rel), True, str(exc), None, None, None)
    return Stub(posix(rel), True, None, _first(anchor, lines, "id"), _first(_STATUS, lines),
                _first(_LOE, lines))


def rows_sha256(items: List[Dict[str, Any]], top_n: int) -> str:
    """sha256 of the canonical ``[id, rank, status, title]`` rows of the first ``top_n`` items by rank."""
    rows = [[i.get("id"), i.get("rank"), i.get("status"), i.get("title")] for i in top_items(items, top_n)]
    text = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def top_items(items: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    """The first ``top_n`` items by rank."""
    ranked = [i for i in items if isinstance(i, dict)]
    return sorted(ranked, key=lambda i: i.get("rank") if isinstance(i.get("rank"), int) else 1 << 30)[:top_n]


def parse_header(first_line: str) -> Optional[SnapshotHeader]:
    """The snapshot header in ``first_line``, or None."""
    match = HEADER.match(first_line.strip())
    if not match:
        return None
    return SnapshotHeader(match["source"], int(match["top"]), match["sha"], match["rendered"])


def _read_first_line(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readline()
    except OSError:
        return ""


class Sources:
    """Per-run lazy view of a project's TODO, research and plan artifacts."""

    def __init__(self, cfg: HarnessConfig) -> None:
        self.cfg = cfg
        self.root = cfg.project_root
        self._cache: Dict[str, Any] = {}
        self._reported: Set[str] = set()

    def _memo(self, key: str, build: Any) -> Any:
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    def claim(self, rel: str) -> bool:
        """True the first time an unreadable input ``rel`` is reported, so one finding covers it."""
        if rel in self._reported:
            return False
        self._reported.add(rel)
        return True

    def rel(self, path: Path) -> str:
        """Repo-relative POSIX path of an absolute path under the project."""
        return path.relative_to(self.root).as_posix()

    @property
    def todo(self) -> JsonFile:
        """The TODO catalog (``todo.catalog``)."""
        return self._memo("todo", lambda: read_json(self.root, self.cfg.todo.catalog))

    @property
    def research(self) -> JsonFile:
        """The research catalog (``todo.research.catalog``)."""
        return self._memo("research", lambda: read_json(self.root, self.cfg.todo.research.catalog))

    @property
    def research_root(self) -> Path:
        """Absolute research root (``artifacts.research``)."""
        return self.cfg.path(self.cfg.artifacts.research)

    def entries(self) -> List[Dict[str, Any]]:
        """Research catalog entries that are objects."""
        data = self.research.data if self.research.ok else None
        entries = data.get("entries") if isinstance(data, dict) else None
        return [e for e in entries or [] if isinstance(e, dict)]

    def items(self) -> List[Dict[str, Any]]:
        """TODO catalog items that are objects."""
        data = self.todo.data if self.todo.ok else None
        items = data.get("items") if isinstance(data, dict) else None
        return [i for i in items or [] if isinstance(i, dict)]

    def stub(self, rel: str) -> Stub:
        """The stub at ``rel`` (cached)."""
        anchor = re.compile(self.cfg.todo.research.anchor_pattern)
        return self._memo(f"stub:{posix(rel)}", lambda: read_stub(self.root, posix(rel), anchor))

    def stub_files(self) -> List[str]:
        """Repo-relative paths of every ``stub_name`` file under the research root."""
        name = self.cfg.todo.research.stub_name
        return self._memo("stub_files", lambda: sorted(
            self.rel(p) for p in self.research_root.rglob(name) if p.is_file()))

    def plan_pairs(self) -> List[PlanPair]:
        """Top-level plan pairs of ``artifacts.plans``, by prefix."""
        return self._memo("plans", self._load_pairs)

    def _load_pairs(self) -> List[PlanPair]:
        folder = self.cfg.path(self.cfg.artifacts.plans)
        if not folder.is_dir():
            return []
        names = {p.name for p in folder.iterdir() if p.is_file()}
        prefixes = sorted({n[:-len(s)] for n in names for s in (PLAN_SUFFIX, PIP_SUFFIX) if n.endswith(s)})
        return [self._pair(folder, p, names) for p in prefixes]

    def _pair(self, folder: Path, prefix: str, names: Set[str]) -> PlanPair:
        plan_name, pip_name = prefix + PLAN_SUFFIX, prefix + PIP_SUFFIX
        plan = read_json(self.root, self.rel(folder / plan_name)) if plan_name in names else None
        if pip_name not in names:
            return PlanPair(prefix, plan, None, None)
        pip_path = folder / pip_name
        try:
            doc = parse_pip(pip_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            doc = None
        return PlanPair(prefix, plan, self.rel(pip_path), doc)

    def snapshot(self) -> Optional[Snapshot]:
        """The newest snapshot in ``todo.snapshots.dir``, or None when there is none."""
        return self._memo("snapshot", self._load_snapshot)

    def _load_snapshot(self) -> Optional[Snapshot]:
        folder = self.cfg.path(self.cfg.todo.snapshots.dir)
        if not folder.is_dir():
            return None
        pattern = re.compile(self.cfg.todo.snapshots.name_pattern)
        found: List[Tuple[Tuple[str, int], Path]] = []
        for path in folder.iterdir():
            match = pattern.fullmatch(path.name)
            if match and path.is_file():
                date = (match.group("date") or "").replace("_", "")
                found.append(((date, path.stat().st_mtime_ns), path))
        if not found:
            return None
        newest = max(found, key=lambda pair: pair[0])[1]
        return Snapshot(self.rel(newest), parse_header(_read_first_line(newest)))
