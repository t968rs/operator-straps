"""Canned commit messages for pre-determined change sets (the commit-message skills' shortcut).

``LOOKUP`` maps a set of file patterns to the commit message for a change made of those files alone. A change
set takes an entry's message when every changed file matches at least one of the entry's patterns, so a change
touching only some of the files still qualifies and one touching any other file does not. A pattern holding a
``/`` is matched against the whole repo-relative path; any other pattern, against the file name.

The entries cover generated files whose paths and names are plugin defaults (``config/defaults.json``); a
project that moves them away from the defaults gets no canned message and drafts one as usual.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import FrozenSet, Iterable, Mapping, Optional

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
        "pr_review_agent_usage.jsonl",
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


def get_canned_message(changed_files: Iterable[str]) -> Optional[str]:
    """The message of the first ``LOOKUP`` entry covering every changed file, or None.

    No changed files, or a file outside every entry, gives None.
    """
    paths = [_norm_path(path) for path in changed_files]
    if not paths:
        return None
    return next((message for patterns, message in LOOKUP.items() if _covers(patterns, paths)), None)


def has_canned_message(changed_files: Iterable[str]) -> bool:
    """True when ``get_canned_message`` finds a message for the change set."""
    return get_canned_message(changed_files) is not None
