"""Canned commit messages for pre-determined change sets (the commit-message skills' shortcut).

``LOOKUP`` maps a set of file patterns to the commit message for a change made of those files alone. A change
set takes an entry's message when every changed file matches at least one of the entry's patterns, so a change
touching only some of the files still qualifies and one touching any other file does not. A pattern holding a
``/`` is matched against the whole repo-relative path; any other pattern, against the file name.

The entries use the plugin's default file names (``config/defaults.json``: the ``todo`` names, ``matrix_path``
and ``agent_usage_path``) and, for review artifacts, the default folders (``artifacts.reviews``,
``artifacts.summaries``). ``LOOKUP`` reads no config: it is a fixed, read-only table, so a built-in message
never depends on which project is active, and a project that renames those files, or moves the review
artifacts away from the defaults, gets no built-in message and drafts one as usual (an accepted limitation, not
a drift bug).

A project adds its own sets with the ``canned_messages`` config key. ``get_canned_message`` takes them as
``extra`` and tries them, in order, before ``LOOKUP``, so a project set can replace a built-in message for the
same files; ``project_canned_message`` reads them from the active configuration and is what the commit-message
drivers call. The config load refuses a set whose message fails the commit-message checks ``build`` runs. A
project set also drives build-time folding: a file it covers that appears or vanishes between capture and
build is folded into the blocks (``harness_lib.canned_fold``) without the coverage check, so a set should
cover generated files only. Patterns use ``fnmatch``, whose ``*`` crosses ``/``: ``docs/*.md`` also matches
nested files.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import FrozenSet, Iterable, Mapping, Optional, Sequence

from harness_lib.config import CannedSet, active

LOOKUP: Mapping[FrozenSet[str], str] = MappingProxyType({
    frozenset({
        "_IMPL_TODO.md",
        "RepoToDo.json",
        "ResearchImplementationCatalog.json",
        "TODO_Snapshot_*.md",
    }): "Chore(todo): refresh TODO catalog, research stubs and snapshot",
    frozenset({
        "docs/PR_REVIEWS/*.json",
        "docs/PR_SUMMARIES/*.md",
        "agent_usage.jsonl",
        "pr_review_invocation_test_matrix.jsonl",
    }): "Chore(reviews): record PR review, summary and run-log artifacts",
})


def _norm_path(path: str) -> str:
    """The path with forward slashes and no leading ``./``."""
    return str(PurePosixPath(path.replace("\\", "/")))


def _matches(path: str, pattern: str) -> bool:
    """True when ``path`` fits ``pattern``: the whole path for a pattern with a ``/``, else the file name."""
    target = path if "/" in pattern else PurePosixPath(path).name
    return fnmatchcase(target, pattern)


def _covers(patterns: FrozenSet[str], paths: Iterable[str]) -> bool:
    """True when every path matches at least one of ``patterns``."""
    return all(any(_matches(path, pattern) for pattern in patterns) for path in paths)


def get_canned_message(changed_files: Iterable[str], extra: Sequence[CannedSet] = ()) -> Optional[str]:
    """The message of the first ``extra`` set, then the first ``LOOKUP`` entry, covering every changed file.

    No changed files, or a file outside every set, gives None.
    """
    paths = [_norm_path(path) for path in changed_files]
    if not paths:
        return None
    sets = [(frozenset(s.patterns), s.message) for s in extra] + list(LOOKUP.items())
    return next((message for patterns, message in sets if _covers(patterns, paths)), None)


def project_canned_message(changed_files: Iterable[str]) -> Optional[str]:
    """``get_canned_message`` with the active project's ``canned_messages`` sets tried first."""
    return get_canned_message(changed_files, extra=active().canned_messages)


def has_canned_message(changed_files: Iterable[str], extra: Sequence[CannedSet] = ()) -> bool:
    """True when ``get_canned_message`` finds a message for the change set.

    Only the built-in ``LOOKUP`` is checked unless ``extra`` is given; pass ``active().canned_messages`` to
    match what the drivers' ``project_canned_message`` finds.
    """
    return get_canned_message(changed_files, extra) is not None
