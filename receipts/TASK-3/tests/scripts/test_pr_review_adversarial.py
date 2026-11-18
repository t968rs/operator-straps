"""pr_review.py with ``capture -a`` / ``--adversarial``: the Workflow row, the pre-run refusals, refuter
``init``, ``merge`` over refutations, the REFUTED resolutions ``build`` writes, the developer overrules
(``refute`` adds REFUTED on any built review; ``unrefute --fix`` appends NOT_RESOLVED, ``unrefute --bubble``
appends BUBBLED and bubbles the id), and the Phase 5 commands that skip or refuse a refuted id. Runs on local
``--range`` reviews, so no gh stub is needed; review-local takes the same path.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List, Sequence, Set

import pytest

from conftest import FIXTURES, git
from harness_lib import review_merge as rmg
from harness_lib import review_models as rm

WALK_ROOTS = ()  # walks only the run folder inside a make_project repo
_FIXTURES = FIXTURES
_SCRATCH = "build/review_runs"
_BRANCH = "1200-adv"
_KEY = f"local-{_BRANCH}"
_CONFIG = {"base_branch": "main", "state_dir": "build/harness_state", "exclusions": "config/exclusions.json",
           "artifacts": {"scratch": _SCRATCH}}
_PRE_FIX = {
    "current_branch_check": {"command": "git rev-parse --abbrev-ref HEAD", "stdout": _BRANCH, "result": "OK"},
    "branch_match_check": {"assertion": "CURRENT_BRANCH == headRefName", "current_branch": _BRANCH,
                           "head_ref_name": _BRANCH, "result": "OK (match)"},
    "clean_tree_check": {"command": "git status --porcelain", "stdout": "", "result": "OK (empty)"},
    "sha_ancestry_check": {"base_sha": "x", "head_sha": "y", "base_ancestor_command": "c",
                           "base_ancestor_exit": 0, "head_ancestor_command": "c", "head_ancestor_exit": 0,
                           "result": "OK (both ancestors)"},
    "base_branch_recorded": {"source": "plan.json meta.base_branch", "value": "main",
                             "result": "OK (recorded)"},
}
_STOP = {**_PRE_FIX, "clean_tree_check": {"command": "git status --porcelain", "stdout": " M x",
                                          "result": "STOP (dirty)"}}
_EVIDENCE = "src/pkg/a.py:2 returns 2 as the change intends"
_ATTACK_TEXT = "test_a passes while f() returns 2"


def _finding(name: str, file: str, lines: str, **extra: object) -> Dict[str, object]:
    base = {"severity": "minor", "name": name, "summary": "s", "fix": ["f"], "file": file, "lines": lines,
            "fix_kind": "mechanical"}
    base.update(extra)
    return base


_WRONG = _finding("Wrong value", "src/pkg/a.py", "2")
_ATTACK = _finding("Breaks on call", "tests/test_a.py", "1", attack=_ATTACK_TEXT)


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("pr_review_adversarial_under_test",
                                                  plugin_root / "scripts" / "pr_review.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def _stamps(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh run id per capture, so two captures within one second never share a run directory."""
    counter = itertools.count()

    def fresh(key: object) -> str:
        return rm.run_id_for(key, f"20261112T0000{next(counter):02d}Z")

    monkeypatch.setattr(script, "run_id_for", fresh)


@pytest.fixture()
def repo(make_project) -> Path:
    """Branch 1200-adv one commit past main: a runtime file, a test and a doc changed."""
    exclusions = json.loads((_FIXTURES / "pr_review_exclusions.json").read_text(encoding="utf-8"))
    files = {"config/exclusions.json": exclusions, ".gitignore": "build/\n__pycache__/\n",
             "src/pkg/a.py": "def f():\n    return 1\n", "docs/a.md": "# A\n\nold\n"}
    root = make_project(config=_CONFIG, files=files, name="work")
    git(root, "checkout", "-q", "-b", _BRANCH)
    changed = {"src/pkg/a.py": "def f():\n    return 2\n", "tests/test_a.py": "def test_a():\n    pass\n",
               "docs/a.md": "# A\n\nnew\n"}
    for rel, text in changed.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Feature(a): local change")
    return root


# --- helpers ------------------------------------------------------------------------------------------------


def _run(script: ModuleType, repo: Path, *argv: str) -> int:
    return script.main(["--repo", str(repo), *argv])


