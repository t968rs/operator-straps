"""Plan a branch's commit groups from its merge-base capture (branch-commit-msg mechanics).

Input is the capture: every path differing between the merge base and the working tree
(``git diff --name-status -M -z <merge-base>`` plus untracked files). Output is an ordered list of
``CommitGroup`` (paths + carried-forward message) and a ``Split:`` rationale. Commit messages are
not drafted here. This module is the source of truth for pairing, split and ordering rules.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from harness_lib.branch_commits import (
    BUCKET_ORDER,
    BranchCommitDocument,
    Bucket,
    CommitEntry,
    commit_bucket,
    is_planning_path,
    is_registry_path,
    is_source_path,
    path_bucket,
)
from harness_lib.config import active

_GLOB_CHARS = frozenset("*?[")
_ROOT_BUCKETS = frozenset({Bucket.RUNTIME.value, Bucket.TEST.value})

RegistryTargets = Mapping[str, Sequence[str]]


@dataclass(frozen=True)
class CapturedPath:
    """One capture line: status letter (A/M/D/R), path, and the pre-rename path for ``R``."""

    status: str
    path: str
    old_path: Optional[str] = None

    @property
    def paths(self) -> Tuple[str, ...]:
        """Paths to stage: the path, plus the old path of a rename (its deletion side)."""
        return (self.path, self.old_path) if self.old_path else (self.path,)

    @property
    def bucket(self) -> Bucket:
        """Bucket, by the new path for a rename."""
        return path_bucket(self.path)


@dataclass(frozen=True)
class CommitGroup:
    """One planned commit: its paths in staging order and a message (empty when not yet drafted)."""

    paths: Tuple[str, ...]
    message: str = ""


def parse_name_status_z(text: str) -> List[CapturedPath]:
    """Parse ``git diff --name-status -M -z`` output; copies (``C``) are treated as additions."""
    tokens = [token for token in text.split("\0") if token]
    captures: List[CapturedPath] = []
    idx = 0
    while idx < len(tokens):
        status = tokens[idx][0]
        if status == "R":
            captures.append(CapturedPath("R", tokens[idx + 2], tokens[idx + 1]))
            idx += 3
        elif status == "C":
            captures.append(CapturedPath("A", tokens[idx + 2]))
            idx += 3
        else:
            captures.append(CapturedPath(status, tokens[idx + 1]))
            idx += 2
    return captures


def merge_capture(diff: Iterable[CapturedPath], untracked: Iterable[str]) -> List[CapturedPath]:
    """Union the diff with untracked files (status ``A``), one entry per path, sorted by path."""
    by_path: Dict[str, CapturedPath] = {capture.path: capture for capture in diff}
    for path in untracked:
        by_path.setdefault(path, CapturedPath("A", path))
    return [by_path[path] for path in sorted(by_path)]


def captured_set(captures: Iterable[CapturedPath]) -> Set[str]:
    """Every path the rebuild must stage, rename old sides included."""
    return {path for capture in captures for path in capture.paths}


def _test_core(path: str) -> str:
    """Test stem with the ``test_`` prefix and ``_local`` suffix removed, lowercased."""
    stem = PurePosixPath(path).stem.lower()
    stem = stem[len("test_"):] if stem.startswith("test_") else stem
    return stem[:-len("_local")] if stem.endswith("_local") else stem


def _anonymous_dirs() -> Set[str]:
    """Lowercased directory names of the shared roots: test roots and ``Runtime``/``Test`` rule prefixes.

    A root says nothing about which module a test covers, so pairing ignores it.
    """
    cfg = active()
    prefixes = [p for rule in cfg.commit_buckets if rule.bucket in _ROOT_BUCKETS for p in rule.prefixes]
    return {part.lower() for prefix in [*prefixes, *cfg.tests.roots] for part in PurePosixPath(prefix).parts}


def _dirs(path: str) -> Set[str]:
    """Lowercased directory names of ``path``, minus the shared roots."""
    return {part.lower() for part in PurePosixPath(path).parts[:-1]} - _anonymous_dirs()


def _pair_score(test: str, runtime: str) -> Tuple[int, int]:
    """Score a test/runtime match: (2 equal stem | 1 parent-dir prefix + stem | 0 none, shared dirs)."""
    core, stem = _test_core(test), PurePosixPath(runtime).stem.lower()
    shared = len(_dirs(test) & _dirs(runtime))
    if core == stem:
        return 2, shared
    if core.endswith(f"_{stem}") and core[:-len(stem) - 1] in _dirs(runtime):
        return 1, shared
    return 0, 0


def parse_registry_targets(text: str) -> Dict[str, List[str]]:
    """Map each test registry entry's ``file`` to its ``properties.test_target_paths``.

    Unparseable JSON yields an empty map.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    targets: Dict[str, List[str]] = {}
    for entry in data.get("tests", []) if isinstance(data, dict) else []:
        paths = (entry.get("properties") or {}).get("test_target_paths") if isinstance(entry, dict) else None
        if entry.get("file") and paths:
            targets[entry["file"]] = list(paths)
    return targets


