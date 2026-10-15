"""Build a PR merge-body Markdown file from the current branch's commit-message TXT files.

Usage: merge_body.py [--repo PATH] [--all]

Reads ``*.txt`` from the project's ``artifacts.commit_messages`` directory (default ``docs/_commit_messages``)
whose sanitized stem contains the sanitized current branch name, sorted by filename. ``--all`` takes every
``*.txt`` instead; without it, a branch with no matching file is a problem. Writes
``merge-body-<branch>.md`` into the same directory (overwriting) and prints only its absolute path.
Problems go to stderr as ``problem: ...`` lines with exit 1.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

_UNSAFE = re.compile(r'[\\/:*?"<>|]')
OUTPUT_PREFIX = "merge-body"


class MergeBodyError(RuntimeError):
    """A precondition for building the merge body does not hold."""


def git(repo: Path, *args: str) -> Optional[str]:
    """Stripped stdout of ``git -C repo args``, or None when git exits non-zero."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def safe_stem(value: str) -> str:
    """``value`` with path separators and filename-invalid characters replaced by ``_``."""
    return _UNSAFE.sub("_", value)


def current_branch(repo: Path) -> str:
    """The checked-out branch name; a detached HEAD is a problem."""
    branch = git(repo, "branch", "--show-current")
    if not branch:
        raise MergeBodyError("no current branch (detached HEAD); check out the PR branch first")
    return branch


def select_sources(folder: Path, branch: str, take_all: bool) -> List[Path]:
    """TXT files for ``branch`` (or every TXT with ``take_all``), sorted by filename."""
    every = sorted((p for p in folder.glob("*.txt") if p.is_file()), key=lambda p: p.name)
    if not every:
        raise MergeBodyError(f"no .txt commit-message files in {folder.as_posix()}")
    if take_all:
        return every
    key = safe_stem(branch)
    mine = [p for p in every if key in safe_stem(p.stem)]
    if not mine:
        raise MergeBodyError(f"no .txt file for branch {branch!r} in {folder.as_posix()}; "
                             f"pass --all to use every file there")
    return mine


def fence_for(text: str) -> str:
    """A backtick fence longer than any backtick run inside ``text`` (at least four)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def render(sources: Sequence[Path], label: str) -> str:
    """The merge-body Markdown for ``sources``; ``label`` names the directory in the summary line."""
    lines = ["## Merge Summary", "", f"Generated from existing commit-message files in `{label}/`.", "",
             "## Source Files", ""]
    lines += [f"- `{p.name}`" for p in sources]
    lines += ["", "## Commit Messages", ""]
    for path in sources:
        body = path.read_text(encoding="utf-8").rstrip()
        fence = fence_for(body)
        lines += [f"### `{path.name}`", "", f"{fence}text", body, fence, ""]
    return "\n".join(lines)


def build(repo: Path, take_all: bool) -> Path:
    """Write the merge body for the project at ``repo`` and return its absolute path."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    if git(repo, "rev-parse", "--show-toplevel") is None:
        raise MergeBodyError(f"not a git repository: {repo}")
    cfg = activate(load_config(project_root(repo)))
    label = cfg.artifacts.commit_messages.strip("/")
    folder = cfg.path(label)
    if not folder.is_dir():
        raise MergeBodyError(f"commit-message directory does not exist: {folder.as_posix()}")
    branch = current_branch(cfg.project_root)
    target = folder / f"{OUTPUT_PREFIX}-{safe_stem(branch)}.md"
    target.write_text(render(select_sources(folder, branch, take_all), label), encoding="utf-8", newline="\n")
    return target.resolve()


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="merge_body.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project checkout (default: cwd)")
    parser.add_argument("--all", action="store_true", dest="take_all",
                        help="use every .txt in the directory, not only the current branch's")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    from harness_lib.config import ConfigError
    args = parse_args(argv)
    try:
        path = build(args.repo, args.take_all)
    except (MergeBodyError, ConfigError) as exc:
        sys.stderr.write(f"problem: {exc}\n")
        return 1
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