def _capture(script: ModuleType, repo: Path, *extra: str) -> int:
    return _run(script, repo, "capture", "--range", "main..HEAD", "--no-fetch", "--roast", "no", *extra)


def _current(repo: Path) -> str:
    return (repo / _SCRATCH / _KEY / "current").read_text(encoding="utf-8").strip()


def _run_folder(repo: Path) -> Path:
    return repo / _SCRATCH / _KEY / _current(repo)


def _plan(repo: Path) -> Dict[str, object]:
    return json.loads((_run_folder(repo) / "plan.json").read_text(encoding="utf-8"))


def _draft_issue(repo: Path, name: str) -> Dict[str, object]:
    draft = json.loads((_run_folder(repo) / "draft.json").read_text(encoding="utf-8"))
    return next(i for i in draft["issues"] if i["name"] == name)


def _review(repo: Path) -> Dict[str, object]:
    return json.loads(next((repo / "docs" / "PR_REVIEWS").glob("LOCAL_*.json")).read_text(encoding="utf-8"))


def _issues(doc: Dict[str, object]) -> List[Dict[str, object]]:
    return [i for tier in rmg.TIERS for i in doc["issues"].get(tier, [])]  # type: ignore[union-attr]


def _id_of(doc: Dict[str, object], name: str) -> str:
    return next(str(i["id"]) for i in _issues(doc) if i["name"] == name)


def _phase4(script: ModuleType, monkeypatch: pytest.MonkeyPatch, rc: int, block: Dict[str, object]) -> None:
    monkeypatch.setattr(script, "run_phase4", lambda repo, pr: (rc, json.dumps(block), ""))


def _record_reviewers(repo: Path) -> None:
    """Every reviewer slot recorded; only the runtime slot holds a finding."""
    for slot in _plan(repo)["slots"]:
        found = [_WRONG] if slot["id"] == "runtime" else []
        rm.record(_KEY, slot["id"], found, ["clear seams"], repo=repo)


def _record_code(repo: Path) -> None:
    for code in _plan(repo)["adversarial"]["code"]:
        rm.record_attacks(_KEY, code["id"], [_ATTACK], repo=repo)


def _record_refutations(repo: Path, refuted: Sequence[str]) -> None:
    """One refutation entry per finding of each target; targets in ``refuted`` are refuted, others upheld."""
    for ref in _plan(repo)["adversarial"]["refute"]:
        report = rm.load_report(_run_folder(repo) / "findings" / f"{ref['target']}.json")
        verdict = "refuted" if ref["target"] in refuted else "upheld"
        entries = [{"key": rm.finding_key(f), "verdict": verdict, "evidence": _EVIDENCE}
                   for f in report.findings]
        rm.record_refutations(_KEY, ref["id"], ref["target"], entries, repo=repo)


def _round(script: ModuleType, repo: Path, refuted: Sequence[str] = ("runtime",)) -> None:
    """``capture -a``, then every reviewer, code refuter and refuter records."""
    assert _capture(script, repo, "-a") == 0
    _record_reviewers(repo)
    _record_code(repo)
    _record_refutations(repo, refuted)


def _merged(script: ModuleType, repo: Path, capsys: pytest.CaptureFixture,
            refuted: Sequence[str] = ("runtime",)) -> None:
    _round(script, repo, refuted)
    rc = _run(script, repo, "merge", "--pr", _KEY)
    assert rc == 0, capsys.readouterr().err


def _built(script: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
           refuted: Sequence[str] = ("runtime",)) -> Dict[str, object]:
    _merged(script, repo, capsys, refuted)
    _phase4(script, monkeypatch, 0, _PRE_FIX)
    rc = _run(script, repo, "build", "--pr", _KEY)
    assert rc == 0, capsys.readouterr().err
    return _review(repo)


def _workflow_lines(out: str) -> Dict[str, str]:
    """The ``scriptPath=`` and ``args=`` values of the printed Workflow row."""
    pairs = [line.split("=", 1) for line in out.splitlines() if line.startswith(("scriptPath=", "args="))]
    assert [key for key, _ in pairs] == ["scriptPath", "args"], out
    return dict(pairs)


# --- capture ------------------------------------------------------------------------------------------------


def test_only_the_flag_plans_an_adversarial_run(script, repo, capsys) -> None:
    assert _capture(script, repo) == 0
    out = capsys.readouterr().out
    plan = _plan(repo)
    assert "adversarial" not in plan and "adversarial_check" not in plan["dispatch_time"]
    assert "scriptPath=" not in out and "agent=harness:pr-reviewer" in out
    rc = _capture(script, repo, "--adversarial")
    assert rc == 0, capsys.readouterr().err
    assert "adversarial" in _plan(repo)


