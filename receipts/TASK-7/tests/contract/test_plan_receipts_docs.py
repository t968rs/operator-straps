"""The rules and docs name the plan-bound DesignEvolution, receipts and the derived ``live.js`` sidecar.

The plan folder's own ``.gitignore`` (written by the driver) keeps ``live.js`` out of git, so no project adds
an ignore line; the README says what the sidecar is.
"""
from __future__ import annotations

import re
from pathlib import Path


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def test_the_harness_rules_bind_design_evolution_to_the_plan(plugin_root: Path) -> None:
    text = _flat(plugin_root / "rules" / "HARNESS_RULES.md")
    assert "`<artifacts.plans>/NNNN/DesignEvolution.json`" in text and "`evolution_api`" in text
    assert "beside the plan's research notes" not in text
    assert "a receipt that differs from its item cites" in text


def test_the_repo_readme_names_the_live_js_sidecar(repo_root: Path) -> None:
    assert "live.js" in _flat(repo_root / "README.md")


def test_the_schema_readme_names_the_receipt_schema(plugin_root: Path) -> None:
    text = _flat(plugin_root / "schemas" / "README.md")
    assert "Receipt.schema.json" in text and "DesignEvolutionCatalog.schema.json" in text
