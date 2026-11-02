"""Review-local: the git-side seam that lets the pr-review driver review a local commit range.

``pr_review.py capture --range BASE..HEAD`` calls ``local_metadata`` in place of ``gh pr view``: it resolves
the range with git and returns the same projected object a PR capture reads, with state ``LOCAL`` and the
run key as its number. ``LocalMeta`` diffs from the base revision itself (a PR diffs from ``origin/<base>``).
``phase4_meta`` gives ``phase4_branch_safety.py`` the branch, base and SHAs a local run's ``plan.json``
recorded, in the shape its gh read returns. Requires an activated config.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from harness_lib import review_models as rm
from harness_lib.branch_capture import CaptureError, current_branch, git, git_out
from harness_lib.pr_capture import PrMeta
from harness_lib.review_local_models import (
    LOCAL_PREFIX,
    LOCAL_STATE,
    LocalRange,
    RunKey,
    branch_label,
    is_local_key,
)

__all__ = ["LocalMeta", "local_key_for", "local_metadata", "local_check", "local_meta", "phase4_meta"]

DETACHED = "HEAD"


@dataclass(frozen=True)
class LocalMeta(PrMeta):
    """``PrMeta`` of a local range: ``number`` holds the local key and the diff starts at ``base``."""

    @property
    def base_tip(self) -> str:
        """The range's base revision, as given."""
        return self.base


def _commit(repo: Path, rev: str) -> str:
    """Full SHA of ``rev``; raise ``CaptureError`` when it names no commit."""
    done = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if done.returncode != 0:
        raise CaptureError([f"range end {rev!r} names no commit"])
    return done.stdout.strip()


def head_branch(repo: Path, head: str, head_sha: str) -> str:
    """The branch the range's head is: the checked-out branch when HEAD is the head commit, else ``head``
    when it names a local branch, else ``HEAD`` (detached)."""
    branch = current_branch(repo)
    if branch and _commit(repo, "HEAD") == head_sha:
        return branch
    if git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{head}").returncode == 0:
        return head
    return DETACHED


def _require_branch(head: str, branch: str) -> None:
    """Raise ``CaptureError`` when the range head resolved to no branch: Phase 4 checks the fix branch
    against ``headRefName``, so a detached head would pass on any detached checkout and STOP on a branch."""
    if branch == DETACHED:
        raise CaptureError([f"range end {head!r} is on no local branch: check out the branch to review and "
                            f"end the range at HEAD (or name the branch as the range end), so Phase 4 can "
                            f"check the fix branch"])


def local_key_for(key: Optional[RunKey], branch: str, head_sha: str) -> str:
    """``key`` when it is a local key; ``local-<branch label>`` when None; a PR number raises."""
    if key is None:
        return LOCAL_PREFIX + branch_label(None if branch == DETACHED else branch, head_sha)
    if not is_local_key(key):
        raise CaptureError([f"--pr {key}: a --range review takes a local-<label> key (or none, for "
                            f"local-<branch label>)"])
    return str(key)


def local_metadata(repo: Path, key: Optional[RunKey], rng: LocalRange,
                   title: Optional[str] = None) -> Tuple[Dict[str, object], str]:
    """The projected metadata object of a local range and the raw git output it was read from."""
    head_sha, base_sha = _commit(repo, rng.head), _commit(repo, rng.base)
    merge_base = git_out(repo, "merge-base", base_sha, head_sha).strip()
    branch = head_branch(repo, rng.head, head_sha)
    _require_branch(rng.head, branch)
    run_key = local_key_for(key, branch, head_sha)
    count = git_out(repo, "rev-list", "--count", f"{merge_base}..{head_sha}").strip()
    raw = "\n".join([head_sha, merge_base, branch, count]) + "\n"
    data: Dict[str, object] = {
        "number": run_key, "title": title or (branch if branch != DETACHED else rng.head),
        "headRefName": branch, "baseRefName": rng.base, "state": LOCAL_STATE, "url": None,
        "headRefOid": head_sha, "mergeCommit": None, "commits_count": int(count or 0),
        "first_sha": merge_base, "last_sha": head_sha,
    }
    return data, raw


def local_check(rng: LocalRange, raw: str) -> Dict[str, str]:
    """The ``pr_metadata_check`` block of a local capture: the git commands, their raw output, OK."""
    command = (f"git rev-parse --verify --quiet {rng.head}^{{commit}}; "
               f"git rev-parse --verify --quiet {rng.base}^{{commit}}; "
               "git merge-base <base sha> <head sha>; git branch --show-current; "
               f"git show-ref --verify --quiet refs/heads/{rng.head}; "
               "git rev-list --count <merge base>..<head sha>")
    return {"command": command, "stdout": raw, "result": f"OK (state={LOCAL_STATE}; no PR)"}


def local_meta(data: Dict[str, object]) -> LocalMeta:
    """``LocalMeta`` from ``local_metadata``'s object."""
    return LocalMeta(data["number"], str(data["title"]), str(data["baseRefName"]),  # type: ignore[arg-type]
                     str(data["headRefName"]), str(data["headRefOid"]), None)


def phase4_meta(key: str, repo: Optional[Path] = None) -> Dict[str, str]:
    """The fields Phase 4 compares against, from the local run's ``plan.json``; raise ``RuntimeError`` when
    the run or a field is missing."""
    try:
        plan = json.loads((rm.run_dir(key, repo) / "plan.json").read_text(encoding="utf-8"))
        meta = plan["meta"]
        return {"headRefName": str(meta["branch"]), "baseRefName": str(meta["base_branch"]),
                "state": str(plan["state"]), "first_sha": str(plan["first_sha"]),
                "last_sha": str(plan["last_sha"]), "base_source": "plan.json meta.base_branch"}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"no readable plan.json for {key} ({exc}); rerun capture --range") from exc