def _stem_match(test: str, source_paths: Sequence[str]) -> Optional[str]:
    """Best name-based source for ``test``, or None."""
    scored = [(_pair_score(test, source), source) for source in source_paths]
    candidates = sorted((s for s in scored if s[0][0] > 0), key=lambda s: (-s[0][0], -s[0][1], s[1]))
    return candidates[0][1] if candidates else None


def find_pairs(
        source_paths: Sequence[str],
        test_paths: Sequence[str],
        registry_targets: Optional[RegistryTargets] = None,
) -> Dict[str, List[str]]:
    """Map each paired source path to its test paths; unmatched tests are left out.

    A test's registry ``test_target_paths`` entry wins when it names a captured source; name
    matching is the fallback.
    """
    sources = set(source_paths)
    pairs: Dict[str, List[str]] = {}
    for test in sorted(test_paths):
        listed = sorted(t for t in (registry_targets or {}).get(test, ()) if t in sources)
        match = listed[0] if listed else _stem_match(test, source_paths)
        if match:
            pairs.setdefault(match, []).append(test)
    return pairs


def _is_fix(path: str) -> bool:
    """True for ``fix_*`` modules and their ``test_fix_*`` tests."""
    return PurePosixPath(path).stem.lower().startswith(("fix_", "test_fix_"))


def _chunk_key(source: str, tests: Sequence[str]) -> Tuple[str, bool]:
    """Commit key for a pair: (source module directory, fix intent)."""
    return str(PurePosixPath(source).parent), any(_is_fix(path) for path in [source, *tests])


def split_triggers(pairs: Mapping[str, Sequence[str]]) -> List[str]:
    """Return why the pairs span more than one commit: cross-module and/or mixed intent (empty means one)."""
    keys = {_chunk_key(source, tests) for source, tests in pairs.items()}
    triggers: List[str] = []
    modules = {PurePosixPath(module).name for module, _ in keys}
    if len(modules) >= 2:
        triggers.append(f"cross-module ({', '.join(sorted(modules))})")
    if len({fix for _, fix in keys}) == 2:
        triggers.append("mixed intent (fix_* and feature pairs)")
    return triggers


def _group(captures: Iterable[CapturedPath], message: str = "") -> CommitGroup:
    """Group the captures' paths (rename old sides included) into one commit."""
    return CommitGroup(tuple(path for capture in captures for path in capture.paths), message)


def capture_pairs(
        captures: Iterable[CapturedPath], registry_targets: Optional[RegistryTargets] = None,
) -> Dict[str, List[str]]:
    """Pair Python source captures (runtime, agent, other) with test captures; the registry never pairs."""
    captures = list(captures)
    sources = [c.path for c in captures if is_source_path(c.path)]
    tests = [c.path for c in captures if c.bucket is Bucket.TEST and not is_registry_path(c.path)]
    return find_pairs(sources, tests, registry_targets)


def _pair_chunks(
        captures: Sequence[CapturedPath], registry_targets: Optional[RegistryTargets],
) -> List[List[CapturedPath]]:
    """Return one chunk per (module, intent).

    Pairs sharing a source directory and fix intent commit together.
    """
    pairs = capture_pairs(captures, registry_targets)
    lookup = {capture.path: capture for capture in captures}
    chunks: Dict[Tuple[str, bool], List[CapturedPath]] = {}
    for source in sorted(pairs):
        chunk = chunks.setdefault(_chunk_key(source, pairs[source]), [])
        chunk.extend([lookup[source], *(lookup[test] for test in pairs[source])])
    return [chunks[key] for key in sorted(chunks)]


def _is_test_file(path: str) -> bool:
    """True for a ``test_*.py`` module (as opposed to conftest, helpers, fixtures)."""
    name = PurePosixPath(path).name
    return name.startswith("test_") and name.endswith(".py")


def _on_test_tree(folder: PurePosixPath, test: str) -> bool:
    """True when ``folder`` is the test's directory, one of its ancestors, or a directory below it."""
    test_dir = PurePosixPath(test).parent
    return folder in PurePosixPath(test).parents or test_dir in folder.parents


