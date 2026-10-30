"""Write or check ``ActionPlan.schema.json``, generated from the models of ``harness_lib.plan_models``.

Usage: gen_plan_schema.py [--check]

Without an option the schema file under ``plugins/harness/schemas/`` is rewritten from
``plan_models.schema_text()``. With ``--check`` nothing is written: the committed file is parsed and compared
with the generated schema (parsed JSON, so line endings never matter), and the exit code is 1 on any drift.

This is a repository tool, not a plugin driver: a consuming project never runs it (a project that pins the
schema drops the pin or copies the plugin's generated file), and the plugin directory stays read-only for
every driver.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "plugins" / "harness" / "schemas" / "ActionPlan.schema.json"
sys.path.insert(0, str(ROOT / "plugins" / "harness" / "lib"))


def _drifted(expected: dict) -> bool:
    try:
        return json.loads(SCHEMA.read_text(encoding="utf-8")) != expected
    except (OSError, ValueError):
        return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="gen_plan_schema.py", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Compare the committed schema; write nothing.")
    args = parser.parse_args(argv)
    from harness_lib import plan_models as pm

    if args.check:
        if _drifted(pm.schema_dict()):
            print(f"drift: {SCHEMA.relative_to(ROOT).as_posix()} differs from the models; "
                  "run python tools/gen_plan_schema.py", file=sys.stderr)
            return 1
        print("ok: ActionPlan.schema.json matches the models")
        return 0
    SCHEMA.write_text(pm.schema_text(), encoding="utf-8", newline="\n")
    print(f"wrote {SCHEMA.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
