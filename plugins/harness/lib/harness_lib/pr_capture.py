"""PR capture from local git: metadata from one ``gh pr view`` read, facts and budgeted diffs from git.

Shared by the harness plugin's pr-sum driver (``scripts/pr_sum.py``) and pr-review driver
(``scripts/pr_review.py``). ``capture_pr`` fetches the PR head and the base side, takes the merge base of the
head with the base tip, and lists the changed paths with their line counts; on request it reads the local PR
branch's HEAD and working tree in place of the committed PR head. ``budgeted_diff`` renders the diff
of a chosen file set under a changed-line read budget and an output character budget; ``file_patches`` reads
the per-file diffs it renders with one ``git diff`` per pathspec chunk. Test paths are recognized through the
active harness configuration (``tests.roots`` / ``tests.file_pattern``).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from harness_lib.branch_capture import (
    CaptureError,
    capture_paths,
    current_branch,
    file_lines,
    git_out,
    is_binary,
    path_diff,
    read_untracked,
    render_section,
    untracked_paths,
)
from harness_lib.commit_diff import DiffStat, cap_sections, parse_numstat_z, plan_reads
from harness_lib.commit_grouping import CapturedPath
from harness_lib.config import active
from harness_lib.pr_summary import PrFacts, PrFile

GH_FIELDS = "number,title,baseRefName,headRefName,headRefOid,mergeCommit"
DOC_ROOTS = ("docs", "doc")
DOC_SUFFIXES = (".md", ".rst", ".adoc")
PATHSPEC_CHARS = 8000
_STATUSES = ("A", "M", "D", "R")
_SECTION_START = re.compile(r"^(?=diff --git )", re.M)


@dataclass(frozen=True)
class PrMeta:
    """The ``gh pr view`` fields a capture needs."""

    number: int
    title: str
    base: str
    head: str
    head_sha: str
    merge_commit: Optional[str]

    @classmethod
    def from_gh(cls, raw: Mapping[str, object]) -> PrMeta:
        """Parse ``gh pr view --json`` output (``GH_FIELDS``); a missing field raises ``KeyError``."""
        merge = raw.get("mergeCommit")
        return cls(
            int(raw["number"]), str(raw["title"]), str(raw["baseRefName"]), str(raw["headRefName"]),
            str(raw["headRefOid"]), merge.get("oid") if isinstance(merge, dict) else None,
        )

    @property
    def base_tip(self) -> str:
        """Base commit to diff from: the merge commit's first parent once merged, ``origin/<base>`` before."""
        return f"{self.merge_commit}^1" if self.merge_commit else f"origin/{self.base}"

    @property
    def fetch_refs(self) -> Tuple[str, str]:
        """``git fetch origin`` refs: the merge commit (once merged) or the base branch, plus the PR head."""
        return self.merge_commit or self.base, f"pull/{self.number}/head"


