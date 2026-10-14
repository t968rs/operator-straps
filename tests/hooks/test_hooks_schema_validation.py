"""Subprocess coverage for the ``validate_pr_json_schema.py`` PostToolUse hook.

Every case runs the plugin hook as a child process with a JSON payload on stdin whose ``cwd`` names a
throwaway project built by ``make_project``. Artifact directories come from the project's harness
config; schemas resolve to the plugin copies unless the project pins its own.

Discriminator for the silent-no-op regression: ``test_hook_fires_on_invalid_plan`` asserts exit 1 AND a
SCHEMA VIOLATION line. A hook that never parses its payload exits 0 regardless of the target.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from conftest import PLUGIN_ROOT

_HOOK_PY = PLUGIN_ROOT / "hooks" / "validate_pr_json_schema.py"

_VALID_PLAN = {
    "plan_id": "0001",
    "plan_created": "2026-04-15",
    "execution_model": "serial",
    "pr_attributes": [{"pr": 1, "branch": "feature/x", "base_branch": "main"}],
    "items": [{"id": "TST-1", "title": "test item", "action": "noop", "status": "PENDING", "evidence": ""}],
}

# plan_id violates ^[0-9]{4}$; item id "L01" violates ^[A-Z]{2,4}-[0-9.]+$
_INVALID_PLAN = {
    "plan_id": "L01",
    "plan_created": "2026-04-15",
    "execution_model": "serial",
    "items": [{"id": "L01", "title": "bad id", "action": "noop", "status": "PENDING", "evidence": ""}],
}


def _hook_env() -> Dict[str, str]:
    """Child env without debugger chatter or a stray project override."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _run_hook(
    payload: Optional[Dict[str, Any]], *, stdin: Optional[str] = None
) -> subprocess.CompletedProcess:
    text = stdin if stdin is not None else json.dumps(payload)
    return subprocess.run([sys.executable, str(_HOOK_PY)], input=text, capture_output=True, text=True,
                          env=_hook_env(), check=False)


def _write_payload(project: Path, target: Path) -> Dict[str, Any]:
    return {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(target)}}


def _write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_hook_implementation_file_exists() -> None:
    """A moved hook would make every subprocess case fail for the wrong reason."""
    assert _HOOK_PY.is_file(), f"hook implementation not found at {_HOOK_PY}"


def test_hook_silently_accepts_valid_plan(make_project) -> None:
    project = make_project()
    plan = _write(project / "docs" / "PLANS" / "0001_test_ActionPlan.json", _VALID_PLAN)
    result = _run_hook(_write_payload(project, plan))
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert result.stderr == ""


def test_hook_silently_skips_non_matching_path(make_project) -> None:
    project = make_project()
    src = project / "some_source.py"
    src.write_text("print('hi')", encoding="utf-8")
    result = _run_hook(_write_payload(project, src))
    assert result.returncode == 0
    assert result.stderr == ""


def test_hook_fires_on_invalid_plan(make_project) -> None:
    """Discriminator for the silent-no-op regression: exit 1 plus the specific violation."""
    project = make_project()
    bad = _write(project / "docs" / "PLANS" / "bad_ActionPlan.json", _INVALID_PLAN)
    result = _run_hook(_write_payload(project, bad))
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}; stderr={result.stderr!r}"
    assert "ActionPlan SCHEMA VIOLATION" in result.stderr
    assert "plan_id" in result.stderr


def test_hook_enforces_sibling_pr_attributes_schema(make_project) -> None:
    """A bad ``pr_attributes`` entry fails through the resolved prAttributes ref, never as a setup error."""
    project = make_project()
    bad = _write(project / "docs" / "PLANS" / "0001_ActionPlan.json",
                 dict(_VALID_PLAN, pr_attributes=[{"bogus": 1}]))
    result = _run_hook(_write_payload(project, bad))
    assert result.returncode == 1, f"stderr: {result.stderr!r}"
    assert "ActionPlan SCHEMA VIOLATION" in result.stderr
    assert "'pr' is a required property" in result.stderr


def test_hook_follows_configured_plans_dir(make_project) -> None:
    """``artifacts.plans`` relocates the plan target; the default directory stops matching."""
    project = make_project(config={"artifacts": {"plans": "planning/active"}})
    moved = _write(project / "planning" / "active" / "bad_ActionPlan.json", _INVALID_PLAN)
    default_dir = _write(project / "docs" / "PLANS" / "bad_ActionPlan.json", _INVALID_PLAN)
    assert _run_hook(_write_payload(project, moved)).returncode == 1
    assert _run_hook(_write_payload(project, default_dir)).returncode == 0


