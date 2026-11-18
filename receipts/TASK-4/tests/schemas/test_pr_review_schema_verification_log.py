"""Guard tests pinning the PR_REVIEW.schema.json verification_log oneOf contract and the hook layers.

Three shapes are accepted by the schema:
  (1) skipped advisory: {"skipped": true, "reason": "..."}
  (2) canonical nested: {"dispatch_time": {...}, "pre_fix_time": "pending..." | {...}}
  (3) legacy flat: at least one of current_branch_check / pr_metadata_check /
      branch_match_check / clean_tree_check / sha_ancestry_check at the top level.

New review JSONs MUST use (1) or (2). Shape (3) exists only to keep pre-contract
artifacts validating.

Hook cases run the plugin's ``validate_pr_json_schema.py`` as a subprocess with a payload whose ``cwd``
is a ``make_project`` project; review files and Phase 5 sentinels live inside that project.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import jsonschema
import pytest

from conftest import PLUGIN_ROOT
from harness_lib.config import load_config
from harness_lib.validation import id_handling as refs
from harness_lib.validation.artifact_names import phase5_sentinel_path
from harness_lib.validation.pr_json_validation import IssueTabulationError

_SCHEMA_FILE = PLUGIN_ROOT / "schemas" / "PR_REVIEW.schema.json"
_HOOK_PY = PLUGIN_ROOT / "hooks" / "validate_pr_json_schema.py"


def _load_schema() -> dict:
    return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))


_PR_REVIEW_VERSION = _load_schema().get("$version")


def _pending_literal() -> str:
    """Return the pre_fix_time pending sentinel exactly as the schema's const defines it."""
    canonical = _load_schema()["properties"]["verification_log"]["oneOf"][1]
    return canonical["properties"]["pre_fix_time"]["oneOf"][0]["const"]


def _minimal_valid_envelope() -> dict:
    """Return a PR_REVIEW JSON skeleton minus verification_log; tests fill that in."""
    return {
        "schema_ref": "PR_REVIEW.schema.json",
        "version": _PR_REVIEW_VERSION,
        "pr": 1,
        "pr_title": "test",
        "branch": "test-branch",
        "base_branch": "main",
        "base_sha": "0" * 40,
        "head_sha": "1" * 40,
        "review_date": "2026-05-05",
        "bubbles": ["C2"],
        "reviewers": ["test"],
        "stats": {"additions": 0, "deletions": 0, "files_changed": 0},
        "verdict": "READY TO MERGE",
        "strengths": [],
        "issues": {"critical": [], "important": [], "minor": []},
        "bubble_up": [],
    }


def _dispatch_time(pr_stdout: str = None) -> Dict[str, Any]:
    stdout = pr_stdout if pr_stdout is not None else (
        '{"number": 1, "title": "test", "headRefName": "test-branch", "baseRefName": "main", "state": "OPEN"}'
    )
    return {
        "pr_metadata_check": {
            "command": "gh pr view 1 --json number,title,headRefName,baseRefName,state",
            "stdout": stdout,
            "result": "OK (state=OPEN)",
        },
        "structural_guards_check": {
            "applies": False,
            "command": "",
            "stdout_tail": "",
            "result": "SKIPPED (no CICD/test-infra paths in PR)",
        },
    }


def _full_pre_fix(branch_stdout: str = "test-branch", clean_stdout: str = "") -> Dict[str, Any]:
    return {
        "current_branch_check": {
            "command": "git -C $REPO rev-parse --abbrev-ref HEAD",
            "stdout": branch_stdout,
            "result": "OK",
        },
        "branch_match_check": {
            "assertion": "CURRENT_BRANCH == headRefName",
            "current_branch": "test-branch",
            "head_ref_name": "test-branch",
            "result": "OK (match)",
        },
        "clean_tree_check": {
            "command": "git -C $REPO status --porcelain",
            "stdout": clean_stdout,
            "result": "OK (empty)",
        },
        "sha_ancestry_check": {
            "base_sha": "0" * 40,
            "head_sha": "1" * 40,
            "base_ancestor_command": "git merge-base --is-ancestor " + ("0" * 40) + " HEAD",
            "base_ancestor_exit": 0,
            "head_ancestor_command": "git merge-base --is-ancestor " + ("1" * 40) + " HEAD",
            "head_ancestor_exit": 0,
            "result": "OK (both ancestors)",
        },
        "base_branch_recorded": {
            "source": "gh pr view 1 --json baseRefName --jq .baseRefName",
            "value": "main",
            "result": "OK (recorded)",
        },
    }


