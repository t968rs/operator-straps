"""PR title check shared by merge-commit-msg and pr-sum, and the ``gh pr edit`` call of ``--auto-title``.

A title heads a commit subject when it is one non-empty line of ASCII that is not just the branch name with
its hyphens or underscores turned into spaces (the default ``gh`` derives from a branch; it loses version
dots). The conventional rule adds the ``Word(scope): summary`` shape a squash commit needs: a word of
letters, an optional scope, a colon and a non-empty summary (the type is not checked against a type list).
``change_pr_title`` always applies the conventional rule, so a title it writes heads either subject.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional

from harness_lib.commit_txt import subject_parts

_SLUG_SPLIT = re.compile(r"[-_/\s]+")
CONVENTIONAL = ("is not a Word(scope): summary subject (Conventional-Commit shape: a word, an optional "
                "scope, a colon and a non-empty summary), which a squash commit needs")


class TitleError(RuntimeError):
    """A new PR title was refused, or ``gh pr edit`` could not set it."""


def _tokens(text: str) -> List[str]:
    return [t for t in _SLUG_SPLIT.split(text.casefold()) if t]


def title_defect(title: str, head: str, conventional: bool = False) -> Optional[str]:
    """Why ``title`` cannot head a commit subject, as a predicate phrase; None when it can."""
    if not title.strip():
        return "is empty"
    if "\n" in title or "\r" in title:
        return "spans more than one line"
    if not title.isascii():
        found = "".join(sorted({c for c in title if not c.isascii()}))
        return f"holds non-ASCII characters {found!r}"
    if _SLUG_SPLIT.search(head) and _tokens(title) == _tokens(head):
        return "reads as the branch name"
    if conventional:
        kind, _, summary = subject_parts(title)
        if kind is None or not summary:
            return CONVENTIONAL
    return None


def title_problem(pr: int, title: str, head: str, conventional: bool = False) -> Optional[str]:
    """``title_defect`` as a problem line naming PR ``pr`` and both ways out; None when there is none."""
    defect = title_defect(title, head, conventional)
    if defect is None:
        return None
    fix = f"retitle it with gh pr edit {pr} --title, or rerun with --auto-title"
    return f"PR #{pr} title {title!r} {defect}; {fix}"


def change_pr_title(pr_no: int, new_title: str, repo: Path, head: str) -> None:
    """Set PR ``pr_no``'s title to ``new_title`` with ``gh pr edit``, run in ``repo``.

    Raises ``TitleError`` before any call when ``new_title`` fails the conventional rule (``head`` is the
    PR's branch name, for the branch-name rule), and when ``gh`` is missing or fails.
    """
    defect = title_defect(new_title, head, conventional=True)
    if defect is not None:
        raise TitleError(f"new title {new_title!r} {defect}")
    try:
        done = subprocess.run(["gh", "pr", "edit", str(pr_no), "--title", new_title], cwd=repo,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise TitleError("gh is not installed or not on PATH") from exc
    if done.returncode != 0:
        detail = done.stderr.strip() or done.stdout.strip()
        raise TitleError(f"gh pr edit {pr_no} failed: {detail}")
