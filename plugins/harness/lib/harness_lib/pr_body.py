"""The pr-sum summary as a marked block in its PR's description (``pr_sum.py capture --gh``).

The block sits between ``BLOCK_START`` and ``BLOCK_END``, HTML comments GitHub does not render, each on a line
of its own; a marker quoted inline in prose is plain text. A body without them gains the block at its end,
after a blank line; a body with one pair has the text between them replaced, so a rerun never adds a
second copy and text written outside the markers stays as written. A body whose markers do not pair is
refused rather than guessed at. ``publish`` reads the body with ``gh pr view`` and writes it back with
``gh pr edit --body-file -`` (stdin, so no file is written), and only when it changed.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

BLOCK_START = "<!-- pr-sum:start -->"
BLOCK_END = "<!-- pr-sum:end -->"
BODY_LIMIT = 65_536


class BodyError(RuntimeError):
    """The PR body could not be read, merged or written."""


# --------------------------------------------------------------------------------------
# Block merge
# --------------------------------------------------------------------------------------


def _block(summary: str) -> str:
    """``summary`` between the two markers, one per line."""
    return f"{BLOCK_START}\n{summary.strip()}\n{BLOCK_END}"


def _marker_lines(text: str, marker: str) -> List[int]:
    """Offsets of each line of ``text`` that is exactly ``marker`` (a trailing CR allowed).

    ``_block`` writes each marker on its own line, so a marker quoted inline in prose is not one.
    """
    return [m.start() for m in re.finditer(rf"^{re.escape(marker)}\r?$", text, re.M)]


def _span(body: str) -> Optional[Tuple[int, int]]:
    """Start and end offsets of the one marked block in ``body``; None when it has no marker lines.

    Raises ``BodyError`` when the marker lines do not form exactly one start-then-end pair.
    """
    starts, ends = _marker_lines(body, BLOCK_START), _marker_lines(body, BLOCK_END)
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise BodyError(
            f"the PR body holds {len(starts)} start and {len(ends)} end pr-sum markers, "
            "not one pair in order; "
            f"fix the body by hand so it holds one {BLOCK_START} ... {BLOCK_END} block or none"
        )
    return starts[0], ends[0] + len(BLOCK_END)


def _check_summary(summary: str) -> None:
    """Raise ``BodyError`` when ``summary`` holds a marker on a line of its own.

    Such a line would make the published block unfindable on the next publish.
    """
    if _marker_lines(summary, BLOCK_START) or _marker_lines(summary, BLOCK_END):
        raise BodyError(
            f"the summary holds a {BLOCK_START} or {BLOCK_END} line of its own; quote the marker inline "
            "(in backticks) so the published block can be found again"
        )


def merge_block(body: str, summary: str) -> Tuple[str, bool]:
    """``body`` with ``summary`` as its marked block, and whether an earlier block was replaced.

    Raises ``BodyError`` for a summary holding a marker line, for unpaired markers and for a result over
    GitHub's ``BODY_LIMIT`` characters.
    """
    _check_summary(summary)
    span = _span(body)
    if span is not None:
        merged = body[:span[0]] + _block(summary) + body[span[1]:]
    else:
        merged = f"{body.rstrip()}\n\n{_block(summary)}" if body.strip() else _block(summary)
    if len(merged) > BODY_LIMIT:
        raise BodyError(f"the PR body would be {len(merged)} characters; GitHub allows {BODY_LIMIT}")
    return merged, span is not None


# --------------------------------------------------------------------------------------
# gh calls
# --------------------------------------------------------------------------------------


def _gh(pr: int, repo: Path, args: List[str], stdin: Optional[str] = None) -> str:
    """stdout of ``gh pr <args>`` run in ``repo``; raise ``BodyError`` when gh is missing or fails."""
    try:
        done = subprocess.run(["gh", "pr", *args], cwd=repo, input=stdin, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BodyError("gh is not installed or not on PATH") from exc
    if done.returncode != 0:
        detail = done.stderr.strip() or done.stdout.strip()
        raise BodyError(f"gh pr {args[0]} {pr} failed: {detail}")
    return done.stdout


def read_body(pr: int, repo: Path) -> str:
    """PR ``pr``'s description; an empty description reads as ``""``."""
    text = _gh(pr, repo, ["view", str(pr), "--json", "body"])
    try:
        return str(json.loads(text)["body"] or "")
    except (KeyError, TypeError, ValueError) as exc:
        raise BodyError(f"gh pr view {pr} output does not parse ({exc!r})") from exc


def publish(pr: int, repo: Path, summary: str) -> str:
    """Put ``summary`` into PR ``pr``'s description as its marked block; return the receipt line.

    The body is written only when the merge changed it. Line endings do not count as a change: on Windows
    the text-mode stdin of ``gh pr edit`` turns each LF into CRLF, so the stored body reads back with CRLF.
    """
    body = read_body(pr, repo)
    merged, replaced = merge_block(body, summary)
    if merged.replace("\r\n", "\n") == body.replace("\r\n", "\n"):
        return f"PR #{pr} description already holds this summary"
    _gh(pr, repo, ["edit", str(pr), "--body-file", "-"], stdin=merged)
    return f"Published to PR #{pr} description: block {'replaced' if replaced else 'added'}"
