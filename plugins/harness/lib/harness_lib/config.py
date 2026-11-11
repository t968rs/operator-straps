"""Per-project harness configuration: ``<project>/.claude/harness.json`` merged over the plugin defaults.

Every repo-specific value the harness needs (artifact directories, test layout, review guard suites,
commit bucket rules, base branch) arrives through this module. Objects merge key by key; arrays and
scalars replace. Validation uses ``jsonschema`` when it imports, else a top-level key check.
"""
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from harness_lib.project import main_worktree, project_root, run_git

CONFIG_REL = Path(".claude") / "harness.json"
_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULTS_PATH = _CONFIG_DIR / "defaults.json"
SCHEMA_PATH = _CONFIG_DIR / "harness.schema.json"
DEFAULT_WORKTREE_ROOT = "~/.config/harness/worktrees/{repo}"


class ConfigError(ValueError):
    """``harness.json`` is unreadable or violates ``harness.schema.json``."""


@dataclass(frozen=True)
class Artifacts:
    """Project-relative directories the harness writes its output into."""

    reviews: str
    plans: str
    summaries: str
    commit_messages: str
    scratch: str
    research: str
    planning_prefixes: Tuple[str, ...]


@dataclass(frozen=True)
class TestsConfig:
    """Where the project's tests live, how a path is recognized as one, and which registered tests
    pr-review fixers defer (measured slower than ``fixer_test_seconds`` in ``timings``, or flagged) or never
    run side by side (``serial_flags``)."""

    roots: Tuple[str, ...]
    file_pattern: str
    registry: Optional[str]
    registry_names: Tuple[str, ...]
    timings: Optional[str]
    fixer_test_seconds: Optional[float]
    defer_flags: Tuple[str, ...]
    serial_flags: Tuple[str, ...]

    def is_test_path(self, path: str) -> bool:
        """Return True for a repo-relative POSIX path under a test root or matching ``file_pattern``."""
        return path.startswith(self.roots) or re.search(self.file_pattern, path) is not None


@dataclass(frozen=True)
class DomainPointer:
    """Rule text added to a reviewer brief whose scope touches ``prefix``."""

    prefix: str
    pointer: str


@dataclass(frozen=True)
class ReviewConfig:
    """Project guard suites and review-brief additions for pr-review, and the tracking paths (plans, trackers) no
    pr-review fixer owns."""

    guard_suite: Tuple[str, ...]
    local_guards: Tuple[str, ...]
    local_test_pattern: str
    registry_guards: Tuple[str, ...]
    structural_guard_prefixes: Tuple[str, ...]
    content_pin_pattern: Optional[str]
    lenses: Optional[str]
    domain_pointers: Tuple[DomainPointer, ...]
    tracking_paths: Tuple[str, ...]


@dataclass(frozen=True)
class BucketRule:
    """One commit-bucket path rule; the first matching rule wins."""

    bucket: str
    prefixes: Tuple[str, ...]
    names: Tuple[str, ...]
    suffixes: Tuple[str, ...]


@dataclass(frozen=True)
class RunLogsConfig:
    """Where the project's run logs land and how a log file name carries its timestamp."""

    dir: Optional[str]
    name_pattern: str


@dataclass(frozen=True)
class DocstringsConfig:
    """Project values of the docstring convention."""

    line_length: int


@dataclass(frozen=True)
class StrapConfig:
    """Project values of strap-skills: which skills it writes (``harness`` or ``project``)."""

    target: str


@dataclass(frozen=True)
class TodoSnapshots:
    """Where dated TODO snapshots live and how a snapshot file name carries its date."""

    dir: Optional[str]
    name_pattern: str


@dataclass(frozen=True)
class TodoResearch:
    """The research catalog and the stub line naming a catalog entry."""

    catalog: Optional[str]
    anchor_pattern: str
    ignore_folders: Tuple[str, ...]


