"""Pure pr-review planning: review buckets, exclusions, lens triggers, structural guards and reviewer slots.

Used by the pr-review driver (the plugin's ``scripts/pr_review.py``) during ``capture``. Review buckets are a
review concept, separate from the commit buckets of ``harness_lib.branch_commits``: ``PathBucket`` lists them
in precedence order (``cicd > config-or-registry > tests > runtime > docs``); anything else is ``unbucketed``
(reviewed by OVERALL only). ``Lens`` names the catalog's cross-cutting lenses and ``ScopeLens`` the OVERALL
and roast slots; a project lens is its plain name.
Machine-generated paths (the project's exclusions list plus ``Bucket.ARTIFACT``) are never review subjects.

Every project value comes from ``harness_lib.config.active()``, read inside the functions: the exclusions
file (``exclusions``), test roots and registry (``tests``), the guard suites, structural prefixes and content
pin (``review``) and ``schemas_dir``. With none configured, nothing is excluded, no registry
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
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Pattern, Sequence, Tuple, Union

from harness_lib.branch_commits import Bucket, path_bucket

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

SMALL_PR_FILES = 20
CATALOG_NAME = "CrossCuttingLensCatalog.json"
SKILLS_SEGMENT = "skills"
SKILL_FILE = "SKILL.md"
#: Top-level folders always searched for a skill's cross-references; each skill root's top folder joins them.
SKILL_GREP_ROOTS = (".claude", "docs", ".github")

_CONFIG_NAMES = ("pyproject.toml",)
_RUNTIME_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".sh", ".ps1")
_DOCS_SUFFIXES = (".md", ".txt", ".rst")
_LENS_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class _MissStrEnum(StrEnum):
    """A ``StrEnum`` whose lookup also takes a member's name or value in any letter case."""

    @classmethod
    def _missing_(cls, value: object) -> Optional[_MissStrEnum]:
        """The member whose name or value equals ``value`` ignoring case; else None (``ValueError``)."""
        if not isinstance(value, str):
            return None
        wanted = value.lower()
        return next((member for name, member in cls.__members__.items()
                     if wanted in (name.lower(), member.value.lower())), None)


class PathBucket(_MissStrEnum):
    """Review buckets in precedence order; an ``UNBUCKETED`` path gets no slot of its own."""

    CICD = "cicd"
    CFG = "config-or-registry"
    TESTS = "tests"
    RUNTIME = "runtime"
    DOCS = "docs"
    UNBUCKETED = "unbucketed"

    @classmethod
    def slotted(cls) -> Tuple[PathBucket, ...]:
        """The buckets that get a reviewer slot, in precedence order."""
        return tuple(bucket for bucket in cls if bucket is not cls.UNBUCKETED)

    @property
    def slot_id(self) -> str:
        """The bucket slot's id: ``config`` for the config-or-registry bucket, else the value."""
        return "config" if self is PathBucket.CFG else self.value


class Lens(_MissStrEnum):
    """The plugin catalog's cross-cutting lenses, in catalog order."""

    SKILL_PACKAGE = "per-skill-package"
    MULTI_ARTIFACT = "coordinated-multi-artifact"
    SYSTEM_SHAPE = "overall-system-shape"

    @property
    def slot_id(self) -> str:
        """The lens slot's id."""
        return _LENS_SLOT_IDS[self]


class ScopeLens(_MissStrEnum):
    """Slots scoped to every reviewable path: OVERALL, and roast (that scope in the roast voice)."""

    OVERALL = "overall"
    ROAST = "roast"

    @property
    def slot_id(self) -> str:
        """The slot's id: the value."""
        return self.value


#: A slot's lens: a bucket, a catalog lens, a scope lens, or a project lens's name.
SlotLens = Union[PathBucket, Lens, ScopeLens, str]
_ENUMS = (PathBucket, Lens, ScopeLens)
_LENS_SLOT_IDS = {Lens.SKILL_PACKAGE: "skill_package", Lens.MULTI_ARTIFACT: "multi_artifact",
                  Lens.SYSTEM_SHAPE: "system_shape"}
_LENS_VALUES = frozenset(lens.value for lens in Lens)
_RESERVED_SLOT_IDS = frozenset(m.slot_id for m in (*PathBucket.slotted(), *Lens, *ScopeLens))
_RESERVED_NAMES = frozenset(n for enum in _ENUMS for m in enum for n in (m.value, m.name.lower()))


def resolve_lens(value: SlotLens) -> SlotLens:
    """``value`` as its bucket, lens or scope member; a project lens's name stays a plain string."""
    if isinstance(value, _ENUMS):
        return value
    for enum in _ENUMS:
        try:
            return enum(value)
        except ValueError:
            continue
    return value


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


def review_bucket(path: str) -> PathBucket:
    """Returns the review bucket of a repo-relative path; the first match in precedence order wins."""
    if path_bucket(path) is Bucket.CICD:
        return PathBucket.CICD
    if _is_config(path):
        return PathBucket.CFG
    if _cfg().tests.is_test_path(path):
        return PathBucket.TESTS
    if path.endswith(_RUNTIME_SUFFIXES):
        return PathBucket.RUNTIME
    if path.endswith(_DOCS_SUFFIXES) or path.startswith("docs/"):
        return PathBucket.DOCS
    return PathBucket.UNBUCKETED


