"""Report whether this machine and project can run the harness.

Usage: doctor.py [--repo PATH]

Prints the status line, then one line per check (``[ok]``, ``[warn]`` or ``[fail]``, a failing check followed
by its fix). Exits 1 when any check failed. Read-only: nothing is installed, written or changed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from harness_lib import doctor  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project to check (default: cwd)")
    args = parser.parse_args(argv)
    checks = doctor.run_checks(args.repo, os.environ)
    print("\n".join([doctor.summary(checks), *doctor.render(checks)]))
    return doctor.exit_code(checks)


if __name__ == "__main__":
    raise SystemExit(main())
