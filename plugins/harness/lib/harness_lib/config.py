"""Per-project harness configuration: ``<project>/.claude/harness.json`` merged over the plugin defaults.

Every repo-specific value the harness needs (artifact directories, test layout, review guard suites,
commit bucket rules, base branch) arrives through this module. Objects merge key by key; arrays and
scalars replace. Validation uses ``jsonschema`` when it imports, else a top-level key check.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

CONFIG_REL = Path(".claude") / "harness.json"
_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULTS_PATH = _CONFIG_DIR / "defaults.json"
SCHEMA_PATH = _CONFIG_DIR / "harness.schema.json"
DEFAULT_WORKTREE_ROOT = "~/.config/superpowers/worktrees/{repo}"


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
    """Where the project's tests live and how a path is recognized as one."""

    roots: Tuple[str, ...]
    file_pattern: str
    registry: Optional[str]
    registry_names: Tuple[str, ...]

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
    """Project guard suites and review-brief additions for pr-review."""

    guard_suite: Tuple[str, ...]
    local_guards: Tuple[str, ...]
    local_test_pattern: str
    registry_guards: Tuple[str, ...]
    structural_guard_prefixes: Tuple[str, ...]
    content_pin_pattern: Optional[str]
    lenses: Optional[str]
    domain_pointers: Tuple[DomainPointer, ...]


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
class HarnessConfig:
    """Merged, validated harness configuration for one project root."""

    project_root: Path
    source: Optional[Path]
    harness_version: Optional[str]
    base_branch: Optional[str]
    integration_branches: Tuple[str, ...]
    skills_dir: str
    schemas_dir: str
    state_dir: str
    matrix_path: str
    exclusions: Optional[str]
    artifacts: Artifacts
    tests: TestsConfig
    review: ReviewConfig
    commit_buckets: Tuple[BucketRule, ...]
    auto_approve_python_c: bool
    worktree_root: Optional[str]
    runlogs: RunLogsConfig

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
        from harness_lib.project import main_worktree
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
        from harness_lib.project import project_root
        return activate(load_config(project_root()))
    return _ACTIVE


def deactivate() -> None:
    """Forget the activated configuration (tests)."""
    global _ACTIVE
    _ACTIVE = None


def load_config(project_root: Path) -> HarnessConfig:
    """Load ``<project_root>/.claude/harness.json`` over the plugin defaults and validate the result."""
    root = Path(project_root).resolve()
    source = root / CONFIG_REL
    override = _read_json(source) if source.is_file() else {}
    _validate(override, source)
    merged = deep_merge(_read_json(DEFAULTS_PATH), override)
    return _build(merged, root, source if source.is_file() else None)


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


def _build(m: Dict[str, Any], root: Path, source: Optional[Path]) -> HarnessConfig:
    return HarnessConfig(
        project_root=root, source=source, harness_version=m["harness_version"], base_branch=m["base_branch"],
        integration_branches=tuple(m["integration_branches"]), skills_dir=m["skills_dir"],
        schemas_dir=m["schemas_dir"], state_dir=m["state_dir"], matrix_path=m["matrix_path"],
        exclusions=m["exclusions"], artifacts=_artifacts(m["artifacts"]), tests=_tests(m["tests"]),
        review=_review(m["review"]), commit_buckets=tuple(_bucket(b) for b in m["commit_buckets"]),
        auto_approve_python_c=bool(m["auto_approve_python_c"]), worktree_root=m["worktree_root"],
        runlogs=_runlogs(m["runlogs"]),
    )


def _runlogs(r: Dict[str, Any]) -> RunLogsConfig:
    """``runlogs`` with ``name_pattern`` compiled and checked for the required named group ``date``."""
    try:
        pattern = re.compile(r["name_pattern"])
    except re.error as exc:
        raise ConfigError(f"runlogs/name_pattern: {exc}") from exc
    if "date" not in pattern.groupindex:
        raise ConfigError("runlogs/name_pattern: no named group 'date'")
    return RunLogsConfig(r["dir"], r["name_pattern"])


def _artifacts(a: Dict[str, Any]) -> Artifacts:
    return Artifacts(a["reviews"], a["plans"], a["summaries"], a["commit_messages"], a["scratch"],
                     a["research"], tuple(a["planning_prefixes"]))


def _tests(t: Dict[str, Any]) -> TestsConfig:
    return TestsConfig(tuple(t["roots"]), t["file_pattern"], t["registry"], tuple(t["registry_names"]))


def _review(r: Dict[str, Any]) -> ReviewConfig:
    pointers = tuple(DomainPointer(p["prefix"], p["pointer"]) for p in r["domain_pointers"])
    return ReviewConfig(tuple(r["guard_suite"]), tuple(r["local_guards"]), r["local_test_pattern"],
                        tuple(r["registry_guards"]), tuple(r["structural_guard_prefixes"]),
                        r["content_pin_pattern"], r["lenses"], pointers)


def _bucket(b: Dict[str, Any]) -> BucketRule:
    return BucketRule(b["bucket"], tuple(b.get("prefixes", ())), tuple(b.get("names", ())),
                      tuple(b.get("suffixes", ())))


def _origin_head(root: Path) -> Optional[str]:
    """Branch name ``refs/remotes/origin/HEAD`` points at, or None."""
    argv = ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
    done = subprocess.run(argv, capture_output=True, text=True)
    ref = done.stdout.strip()
    return ref.split("/", 1)[1] if done.returncode == 0 and "/" in ref else None
