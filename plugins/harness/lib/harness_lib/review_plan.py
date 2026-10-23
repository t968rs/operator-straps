"""Pure pr-review planning: review buckets, exclusions, lens triggers, structural guards and reviewer slots.

Used by the pr-review driver (the plugin's ``scripts/pr_review.py``) during ``capture``. Review buckets are a
review concept, separate from the commit buckets of ``harness_lib.branch_commits``: precedence is
``cicd > config-or-registry > tests > runtime > docs``, anything else is ``unbucketed`` (reviewed by OVERALL
only).
Machine-generated paths (the project's exclusions list plus ``Bucket.ARTIFACT``) are never review subjects.

Every project value comes from ``harness_lib.config.active()``, read inside the functions: the exclusions
file (``exclusions``), test roots and registry (``tests``), the guard suites, structural prefixes and content
pin (``review``), ``skills_dir`` and ``schemas_dir``. With none configured, nothing is excluded, no registry
file exists and no structural guard runs. The lens catalog is the plugin's ``CrossCuttingLensCatalog.json``
merged with the project's lens file (``review.lenses``); see ``load_lens_catalog``.
The module runs no subprocess and no git; callers pass the path lists and grep output in.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Pattern, Sequence, Tuple

from harness_lib.branch_commits import Bucket, path_bucket

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

SMALL_PR_FILES = 20
PATH_BUCKETS = ("cicd", "config-or-registry", "tests", "runtime", "docs")
UNBUCKETED = "unbucketed"
CATALOG_NAME = "CrossCuttingLensCatalog.json"

SKILL_PACKAGE = "per-skill-package"
MULTI_ARTIFACT = "coordinated-multi-artifact"
SYSTEM_SHAPE = "overall-system-shape"
LENS_NAMES = (SKILL_PACKAGE, MULTI_ARTIFACT, SYSTEM_SHAPE)

_CONFIG_NAMES = ("pyproject.toml",)
_RUNTIME_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".sh", ".ps1")
_DOCS_SUFFIXES = (".md", ".txt", ".rst")
_SLOT_IDS = {"config-or-registry": "config"}
_LENS_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_RESERVED_SLOT_IDS = frozenset(
    {"cicd", "config", "tests", "runtime", "docs", "overall", "roast", "system_shape", "skill_package",
     "multi_artifact"})


def _cfg() -> HarnessConfig:
    """The active harness configuration."""
    from harness_lib.config import active
    return active()


def _dir_prefix(rel: str) -> str:
    """``rel`` as a POSIX directory prefix ending in ``/``."""
    return rel.replace("\\", "/").rstrip("/") + "/"


def exclusion_patterns(repo: Path) -> Tuple[str, ...]:
    """The machine-generated exclusion patterns (the Phase 4 / Phase 2 list) of the project's configured
    ``exclusions`` file under ``repo``, plus any harness pattern the file lacks; empty when none is
    configured."""
    cfg = _cfg()
    if not cfg.exclusions:
        return ()
    from harness_lib.default_exclusions import with_harness_patterns
    from harness_lib.git_status_filter_excluded import load_exclusions
    return tuple(with_harness_patterns(cfg, load_exclusions(Path(repo) / cfg.exclusions)))


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    """Returns True when ``path`` matches an exclusion pattern (``fnmatch``) or buckets as ``ARTIFACT``."""
    return any(fnmatch.fnmatch(path, p) for p in patterns) or path_bucket(path) is Bucket.ARTIFACT


def registry_names() -> Tuple[str, ...]:
    """File names of the project's test registry and its schemas (``tests.registry`` + ``registry_names``)."""
    tests = _cfg().tests
    names = tests.registry_names + ((PurePosixPath(tests.registry).name,) if tests.registry else ())
    return tuple(dict.fromkeys(names))


def skills_dir() -> str:
    """The project's skills directory as a POSIX prefix ending in ``/``."""
    return _dir_prefix(_cfg().skills_dir)


def skill_folder(name: str) -> str:
    """The folder prefix of skill ``name`` under the project's skills directory."""
    return f"{skills_dir()}{name}/"


def _schemas_prefix() -> str:
    """The project's pinned-schema directory as a POSIX prefix ending in ``/``."""
    return _dir_prefix(_cfg().schemas_dir)


def _is_config(path: str) -> bool:
    """Returns True for registry, schema, packaging, settings and pinned-schema JSON paths."""
    name = PurePosixPath(path).name
    return (name in _CONFIG_NAMES or name in registry_names() or name.endswith(".schema.json")
            or fnmatch.fnmatchcase(name, "requirements*.txt")
            or fnmatch.fnmatchcase(path, ".claude/settings*.json")
            or (path.startswith(_schemas_prefix()) and name.endswith(".json")))