def sort_buckets(paths: Sequence[str]) -> Dict[PathBucket, Tuple[str, ...]]:
    """Sorts ``paths`` (order kept, no duplicates) into every ``PathBucket`` key, ``unbucketed`` included."""
    out: Dict[PathBucket, List[str]] = {bucket: [] for bucket in PathBucket}
    for path in dict.fromkeys(paths):
        out[review_bucket(path)].append(path)
    return {key: tuple(value) for key, value in out.items()}


def merge_registry_into_tests(
    buckets: Mapping[PathBucket, Tuple[str, ...]],
) -> Tuple[Dict[PathBucket, Tuple[str, ...]], Tuple[str, ...]]:
    """Folds a config-or-registry bucket of only registry files into tests; returns buckets and rationale."""
    merged = dict(buckets)
    config = merged.get(PathBucket.CFG, ())
    names = registry_names()
    if not config or not names or not all(PurePosixPath(p).name in names for p in config):
        return merged, ()
    merged[PathBucket.TESTS] = tuple(merged.get(PathBucket.TESTS, ())) + tuple(config)
    merged[PathBucket.CFG] = ()
    note = f"{PathBucket.CFG} holds only registry files ({', '.join(config)}); merged into {PathBucket.TESTS}"
    return merged, (note,)


def _skill_folder_of(path: str) -> Optional[str]:
    """``<prefix>skills/<name>/`` when ``path`` sits below a ``skills/<name>/`` folder (first ``skills``
    segment followed by a name and at least one more segment), else None."""
    parts = path.split("/")
    for n, part in enumerate(parts[:-2]):
        if part == SKILLS_SEGMENT:
            return "/".join(parts[:n + 2]) + "/"
    return None


def skill_candidates(paths: Sequence[str]) -> Tuple[str, ...]:
    """The sorted unique ``skills/<name>/`` folders ``paths`` sit under, wherever the ``skills`` folder is."""
    return tuple(sorted({f for f in map(_skill_folder_of, paths) if f}))


def skill_files(candidates: Sequence[str]) -> Tuple[str, ...]:
    """The ``SKILL.md`` path of each candidate folder, in order."""
    return tuple(f"{folder}{SKILL_FILE}" for folder in candidates)


def skill_folders(candidates: Sequence[str], present: Sequence[str]) -> Tuple[str, ...]:
    """The candidate folders whose ``SKILL.md`` is among ``present`` (the files at the PR head), in order."""
    found = set(present)
    return tuple(folder for folder in candidates if f"{folder}{SKILL_FILE}" in found)


def skill_name(folder: str) -> str:
    """A skill's name: its folder's last segment."""
    return PurePosixPath(folder.rstrip("/")).name


def skill_grep_roots(folders: Sequence[str]) -> Tuple[str, ...]:
    """Top-level folders searched for skill cross-references: ``SKILL_GREP_ROOTS`` plus each skill root's
    top folder, once each, in order."""
    return tuple(dict.fromkeys((*SKILL_GREP_ROOTS, *(f.split("/", 1)[0] for f in folders))))


def skill_mentioned(folder: str, grep_lines: Sequence[str], patterns: Sequence[str]) -> bool:
    """Returns True when a ``<path>:<lineno>:<text>`` line outside ``folder`` names its skill whole.

    Hyphens count as name characters, so ``pr-review`` does not match inside ``pr-review-watch``. Lines from
    the skill's own folder, excluded paths and malformed lines never count; a same-name folder under another
    skill root counts.
    """
    word = re.compile(rf"(?<![\w-]){re.escape(skill_name(folder))}(?![\w-])")
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
    trigger ``path_globs``. A name is taken when its slot id is a member's, or when it spells a bucket,
    lens or scope member's value or name (it would resolve to that member)."""
    name = str(lens.get("name", ""))
    if not _LENS_NAME.match(name) or lens_slot_id(name) in _RESERVED_SLOT_IDS or name in _RESERVED_NAMES:
        raise ValueError(f"project lens name {name!r} must be lowercase-hyphenated and not a reserved slot "
                         "or member name")
    trigger = lens.get("trigger")
    if not isinstance(trigger, dict) or not trigger.get("path_globs"):
        raise ValueError(f"project lens {name!r} needs trigger.path_globs")
    if not lens.get("scope_template"):
        raise ValueError(f"project lens {name!r} needs a scope_template")


def lens_slot_id(name: str) -> str:
    """Slot id of a project lens: its name with hyphens as underscores."""
    return name.replace("-", "_")


def extra_lens_names(catalog: Mapping[str, object]) -> Tuple[str, ...]:
    """Names of the catalog's project lenses (every lens beyond ``Lens``), in catalog order."""
    return tuple(str(lens["name"]) for lens in catalog["lenses"]  # type: ignore[union-attr]
                 if lens["name"] not in _LENS_VALUES)


