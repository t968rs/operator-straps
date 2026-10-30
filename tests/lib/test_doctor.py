"""Behavioral tests for ``harness_lib.doctor``: the environment checks behind ``/harness:doctor``."""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import List

import pytest

from conftest import PLUGIN_ROOT
from harness_lib import doctor


def _by_name(checks: List[doctor.Check], name: str) -> doctor.Check:
    return next(check for check in checks if check.name == name)


def test_required_modules_match_the_pr_review_gate() -> None:
    """The doctor must name the same dependencies the pr_review driver refuses to start without."""
    tree = ast.parse((PLUGIN_ROOT / "scripts" / "pr_review.py").read_text(encoding="utf-8"))
    literal = next(node.value for node in tree.body if isinstance(node, ast.AnnAssign)
                   and getattr(node.target, "id", "") == "_REQUIRED_MODULES")
    assert doctor.REQUIRED_MODULES == ast.literal_eval(literal)


def test_modules_pass_when_everything_imports() -> None:
    assert doctor.check_modules().status == doctor.OK


def test_missing_module_fails_with_a_pip_line_for_the_running_interpreter(
        monkeypatch: pytest.MonkeyPatch) -> None:
    gone = (("no_such_module_xyz", None, "no-such-dist>=9"),)
    monkeypatch.setattr(doctor, "REQUIRED_MODULES", doctor.REQUIRED_MODULES + gone)
    check = doctor.check_modules()
    assert check.status == doctor.FAIL
    assert "no-such-dist>=9" in check.detail
    assert check.fix == f'"{sys.executable}" -m pip install "no-such-dist>=9"'


def test_old_major_version_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "REQUIRED_MODULES", (("json", "model_validator", "json>=2"),))
    assert doctor.check_modules().status == doctor.FAIL


def test_python_below_the_floor_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "MIN_PYTHON", (99, 0))
    assert doctor.check_python().status == doctor.FAIL


def test_interpreter_without_configuration_is_the_path_fallback() -> None:
    check = doctor.check_interpreter({})
    assert check.status == doctor.OK
    assert "PATH" in check.detail


def test_interpreter_named_by_harness_py_is_reported_as_such() -> None:
    check = doctor.check_interpreter({"HARNESS_PY": sys.executable})
    assert check.status == doctor.OK
    assert "HARNESS_PY" in check.detail


def test_unusable_harness_py_warns_that_hpy_fell_through(tmp_path: Path) -> None:
    missing = str(tmp_path / "nope" / "python.exe")
    check = doctor.check_interpreter({"HARNESS_PY": missing})
    assert check.status == doctor.WARN
    assert missing in check.detail
    assert sys.executable in check.detail


def test_second_candidate_in_use_still_warns_about_the_skipped_first(tmp_path: Path) -> None:
    env = {"HARNESS_PY": str(tmp_path / "nope"), "CLAUDE_PLUGIN_OPTION_PYTHON": sys.executable}
    check = doctor.check_interpreter(env)
    assert check.status == doctor.WARN
    assert "HARNESS_PY" in check.detail


def _user_settings(tmp_path: Path, options: dict, key: str = "harness@some-marketplace") -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"pluginConfigs": {key: {"options": options}}}), encoding="utf-8")
    return path


def test_configured_python_is_read_from_the_harness_plugin_entry(tmp_path: Path) -> None:
    settings = _user_settings(tmp_path, {"python": "C:/envs/x/python.exe"})
    assert doctor.configured_python(settings) == "C:/envs/x/python.exe"


def test_configured_python_ignores_other_plugins_and_bad_files(tmp_path: Path) -> None:
    other = _user_settings(tmp_path, {"python": "C:/envs/x/python.exe"}, key="pytest-scope@some-marketplace")
    assert doctor.configured_python(other) is None
    assert doctor.configured_python(tmp_path / "absent.json") is None
    other.write_text("{not json", encoding="utf-8")
    assert doctor.configured_python(other) is None


def test_option_set_in_settings_but_not_exported_warns_with_the_env_fix(tmp_path: Path) -> None:
    elsewhere = str(tmp_path / "envs" / "other" / "python.exe")
    check = doctor.check_interpreter({}, elsewhere)
    assert check.status == doctor.WARN
    assert elsewhere in check.detail
    assert "settings.local.json" in (check.fix or "")
    assert "HARNESS_PY" in (check.fix or "")


def test_option_naming_the_running_interpreter_is_not_a_problem() -> None:
    assert doctor.check_interpreter({}, sys.executable).status == doctor.OK


def test_exported_override_wins_over_an_unexported_option(tmp_path: Path) -> None:
    check = doctor.check_interpreter({"HARNESS_PY": sys.executable}, str(tmp_path / "other.exe"))
    assert check.status == doctor.OK


def test_missing_gh_warns_and_missing_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor.check_tool("gh", doctor.WARN, "pr-review needs it").status == doctor.WARN
    assert doctor.check_tool("git", doctor.FAIL, "everything needs it").status == doctor.FAIL


def test_project_without_config_uses_defaults(make_project) -> None:
    root = make_project(None)
    checks = doctor.check_project(root)
    assert _by_name(checks, "config").status == doctor.OK
    assert "defaults" in _by_name(checks, "config").detail


def test_project_with_valid_config_loads(make_project) -> None:
    root = make_project({"base_branch": "main"})
    assert _by_name(doctor.check_project(root), "config").status == doctor.OK


def test_unreadable_config_fails_with_the_loader_message(make_project) -> None:
    root = make_project(None, files={".claude/harness.json": "{not json"})
    check = _by_name(doctor.check_project(root), "config")
    assert check.status == doctor.FAIL
    assert "harness.json" in check.detail


def test_directory_outside_git_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    bare = tmp_path / "plain"
    bare.mkdir()
    assert _by_name(doctor.check_project(bare), "repository").status == doctor.WARN


def test_unwritable_worktree_root_warns(make_project, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_project({"worktree_root": str(tmp_path / "trees" / "{repo}")})
    monkeypatch.setattr(os, "access", lambda path, mode: False)
    assert _by_name(doctor.check_project(root), "worktree_root").status == doctor.WARN


def test_summary_counts_by_status() -> None:
    checks = [doctor.Check(doctor.OK, "a", "x"), doctor.Check(doctor.WARN, "b", "y"),
              doctor.Check(doctor.FAIL, "c", "z", "do this")]
    assert doctor.summary(checks) == "doctor [fail] | 1 fail, 1 warn | 3 checks"
    assert doctor.exit_code(checks) == 1
    assert doctor.exit_code(checks[:2]) == 0


def test_render_puts_the_fix_under_a_failing_check() -> None:
    lines = doctor.render([doctor.Check(doctor.FAIL, "modules", "missing: x", "pip install x")])
    assert lines == ["[fail] modules: missing: x", "       fix: pip install x"]
