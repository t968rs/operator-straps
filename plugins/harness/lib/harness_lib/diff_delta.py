"""Line-count deltas of a diff, split into source and machine-generated paths.

A ``DiffDelta`` holds the added and deleted line counts and the file count of the paths that are not
machine-generated, the sorted machine-generated paths it left out, and in ``full`` the unfiltered delta of
every path. One rule decides what is machine-generated, shared by pr-review and pr-sum: a path matching a
pattern of the project's exclusions file (``exclusions`` in ``.claude/harness.json``, plus the harness's own
output patterns), or a path the commit buckets file as ``Artifact``.

``between`` reads two git refs; ``from_stats`` and ``from_patterns`` build a delta from ``DiffStat`` rows
already read. Library code: the configuration is read through ``active()`` inside the functions.
"""
from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from harness_lib.branch_commits import Bucket, path_bucket
from harness_lib.commit_diff import DiffStat, parse_numstat_z

_GIT_TIMEOUT_SECONDS = 120
_PATTERN_CACHE: Dict[Tuple[object, ...], Tuple[str, ...]] = {}


class DeltaError(ValueError):
    """A delta that cannot be read: a failed git call or an unknown ref."""


@dataclass(frozen=True)
class DiffDelta:
    """Added and deleted lines and the file count of a diff, with the paths left out and the full delta."""

    adds: int
    subs: int
    files: int
    excluded: Tuple[str, ...] = ()
    full: Optional["DiffDelta"] = None

    @cached_property
    def net(self) -> int:
        """Added lines minus deleted lines."""
        return self.adds - self.subs


def is_machine_generated(path: str, patterns: Sequence[str]) -> bool:
    """True when ``path`` matches one of ``patterns`` (``fnmatch``) or buckets as ``Artifact``."""
    return any(fnmatch.fnmatch(path, p) for p in patterns) or path_bucket(path) is Bucket.ARTIFACT


def _totals(stats: Sequence[DiffStat]) -> DiffDelta:
    """The unfiltered delta of ``stats``."""
    return DiffDelta(sum(s.added for s in stats), sum(s.deleted for s in stats), len(stats))


def from_stats(stats: Iterable[DiffStat], excluded: Callable[[str], bool]) -> DiffDelta:
    """The delta of ``stats`` without the paths ``excluded`` accepts; ``full`` holds every path."""
    rows = list(stats)
    kept = [s for s in rows if not excluded(s.path)]
    left_out = tuple(sorted(s.path for s in rows if excluded(s.path)))
    source = _totals(kept)
    return DiffDelta(source.adds, source.subs, source.files, left_out, _totals(rows))


def from_patterns(stats: Iterable[DiffStat], patterns: Sequence[str]) -> DiffDelta:
    """``from_stats`` with the machine-generated rule over ``patterns``."""
    return from_stats(stats, lambda path: is_machine_generated(path, patterns))


def project_patterns(repo: Path) -> Tuple[str, ...]:
    """The exclusion patterns of the project at ``repo``: its configured file plus the harness patterns.

    Empty when ``exclusions`` is null; the harness patterns alone when the configured file is missing.
    """
    from harness_lib.config import active
    from harness_lib.default_exclusions import harness_patterns, with_harness_patterns
    from harness_lib.git_status_filter_excluded import load_exclusions
    cfg = active()
    if not cfg.exclusions:
        return ()
    target = Path(repo) / cfg.exclusions
    if not target.is_file():
        return tuple(harness_patterns(cfg))
    return tuple(with_harness_patterns(cfg, load_exclusions(target)))


def _file_key(target: Path) -> Tuple[object, ...]:
    """The cache key of ``target``: its path, modification time and size (None for a missing file)."""
    try:
        stat = target.stat()
    except OSError:
        return (str(target), None, None)
    return (str(target), stat.st_mtime_ns, stat.st_size)


def active_patterns() -> Tuple[str, ...]:
    """``project_patterns`` of the active project, reread only when its exclusions file changes."""
    from harness_lib.config import active
    from harness_lib.default_exclusions import harness_patterns
    cfg = active()
    if not cfg.exclusions:
        return ()
    key = (*_file_key(cfg.path(cfg.exclusions)), tuple(harness_patterns(cfg)))
    if key not in _PATTERN_CACHE:
        _PATTERN_CACHE[key] = project_patterns(cfg.project_root)
    return _PATTERN_CACHE[key]


def _numstat(repo: Path, ref_a: str, ref_b: str) -> str:
    """``git diff --numstat -M -z`` output between two refs; DeltaError on a failed call."""
    argv = ["git", "-C", str(repo), "diff", "--numstat", "-M", "-z", ref_a, ref_b, "--"]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=_GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeltaError(f"git diff {ref_a} {ref_b}: {exc}") from exc
    if done.returncode != 0:
        raise DeltaError(done.stderr.strip() or f"git diff {ref_a} {ref_b}: exit {done.returncode}")
    return done.stdout


def between(repo: Path, ref_a: str, ref_b: str, patterns: Optional[Sequence[str]] = None) -> DiffDelta:
    """The ``ref_a`` to ``ref_b`` delta in ``repo``, filtered by ``patterns`` (default: the project's)."""
    stats = parse_numstat_z(_numstat(Path(repo), ref_a, ref_b))
    return from_patterns(stats, project_patterns(Path(repo)) if patterns is None else patterns)


def delta_payload(delta: DiffDelta) -> Dict[str, object]:
    """``delta`` as a JSON-ready dict; ``full`` nests the same shape, or None."""
    return {
        "adds": delta.adds, "subs": delta.subs, "net": delta.net, "files": delta.files,
        "excluded": list(delta.excluded),
        "full": None if delta.full is None else delta_payload(delta.full),
    }
