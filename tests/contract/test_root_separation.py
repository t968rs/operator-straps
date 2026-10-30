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

sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))
from _todo_helpers import config, todo_files  # noqa: E402

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


def _merge_build_args(root: Path) -> List[str]:
    """Seed a filled merge-message MD so ``merge_commit_msg.py build`` reaches its write."""
    folder = root / "docs" / "_commit_messages"
    folder.mkdir(parents=True, exist_ok=True)
    message = ["Merge PR #7 — t", "", "Prose.", "", "  - a.py: change", "",
               "Branch lineage: `main` -> `feature`"]
    md = ["- Title: t", "", "## Message", "", "```text", *message, "```", ""]
    (folder / "PR7_merge.md").write_text("\n".join(md), encoding="utf-8")
    return ["skills/merge-commit-msg/commands/merge_commit_msg.py", "--repo", str(root), "build", "7"]


def _runlog_args(root: Path) -> List[str]:
    """Seed one dated log so ``latest_runlog.py`` gets past its no-log exit."""
    folder = root / "logs" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run_2026-10-13_120000.txt").write_text("1 passed\n", encoding="utf-8")
    return ["skills/check-runlogs/commands/latest_runlog.py", "--repo", str(root), "--dir", "logs/runs"]


def _attach_args(root: Path, tmp: Path) -> List[str]:
    """A detached worktree of the case project with one new file, so ``attach_worktree.py`` moves it."""
    wt = tmp / "wt"
    git(root, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    (wt / "new.txt").write_text("new\n", encoding="utf-8")
    return ["skills/a-w/commands/attach_worktree.py", "feature", "--worktree", str(wt)]


def _todo_project(root: Path) -> Path:
    """Turn the case project into a configured todo_sync project (catalogs, stub, plans, snapshot)."""
    for rel, body in {**todo_files(), ".claude/harness.json": config(base_branch="main")}.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return root


def _todo_args(root: Path, *args: str) -> List[str]:
    return ["scripts/todo_sync.py", "--project", str(_todo_project(root)), *args]


def _split_args(root: Path, tmp: Path) -> List[str]:
    """A split of TODO-002 into two parts, its spec outside the project."""
    spec = tmp / "split_spec.json"
    spec.write_text(json.dumps({"parts": [{"title": "Part one"}, {"title": "Part two"}]}), encoding="utf-8")
    return _todo_args(root, "split", "2", "--spec", str(spec))


def _refresh_args(root: Path) -> List[str]:
    """A refresh after a hand edit that moves TODO-003 above TODO-002, so it rewrites the catalog."""
    args = _todo_args(root, "refresh")
    path = root / "docs/RESEARCH/_TODO/RepoToDo.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][2].update(severity=5, impact="silent_wrong_output")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return args


def _parallel2_plan_args(root: Path, tmp: Path) -> List[str]:
    """A one-lane plan file outside the project, for ``parallel2.py plan``."""
    lane = {"id": "task1", "kind": "implement", "model": "haiku", "tools": ["Read"], "files": ["src/a.py"]}
    plan = tmp / "parallel2_plan.json"
    plan.write_text(json.dumps({"lanes": [lane]}), encoding="utf-8")
    return ["scripts/parallel2.py", "--repo", str(root), "plan", str(plan)]


def _strap_new_args(root: Path) -> List[str]:
    """Seed a ``harness`` plugin source tree so ``strap.py new`` finds its plugin dir instead of refusing."""
    manifest = root / "plugins" / "harness" / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": "harness"}) + "\n", encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "plugin manifest")
    return ["scripts/strap.py", "--repo", str(root), "new", "demo-skill"]


def _plan_api_args(root: Path, tmp: Path) -> List[str]:
    """A script that loads and writes a plan through ``plan_api``, as a heredoc would."""
    fixture = REPO_ROOT / "tests" / "fixtures" / "plan_models" / "0001_Minimal_ActionPlan.json"
    target = root / "docs" / "PLANS" / fixture.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    script = tmp / "plan_api_write.py"
    script.write_text("\n".join([
        "import sys", f"sys.path.insert(0, {str(PLUGIN_ROOT / 'lib')!r})", "from harness_lib import plan_api",
        f"plan = plan_api.load('0001', repo={str(root)!r})",
        f"plan_api.write(plan.model_copy(update={{'execution_model': 'parallel'}}, deep=True), "
        f"repo={str(root)!r})", ""]), encoding="utf-8")
    return [str(script)]


CASES = {
    "plan new": lambda r, t: (["scripts/plan.py", "--repo", str(r), "new", "Root separation", "--no-fetch"],
                              None),
    "plan_api write": lambda r, t: (_plan_api_args(r, t), None),
    "parallel2 plan": lambda r, t: (_parallel2_plan_args(r, t), None),
    "todo_sync check": lambda r, t: (_todo_args(r, "check"), None),
    "todo_sync render": lambda r, t: (_todo_args(r, "render", "--date", "2026-10-21"), None),
    "todo_sync retire": lambda r, t: (_todo_args(r, "retire", "1"), None),
    "todo_sync split": lambda r, t: (_split_args(r, t), None),
    "todo_sync refresh": lambda r, t: (_refresh_args(r), None),
    "todo_sync session hook": lambda r, t: (["hooks/todo_sync_session.py"],
                                            {"cwd": str(_todo_project(r)), "source": "startup"}),
    "merge-commit-msg build": lambda r, t: (_merge_build_args(r), None),
    "commit capture --save": lambda r, t: (["scripts/branch_commit_msg.py", "--repo", str(r), "capture",
                                            "--save", "--no-fetch"], None),
    "pr_review config": lambda r, t: (["scripts/pr_review.py", "--repo", str(r), "config"], None),
    "phase4 second run": lambda r, t: (["skills/pr-review/commands/phase4_branch_safety.py", "--second-run",
                                        "7"], None),
    "check-runlogs": lambda r, t: (_runlog_args(r), None),
    "d-w": lambda r, t: (["skills/d-w/commands/new_worktree.py", "--repo", str(r), "--root",
                          str(t / "trees")], None),
    "a-w": lambda r, t: (_attach_args(r, t), None),
    "doctor": lambda r, t: (["skills/doctor/commands/doctor.py", "--repo", str(r)], None),
    "session rules hook": lambda r, t: (["hooks/session_rules.py"], {"cwd": str(r), "source": "startup"}),
    "schema hook": lambda r, t: (["hooks/validate_pr_json_schema.py"], _review_payload(r)),
    "stop hook": lambda r, t: (["hooks/check_phase5_sentinel.py"], {"cwd": str(r), "session_id": "s"}),
    "min-viz stop hook": lambda r, t: (["hooks/check_min_viz_sentinel.py"],
                                       {"cwd": str(r), "session_id": "s"}),
    "bash discipline hook": lambda r, t: (["hooks/bash_discipline.py"], {
        "cwd": str(r), "tool_name": "Bash", "tool_input": {"command": "git status && git log"}}),
    "strap new": lambda r, t: (_strap_new_args(r), None),
}

# Cases that must succeed: a refusal or a missing script would otherwise pass the snapshot check vacuously.
MUST_EXIT_ZERO = frozenset({"strap new", "plan new", "plan_api write"})


@pytest.mark.parametrize("name", sorted(CASES))
def test_entry_point_writes_nothing_under_plugins(name: str, project: Path, tmp_path: Path) -> None:
    script, payload = CASES[name](project, tmp_path)
    before = _snapshot()
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project, payload)
    if name in MUST_EXIT_ZERO:
        assert done.returncode == 0, f"{name} exited {done.returncode}:\n{done.stderr}"
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


