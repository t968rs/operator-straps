"""The line-count delta between two git refs of a project, without its machine-generated paths.

Prints one status line::

    delta [ok] | source +A/-D (net +N), F files | total +A/-D (net +N), F files | excluded X

``source`` counts the paths that are not machine-generated (the project's exclusions file plus the harness
output patterns, or the ``Artifact`` commit bucket); ``total`` counts every path; ``excluded`` is the number
of paths left out. ``--json`` prints the ``harness_lib.diff_delta.delta_payload`` dict instead.

Roots: the project is the git top level of ``--repo`` (default: the working directory); its
``.claude/harness.json`` supplies the exclusions file. The plugin directory supplies only code.

Every failure exits 1 with one ``problem: ...`` line on stderr and nothing on stdout.

Usage::

    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/diff_delta.py" REF_A REF_B
        [--repo DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from harness_lib.config import ConfigError, activate, load_config  # noqa: E402
from harness_lib.default_exclusions import ensure_default_exclusions  # noqa: E402
from harness_lib.diff_delta import DeltaError, DiffDelta, between, delta_payload  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

_GIT_TIMEOUT_SECONDS = 30


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Source-only line counts between two git refs.")
    parser.add_argument("ref_a", help="the older ref")
    parser.add_argument("ref_b", help="the newer ref")
    parser.add_argument("--repo", type=Path, default=None, help="a directory inside the project checkout")
    parser.add_argument("--json", action="store_true", help="print the delta payload as JSON")
    return parser


def _root(repo: Optional[Path]) -> Path:
    """Git top level of ``repo`` (default: cwd); DeltaError for an explicit ``repo`` outside a checkout."""
    if repo is None:
        return project_root(Path.cwd())
    argv = ["git", "-C", str(repo), "rev-parse", "--show-toplevel"]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              stdin=subprocess.DEVNULL, timeout=_GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeltaError(f"--repo {repo}: {exc}") from exc
    if done.returncode != 0:
        raise DeltaError(f"--repo {repo}: not inside a git checkout")
    return Path(done.stdout.strip()).resolve()


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def _part(delta: DiffDelta) -> str:
    """``+A/-D (net +N), F files`` for one delta."""
    return f"+{delta.adds}/-{delta.subs} (net {delta.net:+d}), {_files(delta.files)}"


def status_line(delta: DiffDelta) -> str:
    """The one-line report of ``delta``: source, total and the excluded path count."""
    full = delta.full if delta.full is not None else delta
    return f"delta [ok] | source {_part(delta)} | total {_part(full)} | excluded {len(delta.excluded)}"


def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a config or git failure."""
    _utf8_streams()
    args = _parser().parse_args(argv)
    try:
        cfg = activate(load_config(_root(args.repo)))
        ensure_default_exclusions(cfg)
        delta = between(cfg.project_root, args.ref_a, args.ref_b)
    except (DeltaError, ConfigError, OSError) as exc:
        print(f"problem: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(delta_payload(delta), indent=2) if args.json else status_line(delta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