def _validate_with_log(verification_log: Dict[str, Any]) -> None:
    data = _minimal_valid_envelope()
    data["verification_log"] = verification_log
    jsonschema.validate(data, _load_schema())


# ---------------------------------------------------------------------------
# Schema shape (Layer 1)
# ---------------------------------------------------------------------------


def test_skipped_shape_validates():
    _validate_with_log({"skipped": True, "reason": "catalog only"})


def test_canonical_nested_with_pending_string_validates():
    _validate_with_log({"dispatch_time": _dispatch_time(), "pre_fix_time": _pending_literal()})


def test_canonical_nested_with_full_pre_fix_block_validates():
    _validate_with_log({"dispatch_time": _dispatch_time(), "pre_fix_time": _full_pre_fix()})


def test_legacy_flat_shape_still_validates():
    """Pre-2026-05 JSONs use a flat structure; backward compat must hold."""
    _validate_with_log({"current_branch_check": {"result": "OK"}, "pr_metadata_check": {"result": "OK"}})


@pytest.mark.parametrize("log", [
    pytest.param({"skipped": True, "reason": "test", "extra_field": "not allowed"}, id="skipped_extra_keys"),
    pytest.param({"skipped": False, "reason": "test"}, id="skipped_false"),
    pytest.param({"pre_fix_time": "<pending>"}, id="canonical_missing_dispatch_time"),
    pytest.param({"dispatch_time": {"structural_guards_check": {}}, "pre_fix_time": "<pending>"},
                 id="canonical_missing_pr_metadata_check"),
    pytest.param({"dispatch_time": {"pr_metadata_check": {}, "structural_guards_check": {}},
                  "pre_fix_time": "pending"}, id="pre_fix_time_wrong_literal"),
    pytest.param({}, id="empty_object"),
])
def test_invalid_verification_log_shapes_fail(log: Dict[str, Any]):
    """Shapes matching none of the three accepted forms are rejected."""
    if log.get("pre_fix_time") == "<pending>":
        log = {**log, "pre_fix_time": _pending_literal()}
    with pytest.raises(jsonschema.ValidationError):
        _validate_with_log(log)


def test_schema_rejects_pr_metadata_check_stdout_OK():
    """The 'no stub' contract is enforced: stdout='OK' fails validation."""
    with pytest.raises(jsonschema.ValidationError):
        _validate_with_log(
            {"dispatch_time": _dispatch_time(pr_stdout="OK"), "pre_fix_time": _pending_literal()}
        )


def test_schema_rejects_current_branch_check_stdout_OK():
    """current_branch_check.stdout='OK' is invalid (git rev-parse never emits 'OK')."""
    with pytest.raises(jsonschema.ValidationError):
        _validate_with_log(
            {"dispatch_time": _dispatch_time(), "pre_fix_time": _full_pre_fix(branch_stdout="OK")}
        )


def test_schema_rejects_clean_tree_check_stdout_OK():
    """clean_tree_check.stdout='OK' is invalid (git status --porcelain never emits 'OK')."""
    with pytest.raises(jsonschema.ValidationError):
        _validate_with_log(
            {"dispatch_time": _dispatch_time(), "pre_fix_time": _full_pre_fix(clean_stdout="OK")}
        )


def test_schema_accepts_clean_tree_empty_stdout():
    """Empty stdout in clean_tree_check IS valid: the empty string is the affirmative clean-tree claim."""
    _validate_with_log({"dispatch_time": _dispatch_time(), "pre_fix_time": _full_pre_fix(clean_stdout="")})


# ---------------------------------------------------------------------------
# Hook runners
# ---------------------------------------------------------------------------


def _hook_env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _run_payload(payload: Dict[str, Any]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_HOOK_PY)], input=json.dumps(payload), text=True,
                          capture_output=True, env=_hook_env(), check=False)


def _run_hook(project: Path, target_file: Path) -> subprocess.CompletedProcess:
    """Invoke the PostToolUse hook with a Write payload for ``target_file``."""
    return _run_payload(
        {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(target_file)}}
    )


def _run_hook_bash(project: Path, command: str) -> subprocess.CompletedProcess:
    """Invoke the PostToolUse hook with a Bash-shaped payload (command, no file_path)."""
    return _run_payload({"cwd": str(project), "tool_name": "Bash", "tool_input": {"command": command}})