def _gh_view(repo: Path, pr: int) -> str:
    """Raw ``gh pr view --json`` output; raise ``CaptureError`` when gh is missing or fails."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr), "--json", GH_FIELDS], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise CaptureError([f"gh pr view {pr} could not run ({exc}); install gh or check PATH"]) from exc
    if result.returncode != 0:
        raise CaptureError([f"gh pr view {pr} failed: {result.stderr.strip()}"])
    return result.stdout


def gh_metadata(repo: Path, pr: int) -> PrMeta:
    """PR metadata from one ``gh pr view`` call; raise ``CaptureError`` when it fails or does not parse."""
    text = _gh_view(repo, pr)
    try:
        return PrMeta.from_gh(json.loads(text))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise CaptureError([f"gh pr view {pr} output does not parse ({exc!r})"]) from exc


def _binary_paths(numstat: str) -> FrozenSet[str]:
    """Paths ``git diff --numstat -M -z`` reports as binary (``-`` counts), under their new path."""
    tokens = numstat.split("\0")
    binary: List[str] = []
    pos = 0
    while pos < len(tokens) and tokens[pos]:
        added, _, path = tokens[pos].split("\t", 2)
        pos += 1
        if not path:
            path, pos = tokens[pos + 1], pos + 2
        binary += [path] if added == "-" else []
    return frozenset(binary)


def _revs(merge_base: str, head: Optional[str]) -> List[str]:
    """``git diff`` revisions: merge base against ``head``, or against the working tree when None."""
    return [merge_base, head] if head else [merge_base]


def _numstat(
        repo: Path, merge_base: str, head: Optional[str],
) -> Tuple[Dict[str, DiffStat], FrozenSet[str]]:
    """Changed-line counts per path and the binary paths, from one numstat read of merge_base against
    ``head`` (the working tree when None)."""
    text = git_out(repo, "diff", "--numstat", "-M", "-z", *_revs(merge_base, head))
    return {s.path: s for s in parse_numstat_z(text)}, _binary_paths(text)


def _untracked_facts(repo: Path) -> Tuple[Dict[str, DiffStat], FrozenSet[str], FrozenSet[str]]:
    """Untracked paths with their line counts as additions, the binary ones among them, and all of them."""
    paths = untracked_paths(repo)
    lines = {path: file_lines(repo, path) for path in paths}
    stats = {path: DiffStat(path, len(text) if text is not None else 0, 0) for path, text in lines.items()}
    binary = frozenset(p for p in paths if is_binary(read_untracked(repo, p) or b""))
    return stats, binary, frozenset(paths)


def _pr_file(
        capture: CapturedPath, stats: Mapping[str, DiffStat], binary: FrozenSet[str],
        untracked: FrozenSet[str] = frozenset(),
) -> PrFile:
    """``PrFile`` for one captured path; statuses other than A/D/R read as modified."""
    stat = stats.get(capture.path, DiffStat(capture.path, 0, 0))
    status = capture.status if capture.status in _STATUSES else "M"
    return PrFile(
        status, capture.path, capture.old_path, stat.added, stat.deleted, capture.path in binary,
        capture.path in untracked,
    )


def _commit_lines(repo: Path, merge_base: str, head: str) -> Tuple[str, ...]:
    """``<short sha> <subject>`` per commit in merge_base..head, oldest first."""
    out = git_out(repo, "log", "--reverse", "--format=%h %s", f"{merge_base}..{head}")
    return tuple(line for line in out.splitlines() if line.strip())


def _head(repo: Path, meta: PrMeta, local: bool) -> Tuple[str, str]:
    """(head SHA, source): the checkout's HEAD when ``local`` and it is on the PR branch, else the PR head."""
    if local and current_branch(repo) == meta.head:
        return git_out(repo, "rev-parse", "HEAD").strip(), "local"
    return meta.head_sha, "remote"


def _files(repo: Path, merge_base: str, head: Optional[str]) -> Tuple[PrFile, ...]:
    """Changed files from merge_base to ``head``, or to the working tree plus untracked files when None."""
    captures = capture_paths(repo, merge_base, head)
    stats, binary = _numstat(repo, merge_base, head)
    untracked: FrozenSet[str] = frozenset()
    if head is None:
        extra_stats, extra_binary, untracked = _untracked_facts(repo)
        stats, binary = {**stats, **extra_stats}, binary | extra_binary
    return tuple(_pr_file(c, stats, binary, untracked) for c in captures)


def capture_pr(
        repo: Path, meta: PrMeta, fetch: bool = True, today: Optional[str] = None, local: bool = False,
        working_tree: bool = False,
) -> PrFacts:
    """Facts for the PR ``meta`` describes, from local git (fetching the base side and PR head first).

    ``local`` reads the checked-out PR branch's HEAD in place of the PR head ``gh`` reports;
    ``working_tree`` adds that checkout's staged, unstaged and untracked changes. Both apply only while the
    PR branch is checked out; elsewhere the capture falls back to the committed PR head.
    """
    if fetch:
        git_out(repo, "fetch", "origin", *meta.fetch_refs)
    head_sha, source = _head(repo, meta, local)
    working = working_tree and source == "local"
    merge_base = git_out(repo, "merge-base", meta.base_tip, head_sha).strip()
    return PrFacts(
        meta.number, meta.title, meta.head, meta.base, head_sha, merge_base,
        today or date.today().isoformat(), _commit_lines(repo, merge_base, head_sha),
        _files(repo, merge_base, None if working else head_sha), source, working,
    )


