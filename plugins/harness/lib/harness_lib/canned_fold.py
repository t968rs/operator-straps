"""Fold canned-set paths that appeared or vanished between ``capture`` and ``build`` into the commit blocks.

A canned set's files carry a fixed message (``harness_lib.canned_messages``), so a regenerated one (a TODO
catalog, a review artifact, a project set's report) changing after capture has no bearing on the drafted
messages. ``fold_canned`` brings the skeleton's blocks in line with a fresh capture for those files only;
every other path is left to the coverage check, which still fails on it.
"""
from __future__ import annotations

from typing import AbstractSet, Callable, Dict, List, Optional, Sequence, Tuple

from harness_lib.commit_grouping import expand_entry, is_glob

CommitDict = Dict[int, Tuple[List[str], str]]
Canned = Callable[[Sequence[str]], Optional[str]]


def fold_canned(commits: CommitDict, captured: AbstractSet[str], canned: Canned, pending: bool) -> CommitDict:
    """A copy of ``commits`` with vanished canned paths dropped and appeared ones placed; input untouched.

    Vanished: a literal entry not in ``captured`` that ``canned`` covers is dropped, and a block left empty
    goes. Appeared: each captured path no entry stands for and ``canned`` covers, in sorted order, joins the
    first block when ``pending``, else the first block whose message equals the canned message of its files
    plus the path, else a new block after the last with the path's canned message.
    """
    paths = set(captured)
    folded = _drop_vanished(commits, paths, canned)
    claimed = {path for files, _ in folded.values() for entry in files for path in expand_entry(entry, paths)}
    for path in sorted(paths - claimed):
        if canned([path]) is not None:
            _place(folded, path, canned, pending)
    return folded


def _drop_vanished(commits: CommitDict, captured: AbstractSet[str], canned: Canned) -> CommitDict:
    """Copy of ``commits`` without vanished canned entries or the blocks they leave empty."""
    out: CommitDict = {}
    for key in sorted(commits):
        files, message = commits[key]
        kept = [entry for entry in files if not _vanished_canned(entry, captured, canned)]
        if kept or not files:
            out[key] = (kept, message)
    return out


def _vanished_canned(entry: str, captured: AbstractSet[str], canned: Canned) -> bool:
    """True for a literal entry missing from ``captured`` whose path a canned set covers."""
    return not is_glob(entry) and entry not in captured and canned([entry]) is not None


def _place(folded: CommitDict, path: str, canned: Canned, pending: bool) -> None:
    """Add appeared canned ``path`` to its block in ``folded``, creating one when none fits."""
    if pending and folded:
        key = min(folded)
    else:
        key = next((k for k in sorted(folded) if folded[k][1] == canned([*folded[k][0], path])), None)
    if key is None:
        folded[max(folded, default=0) + 1] = ([path], canned([path]) or "")
        return
    files, message = folded[key]
    folded[key] = ([*files, path], message)
