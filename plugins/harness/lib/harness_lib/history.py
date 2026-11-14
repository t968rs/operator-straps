"""The project folders whose files are history records rather than live code or docs.

Plans, review records, drafted commit messages, PR summaries, run scratch, planning documents and TODO
snapshots quote symbols and ids as they stood when written. Scans that look for live uses of a symbol or an
id (plan sweeps, the TODO reference scans) skip these folders.
"""
from __future__ import annotations

from typing import List, Tuple

from harness_lib.config import HarnessConfig


def posix(rel: str) -> str:
    """``rel`` with forward slashes and no leading ``./``: the one normalizer for repo-relative paths."""
    out = rel.replace("\\", "/")
    return out[2:] if out.startswith("./") else out


def history_paths(cfg: HarnessConfig) -> Tuple[str, ...]:
    """Repo-relative POSIX folders, without a trailing ``/``, whose files are history: plans, reviews,
    commit messages, summaries, scratch, each planning prefix and the TODO snapshots."""
    art = cfg.artifacts
    out: List[str] = []
    for rel in (art.plans, art.reviews, art.commit_messages, art.summaries, art.scratch,
                *art.planning_prefixes, cfg.todo.snapshots.dir):
        path = posix(rel).rstrip("/") if rel else ""
        if path and path not in out:
            out.append(path)
    return tuple(out)
