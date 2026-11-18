"""SessionStart hook ``hooks/remember_prune_session.py``: age-based ``.remember`` prune, silent, fail-open."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from conftest import PLUGIN_ROOT  # noqa: E402

HOOK = PLUGIN_ROOT / "hooks" / "remember_prune_session.py"
DAY = 86400


def _touch(path: Path, age_days: float, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def _run(payload: Optional[object], cwd: Path) -> subprocess.CompletedProcess:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, cwd=cwd, capture_output=True, text=True,
                          timeout=60)


def _seed(remember: Path) -> dict:
    return {
        "old_done": _touch(remember / "today-2026-10-01.done.md", 20),
        "new_done": _touch(remember / "today-2026-11-01.done.md", 2),
        "live_today": _touch(remember / "today-2026-11-03.md", 40),
        "old_tar": _touch(remember / "logs" / "logs-2026-08-30.tar.gz", 60),
        "new_tar": _touch(remember / "logs" / "logs-2026-10-30.tar.gz", 5),
        "old_handoff": _touch(remember / "tmp" / "handoff-path.abc", 30),
        "new_handoff": _touch(remember / "tmp" / "handoff-path.def", 1),
        "bare_handoff": _touch(remember / "tmp" / "handoff-path", 90),
        "old_position": _touch(remember / "tmp" / "position.abc", 30),
        "state": _touch(remember / "tmp" / "last-save.json", 90),
        "rotated": _touch(remember / "archive-2026-09-01.md", 90),
        "core": _touch(remember / "core-memories.md", 90),
    }


def test_removes_only_stale_rule_matches(tmp_path: Path) -> None:
    remember = tmp_path / ".remember"
    files = _seed(remember)
    done = _run({"cwd": str(tmp_path)}, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    gone = {name for name, path in files.items() if not path.exists()}
    assert gone == {"old_done", "old_tar", "old_handoff", "old_position"}


def test_walks_up_from_a_subfolder(tmp_path: Path) -> None:
    remember = tmp_path / ".remember"
    old = _touch(remember / "today-2026-10-01.done.md", 20)
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    assert _run({"cwd": str(sub)}, tmp_path).returncode == 0
    assert not old.exists()


def test_hook_errors_log_is_trimmed_to_the_last_lines(tmp_path: Path) -> None:
    log = tmp_path / ".remember" / "logs" / "hook-errors.log"
    _touch(log, 0, "".join(f"line {n}\n" for n in range(500)))
    assert _run({"cwd": str(tmp_path)}, tmp_path).returncode == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert (len(lines), lines[0], lines[-1]) == (200, "line 300", "line 499")


def test_short_hook_errors_log_is_left_alone(tmp_path: Path) -> None:
    log = tmp_path / ".remember" / "logs" / "hook-errors.log"
    _touch(log, 0, "only\n")
    assert _run({"cwd": str(tmp_path)}, tmp_path).returncode == 0
    assert log.read_text(encoding="utf-8") == "only\n"


def test_project_without_remember_is_silent(tmp_path: Path) -> None:
    done = _run({"cwd": str(tmp_path)}, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert not (tmp_path / ".remember").exists()


def test_garbage_payload_fails_open(tmp_path: Path) -> None:
    done = _run("not json", tmp_path)
    assert (done.returncode, done.stdout) == (0, "")
    assert "Traceback" not in done.stderr