def _write_review(project: Path, name: str, data: dict) -> Path:
    target = project / "docs" / "PR_REVIEWS" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")
    return target


def _arm_sentinel(project: Path, pr) -> Path:
    sentinel = phase5_sentinel_path(load_config(project), pr)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(str(pr), encoding="utf-8")
    return sentinel


def _envelope_with_canonical_pending() -> dict:
    """Envelope whose canonical verification_log still carries the pending pre_fix_time
    (Layer 2 reachable)."""
    data = _minimal_valid_envelope()
    data["verification_log"] = {"dispatch_time": _dispatch_time(), "pre_fix_time": _pending_literal()}
    return data


def _envelope_with_canonical_full_pre_fix() -> dict:
    """Envelope with a complete pre_fix_time (Phase 4 done): Layers 1 and 2 pass, Layer 3 is reached."""
    data = _minimal_valid_envelope()
    data["verification_log"] = {"dispatch_time": _dispatch_time(), "pre_fix_time": _full_pre_fix()}
    return data


def _resolved_resolutions() -> list:
    return [{"id": "C1", "status": "RESOLVED", "date": "2026-05-06", "evidence": "abc1234 fixed in commit"}]


# ---------------------------------------------------------------------------
# Layer 2: pending pre_fix_time incoherent with a progressed review
# ---------------------------------------------------------------------------


def test_hook_blocks_pending_pre_fix_with_ready_verdict(make_project):
    """READY TO MERGE verdict + pending pre_fix_time is incoherent: exit 1."""
    project = make_project()
    data = _envelope_with_canonical_pending()
    data["verdict"] = "READY TO MERGE — all critical issues resolved"
    result = _run_hook(project, _write_review(project, "0001_hook_test_ready.json", data))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "PR_REVIEW INCOHERENCE" in result.stderr
    assert "pre_fix_time" in result.stderr
    assert "phase4_branch_safety.py" in result.stderr


def test_hook_blocks_pending_pre_fix_with_post_review_resolutions(make_project):
    """post_review_resolutions populated + pending pre_fix_time is incoherent: exit 1."""
    project = make_project()
    data = _envelope_with_canonical_pending()
    data["verdict"] = "NOT READY TO MERGE — pending fixes"
    data["post_review_resolutions"] = [
        {
            "id": "M1",
            "status": "RESOLVED",
            "date": "2026-05-05",
            "evidence": "fixed inline during review session",
        }
    ]
    result = _run_hook(project, _write_review(project, "0001_hook_test_resolutions.json", data))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "PR_REVIEW INCOHERENCE" in result.stderr
    assert "post_review_resolutions" in result.stderr


# ---------------------------------------------------------------------------
# Layer 3: mechanical sentinel cleanup at Phase 5 closeout (never blocks)
# ---------------------------------------------------------------------------


def test_layer3_clears_sentinel_when_phase5_closeout_complete(make_project):
    """Closeout state (resolutions populated, verdict not NOT READY) + sentinel exists: deletion."""
    project = make_project()
    sentinel = _arm_sentinel(project, "L3CLEAR")
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "L3CLEAR"
    data["verdict"] = "READY TO MERGE -- all critical resolved"
    data["post_review_resolutions"] = _resolved_resolutions()
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_clear.json", data))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Phase 5 sentinel cleared" in result.stderr
    assert "L3CLEAR" in result.stderr
    assert not sentinel.exists()


def test_layer3_reads_sentinel_under_configured_state_dir(make_project):
    """The sentinel cleared is the one under the project's configured ``state_dir``."""
    project = make_project(config={"state_dir": "var/harness"})
    sentinel = _arm_sentinel(project, "CFG")
    assert sentinel.parent == project / "var" / "harness" / "pr-review"
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "CFG"
    data["post_review_resolutions"] = _resolved_resolutions()
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_cfg.json", data))
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists()


def test_layer3_no_op_when_no_sentinel_exists(make_project):
    """Closeout JSON but no matching sentinel: exit 0 silent, nothing to clean."""
    project = make_project()
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "NOSENT"
    data["verdict"] = "READY TO MERGE -- all resolved"
    data["post_review_resolutions"] = _resolved_resolutions()
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_nosent.json", data))
    assert result.returncode == 0
    assert "Phase 5 sentinel cleared" not in result.stderr