@dataclass(frozen=True)
class TodoConfig:
    """TODO catalog sync: the catalog and the artifacts the todo_sync rules compare it with.

    Paths are project-relative POSIX, resolved from ``todo.folder``, and never climb above the project root;
    each is None while the feature is off (``folder`` null) or its key is null. ``catalog_schema`` and
    ``research.catalog`` left at their defaults are also None while their file is absent; a name the project
    sets explicitly must exist (``ConfigError`` otherwise).
    """

    folder: Optional[str]
    catalog: Optional[str]
    catalog_schema: Optional[str]
    stub_name: Optional[str]
    top_n: int
    snapshots: TodoSnapshots
    research: TodoResearch
    plans_pairs: bool
    gh_repo: Optional[str]
    gh_max_age_hours: float
    rules_disabled: Tuple[str, ...]
    rules_warn_counts: bool
    inject_context: bool
    notice_style: str
    notice_toast_seconds: float
    notice_items: int

    @property
    def enabled(self) -> bool:
        """True once ``todo.folder`` is configured."""
        return self.folder is not None


@dataclass(frozen=True)
class CannedSet:
    """One project canned set: the file patterns a change must stay within, and its commit message."""

    patterns: Tuple[str, ...]
    message: str


@dataclass(frozen=True)
class HarnessConfig:
    """Merged, validated harness configuration for one project root."""

    project_root: Path
    source: Optional[Path]
    harness_version: Optional[str]
    base_branch: Optional[str]
    integration_branches: Tuple[str, ...]
    skills_dir: str
    agents_dir: str
    schemas_dir: str
    state_dir: str
    matrix_path: str
    agent_usage_path: str
    exclusions: Optional[str]
    artifacts: Artifacts
    tests: TestsConfig
    review: ReviewConfig
    commit_buckets: Tuple[BucketRule, ...]
    auto_approve_python_c: bool
    auto_title: bool
    worktree_root: Optional[str]
    worktree_setup: Tuple[Tuple[str, ...], ...]
    worktree_baseline: Tuple[Tuple[str, ...], ...]
    runlogs: RunLogsConfig
    docstrings: DocstringsConfig
    todo: TodoConfig
    strap: StrapConfig
    plugins: Tuple[Tuple[str, str], ...]
    canned_messages: Tuple[CannedSet, ...] = ()

    def plugin(self, name: str) -> Dict[str, Any]:
        """A fresh copy of the ``plugins.<name>`` section; empty when the project sets none."""
        return json.loads(dict(self.plugins).get(name, "{}"))

    def path(self, rel: str) -> Path:
        """Absolute path of a project-relative POSIX path."""
        return self.project_root / Path(rel)

    def resolve_base_branch(self) -> str:
        """Configured base branch, else the branch ``origin/HEAD`` points at, else ``main``."""
        return self.base_branch or _origin_head(self.project_root) or "main"

    def resolve_integration_branches(self) -> Tuple[str, ...]:
        """Configured integration branches, else the base branch plus ``main`` (deduplicated)."""
        if self.integration_branches:
            return self.integration_branches
        return tuple(dict.fromkeys((self.resolve_base_branch(), "main")))

    def resolve_worktree_root(self) -> Path:
        """Folder for new linked worktrees: ``worktree_root`` (``~``, ``{repo}`` expanded) or the default."""
        template = self.worktree_root or DEFAULT_WORKTREE_ROOT
        return Path(template.replace("{repo}", main_worktree(self.project_root).name)).expanduser()


_ACTIVE: Optional[HarnessConfig] = None


def activate(cfg: HarnessConfig) -> HarnessConfig:
    """Make ``cfg`` the process-wide configuration library code reads through ``active()``.

    Drivers (scripts, hooks) call this once at startup; a process serves exactly one project.
    """
    global _ACTIVE
    _ACTIVE = cfg
    return cfg


def active() -> HarnessConfig:
    """The activated configuration, else one loaded (and activated) for the cwd's project."""
    if _ACTIVE is None:
        return activate(load_config(project_root()))
    return _ACTIVE


def deactivate() -> None:
    """Forget the activated configuration (tests)."""
    global _ACTIVE
    _ACTIVE = None