def _tree_distance(folder: PurePosixPath, test: str) -> Optional[int]:
    """Directory levels between ``folder`` and the test's directory; None when off the test's tree."""
    if not _on_test_tree(folder, test):
        return None
    return abs(len(folder.parts) - len(PurePosixPath(test).parent.parts))


def _chunk_distance(chunk: Sequence[CapturedPath], folder: PurePosixPath) -> Optional[int]:
    """Smallest tree distance from ``folder`` to a test in ``chunk``; None when no test is on its tree."""
    distances = [_tree_distance(folder, member.path) for member in chunk if _is_test_file(member.path)]
    return min((distance for distance in distances if distance is not None), default=None)


def _nearest_owner(chunks: List[List[CapturedPath]], folder: PurePosixPath) -> Optional[List[CapturedPath]]:
    """The chunk whose test sits nearest ``folder`` (ties go to the earlier chunk), or None."""
    ranked = [(_chunk_distance(chunk, folder), n) for n, chunk in enumerate(chunks)]
    candidates = [(distance, n) for distance, n in ranked if distance is not None]
    return chunks[min(candidates)[1]] if candidates else None


def _attach_test_support(chunks: List[List[CapturedPath]], captures: Sequence[CapturedPath]) -> None:
    """Append each unpaired test-support file to the chunk with the nearest test above, beside or below it."""
    paired = {capture.path for chunk in chunks for capture in chunk}
    for capture in captures:
        if capture.path in paired or capture.bucket is not Bucket.TEST or _is_test_file(capture.path):
            continue
        owner = _nearest_owner(chunks, PurePosixPath(capture.path).parent)
        if owner is not None:
            owner.append(capture)


def fresh_groups(
        captures: Sequence[CapturedPath], registry_targets: Optional[RegistryTargets] = None,
) -> List[CommitGroup]:
    """Group captures with no existing block.

    The registry commits alone, then pair chunks, then one group per remaining bucket.

    Test-support files (conftest, helpers, fixtures) ride with the pair chunk holding the nearest test above,
    beside or below them (``_attach_test_support``).
    Docs/Planning consolidation and planning-document binning run later, in ``plan_commits``.
    """
    registry = [c for c in captures if is_registry_path(c.path)]
    unregistered = [c for c in captures if not is_registry_path(c.path)]
    chunks = _pair_chunks(unregistered, registry_targets)
    _attach_test_support(chunks, unregistered)
    paired = {capture.path for chunk in chunks for capture in chunk}
    by_bucket: Dict[Bucket, List[CapturedPath]] = {}
    for capture in captures:
        if capture.path not in paired and not is_registry_path(capture.path):
            by_bucket.setdefault(capture.bucket, []).append(capture)
    groups = [_group(registry)] if registry else []
    groups += [_group(chunk) for chunk in chunks]
    return groups + [_group(by_bucket[bucket]) for bucket in BUCKET_ORDER if bucket in by_bucket]


def is_glob(entry: str) -> bool:
    """True when a file-list entry is a glob pattern (artifact commits only)."""
    return not _GLOB_CHARS.isdisjoint(entry)


def expand_entry(entry: str, captured: Set[str]) -> Set[str]:
    """Captured paths a file-list entry stands for (glob matches, or the literal path itself)."""
    if is_glob(entry):
        return {path for path in captured if fnmatchcase(path, entry)}
    return {entry} & captured


def _claim_existing(
        existing: BranchCommitDocument, captured: Set[str],
) -> Tuple[List[List[str]], List[str], Set[str]]:
    """Keep each existing block's still-captured entries; first claim wins.

    Return (paths, messages, claimed).
    """
    claimed: Set[str] = set()
    kept_paths: List[List[str]] = []
    messages: List[str] = []
    for key in sorted(existing.commits):
        commit = existing.commits[key]
        keep: List[str] = []
        for entry in commit.files:
            matched = expand_entry(entry, captured) - claimed
            if matched:
                keep.append(entry)
                claimed |= matched
        if keep:
            kept_paths.append(keep)
            messages.append(commit.message)
    return kept_paths, messages, claimed


def _attach(kept_paths: List[List[str]], anchors: Iterable[str], extra: Sequence[str]) -> bool:
    """Append ``extra`` to the first kept group holding any anchor path; return True when attached."""
    anchor_set = set(anchors)
    for paths in kept_paths:
        if anchor_set & set(paths):
            paths.extend(path for path in extra if path not in paths)
            return True
    return False


def _partners(capture: CapturedPath, pairs: Dict[str, List[str]]) -> List[str]:
    """Pair partners of a runtime or test capture."""
    if capture.path in pairs:
        return pairs[capture.path]
    return [runtime for runtime, tests in pairs.items() if capture.path in tests]