def test_layer3_preserves_sentinel_when_no_sha_evidence(make_project):
    """Resolutions populated but no SHA-shaped evidence: the race-closing gate keeps the sentinel."""
    project = make_project()
    sentinel = _arm_sentinel(project, "NOSHA")
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "NOSHA"
    data["verdict"] = "READY TO MERGE -- all critical resolved"
    data["post_review_resolutions"] = [
        {"id": "C1", "status": "RESOLVED", "date": "2026-05-06", "evidence": "pending fixer commit"}
    ]
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_nosha.json", data))
    assert result.returncode == 0
    assert "Phase 5 sentinel cleared" not in result.stderr
    assert sentinel.exists(), "Layer 3 must preserve sentinel until SHA-shaped evidence appears"


def test_layer3_preserves_sentinel_when_resolutions_empty(make_project):
    """Empty post_review_resolutions: closeout incomplete, sentinel preserved."""
    project = make_project()
    sentinel = _arm_sentinel(project, "EMPTYRES")
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "EMPTYRES"
    data["verdict"] = "READY TO MERGE -- nothing to fix"
    data["post_review_resolutions"] = []
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_emptyres.json", data))
    assert result.returncode == 0
    assert "Phase 5 sentinel cleared" not in result.stderr
    assert sentinel.exists()


def _dispositioned_issue(id_: str) -> dict:
    """A schema-valid issue item (id/name/summary/fix/file)."""
    return {"id": id_, "name": f"issue {id_}", "file": "src/example.py", "summary": f"detail for {id_}",
            "fix": [f"fix {id_}"]}


def test_layer3_clears_sentinel_when_all_issues_dispositioned_via_bubbles(make_project):
    """Bubble-only closeout clears the sentinel even with a NOT READY verdict and no SHA evidence."""
    project = make_project()
    sentinel = _arm_sentinel(project, "ALLBUBBLED")
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "ALLBUBBLED"
    data["verdict"] = "NOT READY TO MERGE -- I1 bubbled for developer decision"
    data["issues"] = {"critical": [], "important": [_dispositioned_issue("I1")],
                      "minor": [_dispositioned_issue("M1")]}
    data["post_review_resolutions"] = []
    data["bubbles"] = ["I1", "M1"]
    data["bubble_up"] = [
        {"id": "I1", "classification": "architectural_ambiguity", "reason": "dev decision"},
        {"id": "M1", "classification": "needs_follow_up", "reason": "follow-up"},
    ]
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_allbubbled.json", data))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Phase 5 sentinel cleared" in result.stderr
    assert "ALLBUBBLED" in result.stderr
    assert not sentinel.exists()


def test_layer3_preserves_sentinel_when_issues_partially_dispositioned(make_project):
    """NOT READY verdict with an undispositioned issue (M2): the bubble-accounted path must not clear."""
    project = make_project()
    sentinel = _arm_sentinel(project, "PARTIAL")
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "PARTIAL"
    data["verdict"] = "NOT READY TO MERGE -- M2 still open"
    data["issues"] = {"critical": [], "important": [],
                      "minor": [_dispositioned_issue("M1"), _dispositioned_issue("M2")]}
    data["post_review_resolutions"] = []
    data["bubbles"] = ["M1"]
    data["bubble_up"] = [{"id": "M1", "classification": "needs_follow_up", "reason": "follow-up"}]
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_partial.json", data))
    assert result.returncode == 0
    assert "Phase 5 sentinel cleared" not in result.stderr
    assert sentinel.exists(), "sentinel must persist while any issue is undispositioned"


def test_layer3_preserves_sentinel_when_verdict_still_not_ready(make_project):
    """NOT READY TO MERGE verdict: closeout incomplete even with resolutions; sentinel preserved."""
    project = make_project()
    sentinel = _arm_sentinel(project, "STILLNR")
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = "STILLNR"
    data["verdict"] = "NOT READY TO MERGE -- C2 still open"
    data["post_review_resolutions"] = _resolved_resolutions()
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_stillnr.json", data))
    assert result.returncode == 0
    assert "Phase 5 sentinel cleared" not in result.stderr
    assert sentinel.exists()


