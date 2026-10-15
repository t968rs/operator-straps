"""Drivers and hooks write into the consuming project, never under the plugin.

An installed plugin lives in a versioned cache directory: anything written there is lost on update and
shared across projects. Each case runs one entry point as a subprocess from a throwaway project and
compares a snapshot of ``plugins/`` before and after.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from conftest import GIT_ENV, PLUGIN_ROOT, REPO_ROOT, git

PLUGINS = REPO_ROOT / "plugins"
Snapshot = Dict[str, Tuple[int, int]]


def _snapshot() -> Snapshot:
    """``relative path -> (size, mtime_ns)`` for every plugin file outside bytecode caches."""
    out: Snapshot = {}
    for path in PLUGINS.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            stat = path.stat()
            out[path.relative_to(PLUGINS).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return out


def _diff(before: Snapshot, after: Snapshot) -> List[str]:
    added = [f"+ {p}" for p in sorted(set(after) - set(before))]
    changed = [f"~ {p}" for p in sorted(set(after) & set(before)) if after[p] != before[p]]
    removed = [f"- {p}" for p in sorted(set(before) - set(after))]
    return added + changed + removed


def _run(argv: List[str], cwd: Path, payload: object = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    stdin = None if payload is None else json.dumps(payload)
    return subprocess.run([sys.executable, *argv], cwd=cwd, input=stdin, capture_output=True, text=True,
                          env=env, timeout=120)


@pytest.fixture()
def project(make_project) -> Path:
    """A project on a feature branch one commit ahead of ``main``."""
    root = make_project({"base_branch": "main"}, files={"src/a.py": "x = 1\n"})
    git(root, "checkout", "-q", "-b", "feature")
    (root / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "b")
    return root


def _review_payload(root: Path) -> dict:
    target = root / "docs" / "PR_REVIEWS" / "0001_Sample.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    return {"cwd": str(root), "hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(target)}, "tool_response": {}}


def _merge_body_args(root: Path) -> List[str]:
    """Seed the feature branch's commit-message TXT so ``merge_body.py`` reaches its write."""
    folder = root / "docs" / "_commit_messages"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "feature.txt").write_text("Feature(x): y\n", encoding="utf-8")
    return ["skills/merge-commit/commands/merge_body.py", "--repo", str(root)]


def _runlog_args(root: Path) -> List[str]:
    """Seed one dated log so ``latest_runlog.py`` gets past its no-log exit."""
    folder = root / "logs" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run_2026-10-13_120000.txt").write_text("1 passed\n", encoding="utf-8")
    return ["skills/check-runlogs/commands/latest_runlog.py", "--repo", str(root), "--dir", "logs/runs"]


CASES = {
    "merge-commit": lambda r, t: (_merge_body_args(r), None),
    "commit capture --save": lambda r, t: (["scripts/branch_commit_msg.py", "--repo", str(r), "capture",
                                            "--save", "--no-fetch"], None),
    "pr_review config": lambda r, t: (["scripts/pr_review.py", "--repo", str(r), "config"], None),
    "phase4 second run": lambda r, t: (["skills/pr-review/commands/phase4_branch_safety.py", "--second-run",
                                        "7"], None),
    "check-runlogs": lambda r, t: (_runlog_args(r), None),
    "d-w": lambda r, t: (["skills/d-w/commands/new_worktree.py", "--repo", str(r), "--root",
                          str(t / "trees")], None),
    "session rules hook": lambda r, t: (["hooks/session_rules.py"], {"cwd": str(r), "source": "startup"}),
    "schema hook": lambda r, t: (["hooks/validate_pr_json_schema.py"], _review_payload(r)),
    "stop hook": lambda r, t: (["hooks/check_phase5_sentinel.py"], {"cwd": str(r), "session_id": "s"}),
    "bash discipline hook": lambda r, t: (["hooks/bash_discipline.py"], {
        "cwd": str(r), "tool_name": "Bash", "tool_input": {"command": "git status && git log"}}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_entry_point_writes_nothing_under_plugins(name: str, project: Path, tmp_path: Path) -> None:
    script, payload = CASES[name](project, tmp_path)
    before = _snapshot()
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project, payload)
    changes = _diff(before, _snapshot())
    assert not changes, f"{name} wrote under plugins/ (rc={done.returncode}):\n" + "\n".join(changes)
    assert "Traceback" not in done.stderr, done.stderr


def test_commit_capture_lands_in_the_project(project: Path) -> None:
    script = PLUGIN_ROOT / "scripts" / "branch_commit_msg.py"
    done = _run([str(script), "--repo", str(project), "capture", "--save", "--no-fetch"], project)
    assert done.returncode == 0, done.stderr
    written = Path(done.stdout.strip().removeprefix("wrote ").strip())
    assert written.is_file()
    assert written.resolve().is_relative_to(project.resolve())


def test_merge_body_lands_in_the_project(project: Path) -> None:
    script, _ = CASES["merge-commit"](project, project)
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project)
    assert done.returncode == 0, done.stderr
    written = Path(done.stdout.strip())
    assert written.is_file()
    assert written.resolve().is_relative_to(project.resolve())


def test_snapshot_notices_a_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "plugins"
    (fake / "p").mkdir(parents=True)
    monkeypatch.setattr(sys.modules[__name__], "PLUGINS", fake)
    before = _snapshot()
    (fake / "p" / "debris.json").write_text("{}", encoding="utf-8")
    assert _diff(before, _snapshot()) == ["+ p/debris.json"]