def test_capture_adversarial_prints_one_workflow_row_and_no_agent_rows(script, repo, capsys) -> None:
    rc = _capture(script, repo, "-a")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert not any(line.startswith("agent=") for line in out.splitlines())
    row = _workflow_lines(out)
    args, plan = json.loads(row["args"]), _plan(repo)
    assert args["run_key"] == _KEY and args["run_id"] == plan["run_id"] and args["guidance"] is None
    assert [r["id"] for r in args["reviewers"]] == [s["id"] for s in plan["slots"]]
    assert [c["id"] for c in args["code"]] == [c["id"] for c in plan["adversarial"]["code"]]
    assert [r["id"] for r in args["refute"]] == [r["id"] for r in plan["adversarial"]["refute"]]


def test_capture_adversarial_prints_a_script_copy_inside_the_project(script, repo, plugin_root,
                                                                    capsys) -> None:
    """The Workflow tool reads a scriptPath only from the working directory, never from the plugin root."""
    assert _capture(script, repo, "-a") == 0
    printed = Path(_workflow_lines(capsys.readouterr().out)["scriptPath"]).resolve()
    original = (plugin_root / rm.ADVERSARIAL_WORKFLOW).resolve()
    assert printed != original and not printed.is_relative_to(plugin_root.resolve())
    assert printed.is_relative_to(repo.resolve()) and printed.parent == _run_folder(repo).resolve()
    assert printed.read_bytes() == original.read_bytes()


def test_stage_workflow_script_refreshes_a_stale_copy_in_the_same_run(script, plugin_root,
                                                                     tmp_path) -> None:
    run = tmp_path / "run"
    copy = script.stage_workflow_script(run)
    copy.write_text("// stale\n", encoding="utf-8")
    again = script.stage_workflow_script(run)
    assert again == copy
    assert again.read_bytes() == (plugin_root / rm.ADVERSARIAL_WORKFLOW).read_bytes()
    assert sorted(p.name for p in run.iterdir()) == [copy.name]