def carry_forward(
        existing: BranchCommitDocument, captures: Sequence[CapturedPath],
        registry_targets: Optional[RegistryTargets] = None,
) -> Tuple[List[CommitGroup], List[CapturedPath]]:
    """Merge Protocol steps 2-4: keep existing groupings; attach rename sides and pair partners.

    Returns (preserved groups, captures still needing a fresh group).
    """
    kept_paths, messages, claimed = _claim_existing(existing, captured_set(captures))
    pairs = capture_pairs(captures, registry_targets)
    remaining: List[CapturedPath] = []
    for capture in captures:
        unclaimed = [path for path in capture.paths if path not in claimed]
        if len(unclaimed) < len(capture.paths):
            _attach(kept_paths, capture.paths, unclaimed)
        elif not _attach(kept_paths, _partners(capture, pairs), capture.paths):
            remaining.append(capture)
            continue
        claimed |= set(capture.paths)
    groups = [CommitGroup(tuple(paths), message) for paths, message in zip(kept_paths, messages)]
    return groups, remaining


def _rank(group: CommitGroup) -> int:
    """Landing rank: a registry-only group first, then ``BUCKET_ORDER``."""
    if all(is_registry_path(path) for path in group.paths):
        return -1
    return BUCKET_ORDER.index(commit_bucket(group.paths))


def _registry_deferred(captures: Iterable[CapturedPath]) -> bool:
    """True when a test file is deleted or renamed, so the registry must land after it."""
    return any(
        c.status in ("D", "R") and path_bucket(c.old_path or c.path) is Bucket.TEST
        and not is_registry_path(c.old_path or c.path)
        for c in captures
    )


def _has_test_path(group: CommitGroup) -> bool:
    """True when the group stages a non-registry test path."""
    return any(path_bucket(path) is Bucket.TEST and not is_registry_path(path) for path in group.paths)


def order_groups(groups: Sequence[CommitGroup], captures: Sequence[CapturedPath]) -> List[CommitGroup]:
    """Sort by landing rank (stable); defer a registry-only group past the last test group when required."""
    ordered = sorted(groups, key=_rank)
    if not ordered or _rank(ordered[0]) != -1 or not _registry_deferred(captures):
        return ordered
    registry, rest = ordered[0], ordered[1:]
    last_test = max((idx for idx, group in enumerate(rest) if _has_test_path(group)), default=-1)
    return rest[:last_test + 1] + [registry] + rest[last_test + 1:]


def _split_line(pairs: Mapping[str, Sequence[str]]) -> str:
    """Render the ``Split:`` rationale from how many (module, intent) commits the pairs need."""
    commits = len({_chunk_key(source, tests) for source, tests in pairs.items()})
    if commits <= 1:
        return f"none - {len(pairs)} pairs, one commit"
    reasons = "; ".join(split_triggers(pairs))
    return f"{reasons} - {len(pairs)} pairs in {commits} commits, one per module and intent"


def plan_commits(
        captures: Sequence[CapturedPath], existing: Optional[BranchCommitDocument] = None,
        registry_targets: Optional[RegistryTargets] = None,
) -> Tuple[List[CommitGroup], str]:
    """Plan ordered commit groups for the capture, carrying forward ``existing`` groupings.

    Return (groups, split).

    ``registry_targets`` (test file -> ``test_target_paths``) takes precedence over name matching for pairing.
    Preserved and fresh groups then pass through ``consolidate_docs`` (one ``DOCS`` and one ``PLANNING``
    group) and ``fold_planning`` (planning documents never commit alone).
    """
    preserved, remaining = (
        carry_forward(existing, captures, registry_targets) if existing else ([], list(captures))
    )
    renames = {capture.old_path: capture.path for capture in captures if capture.old_path}
    groups = consolidate_docs(preserved + fresh_groups(remaining, registry_targets), renames)
    groups = order_groups(fold_planning(groups, renames), captures)
    return groups, _split_line(capture_pairs(captures, registry_targets))


_DOC_TAIL: Tuple[Bucket, ...] = (Bucket.DOCS, Bucket.PLANNING)
Renames = Mapping[str, str]


def _unit_bucket(path: str, renames: Renames) -> Bucket:
    """Bucket of the capture a path belongs to: a rename's old side takes its new path's bucket."""
    return path_bucket(renames.get(path, path))


def _is_doc_tail(group: CommitGroup, renames: Renames) -> bool:
    """True when every path in the group buckets as ``DOCS`` or ``PLANNING``."""
    return all(_unit_bucket(path, renames) in _DOC_TAIL for path in group.paths)


