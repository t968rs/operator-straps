"""pr_review.py over a local commit range (the review-local skill): ``capture --range BASE..HEAD``.

A local run has no PR: capture synthesizes the metadata from git, records state ``LOCAL`` and keys the run
``local-<label>``; every later subcommand takes that key through ``--pr``. The review file is
``LOCAL_<label>_<slug>.json`` so the digit-prefix-means-PR convention of the review folder holds.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List, Optional, Sequence

import pytest

from conftest import git
from harness_lib import review_merge as rmg
from harness_lib import review_models as rm

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_SCRATCH = "build/review_runs"
_BRANCH = "1110-bubbles"
_KEY = f"local-{_BRANCH}"
_PLAN = "docs/plans/0012_ActionPlan.json"
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


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("pr_review_local_under_test", plugin_root / "scripts" /
                                                  "pr_review.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture()
def repo(make_project) -> Path:
    """Branch 1110-bubbles one commit past main: runtime, tests and docs paths changed."""
    exclusions = json.loads((_FIXTURES / "pr_review_exclusions.json").read_text(encoding="utf-8"))
    files = {"config/exclusions.json": exclusions, ".gitignore": "build/\n__pycache__/\n",
             "src/pkg/a.py": "def f():\n    return 1\n", "docs/a.md": "# A\n\nold\n", _PLAN: "{}\n"}
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


@pytest.fixture()
def gh_calls(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> List[Sequence[str]]:
    """Every ``run_gh`` call the driver makes; a local run must make none."""
    calls: List[Sequence[str]] = []

    def fake(repo: Path, args: Sequence[str]) -> str:
        calls.append(list(args))
        raise AssertionError(f"gh called: {args}")

    monkeypatch.setattr(script, "run_gh", fake)
    return calls


def _run(script: ModuleType, repo: Path, *argv: str) -> int:
    return script.main(["--repo", str(repo), *argv])


def _capture(script: ModuleType, repo: Path, *extra: str) -> int:
    return _run(script, repo, "capture", "--range", "main..HEAD", "--no-fetch", "--roast", "no", *extra)


def _run_folder(repo: Path, key: str = _KEY) -> Path:
    folder = repo / _SCRATCH / key
    return folder / (folder / "current").read_text(encoding="utf-8").strip()


def _plan(repo: Path, key: str = _KEY) -> Dict[str, object]:
    return json.loads((_run_folder(repo, key) / "plan.json").read_text(encoding="utf-8"))


def _merged(script: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch,
            findings: Optional[Dict[str, List[Dict[str, object]]]] = None) -> None:
    """Capture, record every slot (``findings`` per slot id, else empty), merge, and stub Phase 4 with a
    passing block."""
    assert _capture(script, repo) == 0
    for slot in _plan(repo)["slots"]:
        rm.record(_KEY, slot["id"], (findings or {}).get(slot["id"], []), ["clear seams"], repo=repo)
    assert _run(script, repo, "merge", "--pr", _KEY) == 0
    monkeypatch.setattr(script, "run_phase4", lambda repo, pr: (0, json.dumps(_PRE_FIX), ""))


def test_capture_range_makes_no_gh_call_and_prints_rows(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert gh_calls == []
    assert "agent=harness:pr-reviewer model=" in out.out
    assert f"PR: {_KEY}" in out.out


def test_capture_range_records_local_state_and_key(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo)
    assert rc == 0, capsys.readouterr().err
    plan = _plan(repo)
    assert plan["state"] == "LOCAL" and plan["pr"] == _KEY and plan["url"] is None
    assert plan["meta"]["branch"] == _BRANCH and plan["meta"]["base_branch"] == "main"
    assert plan["first_sha"] == git(repo, "merge-base", "main", "HEAD")
    assert plan["last_sha"] == git(repo, "rev-parse", "HEAD")


def test_capture_range_takes_an_explicit_local_key(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo, "--pr", "local-mine")
    assert rc == 0, capsys.readouterr().err
    assert _plan(repo, "local-mine")["pr"] == "local-mine"


def test_capture_range_refuses_a_numeric_key(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo, "--pr", "12")
    err = capsys.readouterr().err
    assert rc == 1
    assert "local-<label>" in err, err


@pytest.mark.parametrize("argv", [
    ["capture", "--pr", "local-x", "--no-fetch", "--roast", "no"],
    ["capture", "--no-fetch", "--roast", "no"],
], ids=["local-key-without-range", "no-key-no-range"])
def test_capture_without_range_refuses_before_gh(script, repo, gh_calls, capsys, argv) -> None:
    rc = _run(script, repo, *argv)
    err = capsys.readouterr().err
    assert rc == 1
    assert "--range BASE..HEAD" in err, err
    assert gh_calls == []


def test_capture_refuses_a_missing_plan_pointer(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo, "--plan", "docs/missing.json")
    err = capsys.readouterr().err
    assert rc == 1
    assert "--plan docs/missing.json: no such file" in err, err
    assert gh_calls == []


def test_capture_range_skips_the_fetch_for_a_local_run(script, repo, gh_calls, capsys) -> None:
    rc = _run(script, repo, "capture", "--range", "main..HEAD", "--roast", "no")
    err = capsys.readouterr().err
    assert rc == 0, err
    assert gh_calls == []


def test_local_run_folder_and_run_id_carry_the_key(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo)
    assert rc == 0, capsys.readouterr().err
    run_id = _run_folder(repo).name
    assert re.fullmatch(rf"{_KEY}_\d{{8}}T\d{{6}}Z", run_id), run_id
    assert rm.RUN_ID.match(run_id)
    assert rm.run_dir(_KEY, repo) == _run_folder(repo)


def test_reviewer_record_accepts_a_local_key(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo)
    assert rc == 0, capsys.readouterr().err
    brief = (_run_folder(repo) / "briefs" / "overall.md").read_text(encoding="utf-8")
    assert f'record_draft("{_KEY}", "overall"' in brief
    rm.record(_KEY, "overall", [], ["clear seams"], repo=repo)
    assert (_run_folder(repo) / "findings" / "overall.json").is_file()


def test_build_writes_the_local_review_file(script, repo, gh_calls, monkeypatch, capsys) -> None:
    _merged(script, repo, monkeypatch)
    rc = _run(script, repo, "build", "--pr", _KEY)
    out = capsys.readouterr()
    assert rc == 0, out.err
    target = repo / "docs" / "PR_REVIEWS" / f"LOCAL_{_BRANCH}_{rmg.slugify_title(_BRANCH)}.json"
    assert target.is_file(), out.out
    assert json.loads(target.read_text(encoding="utf-8"))["pr"] == _KEY


def test_build_reports_a_local_straggler(script, repo, gh_calls, monkeypatch, capsys) -> None:
    _merged(script, repo, monkeypatch)
    stray = repo / "docs" / "PR_REVIEWS" / f"LOCAL_{_BRANCH}_old.json"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("{}", encoding="utf-8")
    rc = _run(script, repo, "build", "--pr", _KEY)
    err = capsys.readouterr().err
    assert rc == 1
    assert f"straggler review file docs/PR_REVIEWS/LOCAL_{_BRANCH}_old.json" in err, err


def test_plan_pointer_reaches_every_brief(script, repo, gh_calls, capsys) -> None:
    rc = _capture(script, repo, "--plan", _PLAN)
    assert rc == 0, capsys.readouterr().err
    briefs = sorted((_run_folder(repo) / "briefs").glob("*.md"))
    assert briefs
    for brief in briefs:
        assert f"Plan: {_PLAN}" in brief.read_text(encoding="utf-8"), brief.name


def test_fold_from_gh_review_refused_on_a_local_run(script, repo, gh_calls, capsys) -> None:
    assert _capture(script, repo) == 0
    capsys.readouterr()
    rc = _run(script, repo, "fold", "--pr", _KEY, "--source", "ext", "--kind", "external",
              "--from-gh-review", "https://github.com/o/r/pull/1#pullrequestreview-1")
    err = capsys.readouterr().err
    assert rc == 1
    assert "--findings" in err, err
    assert gh_calls == []


_MINOR = {"severity": "minor", "name": "Tidy src/pkg/a.py", "summary": "s", "fix": ["f"],
          "file": "src/pkg/a.py", "lines": "1", "fix_kind": "mechanical"}


def test_waves_and_closeout_take_a_local_key(script, repo, gh_calls, monkeypatch, capsys) -> None:
    _merged(script, repo, monkeypatch, {"runtime": [_MINOR]})
    assert _run(script, repo, "build", "--pr", _KEY) == 0, capsys.readouterr().err
    assert _run(script, repo, "waves", "--pr", _KEY) == 0, capsys.readouterr().err
    brief = (_run_folder(repo) / "fix_briefs" / "w1_fix_1.md").read_text(encoding="utf-8")
    assert f'record_fixes_draft("{_KEY}", "w1_fix_1"' in brief
    (repo / "src/pkg/a.py").write_text("def f():\n    return 3\n", encoding="utf-8")
    rm.record_fixes(_KEY, "w1_fix_1", [{"id": "M1", "what": "tidied", "files": ["src/pkg/a.py"]}], repo=repo)
    assert _run(script, repo, "closeout", "--pr", _KEY) == 0, capsys.readouterr().err
    target = repo / "docs" / "PR_REVIEWS" / f"LOCAL_{_BRANCH}_{rmg.slugify_title(_BRANCH)}.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert [r["id"] for r in doc["post_review_resolutions"]] == ["M1"]
    assert gh_calls == []


@pytest.mark.parametrize("detach, end", [(True, "HEAD"), (False, "HEAD~1")],
                         ids=["detached-checkout", "non-branch-end-on-a-branch"])
def test_capture_range_refuses_a_head_on_no_branch(script, repo, gh_calls, capsys, detach, end) -> None:
    git(repo, "commit", "-q", "--allow-empty", "-m", "Chore(a): later commit")
    if detach:
        git(repo, "checkout", "-q", "--detach")
    rc = _run(script, repo, "capture", "--range", f"main..{end}", "--no-fetch", "--roast", "no")
    err = capsys.readouterr().err
    assert rc == 1
    assert "is on no local branch" in err, err


def test_build_refuses_the_head_ancestry_waiver_on_a_local_key(script, repo, gh_calls, monkeypatch,
                                                              capsys) -> None:
    _merged(script, repo, monkeypatch)
    rc = _run(script, repo, "build", "--pr", _KEY, "--waive-head-ancestry")
    err = capsys.readouterr().err
    assert rc == 1
    assert "rerun capture --range" in err, err
