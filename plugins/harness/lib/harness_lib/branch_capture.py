"""Git capture shared by the commit-message and PR-summary drivers.

A capture compares a merge base with either the working tree (``head=None``: committed, staged, unstaged
and untracked changes) or a commit (``head=<ref>``: committed changes only). Git failures raise
``CaptureError`` with one problem per line.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from harness_lib.commit_diff import DiffStat, parse_numstat_z
from harness_lib.commit_grouping import CapturedPath, merge_capture, parse_name_status_z

BINARY_PROBE_BYTES = 8192
BINARY_BODY = "Binary file (untracked)"
UNREADABLE_BODY = "Not a readable file (untracked)"
PATHSPEC_CHARS = 8000

_SECTION_START = re.compile(r"^(?=diff --git )", re.M)
# ``git diff -M`` with the header display pinned: ``a/`` and ``b/`` prefixes whatever ``diff.noprefix`` or
# ``diff.mnemonicPrefix`` say, no color, and non-ASCII paths unquoted, so a batched read's section headers
# are the ``diff --git a/<old or path> b/<path>`` lines its lookup expects.
DIFF_DISPLAY = (
    "-c", "core.quotePath=false", "diff", "--no-color", "--src-prefix=a/", "--dst-prefix=b/", "-M",
)


class CaptureError(RuntimeError):
    """Capture or validation failure; ``problems`` holds one message per defect."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git in ``repo`` without raising; output decoded as UTF-8 with undecodable bytes replaced."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def git_out(repo: Path, *args: str) -> str:
    """Run git in ``repo``; return stdout, raising ``CaptureError`` on a non-zero exit."""
    result = git(repo, *args)
    if result.returncode != 0:
        raise CaptureError([f"git {' '.join(args)} failed: {result.stderr.strip()}"])
    return result.stdout


def current_branch(repo: Path) -> str:
    """Return the checked-out branch name (empty on a detached HEAD)."""
    return git_out(repo, "branch", "--show-current").strip()


def resolve_merge_base(repo: Path, base: str, fetch: bool = True) -> str:
    """Merge base of ``HEAD`` with the furthest-forward ``base`` tip, fetching ``origin <base>`` first.

    The local ``base`` is used when it contains ``origin/<base>`` or no ``origin/<base>`` exists (a repo
    without a remote, with ``fetch`` off); otherwise ``origin/<base>`` is used.
    """
    if fetch:
        git_out(repo, "fetch", "origin", base)
    remote = f"origin/{base}"
    has_remote = git(repo, "rev-parse", "--verify", "--quiet", f"{remote}^{{commit}}").returncode == 0
    local_ahead = not has_remote or git(repo, "merge-base", "--is-ancestor", remote, base).returncode == 0
    return git_out(repo, "merge-base", base if local_ahead else remote, "HEAD").strip()


