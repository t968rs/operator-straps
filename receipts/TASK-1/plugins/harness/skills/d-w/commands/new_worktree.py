"""Create a detached-HEAD git worktree and print its absolute path.

Usage: new_worktree.py [BASE] [--name NAME] [--no-fetch] [--no-setup] [--repo PATH] [--root PATH]

BASE defaults to HEAD. The project's integration branches (``integration_branches`` in
``.claude/harness.json``, else the configured or ``origin/HEAD`` base branch plus ``main``) fetch ``origin``
first and cut from ``origin/<base>``; a failed fetch is an error. Without a remote, or with ``--no-fetch``,
they cut from the local branch, else the existing ``origin/<base>``. Any other git ref is cut as given.
Worktrees land in ``<root>/<name>``: ``--root``, else the project's ``worktree_root``, else
``~/.config/harness/worktrees/<repo-name>``. stdout carries only the path, printed and flushed right after the
cut, before any setup step, so a run killed during setup still names the worktree.

A ``--repo`` that is itself a linked worktree draws a warning on stderr; the new worktree is still cut.
After the cut, the project's ``worktree_setup`` commands run in the new worktree, then its
``worktree_baseline`` commands (skipped when a setup command failed); ``--no-setup`` skips both. In each list
the first failure stops the list; a baseline command left unrun is reported as ``baseline [skipped]``. Each
step is reported on stderr as ``setup [ok|fail]`` or ``baseline [ok|fail|skipped]``. A step runs without a
shell, with stdin closed, and is killed with its whole process tree after ``STEP_TIMEOUT_SECONDS``. A bare
program name is looked up on PATH (``.cmd`` shims included on Windows); a relative program path resolves
against the new worktree. A failed step never fails the command: the worktree exists, so the exit code
stays 0.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, TYPE_CHECKING, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig


STEP_TIMEOUT_SECONDS = 600
TAIL_LINES = 15
TAIL_BYTES = 65536
KILL_WAIT_SECONDS = 30


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


def linked_worktree_top(repo: Path) -> Optional[Path]:
    """Top level of ``repo`` when it is a linked worktree (git dir differs from the common dir), else None.

    A submodule keeps one git dir that is also its common dir, so it never reads as a linked worktree.
    """
    git_dir = git(repo, "rev-parse", "--path-format=absolute", "--git-dir", check=False)
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    if not git_dir or not common or Path(git_dir).resolve() == Path(common).resolve():
        return None
    top = git(repo, "rev-parse", "--show-toplevel", check=False)
    return Path(top) if top else None


def resolve_program(program: str, cwd: Path) -> str:
    """The executable to launch for ``program``: a relative path joins ``cwd``, a bare name searches PATH.

    CreateProcess resolves a relative program against the parent's directory, not ``cwd``, and finds only
    ``.exe`` files on PATH; ``shutil.which`` honors PATHEXT, so ``.cmd`` shims such as ``npm`` resolve too.
    """
    if os.sep in program or (os.altsep and os.altsep in program):
        target = Path(program)
        return str(target if target.is_absolute() else cwd / target)
    return shutil.which(program) or program


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and every process it started, so no grandchild outlives the step."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=KILL_WAIT_SECONDS)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=KILL_WAIT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_logged(argv: Sequence[str], cwd: Path, out: IO[bytes]) -> Optional[int]:
    """Run ``argv`` in ``cwd`` with output to ``out`` and stdin closed; exit code, or None on timeout."""
    group = {} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen([resolve_program(argv[0], cwd), *argv[1:]], cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=out, stderr=subprocess.STDOUT, **group)
    try:
        return proc.wait(timeout=STEP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        return None
    except BaseException:
        kill_tree(proc)
        raise


def output_tail(out: IO[bytes]) -> List[str]:
    """The last ``TAIL_LINES`` lines written to ``out``."""
    size = out.seek(0, os.SEEK_END)
    out.seek(max(0, size - TAIL_BYTES))
    return out.read().decode(errors="replace").strip().splitlines()[-TAIL_LINES:]


def run_step(label: str, argv: Sequence[str], cwd: Path) -> bool:
    """Run one configured command in ``cwd``, report it on stderr; True when it exited 0."""
    shown = " ".join(argv)
    with tempfile.TemporaryFile() as out:
        try:
            code = run_logged(argv, cwd, out)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
            print(f"{label} [fail] {shown}: {exc}", file=sys.stderr)
            return False
        if code == 0:
            print(f"{label} [ok] {shown}", file=sys.stderr)
            return True
        why = f"timed out after {STEP_TIMEOUT_SECONDS} s" if code is None else f"exit {code}"
        print(f"{label} [fail] {shown} ({why})", file=sys.stderr)
        for line in output_tail(out):
            print(f"  {line}", file=sys.stderr)
    return False


def run_steps(label: str, commands: Sequence[Sequence[str]], cwd: Path, report_skipped: bool = False) -> bool:
    """Run ``commands`` in order, stopping at the first failure; True when all passed.

    With ``report_skipped``, each command left unrun after a failure gets a ``[skipped]`` line.
    """
    for index, argv in enumerate(commands):
        if not run_step(label, argv, cwd):
            for rest in commands[index + 1:] if report_skipped else ():
                print(f"{label} [skipped] {' '.join(rest)} (earlier {label} failed)", file=sys.stderr)
            return False
    return True


def prepare(cfg: HarnessConfig, path: Path) -> None:
    """Run the project's setup commands, then its baseline commands when setup passed."""
    if not run_steps("setup", cfg.worktree_setup, path):
        if cfg.worktree_baseline:
            print("baseline [skipped] setup failed", file=sys.stderr)
        return
    run_steps("baseline", cfg.worktree_baseline, path, report_skipped=True)


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
    parser.add_argument("--no-setup", action="store_true",
                        help="skip the project's worktree_setup and worktree_baseline commands")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository to cut from (default: cwd)")
    parser.add_argument("--root", type=Path, help="parent directory (default: the project's worktree_root)")
    return parser.parse_args(argv)


def create(args: argparse.Namespace) -> Tuple[Path, HarnessConfig]:
    """Add the worktree; return its absolute path and the project config its setup steps come from."""
    cfg = project_config(args.repo)
    ref, sha = resolve_base(args.repo, args.base, fetch=not args.no_fetch,
                            integration=cfg.resolve_integration_branches())
    root = args.root or cfg.resolve_worktree_root()
    root.mkdir(parents=True, exist_ok=True)
    path = free_path(root, args.name or default_name(args.base, sha)).resolve()
    inside = linked_worktree_top(args.repo)
    if inside is not None:
        print(f"new_worktree: {inside} is itself a linked worktree; cutting another under {root}",
              file=sys.stderr)
    git(args.repo, "worktree", "add", "--quiet", "--detach", str(path), sha)
    print(f"detached worktree at {sha[:9]} ({ref})", file=sys.stderr)
    return path, cfg


def main(argv: Optional[list] = None) -> int:
    """Cut the worktree, print its path before any setup step runs, then run the steps."""
    from harness_lib.config import ConfigError
    args = parse_args(argv)
    try:
        path, cfg = create(args)
    except (GitError, ConfigError) as exc:
        print(f"new_worktree: {exc}", file=sys.stderr)
        return 1
    print(path.as_posix(), flush=True)
    if not args.no_setup:
        prepare(cfg, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