def load_config(project_root: Path, config_path: Optional[Path] = None) -> HarnessConfig:
    """Load ``<project_root>/.claude/harness.json`` over the plugin defaults and validate the result.

    ``config_path`` names an alternate file read in place of the project's own (it must exist).
    """
    root = Path(project_root).resolve()
    source = root / CONFIG_REL if config_path is None else Path(config_path).resolve()
    if config_path is not None and not source.is_file():
        raise ConfigError(f"{source}: not found")
    override = _read_json(source) if source.is_file() else {}
    _validate(override, source)
    merged = deep_merge(_read_json(DEFAULTS_PATH), override)
    return _build(merged, root, source if source.is_file() else None, override)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``override`` into a copy of ``base``: nested objects merge, everything else replaces."""
    out = dict(base)
    for key, value in override.items():
        nested = isinstance(value, dict) and isinstance(out.get(key), dict)
        out[key] = deep_merge(out[key], value) if nested else value
    return out


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be an object")
    return data


def _validate(data: Dict[str, Any], source: Path) -> None:
    schema = _read_json(SCHEMA_PATH)
    try:
        import jsonschema
    except ImportError:
        _validate_minimal(data, schema, source)
        return
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        where = "/".join(str(p) for p in errors[0].absolute_path) or "<root>"
        raise ConfigError(f"{source}: {where}: {errors[0].message}")


def _validate_minimal(data: Dict[str, Any], schema: Dict[str, Any], source: Path) -> None:
    unknown = sorted(set(data) - set(schema["properties"]))
    if unknown:
        raise ConfigError(f"{source}: unknown keys {unknown}")
    pattern = data.get("tests", {}).get("file_pattern")
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{source}: tests/file_pattern: {exc}") from exc


def _build(m: Dict[str, Any], root: Path, source: Optional[Path],
           override: Optional[Dict[str, Any]] = None) -> HarnessConfig:
    return HarnessConfig(
        project_root=root, source=source, harness_version=m["harness_version"], base_branch=m["base_branch"],
        integration_branches=tuple(m["integration_branches"]), skills_dir=m["skills_dir"],
        agents_dir=m["agents_dir"], schemas_dir=m["schemas_dir"], state_dir=m["state_dir"],
        matrix_path=m["matrix_path"],
        agent_usage_path=m["agent_usage_path"], exclusions=m["exclusions"],
        artifacts=_artifacts(m["artifacts"]), tests=_tests(m["tests"]),
        review=_review(m["review"]), commit_buckets=tuple(_bucket(b) for b in m["commit_buckets"]),
        auto_approve_python_c=bool(m["auto_approve_python_c"]), auto_title=bool(m["auto_title"]),
        worktree_root=m["worktree_root"],
        worktree_setup=_argv_list(m["worktree_setup"], "worktree_setup"),
        worktree_baseline=_argv_list(m["worktree_baseline"], "worktree_baseline"),
        runlogs=_runlogs(m["runlogs"]), docstrings=_docstrings(m["docstrings"]),
        todo=_todo(m["todo"], root, (override or {}).get("todo") or {}),
        strap=_strap(m["strap"]),
        plugins=_plugins(m["plugins"]),
        canned_messages=_canned_messages(m["canned_messages"]),
    )


def _strap(s: Dict[str, Any]) -> StrapConfig:
    """``strap`` with ``target`` checked against its two profiles, also on a load without ``jsonschema``."""
    if not isinstance(s, dict):
        raise ConfigError("strap: must be an object")
    unknown = sorted(set(s) - {"target"})
    if unknown:
        raise ConfigError(f"strap: unknown keys {unknown}")
    target = s.get("target")
    if target not in ("harness", "project"):
        raise ConfigError(f"strap/target: {target!r} is not 'harness' or 'project'")
    return StrapConfig(target)


def _plugins(p: Dict[str, Any]) -> Tuple[Tuple[str, str], ...]:
    """``plugins`` as sorted ``(name, JSON text)`` pairs, checked also on a load without ``jsonschema``."""
    if not isinstance(p, dict):
        raise ConfigError("plugins: must be an object")
    names = sorted(n for n in p if not re.fullmatch(r"[a-z][a-z0-9-]*", n))
    if names:
        raise ConfigError(f"plugins: section names {names} must match ^[a-z][a-z0-9-]*$")
    bad = sorted(name for name, section in p.items() if not isinstance(section, dict))
    if bad:
        raise ConfigError(f"plugins: sections {bad} must be objects")
    return tuple((name, json.dumps(p[name], sort_keys=True)) for name in sorted(p))


def _canned_messages(raw: Any) -> Tuple[CannedSet, ...]:
    """``canned_messages`` as ``CannedSet`` tuples in the project's order, checked also on a load without
    ``jsonschema``."""
    if not isinstance(raw, list):
        raise ConfigError("canned_messages: must be a list")
    return tuple(_canned_set(entry, f"canned_messages/{n}") for n, entry in enumerate(raw))


def _canned_set(entry: Any, where: str) -> CannedSet:
    """One ``{patterns, message}`` object; ConfigError on any other shape."""
    if not isinstance(entry, dict) or set(entry) != {"patterns", "message"}:
        raise ConfigError(f"{where}: must be an object with exactly the keys patterns and message")
    patterns, message = entry["patterns"], entry["message"]
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
        raise ConfigError(f"{where}/patterns: must be a non-empty list of non-empty strings")
    if not isinstance(message, str) or not message:
        raise ConfigError(f"{where}/message: must be a non-empty string")
    return CannedSet(tuple(patterns), message)


def _require_group(pattern: str, group: str, where: str) -> None:
    """Raise ConfigError unless ``pattern`` compiles and has the named group ``group``."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{where}: {exc}") from exc
    if group not in compiled.groupindex:
        raise ConfigError(f"{where}: no named group '{group}'")


