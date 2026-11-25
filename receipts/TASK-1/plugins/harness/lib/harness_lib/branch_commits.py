"""Branch commit-breakdown types: ``Bucket``, ``BranchCommitDocument``, and path-to-bucket rules.

Shared by the ``branch-commit-msg`` driver (``scripts/branch_commit_msg.py``) and the TXT parser CLI
(``scripts/txt_to_commit_dict.py``). The path rules come from the active project configuration
(``commit_buckets``, first match wins; registry files from ``tests``); this module owns how they apply
and the landing order (``BUCKET_ORDER``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple, Union

from harness_lib.config import active


class Bucket(StrEnum):
    """Commit-block bucket labels allowed by the branch-commit-msg TXT format."""

    RUNTIME_TEST = "Runtime+Test"
    RUNTIME = "Runtime"
    TEST = "Test"
    CICD = "Cicd"
    AGENT = "Agent"
    OTHER = "Other"
    DOCS = "Docs"
    PLANNING = "Planning"
    ARTIFACT = "Artifact"

    @classmethod
    def _missing_(cls, value: object) -> Optional[Bucket]:
        """Match a label case-insensitively after stripping (legacy lowercase labels)."""
        if not isinstance(value, str):
            return None
        key = value.strip().lower()
        return next((member for member in cls if member.value.lower() == key), None)


BUCKET_ORDER: Tuple[Bucket, ...] = (
    Bucket.RUNTIME_TEST, Bucket.RUNTIME, Bucket.TEST, Bucket.CICD,
    Bucket.AGENT, Bucket.OTHER, Bucket.DOCS, Bucket.PLANNING, Bucket.ARTIFACT,
)

def _matches(path: str, prefixes: Tuple[str, ...], names: Tuple[str, ...], suffixes: Tuple[str, ...]) -> bool:
    """Return True when ``path`` starts with a prefix, has a listed name, or ends with a suffix."""
    name = PurePosixPath(path).name
    return path.startswith(prefixes) or name in names or name.endswith(suffixes)


def _rule_bucket(path: str) -> Optional[Bucket]:
    """Bucket of the first configured ``commit_buckets`` rule matching ``path``, or None."""
    for rule in active().commit_buckets:
        if _matches(path, rule.prefixes, rule.names, rule.suffixes):
            return Bucket(rule.bucket)
    return None


def path_bucket(path: str) -> Bucket:
    """Return the bucket for one repo-relative POSIX path (never ``RUNTIME_TEST``).

    Markdown under ``.claude/`` other than ``CLAUDE.md`` (skills, agent definitions) is prose and
    buckets as ``DOCS``; a registry file (``is_registry_path``) buckets as ``TEST``. Everything else
    takes the first matching configured ``commit_buckets`` rule, then top-level ``.md``/``.txt`` files
    bucket as ``DOCS`` and the rest as ``OTHER``.
    """
    name = PurePosixPath(path).name
    if path.startswith(".claude/") and name.endswith(".md") and name != "CLAUDE.md":
        return Bucket.DOCS
    if is_registry_path(path):
        return Bucket.TEST
    bucket = _rule_bucket(path)
    if bucket is not None:
        return bucket
    if "/" not in path and path.endswith((".md", ".txt")):
        return Bucket.DOCS
    return Bucket.OTHER


def is_planning_path(path: str) -> bool:
    """Return True for an agent planning document: a path under a configured ``artifacts.planning_prefixes``.

    A ``PLANNING`` group holding only planning documents never commits alone: it folds into the
    ``DOCS`` commit, else the artifact commit (``commit_grouping.plan_commits``).
    """
    return path.startswith(active().artifacts.planning_prefixes)


def is_registry_path(path: str) -> bool:
    """Return True for a test registry file, which lands in its own early commit.

    A registry is the configured ``tests.registry`` path or any file named in ``tests.registry_names``;
    with neither configured, nothing is a registry file.
    """
    tests = active().tests
    return path == tests.registry or PurePosixPath(path).name in tests.registry_names


_SOURCE_BUCKETS = frozenset({Bucket.RUNTIME, Bucket.AGENT, Bucket.OTHER})


def is_source_path(path: str) -> bool:
    """Return True for a Python source file a test can pair with (runtime, agent or other ``.py``)."""
    return path.endswith(".py") and path_bucket(path) in _SOURCE_BUCKETS


def commit_bucket(paths: Iterable[str]) -> Bucket:
    """Derive one commit's bucket: a test path with runtime or Python source gives ``RUNTIME_TEST``.

    Any other mix takes the highest-ranked bucket in ``BUCKET_ORDER``.
    """
    paths = list(paths)
    buckets = {path_bucket(path) for path in paths}
    if not buckets:
        raise ValueError("commit_bucket requires at least one path")
    if Bucket.TEST in buckets and (Bucket.RUNTIME in buckets or any(map(is_source_path, paths))):
        return Bucket.RUNTIME_TEST
    return min(buckets, key=BUCKET_ORDER.index)


@dataclass
class CommitEntry:
    """One commit block: its file list, its message, and the message parts parsed from the subject line.

    ``bucket`` accepts a label string at construction; ``BranchCommitDocument.validate`` coerces it to
    ``Bucket`` (reporting unknown labels) and overwrites ``file_count`` with ``len(files)``.
    ``message`` is the verbatim commit message without the ``Branch:`` footer; ``body``, ``bullets``
    and ``branch`` are populated only when parsed from a TXT block.
    """

    index:          int
    bucket:         Union[Bucket, str]
    files:          List[str] = field(default_factory=list)
    header:         Optional[str] = None
    message:        str = ""
    commit_type:    Optional[str] = None
    scope:          Optional[str] = None
    subject:        Optional[str] = None
    tag:            Optional[str] = None
    body:           str = ""
    bullets:        List[Dict[str, str]] = field(default_factory=list)
    branch:         Optional[str] = None
    file_count:     int = 0


@dataclass
class BranchCommitDocument:
    """Branch commit breakdown: header fields plus commit entries keyed by commit number.

    ``one_path_per_commit`` records the commit strategy. ``True`` (the rebuild strategy) requires
    every path to appear in exactly one commit entry; ``False`` permits shared paths.
    ``pending`` marks a ``c-msg`` document: the change pending against HEAD (``merge_base`` is HEAD) as at
    most one commit, saved apart from the branch ledger.
    Construction runs ``validate(validate_null=False)``, so a partially populated document is legal.
    """

    branch:         Optional[str] = None
    merge_base:     Optional[str] = None
    notes:          List[str] = field(default_factory=list)
    commits:        Dict[int, CommitEntry] = field(default_factory=dict)
    one_path_per_commit: bool = True
    pending:        bool = False

    def __post_init__(self) -> None:
        self.validate(validate_null=False)

    def validate(
            self,
            validate_null: bool = True,
            one_path_per_commit: Optional[bool] = None,
    ) -> BranchCommitDocument:
        """Normalize commit entries in place, then raise ``ValueError`` listing every problem found.

        Every call coerces each ``bucket`` to ``Bucket`` and overwrites ``file_count`` with
        ``len(files)``. ``validate_null`` checks that ``branch``, ``merge_base`` and each commit
        ``header`` are set. ``one_path_per_commit`` overrides the instance strategy when not None.
        A ``pending`` document with more than one commit is always a problem.
        """
        unique = self.one_path_per_commit if one_path_per_commit is None else one_path_per_commit
        problems = _normalize_commits(self.commits)
        if self.pending and len(self.commits) > 1:
            problems.append(
                f"pending document has {len(self.commits)} commits; the pending change is one commit"
            )
        if validate_null:
            problems.extend(_null_problems(self))
        if unique:
            problems.extend(_shared_path_problems(self.commits))
        if problems:
            raise ValueError("invalid BranchCommitDocument:\n  " + "\n  ".join(problems))
        return self


def _normalize_commits(commits: Dict[int, CommitEntry]) -> List[str]:
    """Coerce buckets and recount files in place; return bucket problems."""
    problems: List[str] = []
    for key, commit in commits.items():
        commit.file_count = len(commit.files)
        try:
            commit.bucket = Bucket(commit.bucket)
        except ValueError:
            problems.append(f"commit {key}: invalid bucket {commit.bucket!r}")
    return problems


def _null_problems(document: BranchCommitDocument) -> List[str]:
    """Return a problem per unset required document field or commit header."""
    problems = [f"{name} is None" for name in ("branch", "merge_base") if getattr(document, name) is None]
    problems.extend(
        f"commit {key}: header is None" for key, commit in document.commits.items() if commit.header is None
    )
    return problems


def _shared_path_problems(commits: Dict[int, CommitEntry]) -> List[str]:
    """Return a problem per path listed in more than one commit entry."""
    owners: Dict[str, int] = {}
    problems: List[str] = []
    for key in sorted(commits):
        for path in commits[key].files:
            if path in owners:
                problems.append(f"path {path!r} in commit {owners[path]} and commit {key}")
            else:
                owners[path] = key
    return problems
