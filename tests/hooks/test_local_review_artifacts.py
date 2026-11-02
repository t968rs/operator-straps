"""The schema hook (``validate_pr_json_schema.py``) on a local review file, ``LOCAL_<label>_<slug>.json``.

A local review lives beside the PR reviews under a non-digit prefix. The hook must still validate it and, at
closeout, clear the local key's Phase 5 sentinel; otherwise a local run's Stop gate would never lift.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from conftest import PLUGIN_ROOT
from harness_lib.config import load_config
from harness_lib.validation.artifact_names import is_review_artifact_name, phase5_sentinel_path

_HOOK_PY = PLUGIN_ROOT / "hooks" / "validate_pr_json_schema.py"
_SCHEMA = json.loads((PLUGIN_ROOT / "schemas" / "PR_REVIEW.schema.json").read_text(encoding="utf-8"))
_KEY = "local-1110-bubbles"
_NAME = "LOCAL_1110-bubbles_1110-bubbles.json"


def _check(**fields: Any) -> Dict[str, Any]:
    return {"result": "OK", **fields}


def _review() -> Dict[str, Any]:
    """A closeout-shaped local review: one minor issue resolved with SHA evidence, Phase 4 struct filled."""
    pre_fix = {
        "current_branch_check": _check(command="git rev-parse --abbrev-ref HEAD", stdout="1110-bubbles"),
        "branch_match_check": _check(assertion="CURRENT_BRANCH == headRefName", current_branch="1110-bubbles",
                                     head_ref_name="1110-bubbles", result="OK (match)"),
        "clean_tree_check": _check(command="git status --porcelain", stdout="", result="OK (empty)"),
        "sha_ancestry_check": _check(base_sha="0" * 40, head_sha="1" * 40, base_ancestor_command="c",
                                     base_ancestor_exit=0, head_ancestor_command="c", head_ancestor_exit=0,
                                     result="OK (both ancestors)"),
        "base_branch_recorded": _check(source="plan.json meta.base_branch", value="main",
                                       result="OK (recorded)"),
    }
    dispatch = {
        "pr_metadata_check": {"command": "git rev-parse HEAD", "stdout": "1" * 40,
                              "result": "OK (state=LOCAL)"},
        "structural_guards_check": {"applies": False, "command": "", "stdout_tail": "",
                                    "result": "SKIPPED (no CICD/test-infra paths in PR)"},
    }
    issue = {"id": "M1", "name": "Tidy", "file": "src/a.py", "summary": "s", "fix": ["f"]}
    return {
        "schema_ref": "PR_REVIEW.schema.json", "version": _SCHEMA.get("$version"), "pr": _KEY,
        "pr_title": "1110-bubbles", "branch": "1110-bubbles", "base_branch": "main", "base_sha": "0" * 40,
        "head_sha": "1" * 40, "review_date": "2026-11-02", "bubbles": [], "reviewers": ["overall"],
        "stats": {"additions": 1, "deletions": 0, "files_changed": 1},
        "verdict": "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled", "strengths": [],
        "issues": {"critical": [], "important": [], "minor": [issue]}, "bubble_up": [],
        "post_review_resolutions": [{"id": "M1", "status": "RESOLVED", "date": "2026-11-02",
                                     "evidence": "abc1234 (working-tree snapshot) - tidy"}],
        "verification_log": {"dispatch_time": dispatch, "pre_fix_time": pre_fix},
    }


def _run_hook(project: Path, target: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    payload = {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(target)}}
    return subprocess.run([sys.executable, str(_HOOK_PY)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, check=False)


def test_local_review_name_is_a_review_artifact() -> None:
    assert is_review_artifact_name(_NAME)
    assert is_review_artifact_name("0007_some_pr.json")
    assert not is_review_artifact_name("LOCAL.json")
    assert not is_review_artifact_name("LOCALX_a_b.json")
    assert not is_review_artifact_name("local_a_b.json")


def test_local_closeout_clears_the_local_sentinel(make_project) -> None:
    project = make_project()
    sentinel = phase5_sentinel_path(load_config(project), _KEY)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(_KEY, encoding="utf-8")
    target = project / "docs" / "PR_REVIEWS" / _NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_review()), encoding="utf-8")
    result = _run_hook(project, target)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Phase 5 sentinel cleared" in result.stderr
    assert not sentinel.exists()