def _sources(
        groups: Sequence[CommitGroup], bucket: Bucket, renames: Renames,
) -> List[Tuple[int, CommitGroup, Tuple[str, ...]]]:
    """(index, group, paths in ``bucket``) for each doc-only group holding a ``bucket`` path."""
    parts = [
        (n, group, tuple(path for path in group.paths if _unit_bucket(path, renames) is bucket))
        for n, group in enumerate(groups) if _is_doc_tail(group, renames)
    ]
    return [part for part in parts if part[2]]


def _merged(sources: Sequence[Tuple[int, CommitGroup, Tuple[str, ...]]]) -> CommitGroup:
    """One group from its sources; the message survives only when one source contributes all its paths."""
    paths = tuple(dict.fromkeys(path for _, _, part in sources for path in part))
    whole = len(sources) == 1 and sources[0][2] == sources[0][1].paths
    return CommitGroup(paths, sources[0][1].message if whole else "")


def consolidate_docs(groups: Sequence[CommitGroup], renames: Renames) -> List[CommitGroup]:
    """Merge every doc-only group into one ``DOCS`` and one ``PLANNING`` group; mixed groups stay as they are.

    A doc-only group (every path ``DOCS`` or ``PLANNING``) splits by path bucket; rename sides follow the
    new path. Each merged group takes the place of its first source; paths keep first-seen order.
    """
    slots: Dict[int, List[CommitGroup]] = {}
    for bucket in _DOC_TAIL:
        sources = _sources(groups, bucket, renames)
        if sources:
            slots.setdefault(sources[0][0], []).append(_merged(sources))
    out: List[CommitGroup] = []
    for n, group in enumerate(groups):
        out.extend(slots.get(n, []) if _is_doc_tail(group, renames) else [group])
    return out


def _planning_only(group: CommitGroup, renames: Renames) -> bool:
    """True when every path is a planning document (``is_planning_path``), by new path for a rename."""
    return all(is_planning_path(renames.get(path, path)) for path in group.paths)


def _fold_target(groups: Sequence[CommitGroup], renames: Renames) -> Optional[int]:
    """Index of the ``DOCS`` group, else of the first artifact group, else None."""
    docs = (n for n, g in enumerate(groups) if all(_unit_bucket(p, renames) is Bucket.DOCS for p in g.paths))
    artifacts = (n for n, group in enumerate(groups) if _artifact_entries(group.paths))
    return next(docs, next(artifacts, None))


def fold_planning(groups: Sequence[CommitGroup], renames: Renames) -> List[CommitGroup]:
    """Fold a group of planning documents only into the ``DOCS`` group, else the first artifact group.

    With neither present the group stays. The receiving group's message clears so it is rewritten.
    """
    plan = next((n for n, group in enumerate(groups) if _planning_only(group, renames)), None)
    target = None if plan is None else _fold_target(groups, renames)
    if plan is None or target is None:
        return list(groups)
    folded = CommitGroup(groups[target].paths + groups[plan].paths)
    return [folded if n == target else group for n, group in enumerate(groups) if n != plan]


def _artifact_entries(entries: Sequence[str]) -> bool:
    """True when the non-planning entries (paths or globs) are all artifact entries."""
    rest = [entry for entry in entries if not is_planning_path(entry)]
    return bool(rest) and commit_bucket(rest) is Bucket.ARTIFACT


def _artifact_block(commit: CommitEntry) -> bool:
    """True for the artifact block.

    That is an ``ARTIFACT`` bucket, or artifact entries binned with planning documents.
    """
    return Bucket(commit.bucket) is Bucket.ARTIFACT or _artifact_entries(commit.files)


def coverage_problems(document: BranchCommitDocument, captures: Sequence[CapturedPath]) -> List[str]:
    """Return problems where the document's file lists and the capture disagree.

    Glob entries are legal only in the artifact block (``_artifact_block``).
    """
    captured = captured_set(captures)
    owners: Dict[str, int] = {}
    problems: List[str] = []
    for key in sorted(document.commits):
        commit = document.commits[key]
        for entry in commit.files:
            matched = expand_entry(entry, captured)
            if is_glob(entry) and not _artifact_block(commit):
                problems.append(f"commit {key}: glob {entry!r} outside the artifact commit")
            if not matched:
                problems.append(f"commit {key}: {entry!r} matches nothing in the merge-base capture")
            for path in sorted(matched):
                if path in owners and owners[path] != key:
                    problems.append(f"path {path!r} in commit {owners[path]} and commit {key}")
                owners.setdefault(path, key)
    problems.extend(f"{path!r} is in no commit" for path in sorted(captured - set(owners)))
    return problems