def untracked_paths(repo: Path) -> List[str]:
    """Untracked, non-ignored paths."""
    listing = git_out(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return [path for path in listing.split("\0") if path]


def _range(merge_base: str, head: Optional[str]) -> List[str]:
    """``git diff`` revision arguments: merge base against ``head``, or against the working tree."""
    return [merge_base, head] if head else [merge_base]


def capture_paths(repo: Path, merge_base: str, head: Optional[str] = None) -> List[CapturedPath]:
    """Every path differing from ``merge_base``.

    Compared against ``head`` when given; otherwise the working tree plus untracked files.
    """
    listing = git_out(repo, "diff", "--name-status", "-M", "-z", *_range(merge_base, head))
    diff = parse_name_status_z(listing)
    return merge_capture(diff, [] if head else untracked_paths(repo))


def read_untracked(repo: Path, path: str) -> Optional[bytes]:
    """Bytes of an untracked regular file.

    None for a directory (a nested repo) or an unreadable file.
    """
    target = repo / path
    if not target.is_file():
        return None
    try:
        return target.read_bytes()
    except OSError:
        return None


def is_binary(data: bytes) -> bool:
    """True when a NUL byte appears within the first ``BINARY_PROBE_BYTES`` bytes."""
    return b"\0" in data[:BINARY_PROBE_BYTES]


def file_lines(repo: Path, path: str) -> Optional[List[str]]:
    """Text lines of an untracked file (undecodable bytes replaced); None when binary or unreadable."""
    data = read_untracked(repo, path)
    if data is None or is_binary(data):
        return None
    return data.decode("utf-8", errors="replace").splitlines()


def untracked_facts(repo: Path, paths: Sequence[str]) -> Tuple[Dict[str, DiffStat], FrozenSet[str]]:
    """Stat per untracked path (line count as additions; zero when binary or unreadable) and the binary
    paths among them. Each file is read once."""
    stats: Dict[str, DiffStat] = {}
    binary: List[str] = []
    for path in paths:
        data = read_untracked(repo, path)
        if data is not None and is_binary(data):
            binary.append(path)
        lines = data.decode("utf-8", errors="replace").splitlines() if data and path not in binary else []
        stats[path] = DiffStat(path, len(lines), 0)
    return stats, frozenset(binary)


def capture_stats(
        repo: Path, merge_base: str, captures: Sequence[CapturedPath], head: Optional[str] = None,
) -> Dict[str, DiffStat]:
    """Changed-line counts per captured path: numstat, plus file length for untracked paths.

    Untracked lengths are added only for the working-tree mode (``head=None``).
    """
    numstat = git_out(repo, "diff", "--numstat", "-M", "-z", *_range(merge_base, head))
    stats = {s.path: s for s in parse_numstat_z(numstat)}
    if head:
        return stats
    untracked = set(untracked_paths(repo))
    extra, _ = untracked_facts(repo, [c.path for c in captures if c.path in untracked])
    stats.update(extra)
    return stats


def untracked_diff(repo: Path, path: str) -> str:
    """Pseudo-diff of an untracked file: all lines as additions, or a one-line binary/unreadable note."""
    data = read_untracked(repo, path)
    if data is None:
        return UNREADABLE_BODY
    if is_binary(data):
        return BINARY_BODY
    return "\n".join(f"+{line}" for line in data.decode("utf-8", errors="replace").splitlines())


def _tracked_diff(repo: Path, merge_base: str, head: Optional[str], paths: Sequence[str]) -> str:
    """``git diff -M`` of ``paths`` with the display pinned by ``DIFF_DISPLAY``."""
    return git_out(repo, *DIFF_DISPLAY, *_range(merge_base, head), "--", *paths)


def path_diff(
        repo: Path, merge_base: str, path: str, old_path: Optional[str], untracked: bool,
        head: Optional[str] = None,
) -> str:
    """Unified diff of one path against the merge base; an untracked file reads as all additions."""
    if untracked:
        return untracked_diff(repo, path)
    return _tracked_diff(repo, merge_base, head, [path, old_path] if old_path else [path])


def _pathspec_chunks(pairs: Sequence[Tuple[str, Optional[str]]]) -> List[List[str]]:
    """Pathspecs (a path and its rename's old path together) in chunks under ``PATHSPEC_CHARS`` characters."""
    chunks: List[List[str]] = []
    size = PATHSPEC_CHARS
    for path, old_path in pairs:
        paths = [path, old_path] if old_path else [path]
        width = sum(len(p) + 1 for p in paths)
        if size + width > PATHSPEC_CHARS:
            chunks.append([])
            size = 0
        chunks[-1] += paths
        size += width
    return chunks


def path_diffs(
        repo: Path, merge_base: str, pairs: Sequence[Tuple[str, Optional[str]]], untracked: FrozenSet[str],
        head: Optional[str] = None,
) -> Dict[str, str]:
    """Path -> its ``path_diff`` text, the tracked paths read with one ``git diff`` per pathspec chunk.

    Both reads pin the header display (``_tracked_diff``), so user git config does not move the headers.
    A path whose section is not under its ``diff --git a/<old or path> b/<path>`` header (a path git still
    quotes, such as one holding a tab or a quote, or a different rename pairing) and an untracked path are
    read on their own, so each value equals ``path_diff`` of that path.
    """
    tracked = [(path, old) for path, old in pairs if path not in untracked]
    sections: Dict[str, str] = {}
    for chunk in _pathspec_chunks(tracked):
        diff = _tracked_diff(repo, merge_base, head, chunk)
        parts = _SECTION_START.split(diff)
        sections.update({part.split("\n", 1)[0]: part for part in parts if part.startswith("diff --git ")})
    texts: Dict[str, str] = {}
    for path, old in pairs:
        header = f"diff --git a/{old or path} b/{path}"
        if path not in untracked and header in sections:
            texts[path] = sections[header]
        else:
            texts[path] = path_diff(repo, merge_base, path, old, path in untracked, head)
    return texts
