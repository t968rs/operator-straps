"""qa_review_json.py B2: reviewer ``counts.findings`` must equal the sum of its severity counts."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

import pytest


@pytest.fixture(scope="module")
def qa(plugin_root: Path) -> ModuleType:
    target = plugin_root / "skills" / "pr-team" / "commands" / "qa_review_json.py"
    spec = importlib.util.spec_from_file_location("qa_review_json_b_checks", target)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(agent_id: str, findings: int, critical: int, important: int, minor: int) -> Dict[str, Any]:
    counts = {"findings": findings, "critical": critical, "important": important, "minor": minor}
    return {"agent_id": agent_id, "agent_role": "reviewer", "signal": "DONE", "counts": counts}


def _doc(critical: int = 0, important: int = 0, minor: int = 0) -> Dict[str, Any]:
    return {"issues": {
        "critical": [{}] * critical, "important": [{}] * important, "minor": [{}] * minor}}


PLAN = {"agents": [{"id": "rev_a"}, {"id": "rev_b"}]}


def test_consistent_counts_pass(qa: ModuleType) -> None:
    terminals = [_row("rev_a", 3, 1, 1, 1), _row("rev_b", 2, 0, 2, 0)]
    ok, msg = qa.check_b2_findings_count(_doc(1, 2, 1), PLAN, terminals)
    assert ok, msg


def test_inflated_findings_total_fails(qa: ModuleType) -> None:
    terminals = [_row("rev_a", 10, 0, 0, 0), _row("rev_b", 2, 0, 2, 0)]
    ok, msg = qa.check_b2_findings_count(_doc(0, 2, 0), PLAN, terminals)
    assert not ok
    assert "rev_a" in msg and "rev_b" not in msg


def test_deflated_findings_total_fails(qa: ModuleType) -> None:
    terminals = [_row("rev_a", 1, 1, 1, 1)]
    ok, msg = qa.check_b2_findings_count(_doc(1, 1, 1), PLAN, terminals)
    assert not ok
    assert "rev_a" in msg
