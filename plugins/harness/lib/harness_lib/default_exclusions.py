"""The default exclusions file (``.claude/review_exclusions.json``) seeded into a consuming project.

The harness writes review JSONs, PR summaries, run scratch, commit message drafts, bubble memos, runtime
state and the pr-review-watch rows under the project; the clean-tree check and the review capture treat
them as machine-generated. A project whose ``exclusions`` value is the default path (in any equivalent
spelling) gets the file written on first use, with patterns derived from its configured artifact folders
and rows files. Any other path, or null, is never touched.
"""
from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import List, Optional, Sequence

from harness_lib.config import HarnessConfig

DEFAULT_EXCLUSIONS = ".claude/review_exclusions.json"

_COMMENT = ("Machine-generated paths the pr-review clean-tree check and review capture skip "
            "(fnmatch patterns over repo-relative POSIX paths). Seeded by the harness plugin; edit freely.")


def _normalized(rel: str) -> str:
    """``rel`` as a normalized repo-relative POSIX path (backslashes and ``./`` segments folded)."""
    return posixpath.normpath(rel.replace("\\", "/"))


def _entries(cfg: HarnessConfig) -> List[dict]:
    rows = [
        (f"{_normalized(cfg.artifacts.reviews)}/*", "pr-review output"),
        (f"{_normalized(cfg.artifacts.summaries)}/*", "PR summaries"),
        (f"{_normalized(cfg.artifacts.scratch)}/*", "pr-review run scratch"),
        (f"{_normalized(cfg.artifacts.commit_messages)}/*", "commit message drafts"),
        (f"{_normalized(cfg.state_dir)}/*", "harness runtime state"),
        (_normalized(cfg.matrix_path), "pr-review-watch invocation matrix rows"),
        (_normalized(cfg.agent_usage_path), "pr-review agent usage rows"),
        ("*_Bubbles.md", "bubble memos (point-in-time snapshots)"),
        (DEFAULT_EXCLUSIONS, "this file, seeded by the harness"),
    ]
    seen: dict = {}
    for pattern, reason in rows:
        seen.setdefault(pattern, reason)
    return [{"pattern": p, "reason": r} for p, r in seen.items()]


def default_patterns(cfg: HarnessConfig) -> List[str]:
    """The fnmatch patterns a seeded file holds for ``cfg``'s artifact folders."""
    return [e["pattern"] for e in _entries(cfg)]


def harness_patterns(cfg: HarnessConfig) -> List[str]:
    """The fnmatch patterns for what the harness itself writes under the project.

    ``default_patterns`` without the row for the seeded file, which a project on another path never has.
    """
    return [p for p in default_patterns(cfg) if p != DEFAULT_EXCLUSIONS]


def with_harness_patterns(cfg: HarnessConfig, patterns: Sequence[str]) -> List[str]:
    """``patterns`` followed by each harness pattern they lack.

    A file seeded by an earlier version, or a project's own list, never gains the rows added since. The
    harness folders stay exempt in memory, and the file is left as the project wrote it.
    """
    merged = list(patterns)
    return merged + [p for p in harness_patterns(cfg) if p not in merged]


def ensure_default_exclusions(cfg: HarnessConfig) -> Optional[Path]:
    """Write the default exclusions file when ``cfg`` uses the default path and the file is absent.

    Returns the written path, or None when nothing was written: the project disabled exclusions, names its
    own file, already has the default file, or the folder is not writable. The exclusive create never
    overwrites a file another process wrote first.
    """
    if not cfg.exclusions or _normalized(cfg.exclusions) != DEFAULT_EXCLUSIONS:
        return None
    target = cfg.path(DEFAULT_EXCLUSIONS)
    if target.exists():
        return None
    body = {"_comment": _COMMENT, "exclusions": _entries(cfg)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(body, indent=2) + "\n")
    except OSError:
        return None
    return target
