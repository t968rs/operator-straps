"""SessionStart hook ``hooks/todo_sync_session.py``: writes the runner pointer only, silently, fail-open."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import config, todo_files  # noqa: E402
from conftest import GIT_ENV, PLUGIN_ROOT  # noqa: E402

HOOK = PLUGIN_ROOT / "hooks" / "todo_sync_session.py"
STATE = Path(".claude") / "state" / "harness" / "todo-sync"


def _run(payload: Optional[object], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=60)


def test_writes_the_runner_pointer_and_nothing_else(make_project, tmp_path: Path) -> None:
    root = make_project(config(), files=todo_files())
    done = _run({"cwd": str(root), "hook_event_name": "SessionStart", "source": "startup"}, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert [p.name for p in (root / STATE).iterdir()] == ["runner.json"]
    pointer = json.loads((root / STATE / "runner.json").read_text(encoding="utf-8"))
    assert pointer["project"] == root.resolve().as_posix()
    assert Path(pointer["script"]) == PLUGIN_ROOT / "scripts" / "todo_sync.py"


def test_inactive_project_is_silent_and_writes_nothing(make_project, tmp_path: Path) -> None:
    root = make_project({})
    done = _run({"cwd": str(root)}, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert not (root / ".claude" / "state").exists()


def test_broken_config_fails_open(make_project, tmp_path: Path) -> None:
    root = make_project({"todo": {"top_n": 0}})
    done = _run({"cwd": str(root)}, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_unwritable_state_dir_fails_open(make_project, tmp_path: Path) -> None:
    cfg = config(state_dir="blocked/state")
    root = make_project(cfg, files={**todo_files(), "blocked": "a file where a folder belongs\n"})
    done = _run({"cwd": str(root)}, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_garbage_payload_fails_open(tmp_path: Path) -> None:
    done = _run("not json", tmp_path)
    assert (done.returncode, done.stdout) == (0, "")
    assert "Traceback" not in done.stderr