def test_layer3_uses_pr_value_verbatim_for_sentinel_filename(make_project):
    """An integer pr field 42 clears the sentinel named ``.phase5_pending_42``."""
    project = make_project()
    sentinel = _arm_sentinel(project, 42)
    data = _envelope_with_canonical_full_pre_fix()
    data["pr"] = 42
    data["verdict"] = "READY TO MERGE"
    data["post_review_resolutions"] = _resolved_resolutions()
    result = _run_hook(project, _write_review(project, "0001_hook_test_layer3_intpr.json", data))
    assert result.returncode == 0
    assert "Phase 5 sentinel cleared" in result.stderr
    assert "42" in result.stderr
    assert not sentinel.exists()


# ---------------------------------------------------------------------------
# Issue-count tabulation (validate_issue_counts): accounting is by ID-SET
# MEMBERSHIP across post_review_resolutions, the transient `bubbles` array,
# and the `bubble_up` ledger.
#   * READY verdict: every issue id MUST be accounted for (else exit 1).
#   * any verdict: an ORPHAN disposition id is always a defect (exit 1).
#   * NOT READY with no orphans: partial or zero disposition is legitimate.
#   * clean review (no issues): exit 0; ActionPlan exempt entirely.
# ---------------------------------------------------------------------------


def _issue(issue_id: str) -> dict:
    return {"id": issue_id, "name": "x", "file": "a.py", "summary": "s", "fix": ["f"]}


def _resolution(issue_id: str) -> dict:
    return {"id": issue_id, "status": "RESOLVED", "date": "2026-06-25", "evidence": f"{issue_id}.py:1"}


def _closeout_envelope() -> dict:
    """READY closeout envelope (full pre_fix, no stray bubble) for tabulation tests."""
    data = _envelope_with_canonical_full_pre_fix()
    data["bubbles"] = []
    data["verdict"] = "READY TO MERGE — all resolved"
    return data


def _open_envelope() -> dict:
    """NOT-READY open-review envelope (full pre_fix) for intermediate-state tests."""
    data = _envelope_with_canonical_full_pre_fix()
    data["bubbles"] = []
    data["verdict"] = "NOT READY TO MERGE — open issues"
    return data


def _tabulate(make_project, data: dict, name: str) -> subprocess.CompletedProcess:
    project = make_project()
    return _run_hook(project, _write_review(project, name, data))


def test_issue_counts_coherent_closeout_passes(make_project):
    """READY + every issue resolved: exit 0."""
    data = _closeout_envelope()
    data["issues"] = {"critical": [], "important": [], "minor": [_issue("M1"), _issue("M2")]}
    data["post_review_resolutions"] = [_resolution("M1"), _resolution("M2")]
    result = _tabulate(make_project, data, "0001_tab_coherent.json")
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_issue_counts_bubbles_count_toward_accounting(make_project):
    """READY + a bubbled id counts as accounted for (1 resolved + 1 bubbled): exit 0."""
    data = _closeout_envelope()
    data["issues"] = {"critical": [], "important": [], "minor": [_issue("M1"), _issue("M2")]}
    data["post_review_resolutions"] = [_resolution("M1")]
    data["bubbles"] = ["M2"]
    result = _tabulate(make_project, data, "0001_tab_bubble.json")
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_issue_counts_bubble_up_counts_toward_accounting(make_project):
    """READY + an id in the bubble_up ledger (bubbles empty) is accounted for: exit 0."""
    data = _closeout_envelope()
    data["issues"] = {"critical": [], "important": [], "minor": [_issue("M1"), _issue("M2")]}
    data["post_review_resolutions"] = [_resolution("M1")]
    data["bubble_up"] = [{"id": "M2", "classification": "out_of_scope", "reason": "deferred"}]
    result = _tabulate(make_project, data, "0001_tab_bubbleup.json")
    assert result.returncode == 0, f"stderr={result.stderr!r}"


@pytest.mark.parametrize("issues, resolutions, envelope", [
    pytest.param(["M1", "M2", "M3"], ["M1"], _closeout_envelope, id="ready_unaccounted"),
    pytest.param(["M1"], [], _closeout_envelope, id="ready_undispositioned"),
    pytest.param(["M1", "M2"], ["M1", "M1"], _closeout_envelope, id="double_disposition_orphans_M2"),
    pytest.param(["M1"], ["M1", "M9"], _open_envelope, id="orphan_resolution_any_verdict"),
])
def test_issue_counts_violations_block(make_project, issues, resolutions, envelope):
    """Unaccounted ids under READY, or orphan dispositions under any verdict: exit 1."""
    data = envelope()
    data["issues"] = {"critical": [], "important": [], "minor": [_issue(i) for i in issues]}
    data["post_review_resolutions"] = [_resolution(r) for r in resolutions]
    result = _tabulate(make_project, data, "0001_tab_violation.json")
    assert result.returncode == 1, f"stderr={result.stderr!r}"
    assert "ISSUE COUNT VIOLATION" in result.stderr


