"""Create a detached-HEAD git worktree and print its absolute path.

Usage: new_worktree.py [BASE] [--name NAME] [--no-fetch] [--repo PATH] [--root PATH]

BASE defaults to HEAD. The project's integration branches (``integration_branches`` in
``.claude/harness.json``, else the configured or ``origin/HEAD`` base branch plus ``main``) fetch ``origin``
first and cut from ``origin/<base>``; a failed fetch is an error. Without a remote, or with ``--no-fetch``,
they cut from the local branch, else the existing ``origin/<base>``. Any other git ref is cut as given.
Worktrees land in ``<root>/<name>``: ``--root``, else the project's ``worktree_root``, else
``~/.config/harness/worktrees/<repo-name>``. stdout carries only the path.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig


class GitError(RuntimeError):
    """A git command exited non-zero."""


def git(repo: Path, *args: str, check: bool = True) -> Optional[str]:
    """Run git in ``repo``; return stripped stdout, or None on failure when ``check`` is False."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode == 0:
        return done.stdout.strip()
    if check:
        raise GitError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return None


def project_config(repo: Path) -> HarnessConfig:
    """The project's activated harness config; raises ``ConfigError`` for an unreadable ``harness.json``."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    return activate(load_config(project_root(repo)))


def resolve_base(repo: Path, base: str, fetch: bool, integration: Sequence[str]) -> Tuple[str, str]:
    """Return ``(ref, sha)`` for the requested base; integration branches prefer the fetched remote."""
    if base.upper() == "HEAD":
        return "HEAD", git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    candidates = integration_candidates(repo, base, fetch) if base in integration else [base]
    for ref in candidates:
        sha = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if sha:
            return ref, sha
    raise GitError(f"unknown ref: {base}")


def integration_candidates(repo: Path, base: str, fetch: bool) -> List[str]:
    """Refs to try for integration branch ``base``, best first.

    With an ``origin`` and fetching on: fetch, then only ``origin/<base>``; a failed fetch raises rather than
    cutting from a stale remote-tracking ref. Without ``origin``, or with ``--no-fetch``: the local branch,
    then the existing ``origin/<base>``.
    """
    if not fetch or git(repo, "remote", "get-url", "origin", check=False) is None:
        return [base, f"origin/{base}"]
    try:
        git(repo, "fetch", "--quiet", "origin", base)
    except GitError as exc:
        raise GitError(f"fetch origin {base} failed ({exc}); rerun with --no-fetch to cut from the "
                       f"local branch") from exc
    return [f"origin/{base}"]


def free_path(root: Path, name: str) -> Path:
    """First of ``root/name``, ``root/name-2``, ... that does not exist yet."""
    candidate, n = root / name, 2
    while candidate.exists():
        candidate, n = root / f"{name}-{n}", n + 1
    return candidate


def default_name(base: str, sha: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower() or "wt"
    return f"{slug}-{sha[:9]}"


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", default="HEAD",
                        help="HEAD (default), an integration branch, or any ref")
    parser.add_argument("--name", help="worktree directory name (default: <base>-<short-sha>)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip fetching origin for integration branches")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository to cut from (default: cwd)")
    parser.add_argument("--root", type=Path, help="parent directory (default: the project's worktree_root)")
    return parser.parse_args(argv)


def create(args: argparse.Namespace) -> Path:
    """Add the worktree and return its absolute path."""
    cfg = project_config(args.repo)
    ref, sha = resolve_base(args.repo, args.base, fetch=not args.no_fetch,
                            integration=cfg.resolve_integration_branches())
    root = args.root or cfg.resolve_worktree_root()
    root.mkdir(parents=True, exist_ok=True)
    path = free_path(root, args.name or default_name(args.base, sha)).resolve()
    git(args.repo, "worktree", "add", "--quiet", "--detach", str(path), sha)
    print(f"detached worktree at {sha[:9]} ({ref})", file=sys.stderr)
    return path


def main(argv: Optional[list] = None) -> int:
    from harness_lib.config import ConfigError
    try:
        path = create(parse_args(argv))
    except (GitError, ConfigError) as exc:
        print(f"new_worktree: {exc}", file=sys.stderr)
        return 1
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
