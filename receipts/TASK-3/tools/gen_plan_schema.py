"""Write or check the plan schemas generated from the models of ``harness_lib``.

Usage: gen_plan_schema.py [--check]

Covers ``ActionPlan.schema.json`` (``plan_models``), ``catalogs/DesignEvolutionCatalog.schema.json``
(``evolution_models``) and ``Receipt.schema.json`` (``receipt_models``), all under ``plugins/harness/schemas/``.
Without an option each schema file is rewritten from its module's ``schema_text()``. With ``--check`` nothing is
written: each committed file is parsed and compared with its module's ``schema_dict()`` (parsed JSON, so line
endings never matter), and the exit code is 1 when any file drifts.

This is a repository tool, not a plugin driver: a consuming project never runs it (a project that pins the
schema drops the pin or copies the plugin's generated file), and the plugin directory stays read-only for
every driver.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "plugins" / "harness" / "schemas"
sys.path.insert(0, str(ROOT / "plugins" / "harness" / "lib"))


def _targets() -> List[Tuple[Path, ModuleType]]:
    from harness_lib import evolution_models, plan_models, receipt_models

    return [
        (SCHEMAS / "ActionPlan.schema.json", plan_models),
        (SCHEMAS / "catalogs" / "DesignEvolutionCatalog.schema.json", evolution_models),
        (SCHEMAS / "Receipt.schema.json", receipt_models),
    ]


def _drifted(path: Path, expected: dict) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")) != expected
    except (OSError, ValueError):
        return True


def _check(targets: List[Tuple[Path, ModuleType]]) -> int:
    status = 0
    for path, module in targets:
        if _drifted(path, module.schema_dict()):
            print(f"drift: {path.relative_to(ROOT).as_posix()} differs from the models; "
                  "run python tools/gen_plan_schema.py", file=sys.stderr)
            status = 1
        else:
            print(f"ok: {path.name} matches the models")
    return status


def _write(targets: List[Tuple[Path, ModuleType]]) -> int:
    for path, module in targets:
        path.write_text(module.schema_text(), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT).as_posix()}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="gen_plan_schema.py", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Compare the committed schemas; write nothing.")
    args = parser.parse_args(argv)
    targets = _targets()
    if args.check:
        return _check(targets)
    return _write(targets)


if __name__ == "__main__":
    sys.exit(main())