def sub_lenses_for(slot: Slot, catalog: Mapping[str, object]) -> List[Mapping[str, object]]:
    """The catalog's default sub-lens rows that run in ``slot``, in catalog order.

    A row's optional ``skip_lenses`` names the lenses it does not run in (the plugin's linear
    docstring-vs-code pass skips ``roast``); a row without it runs in every slot.
    """
    rows: List[Mapping[str, object]] = catalog["default_sub_lenses"]  # type: ignore[assignment]
    return [row for row in rows if slot.lens not in _skipped_lenses(row)]


def _skipped_lenses(row: Mapping[str, object]) -> frozenset:
    """The lenses a default sub-lens row names in ``skip_lenses``, resolved to their members."""
    return frozenset(resolve_lens(str(name)) for name in row.get("skip_lenses") or ())  # type: ignore[union-attr]


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
    """One reviewer dispatch: slot id, lens, model, scope paths and embedded catalog lens templates.

    ``lens`` is a ``PathBucket``, ``Lens`` or ``ScopeLens`` member, or a project lens's name; a string naming
    a member resolves to it. The roast slot's lens is ``ScopeLens.ROAST`` whether it replaces OVERALL (small
    PR) or runs beside it. ``templates`` holds catalog lens names only.
    """

    id: str
    lens: SlotLens
    model: str
    paths: Tuple[str, ...]
    templates: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Resolve ``lens`` to its member."""
        object.__setattr__(self, "lens", resolve_lens(self.lens))

    @property
    def roast(self) -> bool:
        """True for the roast slot."""
        return self.lens is ScopeLens.ROAST

    @property
    def bucket(self) -> Optional[PathBucket]:
        """The slot's path bucket; None for a lens or scope slot."""
        return self.lens if isinstance(self.lens, PathBucket) else None

    @property
    def overall_scope(self) -> bool:
        """True for the OVERALL and roast slots, which review every reviewable path as one change."""
        return isinstance(self.lens, ScopeLens)

    @property
    def lists_skills(self) -> bool:
        """True for the per-skill-package slot, whose brief names the triggered skills."""
        return self.lens is Lens.SKILL_PACKAGE

    def record(self) -> Dict[str, object]:
        """The slot's ``plan.json`` entry: its fields plus the derived ``roast`` flag."""
        return {**asdict(self), "roast": self.roast}


def _scope_slot(lens: Union[Lens, ScopeLens], paths: Tuple[str, ...], templates: Tuple[str, ...]) -> Slot:
    """An ``opus`` slot for ``lens`` with the lens's own slot id."""
    return Slot(lens.slot_id, lens, "opus", paths, templates)


def _bucket_slots(buckets: Mapping[PathBucket, Tuple[str, ...]]) -> List[Slot]:
    """Returns one slot per non-empty path bucket; a single-file bucket runs on ``sonnet``."""
    slots = []
    for bucket in PathBucket.slotted():
        paths = tuple(buckets.get(bucket, ()))
        if paths:
            model = "sonnet" if len(paths) == 1 else "opus"
            slots.append(Slot(bucket.slot_id, bucket, model, paths, ()))
    return slots


def _lens_slots(lenses: Mapping[str, Tuple[str, ...]], extra: Sequence[str]) -> List[Slot]:
    """Returns the per-skill-package, multi-artifact and project-lens slots; an unknown name raises."""
    unknown = sorted(set(lenses) - _LENS_VALUES - set(extra))
    if unknown:
        raise ValueError(f"unknown lens name(s): {', '.join(unknown)}")
    ids = (*((lens, lens.slot_id) for lens in (Lens.SKILL_PACKAGE, Lens.MULTI_ARTIFACT)),
           *((name, lens_slot_id(name)) for name in extra))
    return [Slot(sid, name, "opus", tuple(lenses[name]), (name,)) for name, sid in ids if lenses.get(name)]


def _system_shape(buckets: Mapping[PathBucket, Tuple[str, ...]],
                  lenses: Mapping[str, Tuple[str, ...]]) -> bool:
    """Returns True when three or more path buckets are non-empty or the lens mapping names system shape."""
    return bool(lenses.get(Lens.SYSTEM_SHAPE)) or sum(1 for b in PathBucket.slotted() if buckets.get(b)) >= 3


def _overall_slots(shape: bool, roast: bool, reviewable: Tuple[str, ...]) -> List[Slot]:
    """Returns the OVERALL, system-shape and roast slots under the small-PR lens cut."""
    if len(reviewable) < SMALL_PR_FILES:
        folded = (Lens.SYSTEM_SHAPE,) if shape else ()
        return [_scope_slot(ScopeLens.ROAST if roast else ScopeLens.OVERALL, reviewable, folded)]
    slots = [_scope_slot(ScopeLens.OVERALL, reviewable, ())]
    if shape:
        slots.append(_scope_slot(Lens.SYSTEM_SHAPE, reviewable, (Lens.SYSTEM_SHAPE,)))
    if roast:
        slots.append(_scope_slot(ScopeLens.ROAST, reviewable, ()))
    return slots


def slot_plan(buckets: Mapping[PathBucket, Tuple[str, ...]], lenses: Mapping[str, Tuple[str, ...]],
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