def review_bucket(path: str) -> str:
    """Returns the review bucket of a repo-relative path: a ``PATH_BUCKETS`` member or ``unbucketed``."""
    if path_bucket(path) is Bucket.CICD:
        return "cicd"
    if _is_config(path):
        return "config-or-registry"
    if _cfg().tests.is_test_path(path):
        return "tests"
    if path.endswith(_RUNTIME_SUFFIXES):
        return "runtime"
    if path.endswith(_DOCS_SUFFIXES) or path.startswith("docs/"):
        return "docs"
    return UNBUCKETED


def sort_buckets(paths: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    """Sorts ``paths`` (order kept, no duplicates) into every ``PATH_BUCKETS`` key plus ``unbucketed``."""
    out: Dict[str, List[str]] = {key: [] for key in PATH_BUCKETS + (UNBUCKETED,)}
    for path in dict.fromkeys(paths):
        out[review_bucket(path)].append(path)
    return {key: tuple(value) for key, value in out.items()}


def merge_registry_into_tests(
    buckets: Mapping[str, Tuple[str, ...]],
) -> Tuple[Dict[str, Tuple[str, ...]], Tuple[str, ...]]:
    """Folds a config-or-registry bucket of only registry files into tests; returns buckets and rationale."""
    merged = dict(buckets)
    config = merged.get("config-or-registry", ())
    names = registry_names()
    if not config or not names or not all(PurePosixPath(p).name in names for p in config):
        return merged, ()
    merged["tests"] = tuple(merged.get("tests", ())) + tuple(config)
    merged["config-or-registry"] = ()
    note = f"config-or-registry holds only registry files ({', '.join(config)}); merged into tests"
    return merged, (note,)


def skills_touched(paths: Sequence[str]) -> Tuple[str, ...]:
    """Returns the sorted unique skill names of paths under ``<skills_dir>/<name>/``."""
    root = skills_dir()
    names = {p[len(root):].split("/", 1)[0] for p in paths if p.startswith(root) and "/" in p[len(root):]}
    return tuple(sorted(names))


def skill_mentioned(name: str, grep_lines: Sequence[str], patterns: Sequence[str]) -> bool:
    """Returns True when a ``<path>:<lineno>:<text>`` line outside the skill folder names ``name`` whole.

    Hyphens count as name characters, so ``pr-review`` does not match inside ``pr-review-watch``. Lines from
    excluded paths and malformed lines never count.
    """
    word = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
    folder = skill_folder(name)
    for line in grep_lines:
        parts = line.split(":", 2)
        if len(parts) < 3 or parts[0].startswith(folder) or is_excluded(parts[0], patterns):
            continue
        if word.search(parts[2]):
            return True
    return False


def multi_artifact(files: Sequence[Tuple[str, str]]) -> Tuple[str, ...]:
    """Returns the NEW (status ``A``) schema / pinned-schema paths when there are two or more, else ``()``."""
    prefix = _schemas_prefix()
    new = tuple(path for status, path in files if status == "A"
                and (path.endswith(".schema.json") or path.startswith(prefix)))
    return new if len(new) >= 2 else ()


# --- lens catalog -------------------------------------------------------------------------------------------


def load_lens_catalog(cfg: Optional[HarnessConfig] = None) -> Dict[str, object]:
    """The plugin lens catalog merged with the project's lens file (``review.lenses``) when configured.

    A project lens named like a catalog lens replaces its ``summary`` / ``scope_template`` only; any other
    project lens is appended (validated by ``_check_project_lens``); project ``default_sub_lenses`` follow
    the plugin's. A malformed lens file raises ``ValueError``.
    """
    from harness_lib.project import plugin_root
    cfg = cfg or _cfg()
    catalog = json.loads((plugin_root() / "schemas" / "catalogs" / CATALOG_NAME).read_text(encoding="utf-8"))
    if not cfg.review.lenses:
        return catalog
    path = cfg.path(cfg.review.lenses)
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"lens file {path}: {exc}") from exc
    return _merge_catalog(catalog, project)


