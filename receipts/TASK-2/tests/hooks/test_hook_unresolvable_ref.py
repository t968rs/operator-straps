"""The schema hook reports a pinned schema whose ``$ref`` cannot be resolved, never a quiet setup error.

A project that pinned the draft-07 ``ActionPlan.schema.json`` still refers to ``prAttributes.schema.json``,
which the plugin no longer ships. Validation through that pin cannot happen, so the hook says so and blocks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from conftest import PLUGIN_ROOT

HOOK = PLUGIN_ROOT / "hooks" / "validate_pr_json_schema.py"
PLAN = {
    "plan_id": "0001", "plan_created": "2026-04-15", "execution_model": "serial",
    "pr_attributes": [{"pr": 1, "branch": "feature/x", "base_branch": "main"}],
    "items": [{"id": "TST-1", "title": "t", "action": "noop", "status": "PENDING", "evidence": ""}],
}
PINNED = {
    "$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
    "properties": {"pr_attributes": {"type": "array", "items": {"$ref": "prAttributes.schema.json"}}},
}


def _run(project: Path, target: Path) -> subprocess.CompletedProcess:
    payload = {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(target)}}
    env: Dict[str, Any] = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, check=False)


def test_a_pinned_schema_with_an_unresolvable_ref_blocks_and_names_both_files(make_project) -> None:
    project = make_project(files={".claude/agent-schemas/ActionPlan.schema.json": PINNED})
    plan = project / "docs" / "PLANS" / "0001_ActionPlan.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    result = _run(project, plan)
    assert result.returncode == 1, result.stderr
    assert "unresolvable" in result.stderr.lower()
    assert "prAttributes.schema.json" in result.stderr and "ActionPlan.schema.json" in result.stderr
    assert "setup error" not in result.stderr
