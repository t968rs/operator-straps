"""Write or check ``plugins/harness/schemas/SkillSpec.schema.json`` from ``strap_models.schema_text()``.

Usage: gen_skillspec_schema.py [--path PATH] [--check]

Without ``--check`` the schema text is written with LF endings and the exit code is 0. With ``--check`` the
file is never written: exit 0 when it equals the generated text after CRLF -> LF folding, exit 1 when it
differs or is missing (one ``problem:`` line on stderr). ``--path`` defaults to the committed schema,
resolved from this file's location.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIB = _REPO_ROOT / "plugins" / "harness" / "lib"
_DEFAULT_PATH = _REPO_ROOT / "plugins" / "harness" / "schemas" / "SkillSpec.schema.json"


def _generated() -> bytes:
    """The schema text as UTF-8 bytes; imports the model module after putting its library on ``sys.path``."""
    if str(_LIB) not in sys.path:
        sys.path.insert(0, str(_LIB))
    from harness_lib import strap_models

    return strap_models.schema_text().encode("utf-8")


def _check(path: Path, expected: bytes) -> int:
    """Exit code for ``--check``: 0 in sync, 1 on a missing or differing file."""
    if not path.is_file():
        print(f"problem: {path} is missing; run tools/gen_skillspec_schema.py", file=sys.stderr)
        return 1
    if path.read_bytes().replace(b"\r\n", b"\n") != expected:
        print(f"problem: {path} differs from schema_text(); run gen_skillspec_schema.py", file=sys.stderr)
        return 1
    return 0


def _write(path: Path, expected: bytes) -> int:
    path.write_bytes(expected)
    return 0


def _parse(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or check SkillSpec.schema.json.")
    parser.add_argument("--path", type=Path, default=_DEFAULT_PATH, help="schema file to write or check")
    parser.add_argument("--check", action="store_true", help="exit 1 when the file differs; never write")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse(argv)
    expected = _generated()
    if args.check:
        return _check(args.path, expected)
    return _write(args.path, expected)


if __name__ == "__main__":
    sys.exit(main())
