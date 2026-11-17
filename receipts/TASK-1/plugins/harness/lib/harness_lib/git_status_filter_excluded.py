#!/usr/bin/env python3
"""Filter git status / file-list output by fnmatch exclusion patterns.

Reads stdin and emits lines whose paths do NOT match any pattern from the
exclusions JSON (``{"exclusions": [{"pattern": "<fnmatch glob>"}, ...]}``).

The exclusions file is the positional argument when given; otherwise the
project's configured ``exclusions`` path (``.claude/harness.json``), resolved
against the project at ``--repo`` (default: the working directory). A project
with ``exclusions`` set to null filters nothing: every line passes through.
A project on the default exclusions path gets the default file seeded
(written into the project) when it is absent. Only the configured route
seeds; a positional path is read as given and must exist.

Two input modes:
  - default: stdin is `git status --porcelain --untracked-files=all` output
    (status code prefix in cols 0-2, path from col 3); the filter strips the
    prefix when matching against patterns, and re-emits the full line on pass.
    Without `--untracked-files=all`, git collapses an untracked folder to one
    `?? <dir>/` line that a file pattern never matches.
  - --paths-only: stdin is bare paths (one per line, no status prefix), as
    produced by e.g. `gh pr view <PR> --json files --jq '.files[].path'`;
    the filter matches each line as a path directly. Same exclusions apply
    at both call sites: the pr-review dirty-tree check (default) and its
    bucket-sort gate (--paths-only).

Exit codes:
  0: success
  1: JSON missing, malformed, or I/O error; project configuration invalid
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import List, Optional

_LIB = Path(__file__).resolve().parents[1]


def load_exclusions(json_path: Path) -> List[str]:
    """Load fnmatch patterns from JSON file.

    Args:
        json_path: Path to exclusions JSON file.

    Returns:
        List of fnmatch pattern strings.

    Raises:
        FileNotFoundError: If json_path does not exist.
        json.JSONDecodeError: If JSON is malformed.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"Exclusions file not found: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    return [e["pattern"] for e in data["exclusions"]]


def _ensure_lib_on_path() -> None:
    """Make ``harness_lib`` importable when this file runs as a standalone script."""
    if str(_LIB) not in sys.path:
        sys.path.insert(0, str(_LIB))


def configured_exclusions(repo: Path) -> Optional[Path]:
    """Absolute exclusions file configured for the project at ``repo``, or None when disabled.

    Loads the project's configuration without activating it, so the process-wide ``active()``
    configuration is left untouched. A project on the default path gets the default file seeded when
    it is absent.

    Raises:
        ConfigError: If the project's ``.claude/harness.json`` is malformed or fails validation.
    """
    _ensure_lib_on_path()
    from harness_lib.config import load_config
    from harness_lib.default_exclusions import ensure_default_exclusions
    from harness_lib.project import project_root

    cfg = load_config(project_root(repo))
    ensure_default_exclusions(cfg)
    return cfg.path(cfg.exclusions) if cfg.exclusions else None


def filter_status_lines(
    patterns: List[str],
    paths_only: bool = False,
) -> None:
    """Read lines from stdin, filter by patterns, write to stdout.

    Args:
        patterns: fnmatch patterns to match against paths.
        paths_only: When False (default), input is `git status --porcelain`
            format -- strip status code from cols 0-2 and match cols 3+.
            When True, input is bare paths (one per line); match the whole
            line as a path.
    """
    for line in sys.stdin:
        path = line.rstrip() if paths_only else line[3:].rstrip()
        if not any(fnmatch.fnmatch(path, p) for p in patterns):
            sys.stdout.write(line)


def _parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Filter git status --porcelain or bare path list by exclusion patterns"
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        help="Path to exclusions JSON (default: the project's configured exclusions file; "
             "none configured filters nothing; a project on the default exclusions path gets "
             "the default file seeded when it is absent)",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(),
        help="Project whose configured exclusions apply when json_path is omitted (default: cwd).",
    )
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="Treat stdin as bare paths (one per line) instead of git status --porcelain format. "
             "Use with `gh pr view <PR> --json files --jq '.files[].path' | ... --paths-only` "
             "for pr-review bucket-sort filtering.",
    )
    return parser


def _patterns(json_path: Optional[str], repo: Path) -> List[str]:
    """Patterns from ``json_path``, else from the project's configured exclusions (none when disabled)."""
    path = Path(json_path) if json_path else configured_exclusions(repo)
    return load_exclusions(path) if path is not None else []


def main() -> int:
    """Orchestrate JSON load and stdin filtering.

    Returns:
        0 on success, 1 on error.
    """
    args = _parser().parse_args()
    _ensure_lib_on_path()
    from harness_lib.config import ConfigError

    try:
        filter_status_lines(_patterns(args.json_path, args.repo), paths_only=args.paths_only)
        return 0
    except (FileNotFoundError, json.JSONDecodeError, ConfigError) as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Unexpected error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
