"""PreToolUse hook ``hooks/guard_commit_txt.py``: denies hand edits of build-owned commit TXT files."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

from conftest import GIT_ENV, PLUGIN_ROOT
from harness_lib.commit_txt import CHANGE_ROUTE

HOOK = PLUGIN_ROOT / "hooks" / "guard_commit_txt.py"
REASON = "Commit-message TXT files are build output and final as saved."


def _run(stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=60)


def _call(root: Path, rel: str, tool: str = "Edit",
          cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(cwd or root),
               "tool_input": {"file_path": str(root / rel)}}
    return _run(json.dumps(payload), cwd or root)


def _denied(done: subprocess.CompletedProcess) -> bool:
    assert done.returncode == 0, done.stderr
    if not done.stdout.strip():
        return False
    out: Dict[str, Dict[str, str]] = json.loads(done.stdout)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert decision["permissionDecisionReason"].startswith(REASON)
    return True


def _project(make_project, config: Optional[dict] = None, folder: str = "docs/_commit_messages") -> Path:
    files = {f"{folder}/b.txt": "x\n", f"{folder}/feat/x.txt": "x\n", "docs/notes.txt": "x\n"}
    return make_project(config if config is not None else {}, files=files)


def test_edit_of_a_branch_txt_is_denied(make_project) -> None:
    assert _denied(_call(_project(make_project), "docs/_commit_messages/b.txt"))


def test_nested_branch_txt_is_denied(make_project) -> None:
    assert _denied(_call(_project(make_project), "docs/_commit_messages/feat/x.txt", tool="Write"))


def test_write_of_a_new_txt_in_a_new_subfolder_is_denied(make_project) -> None:
    assert _denied(_call(_project(make_project), "docs/_commit_messages/fix/new/y.txt", tool="Write"))


def test_merge_txt_write_is_denied_with_the_stdin_route(make_project) -> None:
    done = _call(_project(make_project), "docs/_commit_messages/PR12_merge.txt", tool="Write")
    assert _denied(done)
    reason = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "merge-commit-msg build" in reason and "stdin" in reason
    assert "_merge.txt" in reason
    assert "_merge.md" not in reason
    assert CHANGE_ROUTE not in reason


def test_skeleton_json_and_bak_are_allowed(make_project) -> None:
    root = _project(make_project)
    assert not _denied(_call(root, "docs/_commit_messages/b.json"))
    assert not _denied(_call(root, "docs/_commit_messages/b.txt.bak"))


def test_txt_outside_the_folder_is_allowed(make_project) -> None:
    assert not _denied(_call(_project(make_project), "docs/notes.txt"))


def test_configured_folder_is_guarded(make_project) -> None:
    root = _project(make_project, {"artifacts": {"commit_messages": "notes/commits"}}, folder="notes/commits")
    assert _denied(_call(root, "notes/commits/b.txt"))
    assert not _denied(_call(root, "docs/_commit_messages/b.txt"))


def test_file_project_wins_over_the_session_cwd(make_project, tmp_path: Path) -> None:
    root = _project(make_project)
    assert _denied(_call(root, "docs/_commit_messages/b.txt", cwd=tmp_path))


def test_deny_reason_puts_every_route_behind_the_developers_ask(make_project) -> None:
    done = _call(_project(make_project), "docs/_commit_messages/b.txt")
    reason = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "final as saved" in reason and reason.endswith(CHANGE_ROUTE)
    assert "skeleton" not in reason and "build" not in reason.split("final as saved")[1]


def test_garbage_payload_fails_open(tmp_path: Path) -> None:
    done = _run("not json", tmp_path)
    assert (done.returncode, done.stdout) == (0, "")


def test_payload_without_a_file_path_fails_open(tmp_path: Path) -> None:
    done = _run(json.dumps({"tool_name": "Edit", "tool_input": {}}), tmp_path)
    assert (done.returncode, done.stdout) == (0, "")


def test_relative_file_path_is_not_denied(make_project) -> None:
    root = _project(make_project)
    tool_input = {"file_path": "docs/_commit_messages/b.txt"}
    done = _run(json.dumps({"tool_name": "Edit", "cwd": str(root), "tool_input": tool_input}), root)
    assert (done.returncode, done.stdout) == (0, "")


def test_unusable_harness_config_never_blocks(make_project) -> None:
    root = make_project(files={"docs/_commit_messages/b.txt": "x\n", ".claude/harness.json": "{"})
    done = _call(root, "docs/_commit_messages/b.txt")
    assert (done.returncode, done.stdout) == (0, "")


def test_uppercase_branch_txt_is_denied(make_project) -> None:
    assert _denied(_call(_project(make_project), "docs/_commit_messages/B.TXT"))


def test_mixed_case_merge_txt_write_is_denied(make_project) -> None:
    assert _denied(_call(_project(make_project), "docs/_commit_messages/pr12_MERGE.txt", tool="Write"))
