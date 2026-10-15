"""Print the absolute path of the project's newest run log, newest first.

Usage: latest_runlog.py [--count N] [--dir PATH] [--repo PATH]

The folder is ``--dir`` (relative to the project root, or absolute), else ``runlogs.dir`` in
``.claude/harness.json``; dated subfolders under it (archived logs) are searched too. A file counts as a run
log when its name fully matches ``runlogs.name_pattern``: named group ``date`` (YYYY-MM-DD), optional ``time``
(HHMMSS), both checked as real calendar values. A date-only name sorts as midnight; equal stamps fall back to
mtime. An explicit ``--repo`` must be a git checkout; without it the project is the cwd's checkout, else
``CLAUDE_PROJECT_DIR``. stdout carries only paths; stderr carries one summary line. Read-only: nothing is
moved or written.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

SortKey = Tuple[datetime, int, str]


class RunLogError(RuntimeError):
    """The run-log folder or name pattern is unusable, or the folder holds no run log."""


def compile_pattern(text: str) -> "re.Pattern[str]":
    """Compile ``runlogs.name_pattern``; it must define a ``date`` group."""
    try:
        pattern = re.compile(text)
    except re.error as exc:
        raise RunLogError(f"runlogs.name_pattern does not compile: {exc}") from exc
    if "date" not in pattern.groupindex:
        raise RunLogError("runlogs.name_pattern has no named group 'date'")
    return pattern


def stamp(name: str, pattern: "re.Pattern[str]") -> Optional[datetime]:
    """The timestamp a log name carries, or None for a name that is not a run log."""
    match = pattern.fullmatch(name)
    if match is None:
        return None
    time_text = match.groupdict().get("time") or "000000"
    try:
        return datetime.strptime(f"{match['date']}_{time_text}", "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None


def find_runlogs(folder: Path, pattern: "re.Pattern[str]") -> List[Tuple[SortKey, Path]]:
    """Every run log under ``folder`` (subfolders included), newest first."""
    found = []
    for path in folder.rglob("*"):
        when = stamp(path.name, pattern)
        if when is not None and path.is_file():
            found.append(((when, path.stat().st_mtime_ns, path.as_posix()), path.resolve()))
    return sorted(found, reverse=True)


def resolve_folder(root: Path, flag: Optional[str], configured: Optional[str]) -> Path:
    """``--dir``, else the configured folder, against the project root; it must exist."""
    rel = flag or configured
    if rel is None:
        raise RunLogError("runlogs.dir is not set in .claude/harness.json; set it or pass --dir")
    folder = root / rel
    if not folder.is_dir():
        raise RunLogError(f"run-log folder not found: {folder.as_posix()}")
    return folder


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1, help="print the N newest logs (default 1)")
    parser.add_argument("--dir", help="run-log folder (default: runlogs.dir in .claude/harness.json)")
    parser.add_argument("--repo", type=Path, help="project checkout (default: the cwd's project)")
    return parser.parse_args(argv)


def checked_repo(repo: Optional[Path]) -> Optional[Path]:
    """An explicit ``--repo`` must be a git checkout, so it never falls back to ``CLAUDE_PROJECT_DIR``."""
    if repo is None:
        return None
    argv = ["git", "-C", str(repo), "rev-parse", "--show-toplevel"]
    if not repo.is_dir() or subprocess.run(argv, capture_output=True).returncode != 0:
        raise RunLogError(f"not a git repository: {repo.as_posix()}")
    return repo


def newest(args: argparse.Namespace) -> List[Tuple[SortKey, Path]]:
    """The ``--count`` newest run logs; raises ``RunLogError`` when there are none."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    cfg = activate(load_config(project_root(checked_repo(args.repo))))
    folder = resolve_folder(cfg.project_root, args.dir, cfg.runlogs.dir)
    logs = find_runlogs(folder, compile_pattern(cfg.runlogs.name_pattern))
    if not logs:
        raise RunLogError(f"no run log under {folder.as_posix()} matches runlogs.name_pattern")
    print(f"{len(logs)} run logs under {folder.as_posix()}; newest {logs[0][0][0]:%Y-%m-%d %H:%M:%S}",
          file=sys.stderr)
    return logs[:max(args.count, 1)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    from harness_lib.config import ConfigError
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        logs = newest(parse_args(argv))
    except (RunLogError, ConfigError) as exc:
        print(f"problem: {exc}", file=sys.stderr)
        return 1
    for _, path in logs:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
