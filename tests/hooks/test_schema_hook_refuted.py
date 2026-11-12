"""``validate_pr_json_schema.py`` with REFUTED, BUBBLED and NOT_RESOLVED resolutions.

Layer 2 (``_incoherent``) exempts REFUTED / BUBBLED / NOT_RESOLVED resolutions while ``pre_fix_time`` is
pending, but a READY verdict or any other resolution there still blocks. Layer 3 (``_closeout_reason``)
counts only the other resolutions toward the SHA-evidence test, so an all-refuted review and a
refuted-plus-bubbled review clear the Phase 5 sentinel, while an id reopened by NOT_RESOLVED keeps it until
its fix lands. Every case runs the hook as a child process with a Write payload whose ``cwd`` is a
``make_project`` project, as the existing hook tests do.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

from conftest import PLUGIN_ROOT
from harness_lib.config import load_config
from harness_lib.validation.artifact_names import phase5_sentinel_path

_SCHEMA_FILE = PLUGIN_ROOT / "schemas" / "PR_REVIEW.schema.json"
_HOOK_PY = PLUGIN_ROOT / "hooks" / "validate_pr_json_schema.py"
_DATE = "2026-11-12"
_GUARDED = "src/a.py:3 is guarded by the length check at :2"


def _schema() -> dict:
    return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))


def _pending_literal() -> str:
    canonical = _schema()["properties"]["verification_log"]["oneOf"][1]
    return canonical["properties"]["pre_fix_time"]["oneOf"][0]["const"]


def _dispatch_time() -> Dict[str, object]:
    return {"pr_metadata_check": {"command": "gh pr view 1", "stdout": "{\"state\": \"OPEN\"}",
                                  "result": "OK (state=OPEN)"},
            "structural_guards_check": {"applies": False, "command": "", "stdout_tail": "",
                                        "result": "SKIPPED (no CICD/test-infra paths in PR)"}}


def _pre_fix_time() -> Dict[str, object]:
    return {
        "current_branch_check": {"command": "git rev-parse --abbrev-ref HEAD", "stdout": "b", "result": "OK"},
        "branch_match_check": {"assertion": "CURRENT_BRANCH == headRefName", "current_branch": "b",
                               "head_ref_name": "b", "result": "OK (match)"},
        "clean_tree_check": {"command": "git status --porcelain", "stdout": "", "result": "OK (empty)"},
        "sha_ancestry_check": {"base_sha": "0" * 40, "head_sha": "1" * 40, "base_ancestor_command": "c",
                               "base_ancestor_exit": 0, "head_ancestor_command": "c", "head_ancestor_exit": 0,
                               "result": "OK (both ancestors)"},
        "base_branch_recorded": {"source": "gh", "value": "main", "result": "OK (recorded)"},
    }


def _issue(issue_id: str) -> Dict[str, object]:
    return {"id": issue_id, "name": f"issue {issue_id}", "file": "src/a.py", "summary": f"s {issue_id}",
            "fix": [f"fix {issue_id}"]}


def _entry(issue_id: str, status: str, evidence: str = _GUARDED) -> Dict[str, str]:
    return {"id": issue_id, "status": status, "date": _DATE, "evidence": evidence}


def _review(pr: str, verdict: str, pending: bool, resolutions: List[Dict[str, str]],
            important: Sequence[str] = (), minor: Sequence[str] = ("M1", "M2")) -> Dict[str, object]:
    """A schema-valid review of PR ``pr``; ``pending`` keeps ``pre_fix_time`` as the Phase 4 placeholder."""
    return {
        "schema_ref": "PR_REVIEW.schema.json", "version": _schema()["$version"], "pr": pr, "pr_title": "t",
        "branch": "b", "base_branch": "main", "base_sha": "0" * 40, "head_sha": "1" * 40,
        "review_date": _DATE, "verdict": verdict,
        "stats": {"additions": 1, "deletions": 0, "files_changed": 1},
        "reviewers": ["runtime (opus)"], "bubbles": [], "strengths": [], "bubble_up": [],
        "issues": {"critical": [], "important": [_issue(i) for i in important],
                   "minor": [_issue(i) for i in minor]},
        "post_review_resolutions": resolutions,
        "verification_log": {"dispatch_time": _dispatch_time(),
                             "pre_fix_time": _pending_literal() if pending else _pre_fix_time()},
    }


def _hook_env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _run_hook(project: Path, data: Dict[str, object]) -> subprocess.CompletedProcess:
    """Write ``data`` as a review under the project's reviews directory and run the hook on it."""
    target = project / "docs" / "PR_REVIEWS" / "0001_refuted_review.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")
    payload = {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(target)}}
    return subprocess.run([sys.executable, str(_HOOK_PY)], input=json.dumps(payload), text=True,
                          capture_output=True, env=_hook_env(), check=False)


def _arm_sentinel(project: Path, pr: str) -> Path:
    sentinel = phase5_sentinel_path(load_config(project), pr)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(pr, encoding="utf-8")
    return sentinel


_NOT_READY = "NOT READY TO MERGE - minor findings pending Phase 5: M1, M2"


# --- Layer 2 -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("overrule", [None, "BUBBLED", "NOT_RESOLVED"])
def test_pending_review_with_overrule_entries_is_coherent(make_project, overrule: Optional[str]) -> None:
    resolutions = [_entry("M1", "REFUTED")]
    if overrule is not None:
        resolutions.append(_entry("M1", overrule, "the guard at :2 is dead code"))
    result = _run_hook(make_project(), _review("1", _NOT_READY, True, resolutions))
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "INCOHERENCE" not in result.stderr


