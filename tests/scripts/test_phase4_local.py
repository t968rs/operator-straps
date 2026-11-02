"""phase4_branch_safety.py with a local key (``local-<label>``): Phase 4 from the run's plan.json, no gh.

A local review has no PR, so the branch, base and SHAs the checks compare against come from the plan
``capture --range`` recorded. The checks and the emitted block keep the PR shape, so the review schema and
``build`` need nothing new; the second run arms the sentinel under the local key.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import List, Tuple

import pytest

from conftest import git

_STATE = "var/harness_state"
_SCRATCH = "build/review_runs"
_KEY = "local-1110-bubbles"
_RUN_ID = f"{_KEY}_20261102T120000Z"


@pytest.fixture(scope="module")
def phase4(plugin_root: Path) -> ModuleType:
    path = plugin_root / "skills" / "pr-review" / "commands" / "phase4_branch_safety.py"
    spec = importlib.util.spec_from_file_location("phase4_branch_safety_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_run(make_project) -> Tuple[Path, str, str]:
    """A project on branch 1110-bubbles one commit past main, with a captured local plan.

    Returns (root, base, head)."""
    config = {"state_dir": _STATE, "artifacts": {"scratch": _SCRATCH}, "base_branch": "main"}
    root = make_project(config=config,
                        files={".gitignore": "build/\nvar/\n"})
    git(root, "checkout", "-q", "-b", "1110-bubbles")
    (root / "src.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Feature(x): local change")
    base, head = git(root, "merge-base", "main", "HEAD"), git(root, "rev-parse", "HEAD")
    folder = root / _SCRATCH / _KEY
    (folder / _RUN_ID).mkdir(parents=True)
    (folder / "current").write_text(_RUN_ID + "\n", encoding="utf-8")
    plan = {"run_id": _RUN_ID, "pr": _KEY, "state": "LOCAL", "url": None, "first_sha": base, "last_sha": head,
            "meta": {"pr": _KEY, "pr_title": "1110-bubbles", "branch": "1110-bubbles", "base_branch": "main",
                     "base_sha": base, "head_sha": head}}
    (folder / _RUN_ID / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return root, base, head


def _no_gh(monkeypatch: pytest.MonkeyPatch, phase4: ModuleType) -> List[str]:
    calls: List[str] = []

    def fake(pr_number: str) -> dict:
        calls.append(pr_number)
        raise RuntimeError("gh called for a local key")

    monkeypatch.setattr(phase4, "_gh_pr_metadata", fake)
    return calls


def test_local_key_reads_plan_json_without_gh(make_project, phase4, monkeypatch, capsys) -> None:
    root, base, head = _local_run(make_project)
    monkeypatch.chdir(root)
    calls = _no_gh(monkeypatch, phase4)
    rc = phase4.main(["phase4_branch_safety.py", _KEY])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert calls == []
    block = json.loads(out.out)
    assert block["branch_match_check"]["head_ref_name"] == "1110-bubbles"
    assert block["sha_ancestry_check"]["base_sha"] == base
    assert block["sha_ancestry_check"]["head_sha"] == head
    assert block["base_branch_recorded"]["value"] == "main"
    assert "gh pr view" not in block["base_branch_recorded"]["source"]


@pytest.mark.parametrize("key", [_KEY, "local-Upper"])
def test_local_key_without_a_run_fails_without_gh(make_project, phase4, monkeypatch, capsys, key) -> None:
    config = {"state_dir": _STATE, "artifacts": {"scratch": _SCRATCH}, "base_branch": "main"}
    root = make_project(config=config, files={".gitignore": "build/\nvar/\n"})
    monkeypatch.chdir(root)
    calls = _no_gh(monkeypatch, phase4)
    rc = phase4.main(["phase4_branch_safety.py", key])
    out = capsys.readouterr()
    assert rc == 1, out.err
    assert "cannot read the local run" in out.err
    assert calls == []


def test_local_branch_mismatch_stops(make_project, phase4, monkeypatch, capsys) -> None:
    root, _, _ = _local_run(make_project)
    git(root, "checkout", "-q", "-b", "other")
    monkeypatch.chdir(root)
    _no_gh(monkeypatch, phase4)
    rc = phase4.main(["phase4_branch_safety.py", _KEY])
    out = capsys.readouterr()
    assert rc == 1
    assert out.out.strip(), out.err
    block = json.loads(out.out)
    assert block["branch_match_check"]["result"].startswith("STOP")


def test_local_second_run_arms_the_local_sentinel(make_project, phase4, monkeypatch, capsys) -> None:
    root, _, _ = _local_run(make_project)
    monkeypatch.chdir(root)
    _no_gh(monkeypatch, phase4)
    rc = phase4.main(["phase4_branch_safety.py", "--second-run", _KEY])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert (root / _STATE / "pr-review" / f".phase5_pending_{_KEY}").is_file()