def _merge_catalog(catalog: Dict[str, object], project: Mapping[str, object]) -> Dict[str, object]:
    """``catalog`` with the project lens file's lenses and default sub-lenses merged in."""
    out = copy.deepcopy(catalog)
    lenses: List[Dict[str, object]] = out["lenses"]  # type: ignore[assignment]
    by_name = {str(lens["name"]): lens for lens in lenses}
    for lens in project.get("lenses") or []:  # type: ignore[union-attr]
        name = str(lens.get("name", ""))
        if name in by_name:
            by_name[name].update({k: lens[k] for k in ("summary", "scope_template") if k in lens})
            continue
        _check_project_lens(lens)
        lenses.append(copy.deepcopy(dict(lens)))
        by_name[name] = lenses[-1]
    out["default_sub_lenses"] = [*out["default_sub_lenses"],  # type: ignore[misc]
                                 *(project.get("default_sub_lenses") or [])]  # type: ignore[misc]
    return out


def _check_project_lens(lens: Mapping[str, object]) -> None:
    """Raise ``ValueError`` unless ``lens`` has a free lowercase-hyphenated name, a scope template and
    trigger ``path_globs``."""
    name = str(lens.get("name", ""))
    if not _LENS_NAME.match(name) or lens_slot_id(name) in _RESERVED_SLOT_IDS:
        raise ValueError(f"project lens name {name!r} must be lowercase-hyphenated and not a reserved slot")
    trigger = lens.get("trigger")
    if not isinstance(trigger, dict) or not trigger.get("path_globs"):
        raise ValueError(f"project lens {name!r} needs trigger.path_globs")
    if not lens.get("scope_template"):
        raise ValueError(f"project lens {name!r} needs a scope_template")


def lens_slot_id(name: str) -> str:
    """Slot id of a project lens: its name with hyphens as underscores."""
    return name.replace("-", "_")


def extra_lens_names(catalog: Mapping[str, object]) -> Tuple[str, ...]:
    """Names of the catalog's project lenses (every lens beyond ``LENS_NAMES``), in catalog order."""
    return tuple(str(lens["name"]) for lens in catalog["lenses"]  # type: ignore[union-attr]
                 if lens["name"] not in LENS_NAMES)