def test_pending_review_with_another_resolution_stays_incoherent(make_project) -> None:
    resolutions = [_entry("M1", "REFUTED"), _entry("M1", "NOT_RESOLVED", "overruled"),
                   _entry("M2", "RESOLVED", "fixed inline")]
    result = _run_hook(make_project(), _review("1", _NOT_READY, True, resolutions))
    assert result.returncode == 1
    assert "PR_REVIEW INCOHERENCE" in result.stderr, result.stderr


def test_pending_review_with_a_ready_verdict_stays_incoherent(make_project) -> None:
    resolutions = [_entry("M1", "REFUTED"), _entry("M2", "REFUTED")]
    verdict = "READY TO MERGE - 2 of 2 findings resolved, 0 bubbled"
    result = _run_hook(make_project(), _review("1", verdict, True, resolutions))
    assert result.returncode == 1
    assert "PR_REVIEW INCOHERENCE" in result.stderr, result.stderr


# --- Layer 3 -------------------------------------------------------------------------------------------


_READY_ONE_BUBBLED = "READY TO MERGE - 1 of 2 findings resolved, 1 bubbled"


def _cleared(project: Path, sentinel: Path, data: Dict[str, object]) -> bool:
    """Run the hook on ``data``; True when it exits 0 and clears ``sentinel``."""
    result = _run_hook(project, data)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    return "Phase 5 sentinel cleared" in result.stderr and not sentinel.exists()


def _bubble_m1(data: Dict[str, object]) -> Dict[str, object]:
    data["bubbles"] = ["M1"]
    data["bubble_up"] = [{"id": "M1", "classification": "needs_follow_up", "reason": "follow-up"}]
    return data


def test_all_refuted_review_clears_the_sentinel(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "ALLREFUTED")
    data = _review("ALLREFUTED", "READY TO MERGE - 2 of 2 findings resolved, 0 bubbled", False,
                   [_entry("I1", "REFUTED"), _entry("M1", "REFUTED")], important=["I1"], minor=["M1"])
    assert _cleared(project, sentinel, data)


def test_refuted_and_bubbled_review_clears_the_sentinel(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "REFBUB")
    data = _review("REFBUB", _READY_ONE_BUBBLED, False, [_entry("I1", "REFUTED")],
                   important=["I1"], minor=["M1"])
    assert _cleared(project, sentinel, _bubble_m1(data))


def test_refutation_overruled_to_a_bubble_clears_the_sentinel(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "OVERBUB")
    resolutions = [_entry("I1", "REFUTED"), _entry("M1", "REFUTED"), _entry("M1", "BUBBLED", "dev call")]
    data = _review("OVERBUB", _READY_ONE_BUBBLED, False, resolutions, important=["I1"], minor=["M1"])
    assert _cleared(project, sentinel, _bubble_m1(data))


def test_refutation_overruled_to_a_fix_keeps_the_sentinel_until_the_fix(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "OVERFIX")
    reopened = [_entry("I1", "REFUTED"), _entry("M1", "REFUTED"), _entry("M1", "NOT_RESOLVED", "overruled")]
    data = _review("OVERFIX", "NOT READY TO MERGE - minor findings pending Phase 5: M1", False, reopened,
                   important=["I1"], minor=["M1"])
    assert not _cleared(project, sentinel, data)
    assert sentinel.exists()
    fixed = [*reopened, _entry("M1", "RESOLVED", "a9630b7 fixed the empty-list path")]
    data = _review("OVERFIX", "READY TO MERGE - 2 of 2 findings resolved, 0 bubbled", False, fixed,
                   important=["I1"], minor=["M1"])
    assert _cleared(project, sentinel, data)


def test_refutation_overruled_to_a_fix_after_a_bubble_keeps_the_sentinel(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "BUBFIX")
    reopened = [_entry("I1", "REFUTED"), _entry("M1", "REFUTED"), _entry("M1", "NOT_RESOLVED", "overruled")]
    data = _review("BUBFIX", "NOT READY TO MERGE - minor findings pending Phase 5: M1", False, reopened,
                   important=["I1"], minor=["M1"])
    data["bubble_up"] = [{"id": "M1", "classification": "needs_follow_up", "reason": "follow-up"}]
    assert not _cleared(project, sentinel, data)
    assert sentinel.exists()


def test_a_refuted_sha_evidence_does_not_clear_a_ready_review(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "REFSHA")
    resolutions = [_entry("I1", "REFUTED", "a9630b7 guards the empty list"),
                   _entry("M1", "RESOLVED", "pending fixer commit")]
    data = _review("REFSHA", "READY TO MERGE - 1 of 2 findings resolved, 0 bubbled, 1 refuted", False,
                   resolutions, important=["I1"], minor=["M1"])
    assert not _cleared(project, sentinel, data)
    assert sentinel.exists()


def test_refuted_entries_do_not_lift_the_sha_evidence_rule(make_project) -> None:
    project = make_project()
    sentinel = _arm_sentinel(project, "NOSHA")
    resolutions = [_entry("I1", "REFUTED"), _entry("M1", "RESOLVED", "pending fixer commit")]
    data = _review("NOSHA", "READY TO MERGE - 2 of 2 findings resolved, 0 bubbled", False, resolutions,
                   important=["I1"], minor=["M1"])
    assert not _cleared(project, sentinel, data)
    assert sentinel.exists()