def _argv_list(commands: List[List[str]], where: str) -> Tuple[Tuple[str, ...], ...]:
    """Each configured command as an immutable argv tuple; ConfigError unless each is a non-empty str list.

    Repeats the schema's ``argvList`` shape check, so a load without ``jsonschema`` never splits a
    command string into one-character argv entries.
    """
    if not isinstance(commands, list) or not all(_is_argv(argv) for argv in commands):
        raise ConfigError(f"{where}: must be a list of non-empty lists of non-empty strings")
    return tuple(tuple(argv) for argv in commands)


def _is_argv(argv: Any) -> bool:
    """True when ``argv`` is a non-empty list of non-empty strings."""
    return isinstance(argv, list) and bool(argv) and all(isinstance(a, str) and a for a in argv)


def _runlogs(r: Dict[str, Any]) -> RunLogsConfig:
    """``runlogs`` with ``name_pattern`` compiled and checked for the required named group ``date``."""
    _require_group(r["name_pattern"], "date", "runlogs/name_pattern")
    return RunLogsConfig(r["dir"], r["name_pattern"])


def _docstrings(d: Dict[str, Any]) -> DocstringsConfig:
    """``docstrings`` with ``line_length`` checked as a positive integer, also on a load without
    ``jsonschema``."""
    if not isinstance(d, dict):
        raise ConfigError("docstrings: must be an object")
    unknown = sorted(set(d) - {"line_length"})
    if unknown:
        raise ConfigError(f"docstrings: unknown keys {unknown}")
    length = d.get("line_length")
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ConfigError(f"docstrings/line_length: {length!r} is not a positive integer")
    return DocstringsConfig(length)


def _inside_root(rel: str, where: str) -> str:
    """``rel`` unless it climbs above the project root (``..`` or ``../...``); ConfigError then."""
    if rel == ".." or rel.startswith("../"):
        raise ConfigError(f"{where}: {rel} resolves above the project root")
    return rel


def _in_folder(folder: Optional[str], name: Optional[str], where: str) -> Optional[str]:
    """``name`` joined to ``folder`` and normalized (``..`` folds); None when either is None.

    Raises ConfigError when the result climbs above the project root.
    """
    if folder is None or name is None:
        return None
    return _inside_root(posixpath.normpath(posixpath.join(folder, name.replace("\\", "/"))), where)