def _is_doc_path(path: str) -> bool:
    """True for a path under a top-level ``docs/`` or ``doc/`` directory, or a prose markup file."""
    parts = PurePosixPath(path).parts
    return (len(parts) > 1 and parts[0] in DOC_ROOTS) or path.lower().endswith(DOC_SUFFIXES)


def read_rank(path: str) -> int:
    """Diff read order: source 0, tests 1 (the active configuration's test layout), documentation 2."""
    if active().tests.is_test_path(path):
        return 1
    return 2 if _is_doc_path(path) else 0


def _header(f: PrFile) -> str:
    """The ``diff --git`` line git prints for ``f`` with default prefixes and an unquoted path."""
    return f"diff --git a/{f.old_path or f.path} b/{f.path}"


def _pathspec_chunks(files: Sequence[PrFile]) -> List[List[str]]:
    """Pathspecs (each file's path and old path together) in chunks under ``PATHSPEC_CHARS`` characters."""
    chunks: List[List[str]] = []
    size = PATHSPEC_CHARS
    for f in files:
        paths = [f.path, f.old_path] if f.old_path else [f.path]
        if size + sum(len(p) + 1 for p in paths) > PATHSPEC_CHARS:
            chunks.append([])
            size = 0
        chunks[-1] += paths
        size += sum(len(p) + 1 for p in paths)
    return chunks


def _sections(text: str) -> Dict[str, str]:
    """``diff --git`` header line -> its whole section, for one multi-file patch."""
    parts = _SECTION_START.split(text)
    return {part.split("\n", 1)[0]: part for part in parts if part.startswith("diff --git ")}


def file_patches(repo: Path, facts: PrFacts, files: Sequence[PrFile]) -> Dict[str, str]:
    """Path -> its ``git diff -M merge_base head`` text, read with one ``git diff`` per pathspec chunk.

    A working-tree capture diffs against the working tree, and an untracked file reads as all additions.
    A file whose section does not appear under ``_header`` (a quoted path, a non-default diff prefix, a
    different rename pairing, an untracked file) is read on its own with ``path_diff``, so each value
    equals that read.
    """
    head = None if facts.working_tree else facts.head_sha
    sections: Dict[str, str] = {}
    for chunk in _pathspec_chunks([f for f in files if not f.untracked]):
        diff = git_out(repo, "diff", "-M", *_revs(facts.merge_base, head), "--", *chunk)
        sections.update(_sections(diff))
    return {f.path: sections[_header(f)] if _header(f) in sections
            else path_diff(repo, facts.merge_base, f.path, f.old_path, f.untracked, head) for f in files}


def budgeted_diff(
        repo: Path, facts: PrFacts, files: Sequence[PrFile], block_budget: int, char_budget: int,
        patches: Optional[Mapping[str, str]] = None,
) -> str:
    """Diff sections for ``files`` (source, tests, docs order) under the read and character budgets.

    Paths are read in full until ``block_budget`` changed lines are spent; later paths are summarized. Output
    past ``char_budget`` characters keeps only each section's header. ``patches`` (``file_patches`` output)
    supplies already-read diffs; the files it lacks are read here in one batch.
    """
    chosen = sorted(files, key=lambda f: read_rank(f.path))
    texts = dict(patches or {})
    texts.update(file_patches(repo, facts, [f for f in chosen if f.path not in texts]))
    stats = [DiffStat(f.path, f.added, f.deleted) for f in chosen]
    modes = plan_reads(stats, block_budget)
    rendered = [render_section(stat, modes[stat.path], texts[stat.path]) for stat in stats]
    return "\n".join(cap_sections(rendered, char_budget))
