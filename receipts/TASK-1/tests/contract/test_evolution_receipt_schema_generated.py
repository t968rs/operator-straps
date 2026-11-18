"""``DesignEvolutionCatalog.schema.json`` and ``Receipt.schema.json`` are generated from their models.

``tools/gen_plan_schema.py`` writes and checks all three plan schemas; the committed files equal the ones the
models generate, so the models stay the one definition of each shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness_lib import evolution_models as em
from harness_lib import receipt_models as rm


def _schemas(repo_root: Path) -> Path:
    return repo_root / "plugins" / "harness" / "schemas"


def test_the_committed_evolution_schema_equals_the_generated_one(repo_root: Path) -> None:
    path = _schemas(repo_root) / "catalogs" / "DesignEvolutionCatalog.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == em.schema_dict()


def test_the_committed_receipt_schema_equals_the_generated_one(repo_root: Path) -> None:
    path = _schemas(repo_root) / "Receipt.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == rm.schema_dict()


def test_the_generator_checks_all_three_schemas(repo_root: Path) -> None:
    done = subprocess.run([sys.executable, str(repo_root / "tools" / "gen_plan_schema.py"), "--check"],
                          capture_output=True, text=True, cwd=repo_root)
    assert done.returncode == 0, done.stdout + done.stderr
    for name in ("ActionPlan.schema.json", "DesignEvolutionCatalog.schema.json", "Receipt.schema.json"):
        assert name in done.stdout