def project_lens_paths(catalog: Mapping[str, object],
                       reviewable: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    """Triggered project lenses: name -> reviewable paths matching its ``path_globs``, when at least
    ``min_files`` (default 1) match."""
    extra = set(extra_lens_names(catalog))
    out: Dict[str, Tuple[str, ...]] = {}
    for lens in catalog["lenses"]:  # type: ignore[union-attr]
        if lens["name"] not in extra:
            continue
        trigger = lens["trigger"]
        hits = tuple(p for p in reviewable if any(fnmatch.fnmatch(p, g) for g in trigger["path_globs"]))
        if hits and len(hits) >= int(trigger.get("min_files", 1)):
            out[str(lens["name"])] = hits
    return out


# --- structural guards --------------------------------------------------------------------------------------


def content_pin() -> Optional[Pattern[str]]:
    """The project's compiled ``review.content_pin_pattern``, or None."""
    pattern = _cfg().review.content_pin_pattern
    return re.compile(pattern) if pattern else None


def is_pin_candidate(path: str) -> bool:
    """True when a content pin is configured and ``path`` is one of the project's test paths."""
    return bool(_cfg().review.content_pin_pattern) and _cfg().tests.is_test_path(path)


@dataclass(frozen=True)
class GuardDecision:
    """Phase 1 Check 2 outcome: whether the structural guard suite runs, why, and which files it runs."""

    applies: bool
    local: bool
    registry: bool
    reasons: Tuple[str, ...]
    suite: Tuple[str, ...]


def _guard_reasons(
        paths: Sequence[str], pinned_tests: Sequence[str],
) -> Tuple[List[str], List[str], List[str]]:
    """Returns (base reasons, local-test reasons, registry reasons) for the touched paths.

    Local and registry reasons count only when the project configures the matching guards.
    """
    review = _cfg().review
    prefixes = review.structural_guard_prefixes
    base = [f"path prefix: {p}" for p in paths if prefixes and p.startswith(prefixes)]
    base += [f"content pin: {p}" for p in pinned_tests]
    local_test = re.compile(review.local_test_pattern)
    local = [f"local test: {p}" for p in paths if review.local_guards and local_test.search(p)]
    names = registry_names()
    registry = [f"registry: {p}" for p in paths if review.registry_guards and PurePosixPath(p).name in names]
    return base, local, registry


def guard_decision(paths: Sequence[str], pinned_tests: Sequence[str]) -> GuardDecision:
    """Decides the structural guard run from the PR paths and the touched tests carrying a content pin.

    The suite is ``review.guard_suite``, plus ``review.local_guards`` when a ``test_*_local.py`` file is
    touched, plus ``review.registry_guards`` when a registry file is touched; duplicates are dropped in
    order. Without any guard file to run, the decision never applies.
    """
    review = _cfg().review
    base, local, registry = _guard_reasons(paths, pinned_tests)
    reasons = tuple(base + local + registry)
    suite = review.guard_suite + (review.local_guards if local else ()) + \
        (review.registry_guards if registry else ())
    if not reasons or not suite:
        return GuardDecision(False, False, False, (), ())
    return GuardDecision(True, bool(local), bool(registry), reasons, tuple(dict.fromkeys(suite)))


def roll_roast(rng: random.Random) -> bool:
    """Returns the 50/50 roast roll drawn from ``rng`` (same coin as ``to_roast_or_not_to_roast.py``)."""
    return rng.choice([True, False])


# --- slots --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Slot:
    """One reviewer dispatch: slot id, lens or bucket, model, scope paths and embedded catalog lens templates.

    ``lens`` is a bucket name, a catalog lens name, ``overall`` or ``roast``. A roast slot replacing OVERALL
    on a small PR carries ``lens="overall"`` and ``roast=True``. ``templates`` holds catalog lens names only.
    """

    id: str
    lens: str
    model: str
    paths: Tuple[str, ...]
    templates: Tuple[str, ...]
    roast: bool = False


def _bucket_slots(buckets: Mapping[str, Tuple[str, ...]]) -> List[Slot]:
    """Returns one slot per non-empty path bucket; a single-file bucket runs on ``sonnet``."""
    slots = []
    for bucket in PATH_BUCKETS:
        paths = tuple(buckets.get(bucket, ()))
        if paths:
            model = "sonnet" if len(paths) == 1 else "opus"
            slots.append(Slot(_SLOT_IDS.get(bucket, bucket), bucket, model, paths, ()))
    return slots


def _lens_slots(lenses: Mapping[str, Tuple[str, ...]], extra: Sequence[str]) -> List[Slot]:
    """Returns the per-skill-package, multi-artifact and project-lens slots; an unknown name raises."""
    unknown = sorted(set(lenses) - set(LENS_NAMES) - set(extra))
    if unknown:
        raise ValueError(f"unknown lens name(s): {', '.join(unknown)}")
    ids = ((SKILL_PACKAGE, "skill_package"), (MULTI_ARTIFACT, "multi_artifact"),
           *((name, lens_slot_id(name)) for name in extra))
    return [Slot(sid, name, "opus", tuple(lenses[name]), (name,)) for name, sid in ids if lenses.get(name)]


def _system_shape(buckets: Mapping[str, Tuple[str, ...]], lenses: Mapping[str, Tuple[str, ...]]) -> bool:
    """Returns True when three or more path buckets are non-empty or the lens mapping names system shape."""
    return bool(lenses.get(SYSTEM_SHAPE)) or sum(1 for b in PATH_BUCKETS if buckets.get(b)) >= 3


def _overall_slots(shape: bool, roast: bool, reviewable: Tuple[str, ...]) -> List[Slot]:
    """Returns the OVERALL, system-shape and roast slots under the small-PR lens cut."""
    if len(reviewable) < SMALL_PR_FILES:
        folded = (SYSTEM_SHAPE,) if shape else ()
        return [Slot("roast" if roast else "overall", "overall", "opus", reviewable, folded, roast)]
    slots = [Slot("overall", "overall", "opus", reviewable, ())]
    if shape:
        slots.append(Slot("system_shape", SYSTEM_SHAPE, "opus", reviewable, (SYSTEM_SHAPE,)))
    if roast:
        slots.append(Slot("roast", "roast", "opus", reviewable, (), True))
    return slots


def slot_plan(buckets: Mapping[str, Tuple[str, ...]], lenses: Mapping[str, Tuple[str, ...]],
              roast: bool, reviewable: Tuple[str, ...], *,
              extra_lenses: Sequence[str] = ()) -> Tuple[Slot, ...]:
    """Plans the reviewer slots: path buckets, triggered cross-cutting lenses, then OVERALL / shape / roast.

    ``extra_lenses`` names the project lenses ``lenses`` may carry (``extra_lens_names``). Below
    ``SMALL_PR_FILES`` reviewable files, system shape folds into OVERALL's templates and a roast roll
    replaces the OVERALL slot (keeping its full scope). At or above it, all three run as separate slots.
    ``unbucketed`` paths get no slot of their own; OVERALL covers them through ``reviewable``.
    """
    lens_slots = _lens_slots(lenses, extra_lenses)
    shape = _system_shape(buckets, lenses)
    return tuple(_bucket_slots(buckets) + lens_slots + _overall_slots(shape, roast, tuple(reviewable)))