@pytest.mark.parametrize("issues, resolutions, envelope", [
    pytest.param(["M1"], [], _open_envelope, id="not_ready_nothing_dispositioned"),
    pytest.param(["M1", "M2"], ["M1"], _open_envelope, id="not_ready_partial"),
    pytest.param([], [], _closeout_envelope, id="clean_review_no_issues"),
])
def test_issue_counts_open_or_clean_reviews_pass(make_project, issues, resolutions, envelope):
    """A still-open review (no orphans) or a review with no issues: exit 0."""
    data = envelope()
    data["issues"] = {"critical": [], "important": [], "minor": [_issue(i) for i in issues]}
    data["post_review_resolutions"] = [_resolution(r) for r in resolutions]
    result = _tabulate(make_project, data, "0001_tab_pass.json")
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_issue_tabulation_error_is_well_formed():
    """str(exc) carries the message on one line (no leading blank) and names the id."""
    text = str(IssueTabulationError(unaccounted={"M2"}, orphans=set()))
    assert text, "str(exc) must be non-empty (super().__init__ was called)"
    assert not text.startswith("\n"), "message must not start with a blank line"
    assert "M2" in text, "message should name the unaccounted id(s)"


def test_refs_disposition_ids_unions_all_three_channels():
    report = {"post_review_resolutions": [{"id": "C1"}], "bubbles": ["M1"], "bubble_up": [{"id": "I2"}]}
    assert refs.disposition_ids(report) == {"C1", "M1", "I2"}


def test_refs_all_issues_dispositioned_true_when_fully_covered():
    report = {
        "issues": {"critical": [{"id": "I1"}], "important": [], "minor": [{"id": "M1"}]},
        "post_review_resolutions": [],
        "bubbles": ["I1"],
        "bubble_up": [{"id": "M1"}],
    }
    assert refs.all_issues_dispositioned(report) is True


def test_refs_all_issues_dispositioned_false_when_partial():
    report = {"issues": {"critical": [], "important": [], "minor": [{"id": "M1"}, {"id": "M2"}]},
              "bubbles": ["M1"]}
    assert refs.all_issues_dispositioned(report) is False


def test_refs_all_issues_dispositioned_false_when_no_issues():
    """Vacuous case: a review with zero issues is not a closeout to clear on."""
    assert refs.all_issues_dispositioned({"issues": {"critical": [], "important": [], "minor": []}}) is False


# ---------------------------------------------------------------------------
# Bash events: targets recovered from the command string
# ---------------------------------------------------------------------------


def test_bash_event_catches_malformed_review_json(make_project):
    """A Bash command referencing a malformed review JSON is caught (exit 1)."""
    project = make_project()
    data = _minimal_valid_envelope()
    del data["verdict"]
    target = _write_review(project, "0001_bash_written.json", data)
    result = _run_hook_bash(project, f'python -c "..."  # wrote {target}')
    assert result.returncode == 1, f"stderr={result.stderr!r}"
    assert "SCHEMA VIOLATION" in result.stderr


def test_bash_event_resolves_project_relative_token(make_project):
    """A relative artifact path in the command resolves against the payload project."""
    project = make_project()
    data = _minimal_valid_envelope()
    del data["verdict"]
    _write_review(project, "0001_bash_relative.json", data)
    result = _run_hook_bash(project, "cat docs/PR_REVIEWS/0001_bash_relative.json")
    assert result.returncode == 1, f"stderr={result.stderr!r}"


def test_bash_event_passes_for_valid_review_json(make_project):
    """A Bash command referencing a schema-valid review JSON exits 0."""
    project = make_project()
    data = _envelope_with_canonical_full_pre_fix()
    data["verdict"] = "READY TO MERGE -- clean"
    target = _write_review(project, "0001_bash_valid.json", data)
    result = _run_hook_bash(project, f"cat {target}")
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_bash_event_without_review_path_is_noop(make_project):
    """A Bash command touching no plan or review JSON exits 0 silently."""
    result = _run_hook_bash(make_project(), "echo hello && ls src")
    assert result.returncode == 0
    assert "SCHEMA VIOLATION" not in result.stderr
