"""Behavioral tests for the plugin's ``hooks/check_min_viz_sentinel.py`` Stop / SubagentStop hook.

Sentinels live at ``<project>/<state_dir>/pr-sum/.minviz_pending_<PR>``; the project comes from the payload
``cwd``. One assertion per test: no sentinel allows the stop; a hot sentinel blocks through the decision
contract; ``stop_hook_active`` breaks the loop; a stale sentinel is ignored with a notice; another session's
sentinel spares the stopping session, an unowned one or an unknown stopping session fails closed.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pytest

from conftest import PLUGIN_ROOT
from harness_lib.config import load_config
from harness_lib.min_viz_sentinel import arm, sentinel_dir_under, sentinel_path

_HOOK_PATH = PLUGIN_ROOT / "hooks" / "check_min_viz_sentinel.py"


def _load_hook():
    """Import the hook by absolute path; the hooks directory is not a package."""
    spec = importlib.util.spec_from_file_location("_test_check_min_viz_sentinel", str(_HOOK_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


@pytest.fixture
def sentinel_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "pr-sum"
    directory.mkdir(parents=True)
    return directory


def _write(directory: Path, pr: str, owner: str = "sess", age: int = 60, minimum: int = 3) -> Path:
    path = directory / f".minviz_pending_{pr}"
    path.write_text(f"{pr}\n{int(time.time()) - age}\n{owner}\n{minimum}\n", encoding="utf-8")
    return path


class TestFindArmed:
    def test_empty_directory(self, sentinel_dir: Path) -> None:
        assert hook.find_armed(sentinel_dir, "sess", []) is None

    def test_hot_sentinel_blocks_its_session(self, sentinel_dir: Path) -> None:
        path = _write(sentinel_dir, "41", minimum=4)
        armed = hook.find_armed(sentinel_dir, "sess", [])
        assert (armed.pr, armed.minimum, armed.path) == ("41", 4, path)

    def test_other_session_is_spared_with_a_notice(self, sentinel_dir: Path) -> None:
        _write(sentinel_dir, "41", owner="sess-owner")
        notices: List[str] = []
        assert hook.find_armed(sentinel_dir, "sess-other", notices) is None
        assert len(notices) == 1 and "PR #41" in notices[0] and "another session" in notices[0]

    def test_unowned_sentinel_blocks_every_session(self, sentinel_dir: Path) -> None:
        _write(sentinel_dir, "41", owner="")
        assert hook.find_armed(sentinel_dir, "anyone", []) is not None

    def test_unknown_stopping_session_fails_closed(self, sentinel_dir: Path) -> None:
        _write(sentinel_dir, "41", owner="sess-owner")
        assert hook.find_armed(sentinel_dir, None, []) is not None

    def test_stale_sentinel_is_ignored_with_a_notice(self, sentinel_dir: Path) -> None:
        _write(sentinel_dir, "41", age=25 * 3600)
        notices: List[str] = []
        assert hook.find_armed(sentinel_dir, "sess", notices) is None
        assert len(notices) == 1 and "stale" in notices[0]

    def test_mtime_stands_in_for_a_missing_timestamp(self, sentinel_dir: Path) -> None:
        (sentinel_dir / ".minviz_pending_41").write_text("41\n", encoding="utf-8")
        assert hook.find_armed(sentinel_dir, "sess", []) is not None
        old = time.time() - 25 * 3600
        os.utime(sentinel_dir / ".minviz_pending_41", (old, old))
        assert hook.find_armed(sentinel_dir, "sess", []) is None

    def test_first_hot_sentinel_in_sorted_order_wins(self, sentinel_dir: Path) -> None:
        _write(sentinel_dir, "200")
        _write(sentinel_dir, "100")
        assert hook.find_armed(sentinel_dir, "sess", []).pr == "100"

    def test_malformed_minimum_reads_as_zero(self, sentinel_dir: Path) -> None:
        stamp = int(time.time())
        (sentinel_dir / ".minviz_pending_41").write_text(f"41\n{stamp}\nsess\nmany\n", encoding="utf-8")
        assert hook.find_armed(sentinel_dir, "sess", []).minimum == 0


def _project(make_project: Callable[..., Path], session: str = "sess") -> Tuple[Path, Path]:
    project = make_project()
    return project, arm_for(project, session)


def arm_for(project: Path, session: str) -> Path:
    """Arm a sentinel for PR 41 as ``session``."""
    os.environ["CLAUDE_CODE_SESSION_ID"] = session
    try:
        return arm(load_config(project), 41, 3)
    finally:
        del os.environ["CLAUDE_CODE_SESSION_ID"]


def _run_main(
        monkeypatch: pytest.MonkeyPatch, project: Path, capsys: pytest.CaptureFixture,
        payload: Optional[dict],
) -> Tuple[int, str, str]:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload) if payload is not None else ""))
    rc = hook.main()
    out = capsys.readouterr()
    return rc, out.out, out.err


class TestMain:
    def test_no_sentinel_allows_the_stop(self, make_project, monkeypatch, capsys) -> None:
        rc, out, err = _run_main(monkeypatch, make_project(), capsys, {"session_id": "sess"})
        assert (rc, out, err) == (0, "", "")

    def test_hot_sentinel_blocks_with_a_decision(self, make_project, monkeypatch, capsys) -> None:
        project, _ = _project(make_project)
        rc, out, _ = _run_main(monkeypatch, project, capsys, {"cwd": str(project), "session_id": "sess"})
        decision = json.loads(out)
        assert rc == 0 and decision["decision"] == "block"
        assert "PR #41" in decision["reason"] and "at least 3 diagram blocks" in decision["reason"]

    def test_stop_hook_active_breaks_the_loop(self, make_project, monkeypatch, capsys) -> None:
        project, path = _project(make_project)
        payload = {"cwd": str(project), "session_id": "sess", "stop_hook_active": True}
        rc, out, err = _run_main(monkeypatch, project, capsys, payload)
        assert (rc, out) == (0, "") and "stop_hook_active" in err and str(path) in err

    def test_other_session_stops_with_a_notice(self, make_project, monkeypatch, capsys) -> None:
        project, _ = _project(make_project, session="sess-owner")
        rc, out, err = _run_main(monkeypatch, project, capsys, {"cwd": str(project), "session_id": "other"})
        assert (rc, out) == (0, "") and "another session" in err

    def test_empty_stdin_still_blocks(self, make_project, monkeypatch, capsys) -> None:
        project, _ = _project(make_project)
        rc, out, _ = _run_main(monkeypatch, project, capsys, None)
        assert rc == 0 and json.loads(out)["decision"] == "block"

    def test_unusable_config_falls_back_to_the_default_state_dir(
            self, make_project, monkeypatch, capsys,
    ) -> None:
        project = make_project(files={".claude/harness.json": '{"state_dir": ".claude/odd"}'})
        directory = sentinel_dir_under(project, ".claude/odd")
        directory.mkdir(parents=True)
        _write(directory, "41")
        (project / ".claude" / "harness.json").write_text('{"state_dir": ".claude/odd", "bogus": 1}')
        rc, out, err = _run_main(monkeypatch, project, capsys, {"cwd": str(project), "session_id": "sess"})
        assert rc == 0 and json.loads(out)["decision"] == "block" and "config unusable" in err


def test_subprocess_blocks_owning_session(make_project) -> None:
    """End to end: the hook file run as a child process with a SubagentStop payload emits the block."""
    project, _ = _project(make_project, session="sess-owner")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    payload = {"cwd": str(project), "hook_event_name": "SubagentStop", "session_id": "sess-owner"}
    done = subprocess.run([sys.executable, str(_HOOK_PATH)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["decision"] == "block"
    assert sentinel_path(load_config(project), 41).exists()