def test_stage_workflow_script_turns_an_os_error_into_a_problem(script, tmp_path, monkeypatch) -> None:
    def locked(*_args: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(script.shutil, "copyfile", locked)
    with pytest.raises(script.CaptureError) as caught:
        script.stage_workflow_script(tmp_path / "run")
    assert any(problem.startswith("cannot stage ") for problem in caught.value.problems)


def test_capture_adversarial_records_the_refuter_plan(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0, capsys.readouterr().err
    plan = _plan(repo)
    adv = plan["adversarial"]
    assert [(c["id"], sorted(c["paths"]), c["model"]) for c in adv["code"]] == [
        ("adv_code", ["src/pkg/a.py", "tests/test_a.py"], "opus")]
    targets = [s["id"] for s in plan["slots"]] + ["adv_code"]
    assert [(r["id"], r["target"]) for r in adv["refute"]] == [(f"adv_refute_{t}", t) for t in targets]
    assert {r["model"] for r in adv["refute"]} == {rm.REFUTER_MODEL}


def test_capture_adversarial_writes_refuter_briefs_with_the_run_id(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0, capsys.readouterr().err
    run_id = str(_plan(repo)["run_id"])
    briefs = _run_folder(repo) / "briefs"
    code = (briefs / "adv_code.md").read_text(encoding="utf-8")
    refute = (briefs / "adv_refute_runtime.md").read_text(encoding="utf-8")
    assert "record_attacks_draft(" in code and f'run_id="{run_id}"' in code
    assert "record_refutations_draft(" in refute and f'run_id="{run_id}"' in refute


def test_capture_adversarial_logs_the_pending_check(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0, capsys.readouterr().err
    plan = _plan(repo)
    check = plan["dispatch_time"]["adversarial_check"]
    assert check["applies"] is True and check["workflow"] == rm.ADVERSARIAL_WORKFLOW
    assert check["code_slots"] == ["adv_code"]
    assert check["refute_slots"] == [r["id"] for r in plan["adversarial"]["refute"]]
    assert str(check["result"]).startswith("PENDING")


def test_capture_adversarial_refuses_a_missing_script_before_the_run(script, repo, monkeypatch,
                                                                     capsys) -> None:
    assert _capture(script, repo) == 0
    before = _current(repo)
    monkeypatch.setattr(script, "adversarial_script", lambda: repo / "no" / "adversarial-review.js")
    capsys.readouterr()
    rc = _capture(script, repo, "-a")
    err = capsys.readouterr().err
    assert rc == 1
    assert "adversarial-review.js" in err, err
    assert _current(repo) == before


def test_capture_adversarial_refuses_a_pinned_schema_without_refuted(script, repo, plugin_root,
                                                                     capsys) -> None:
    schema = json.loads((plugin_root / "schemas" / rmg.SCHEMA_NAME).read_text(encoding="utf-8"))
    status = schema["definitions"]["post_review_resolution"]["properties"]["status"]
    status["enum"] = [s for s in status["enum"] if s not in ("REFUTED", "BUBBLED", "NOT_RESOLVED")]
    pinned = repo / ".claude" / "agent-schemas" / rmg.SCHEMA_NAME
    pinned.parent.mkdir(parents=True, exist_ok=True)
    pinned.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    assert _capture(script, repo) == 0
    before = _current(repo)
    capsys.readouterr()
    rc = _capture(script, repo, "-a")
    err = capsys.readouterr().err
    assert rc == 1
    assert "agent-schemas" in err and rmg.SCHEMA_NAME in err, err
    assert _current(repo) == before


# --- refuter init -------------------------------------------------------------------------------------------


def _init(script: ModuleType, repo: Path, agent: str, run_id: str) -> int:
    return _run(script, repo, "init", "--pr", _KEY, "--agent", agent, "--run-id", run_id)


def test_init_prints_each_target_finding_under_its_key(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0
    _record_reviewers(repo)
    finding = rm.load_report(_run_folder(repo) / "findings" / "runtime.json").findings[0]
    capsys.readouterr()
    rc = _init(script, repo, "adv_refute_runtime", str(_plan(repo)["run_id"]))
    out = capsys.readouterr()
    assert rc == 0, out.err
    expected = f"[{rm.finding_key(finding)}] minor Wrong value src/pkg/a.py:2"
    assert expected in [line.strip() for line in out.out.splitlines()], out.out


def test_init_refuses_before_the_reviewer_recorded(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0
    capsys.readouterr()
    rc = _init(script, repo, "adv_refute_runtime", str(_plan(repo)["run_id"]))
    err = capsys.readouterr().err
    assert rc == 1
    assert "reviewer runtime has not recorded" in err, err


def test_init_refuses_a_run_id_that_is_not_current(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0
    _record_reviewers(repo)
    stale = f"{_KEY}_20200101T000000Z"
    capsys.readouterr()
    rc = _init(script, repo, "adv_refute_runtime", stale)
    err = capsys.readouterr().err
    assert rc == 1
    assert stale in err, err


def test_init_on_a_slot_without_findings_records_an_empty_report(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0
    _record_reviewers(repo)
    capsys.readouterr()
    rc = _init(script, repo, "adv_refute_overall", str(_plan(repo)["run_id"]))
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "no findings: done" in out.out
    report = rm.load_refutations(_run_folder(repo) / "refutations" / "overall.json")
    assert report.refutations == ()


# --- merge --------------------------------------------------------------------------------------------------


def test_merge_refuses_a_slot_without_refutations(script, repo, capsys) -> None:
    assert _capture(script, repo, "-a") == 0
    _record_reviewers(repo)
    _record_code(repo)
    capsys.readouterr()
    rc = _run(script, repo, "merge", "--pr", _KEY)
    err = capsys.readouterr().err
    assert rc == 1
    assert "adv_refute_runtime" in err, err
    assert not (_run_folder(repo) / "draft.json").exists()


def test_merge_refuses_a_refutation_of_an_older_report(script, repo, capsys) -> None:
    _round(script, repo)
    rm.record(_KEY, "runtime", [_finding("Other value", "src/pkg/a.py", "1")], repo=repo)
    capsys.readouterr()
    rc = _run(script, repo, "merge", "--pr", _KEY)
    err = capsys.readouterr().err
    assert rc == 1
    assert "refutation stale: rerun adv_refute_runtime" in err, err


def test_code_refuter_reports_and_refutations_are_not_strays(script, repo, capsys) -> None:
    _round(script, repo)
    run, plan = _run_folder(repo), _plan(repo)
    assert (run / "findings" / "adv_code.json").is_file()
    assert (run / "refutations" / "runtime.json").is_file()
    assert script.stray_reports(run, plan) == []
    assert ("adv_code", "adv_code (opus)") in [(s, c) for s, _, c in script.report_sources(plan)]


def test_block_reprints_a_refuter_report(script, repo, capsys) -> None:
    _round(script, repo)
    capsys.readouterr()
    finding = rm.load_report(_run_folder(repo) / "findings" / "runtime.json").findings[0]
    rc = _run(script, repo, "block", "--pr", _KEY, "--agent", "adv_refute_runtime")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert rm.finding_key(finding) in out.out and _EVIDENCE in out.out, out.out


def test_fold_refuses_an_adv_source_id(script, repo, tmp_path, capsys) -> None:
    assert _capture(script, repo) == 0
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps([_WRONG]), encoding="utf-8")
    capsys.readouterr()
    rc = _run(script, repo, "fold", "--pr", _KEY, "--source", "adv_code_extra", "--kind", "adhoc",
              "--findings", str(findings))
    err = capsys.readouterr().err
    assert rc == 1
    assert "adv_" in err, err


def test_merge_marks_the_refuted_issue_and_folds_the_attack(script, repo, capsys) -> None:
    _merged(script, repo, capsys)
    wrong, attack = _draft_issue(repo, "Wrong value"), _draft_issue(repo, "Breaks on call")
    assert _EVIDENCE in str(wrong["refuted"])
    assert "refuted" not in attack
    assert f"Attack: {_ATTACK_TEXT}" in str(attack["summary"])


# --- build --------------------------------------------------------------------------------------------------


def test_build_writes_refuted_resolutions_and_keeps_the_issue(script, repo, monkeypatch, capsys) -> None:
    doc = _built(script, repo, monkeypatch, capsys)
    wrong = _id_of(doc, "Wrong value")
    refuted = [r for r in doc["post_review_resolutions"] if r["status"] == "REFUTED"]
    assert [(r["id"], r["evidence"]) for r in refuted] == [(wrong, _EVIDENCE)]
    assert not any("refuted" in issue for issue in _issues(doc))


def test_build_completes_the_adversarial_check(script, repo, monkeypatch, capsys) -> None:
    doc = _built(script, repo, monkeypatch, capsys)
    check = doc["verification_log"]["dispatch_time"]["adversarial_check"]
    assert check["counts"] == {"findings_checked": 2, "findings_refuted": 1, "findings_upheld": 1,
                               "code_findings": 1}
    assert check["refuted_ids"] == [_id_of(doc, "Wrong value")] and check["unrefuted_ids"] == []
    assert str(check["result"]).startswith("OK")


def test_build_prints_each_refuted_id_with_its_evidence(script, repo, monkeypatch, capsys) -> None:
    _merged(script, repo, capsys)
    _phase4(script, monkeypatch, 0, _PRE_FIX)
    capsys.readouterr()
    rc = _run(script, repo, "build", "--pr", _KEY)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert f"refuted: {_id_of(_review(repo), 'Wrong value')} ({_EVIDENCE})" in out.out


def test_build_replace_after_a_phase4_stop_keeps_working(script, repo, monkeypatch, capsys) -> None:
    _merged(script, repo, capsys)
    _phase4(script, monkeypatch, 1, _STOP)
    assert _run(script, repo, "build", "--pr", _KEY) == 1
    assert any(r["status"] == "REFUTED" for r in _review(repo)["post_review_resolutions"])
    _phase4(script, monkeypatch, 0, _PRE_FIX)
    capsys.readouterr()
    rc = _run(script, repo, "build", "--pr", _KEY, "--replace")
    assert rc == 0, capsys.readouterr().err


def test_all_refuted_with_a_phase4_failure_holds_a_valid_review(script, repo, monkeypatch, capsys) -> None:
    _merged(script, repo, capsys, refuted=("runtime", "adv_code"))
    _phase4(script, monkeypatch, 1, _STOP)
    capsys.readouterr()
    rc = _run(script, repo, "build", "--pr", _KEY)
    err = capsys.readouterr().err
    assert rc == 1 and "phase4 first run rc 1" in err and "schema" not in err, err
    doc = _review(repo)
    assert str(doc["verdict"]).startswith("NOT READY TO MERGE - Phase 4 first run failed")
    assert [r["status"] for r in doc["post_review_resolutions"]] == ["REFUTED", "REFUTED"]


def test_only_an_adversarial_build_writes_the_check(script, repo, monkeypatch, capsys) -> None:
    assert _capture(script, repo) == 0
    for slot in _plan(repo)["slots"]:
        rm.record(_KEY, slot["id"], [], [], repo=repo)
    assert _run(script, repo, "merge", "--pr", _KEY) == 0
    _phase4(script, monkeypatch, 0, _PRE_FIX)
    assert _run(script, repo, "build", "--pr", _KEY) == 0
    assert "adversarial_check" not in _review(repo)["verification_log"]["dispatch_time"]
    _merged(script, repo, capsys)
    rc = _run(script, repo, "build", "--pr", _KEY, "--replace")
    assert rc == 0, capsys.readouterr().err
    assert "adversarial_check" in _review(repo)["verification_log"]["dispatch_time"]


# --- developer overrules: refute and unrefute ---------------------------------------------------------------


def _plain_built(script: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch,
                 capsys: pytest.CaptureFixture) -> Dict[str, object]:
    """A review built without ``-a``: one minor finding on the runtime slot."""
    assert _capture(script, repo) == 0
    _record_reviewers(repo)
    assert _run(script, repo, "merge", "--pr", _KEY) == 0
    _phase4(script, monkeypatch, 0, _PRE_FIX)
    rc = _run(script, repo, "build", "--pr", _KEY)
    assert rc == 0, capsys.readouterr().err
    return _review(repo)


def _latest(doc: Dict[str, object], issue_id: str) -> Dict[str, object]:
    return [r for r in doc.get("post_review_resolutions") or [] if r["id"] == issue_id][-1]


def _refute(script: ModuleType, repo: Path, issue_id: str, evidence: str = _EVIDENCE) -> int:
    return _run(script, repo, "refute", "--pr", _KEY, issue_id, "--evidence", evidence)


def _unrefute_fix(script: ModuleType, repo: Path, issue_id: str, *reason: str) -> int:
    return _run(script, repo, "unrefute", "--pr", _KEY, issue_id, "--fix", *reason)


def _assert_names_the_issue(out: str, issue_id: str) -> None:
    """``out`` names the "Wrong value" issue: its id, tier, name and ``file:lines``."""
    for needle in (issue_id, "minor", "Wrong value", "src/pkg/a.py:2"):
        assert needle in out, (needle, out)


def _planned_ids(repo: Path) -> Set[str]:
    store = json.loads((_run_folder(repo) / "waves.json").read_text(encoding="utf-8"))
    return {str(i) for wave in store["waves"] for fixer in wave for i in fixer["issue_ids"]}


def test_refute_on_a_review_without_the_flag_closes_the_id(script, repo, monkeypatch, capsys) -> None:
    doc = _plain_built(script, repo, monkeypatch, capsys)
    wrong = _id_of(doc, "Wrong value")
    assert str(doc["verdict"]).startswith("NOT READY TO MERGE")
    capsys.readouterr()
    rc = _refute(script, repo, wrong)
    out = capsys.readouterr()
    assert rc == 0, out.err
    _assert_names_the_issue(out.out, wrong)
    doc = _review(repo)
    assert (_latest(doc, wrong)["status"], _latest(doc, wrong)["evidence"]) == ("REFUTED", _EVIDENCE)
    assert str(doc["verdict"]).startswith("READY TO MERGE")
    assert "adversarial_check" not in doc["verification_log"]["dispatch_time"]


def test_refute_refuses_an_id_already_closed(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_plain_built(script, repo, monkeypatch, capsys), "Wrong value")
    assert _refute(script, repo, wrong) == 0, capsys.readouterr().err
    capsys.readouterr()
    rc = _refute(script, repo, wrong, "again")
    err = capsys.readouterr().err
    assert rc == 1 and wrong in err, err
    assert [r["status"] for r in _review(repo)["post_review_resolutions"]] == ["REFUTED"]


def test_refute_refuses_an_unknown_id(script, repo, monkeypatch, capsys) -> None:
    _plain_built(script, repo, monkeypatch, capsys)
    capsys.readouterr()
    rc = _refute(script, repo, "M9")
    err = capsys.readouterr().err
    assert rc == 1 and "M9" in err, err
    assert not _review(repo).get("post_review_resolutions")


def test_unrefute_fix_appends_not_resolved_and_reopens_the_id(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    capsys.readouterr()
    rc = _unrefute_fix(script, repo, wrong)
    out = capsys.readouterr()
    assert rc == 0, out.err
    _assert_names_the_issue(out.out, wrong)
    doc = _review(repo)
    assert (_latest(doc, wrong)["status"], _latest(doc, wrong)["evidence"]) == (
        "NOT_RESOLVED", "refutation overruled")
    assert wrong in rmg.undispositioned_ids(doc)
    assert doc["verification_log"]["dispatch_time"]["adversarial_check"]["unrefuted_ids"] == [wrong]
    assert "refuted" not in _draft_issue(repo, "Wrong value")


def test_unrefute_fix_hands_the_id_to_the_next_waves(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    assert _unrefute_fix(script, repo, wrong, "--reason", "line 2 is the bug") == 0, capsys.readouterr().err
    assert _latest(_review(repo), wrong)["evidence"] == "line 2 is the bug"
    rc = _run(script, repo, "waves", "--pr", _KEY)
    assert rc == 0, capsys.readouterr().err
    assert wrong in _planned_ids(repo)


def test_bubble_refute_then_unrefute_fix_hands_the_id_to_waves(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_plain_built(script, repo, monkeypatch, capsys), "Wrong value")
    rc = _run(script, repo, "bubble", "--pr", _KEY, wrong, "--classification", "out_of_scope",
              "--reason", "x")
    assert rc == 0, capsys.readouterr().err
    assert _refute(script, repo, wrong) == 0, capsys.readouterr().err
    assert _unrefute_fix(script, repo, wrong) == 0, capsys.readouterr().err
    doc = _review(repo)
    assert wrong in rmg.undispositioned_ids(doc) and wrong not in doc["bubbles"]
    assert any(b["id"] == wrong for b in doc["bubble_up"])
    rc = _run(script, repo, "waves", "--pr", _KEY)
    assert rc == 0, capsys.readouterr().err
    assert wrong in _planned_ids(repo)


def test_waves_ids_refuses_a_refuted_id_naming_unrefute(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    capsys.readouterr()
    rc = _run(script, repo, "waves", "--pr", _KEY, "--ids", wrong)
    err = capsys.readouterr().err
    assert rc == 1 and wrong in err and "unrefute" in err, err


def test_waves_ids_plans_an_id_after_unrefute_fix(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    assert _unrefute_fix(script, repo, wrong) == 0, capsys.readouterr().err
    rc = _run(script, repo, "waves", "--pr", _KEY, "--ids", wrong)
    assert rc == 0, capsys.readouterr().err
    assert _planned_ids(repo) == {wrong}


def test_unrefute_fix_moves_a_done_run_back_to_fix(script, repo, monkeypatch, capsys) -> None:
    doc = _built(script, repo, monkeypatch, capsys, refuted=("runtime", "adv_code"))
    capsys.readouterr()
    rc = _run(script, repo, "closeout", "--pr", _KEY)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "Phase 5 [done] | 0 issues resolved, 2 refuted |" in out.out, out.out
    assert _plan(repo)["phase"] == "done"
    rc = _unrefute_fix(script, repo, _id_of(doc, "Wrong value"))
    assert rc == 0, capsys.readouterr().err
    assert _plan(repo)["phase"] == "fix"


def test_unrefute_bubble_appends_bubbled_and_bubbles_the_id(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    rc = _run(script, repo, "unrefute", "--pr", _KEY, wrong, "--bubble", "--classification", "out_of_scope",
              "--reason", "needs a developer call")
    assert rc == 0, capsys.readouterr().err
    doc = _review(repo)
    assert (_latest(doc, wrong)["status"], _latest(doc, wrong)["evidence"]) == (
        "BUBBLED", "needs a developer call")
    assert wrong in doc["bubbles"]
    entry = next(b for b in doc["bubble_up"] if b["id"] == wrong)
    assert entry["classification"] == "out_of_scope"
    assert doc["verification_log"]["dispatch_time"]["adversarial_check"]["unrefuted_ids"] == [wrong]


@pytest.mark.parametrize("name, issue_id", [("Breaks on call", None), (None, "M9")],
                         ids=["not-refuted", "unknown"])
def test_unrefute_refuses_an_id_that_is_not_refuted_or_unknown(script, repo, monkeypatch, capsys, name,
                                                                issue_id) -> None:
    doc = _built(script, repo, monkeypatch, capsys)
    target = issue_id or _id_of(doc, name)
    capsys.readouterr()
    rc = _unrefute_fix(script, repo, target)
    err = capsys.readouterr().err
    assert rc == 1 and target in err, err
    assert [r["status"] for r in _review(repo)["post_review_resolutions"]] == ["REFUTED"]


def test_build_replace_refuses_after_a_developer_refute(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_plain_built(script, repo, monkeypatch, capsys), "Wrong value")
    assert _refute(script, repo, wrong) == 0, capsys.readouterr().err
    capsys.readouterr()
    rc = _run(script, repo, "build", "--pr", _KEY, "--replace")
    err = capsys.readouterr().err
    assert rc == 1 and "Phase 5 began" in err, err


def test_build_replace_refuses_after_a_developer_unrefute(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    assert _unrefute_fix(script, repo, wrong) == 0, capsys.readouterr().err
    capsys.readouterr()
    rc = _run(script, repo, "build", "--pr", _KEY, "--replace")
    err = capsys.readouterr().err
    assert rc == 1 and "Phase 5 began" in err, err


def test_build_replace_refuses_after_a_developer_refute_of_an_upheld_id(script, repo, monkeypatch,
                                                                        capsys) -> None:
    attack = _id_of(_built(script, repo, monkeypatch, capsys), "Breaks on call")
    assert _refute(script, repo, attack) == 0, capsys.readouterr().err
    capsys.readouterr()
    rc = _run(script, repo, "build", "--pr", _KEY, "--replace")
    err = capsys.readouterr().err
    assert rc == 1 and "Phase 5 began" in err, err


def test_refute_under_the_flag_adds_the_id_to_refuted_ids(script, repo, monkeypatch, capsys) -> None:
    doc = _built(script, repo, monkeypatch, capsys)
    wrong, attack = _id_of(doc, "Wrong value"), _id_of(doc, "Breaks on call")
    assert _refute(script, repo, attack) == 0, capsys.readouterr().err
    check = _review(repo)["verification_log"]["dispatch_time"]["adversarial_check"]
    assert check["refuted_ids"] == [wrong, attack] and check["unrefuted_ids"] == []


def test_refute_from_done_keeps_the_phase(script, repo, monkeypatch, capsys) -> None:
    attack = _id_of(_built(script, repo, monkeypatch, capsys), "Breaks on call")
    rc = _run(script, repo, "bubble", "--pr", _KEY, attack, "--classification", "out_of_scope",
              "--reason", "x")
    assert rc == 0, capsys.readouterr().err
    assert _run(script, repo, "closeout", "--pr", _KEY) == 0, capsys.readouterr().err
    assert _plan(repo)["phase"] == "done"
    assert _refute(script, repo, attack) == 0, capsys.readouterr().err
    assert _plan(repo)["phase"] == "done"
    assert _latest(_review(repo), attack)["status"] == "REFUTED"


# --- Phase 5 ------------------------------------------------------------------------------------------------


def _assert_unchanged_overrule(doc: Dict[str, object]) -> None:
    """A refused bubble or closeout left the built review's bubbles and resolutions as build wrote them."""
    assert doc["bubbles"] == []
    assert [r["status"] for r in doc["post_review_resolutions"]] == ["REFUTED"]


def test_bubble_refuses_a_refuted_id_naming_unrefute(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    rc = _run(script, repo, "bubble", "--pr", _KEY, wrong, "--classification", "out_of_scope",
              "--reason", "x")
    err = capsys.readouterr().err
    assert rc == 1
    assert "unrefute" in err, err
    _assert_unchanged_overrule(_review(repo))


def test_closeout_resolved_refuses_a_refuted_id_naming_unrefute(script, repo, monkeypatch, capsys) -> None:
    wrong = _id_of(_built(script, repo, monkeypatch, capsys), "Wrong value")
    (repo / "src" / "pkg" / "a.py").write_text("def f():\n    return 3\n", encoding="utf-8")
    rc = _run(script, repo, "closeout", "--pr", _KEY, "--resolved", f"{wrong}=returns 3 now")
    err = capsys.readouterr().err
    assert rc == 1
    assert "unrefute" in err, err
    _assert_unchanged_overrule(_review(repo))


def test_waves_plan_no_fixer_for_a_refuted_id(script, repo, monkeypatch, capsys) -> None:
    doc = _built(script, repo, monkeypatch, capsys)
    rc = _run(script, repo, "waves", "--pr", _KEY)
    assert rc == 0, capsys.readouterr().err
    store = json.loads((_run_folder(repo) / "waves.json").read_text(encoding="utf-8"))
    planned = {str(i) for wave in store["waves"] for fixer in wave for i in fixer["issue_ids"]}
    assert _id_of(doc, "Breaks on call") in planned
    assert _id_of(doc, "Wrong value") not in planned