def test_hook_skips_paths_outside_artifact_dirs(make_project) -> None:
    """An archive directory beside the plans directory is not a target."""
    project = make_project()
    archived = _write(project / "docs" / "_plan_archive" / "old_ActionPlan.json", _INVALID_PLAN)
    result = _run_hook(_write_payload(project, archived))
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert "SCHEMA VIOLATION" not in result.stderr


def test_hook_skips_non_review_json_under_reviews_dir(make_project) -> None:
    project = make_project()
    catalog = _write(project / "docs" / "PR_REVIEWS" / "Catalog.json", {"entries": []})
    result = _run_hook(_write_payload(project, catalog))
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert "SCHEMA VIOLATION" not in result.stderr


def test_hook_uses_pinned_project_schema(make_project) -> None:
    """A schema pinned under ``schemas_dir`` replaces the plugin copy for validation."""
    strict = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "required": ["pinned"]}
    project = make_project(files={".claude/agent-schemas/ActionPlan.schema.json": strict})
    plan = _write(project / "docs" / "PLANS" / "0001_ActionPlan.json", _VALID_PLAN)
    result = _run_hook(_write_payload(project, plan))
    assert result.returncode == 1
    assert "pinned" in result.stderr


def test_hook_handles_empty_stdin_gracefully() -> None:
    """Empty stdin is not a hook failure."""
    assert _run_hook(None, stdin="").returncode == 0


def test_hook_handles_missing_file_path_key(make_project) -> None:
    result = _run_hook({"cwd": str(make_project()), "tool_input": {}})
    assert result.returncode == 0
    assert result.stderr == ""


def test_stop_payload_without_tool_input_is_noop(make_project) -> None:
    """A Stop event carries no ``tool_input``; the hook exits 0 without output."""
    payload = {
        "cwd": str(make_project()),
        "hook_event_name": "Stop",
        "session_id": "s",
        "stop_hook_active": False,
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_unusable_harness_config_exits_zero_with_notice(make_project) -> None:
    """An invalid ``harness.json`` is reported on stderr but never blocks the tool call."""
    project = make_project(config={"not_a_harness_key": True})
    plan = _write(project / "docs" / "PLANS" / "bad_ActionPlan.json", _INVALID_PLAN)
    result = _run_hook(_write_payload(project, plan))
    assert result.returncode == 0
    assert "harness config" in result.stderr


@pytest.mark.parametrize("blocked", ["jsonschema", "referencing"])
def test_missing_validator_warns_once_and_exits_zero(make_project, blocked: str) -> None:
    """Without the validator stack the hook warns on one stderr line instead of skipping silently."""
    project = make_project()
    bad = _write(project / "docs" / "PLANS" / "bad_ActionPlan.json", _INVALID_PLAN)
    shim = (f"import runpy, sys; sys.modules[{blocked!r}] = None; sys.argv = [{str(_HOOK_PY)!r}]; "
            f"runpy.run_path({str(_HOOK_PY)!r}, run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", shim], input=json.dumps(_write_payload(project, bad)),
                            capture_output=True, text=True, env=_hook_env(), check=False)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1
    assert f"{blocked} not installed" in lines[0]


def test_missing_git_exits_zero_with_notice(make_project, tmp_path: Path) -> None:
    """Without git on PATH the project lookup raises OSError; the hook reports it instead of crashing."""
    project = make_project()
    bad = _write(project / "docs" / "PLANS" / "bad_ActionPlan.json", _INVALID_PLAN)
    shim = tmp_path / "no_git_shim.py"
    shim.write_text(
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(PLUGIN_ROOT / 'lib')!r})\n"
        "import harness_lib.project as project\n"
        "def _no_git(base):\n"
        "    raise FileNotFoundError(2, 'git not found')\n"
        "project._git_toplevel = _no_git\n"
        f"sys.argv = [{str(_HOOK_PY)!r}]\n"
        f"runpy.run_path({str(_HOOK_PY)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(shim)], input=json.dumps(_write_payload(project, bad)),
                            capture_output=True, text=True, env=_hook_env(), check=False)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "Traceback" not in result.stderr
    assert "git not found" in result.stderr
