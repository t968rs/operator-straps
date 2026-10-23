"""The default exclusions file (``.claude/review_exclusions.json``) seeded into a consuming project.

The harness writes review JSONs, PR summaries, run scratch and the pr-review-watch rows under the project; the
clean-tree check and the review capture treat them as machine-generated. A project whose ``exclusions`` value
is the default path (in any equivalent spelling) gets the file written on first use, with patterns derived
from its configured artifact folders and rows files. Any other path, or null, is never touched.
"""
from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import List, Optional

from harness_lib.config import HarnessConfig

DEFAULT_EXCLUSIONS = ".claude/review_exclusions.json"

_COMMENT = ("Machine-generated paths the pr-review clean-tree check and review capture skip "
            "(fnmatch patterns over repo-relative POSIX paths). Seeded by the harness plugin; edit freely.")


def _normalized(rel: str) -> str:
    """``rel`` as a normalized repo-relative POSIX path (backslashes and ``./`` segments folded)."""
    return posixpath.normpath(rel.replace("\\", "/"))


def _entries(cfg: HarnessConfig) -> List[dict]:
    rows = [
        (f"{cfg.artifacts.reviews.rstrip('/')}/*", "pr-review output"),
        (f"{cfg.artifacts.summaries.rstrip('/')}/*", "PR summaries"),
        (f"{cfg.artifacts.scratch.rstrip('/')}/*", "pr-review run scratch"),
        (_normalized(cfg.matrix_path), "pr-review-watch invocation matrix rows"),
        (_normalized(cfg.agent_usage_path), "pr-review agent usage rows"),
        (DEFAULT_EXCLUSIONS, "this file, seeded by the harness"),
    ]
    seen: dict = {}
    for pattern, reason in rows:
        seen.setdefault(pattern, reason)
    return [{"pattern": p, "reason": r} for p, r in seen.items()]


def default_patterns(cfg: HarnessConfig) -> List[str]:
    """The fnmatch patterns a seeded file holds for ``cfg``'s artifact folders."""
    return [e["pattern"] for e in _entries(cfg)]


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