def test_merge_build_lands_in_the_project(project: Path) -> None:
    script, _ = CASES["merge-commit-msg build"](project, project)
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project)
    assert done.returncode == 0, done.stderr
    written = project / "docs" / "_commit_messages" / "PR7_merge.txt"
    assert written.is_file()
    assert written.resolve().is_relative_to(project.resolve())


def test_parallel2_plan_lands_in_the_project(project: Path, tmp_path: Path) -> None:
    script, payload = CASES["parallel2 plan"](project, tmp_path)
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project, payload)
    assert done.returncode == 0, done.stderr
    state = project / ".claude/state/harness/parallel2/feature.json"
    assert state.is_file(), f"parallel2 plan did not write {state}:\n{done.stderr}"


TODO_OUTPUTS = {
    "todo_sync check": ".claude/state/harness/todo-sync/report.json",
    "todo_sync render": "docs/RESEARCH/_TODO/Snapshots/TODO_Snapshot_2026_1021.md",
    "todo_sync session hook": ".claude/state/harness/todo-sync/runner.json",
}


@pytest.mark.parametrize("name", sorted(TODO_OUTPUTS))
def test_todo_sync_output_lands_in_the_project(name: str, project: Path, tmp_path: Path) -> None:
    script, payload = CASES[name](project, tmp_path)
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project, payload)
    assert done.returncode == 0, done.stderr
    expected = project / TODO_OUTPUTS[name]
    assert expected.is_file(), f"{name} did not write {TODO_OUTPUTS[name]}:\n{done.stderr}"


def test_snapshot_notices_a_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "plugins"
    (fake / "p").mkdir(parents=True)
    monkeypatch.setattr(sys.modules[__name__], "PLUGINS", fake)
    before = _snapshot()
    (fake / "p" / "debris.json").write_text("{}", encoding="utf-8")
    assert _diff(before, _snapshot()) == ["+ p/debris.json"]