def _if_present(root: Path, rel: Optional[str], explicit: bool, where: str) -> Optional[str]:
    """``rel`` when that project file exists; else None for a defaulted name, ConfigError for an explicit."""
    if rel is None or (root / rel).is_file():
        return rel
    if explicit:
        raise ConfigError(f"{where}: {rel} not found")
    return None


def _todo(t: Dict[str, Any], root: Path, explicit: Dict[str, Any]) -> TodoConfig:
    """``todo`` with every path resolved under ``folder`` and both patterns checked for their named groups.

    ``explicit`` is the project's own ``todo`` block: a file it names must exist, a defaulted one may not.
    """
    snaps, research = t["snapshots"], t["research"]
    _require_group(snaps["name_pattern"], "date", "todo/snapshots/name_pattern")
    _require_group(research["anchor_pattern"], "id", "todo/research/anchor_pattern")
    folder = t["folder"].replace("\\", "/").rstrip("/") if t["folder"] is not None else None
    if folder is not None:
        _inside_root(posixpath.normpath(folder), "todo/folder")
    schema = _if_present(root, _in_folder(folder, t["catalog_schema"], "todo/catalog_schema"),
                         explicit.get("catalog_schema") is not None, "todo/catalog_schema")
    research_catalog = _if_present(root, _in_folder(folder, research["catalog"], "todo/research/catalog"),
                                   (explicit.get("research") or {}).get("catalog") is not None,
                                   "todo/research/catalog")
    return TodoConfig(
        folder=folder, catalog=_in_folder(folder, t["catalog"], "todo/catalog"),
        catalog_schema=schema, stub_name=t["stub_name"], top_n=int(t["top_n"]),
        snapshots=TodoSnapshots(_in_folder(folder, snaps["dir"], "todo/snapshots/dir"),
                                snaps["name_pattern"]),
        research=TodoResearch(research_catalog, research["anchor_pattern"],
                              tuple(research["ignore_folders"])),
        plans_pairs=bool(t["plans"]["pairs"]), gh_repo=t["gh"]["repo"],
        gh_max_age_hours=float(t["gh"]["max_age_hours"]), rules_disabled=tuple(t["rules"]["disabled"]),
        rules_warn_counts=bool(t["rules"]["warn_counts"]), inject_context=bool(t["inject_context"]),
        notice_style=t["notice"]["style"], notice_toast_seconds=float(t["notice"]["toast_seconds"]),
        notice_items=int(t["notice"]["items"]),
    )


def _artifacts(a: Dict[str, Any]) -> Artifacts:
    return Artifacts(a["reviews"], a["plans"], a["summaries"], a["commit_messages"], a["scratch"],
                     a["research"], tuple(a["planning_prefixes"]))


def _tests(t: Dict[str, Any]) -> TestsConfig:
    ceiling = t["fixer_test_seconds"]
    return TestsConfig(tuple(t["roots"]), t["file_pattern"], t["registry"], tuple(t["registry_names"]),
                       t["timings"], None if ceiling is None else float(ceiling), tuple(t["defer_flags"]),
                       tuple(t["serial_flags"]))


def _review(r: Dict[str, Any]) -> ReviewConfig:
    pointers = tuple(DomainPointer(p["prefix"], p["pointer"]) for p in r["domain_pointers"])
    return ReviewConfig(tuple(r["guard_suite"]), tuple(r["local_guards"]), r["local_test_pattern"],
                        tuple(r["registry_guards"]), tuple(r["structural_guard_prefixes"]),
                        r["content_pin_pattern"], r["lenses"], pointers, tuple(r["tracking_paths"]))


def _bucket(b: Dict[str, Any]) -> BucketRule:
    return BucketRule(b["bucket"], tuple(b.get("prefixes", ())), tuple(b.get("names", ())),
                      tuple(b.get("suffixes", ())))


def _origin_head(root: Path) -> Optional[str]:
    """Branch name ``refs/remotes/origin/HEAD`` points at, or None (also when git is missing or hangs)."""
    argv = ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
    try:
        done = run_git(argv)
    except OSError:
        return None
    ref = done.stdout.strip()
    return ref.split("/", 1)[1] if done.returncode == 0 and "/" in ref else None
