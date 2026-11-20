"""Behavioral tests for the plugin's ``hooks/stop_gates.py`` Stop dispatcher.

The dispatcher reads the Stop payload once, resolves the project and its ``state_dir`` once, and decides the
Phase 5 gate (``check_phase5_sentinel.decide``) and the ``--min-viz`` gate (``check_min_viz_sentinel.decide``)
in one launch. One assertion per test: nothing armed allows the stop; one armed gate blocks with its own
reason; both armed block once with both reasons; a gate that raises leaves the other free to decide; the
launch imports neither ``pydantic`` nor ``jsonschema``.
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
from typing import Any, Dict, Optional, Tuple

import pytest

from conftest import PLUGIN_ROOT
from harness_lib.config import load_config
from harness_lib.min_viz_sentinel import sentinel_dir_under as min_viz_dir_under
from harness_lib.validation.artifact_names import phase5_sentinel_dir

_HOOK_PATH = PLUGIN_ROOT / "hooks" / "stop_gates.py"


def _load_hook():
    """Import the dispatcher by absolute path; the hooks directory is not a package."""
    spec = importlib.util.spec_from_file_location("_test_stop_gates", str(_HOOK_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


def _arm_phase5(project: Path, pr: str = "42", owner: str = "sess") -> Path:
    directory = phase5_sentinel_dir(load_config(project))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f".phase5_pending_{pr}"
    path.write_text(f"{pr}\n{int(time.time())}\n{owner}\n", encoding="utf-8")
    return path


def _arm_min_viz(project: Path, pr: str = "41", owner: str = "sess") -> Path:
    directory = min_viz_dir_under(project, load_config(project).state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f".minviz_pending_{pr}"
    path.write_text(f"{pr}\n{int(time.time())}\n{owner}\n3\n", encoding="utf-8")
    return path


def _run_main(
        monkeypatch: pytest.MonkeyPatch, project: Path, capsys: pytest.CaptureFixture,
        payload: Optional[Dict[str, Any]] = None,
) -> Tuple[int, str, str]:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project)
    body = payload if payload is not None else {"cwd": str(project), "session_id": "sess"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(body)))
    rc = hook.main()
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_nothing_armed_allows_the_stop(make_project, monkeypatch, capsys) -> None:
    assert _run_main(monkeypatch, make_project(), capsys) == (0, "", "")


def test_phase5_alone_blocks_with_its_reason(make_project, monkeypatch, capsys) -> None:
    project = make_project()
    _arm_phase5(project)
    _rc, out, _err = _run_main(monkeypatch, project, capsys)
    reason = json.loads(out)["reason"]
    assert "Phase 5 sentinel hot for PR #42" in reason and "--min-viz" not in reason


def test_min_viz_alone_blocks_with_its_reason(make_project, monkeypatch, capsys) -> None:
    project = make_project()
    _arm_min_viz(project)
    _rc, out, _err = _run_main(monkeypatch, project, capsys)
    reason = json.loads(out)["reason"]
    assert "--min-viz is armed for PR #41" in reason and "Phase 5" not in reason


def test_both_armed_block_once_with_both_reasons(make_project, monkeypatch, capsys) -> None:
    project = make_project()
    _arm_phase5(project)
    _arm_min_viz(project)
    _rc, out, _err = _run_main(monkeypatch, project, capsys)
    lines = [line for line in out.splitlines() if line.strip()]
    reason = json.loads(lines[0])["reason"]
    assert len(lines) == 1 and "PR #42" in reason and "PR #41" in reason


def test_stop_hook_active_allows_the_stop_for_both_gates(make_project, monkeypatch, capsys) -> None:
    project = make_project()
    _arm_phase5(project)
    _arm_min_viz(project)
    payload = {"cwd": str(project), "session_id": "sess", "stop_hook_active": True}
    rc, out, err = _run_main(monkeypatch, project, capsys, payload)
    assert (rc, out) == (0, "") and err.count("allowing stop to avoid a block loop") == 2


def test_a_raising_gate_leaves_the_other_to_decide(make_project, monkeypatch, capsys) -> None:
    project = make_project()
    _arm_min_viz(project)

    def _boom(payload: Dict[str, Any], state_root: Path) -> Optional[str]:
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(hook, "HOOK_ORDER", (_boom, hook.HOOK_ORDER[1]))
    _rc, out, err = _run_main(monkeypatch, project, capsys)
    assert "PR #41" in json.loads(out)["reason"] and "gate exploded" in err


def test_unknown_config_key_is_silent_and_keeps_its_state_dir(make_project, monkeypatch, capsys) -> None:
    """No schema validation on Stop: an unknown key is silent; the raw ``state_dir`` is still scanned."""
    project = make_project(config={"state_dir": "var/harness"})
    _arm_phase5(project)
    (project / ".claude" / "harness.json").write_text('{"state_dir": "var/harness", "bogus": 1}')
    _rc, out, err = _run_main(monkeypatch, project, capsys)
    assert "PR #42" in json.loads(out)["reason"] and err == ""


def test_unparseable_config_scans_the_default_with_a_notice(make_project, monkeypatch, capsys) -> None:
    project = make_project()
    _arm_phase5(project)
    (project / ".claude" / "harness.json").write_text("{not json")
    _rc, out, err = _run_main(monkeypatch, project, capsys)
    assert "PR #42" in json.loads(out)["reason"] and "harness config unreadable" in err


def test_the_launch_imports_neither_pydantic_nor_jsonschema() -> None:
    """The Stop launch stays stdlib plus ``harness_lib``: the import cost of either library is the point."""
    probe = (
        "import runpy, sys\n"
        f"sys.argv = [{str(_HOOK_PATH)!r}]\n"
        "sys.stdin = __import__('io').StringIO('{}')\n"
        f"runpy.run_path({str(_HOOK_PATH)!r}, run_name='not_main')\n"
        "print(sorted(m for m in ('pydantic', 'jsonschema') if m in sys.modules))\n"
    )
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_subprocess_blocks_owning_session(make_project) -> None:
    """End to end: the dispatcher run as a child process with a Stop payload emits one block decision."""
    project = make_project()
    _arm_phase5(project, owner="sess-owner")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    payload = {"cwd": str(project), "hook_event_name": "Stop", "session_id": "sess-owner"}
    done = subprocess.run([sys.executable, str(_HOOK_PATH)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["decision"] == "block"
