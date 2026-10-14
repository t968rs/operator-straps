"""Behavioral tests for phase4_branch_safety.py: the --second-run sentinel, argv parsing and the clean-tree
check.

Responsibilities tested in isolation (the network-touching gh call is deliberately not exercised here):

1. Sentinel write helper: where (``<project>/<state_dir>/pr-review/``), with what filename, what content,
   dir auto-mkdir.
2. argv parser: detects --second-run anywhere in argv, strips it cleanly so the remaining positional
   argument is the PR number; ``--exclusions-fixture`` overrides the project's configured exclusions file.
3. Clean-tree check: ``git status --porcelain`` filtered by the configured exclusions, in process.

Every project is a throwaway repo built by ``make_project`` and activated. The Stop hook and the Layer 3
cleanup are exercised in their own test files; this file pins ONLY the producer side of the sentinel
contract.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import ModuleType

import pytest

from conftest import git
from harness_lib.config import activate, load_config

_STATE = "var/harness_state"
_EXCLUSIONS = {"exclusions": [{"pattern": "build/*"}, {"pattern": "*.log"}]}


def _load_phase4_module(plugin_root: Path) -> ModuleType:
    """Load phase4_branch_safety.py from the plugin's pr-review skill as a module and return it."""
    script_path = plugin_root / "skills" / "pr-review" / "commands" / "phase4_branch_safety.py"
    spec = importlib.util.spec_from_file_location("phase4_branch_safety", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def phase4(plugin_root: Path) -> ModuleType:
    return _load_phase4_module(plugin_root)


@pytest.fixture
def project(make_project) -> Path:
    """An activated project with a custom ``state_dir`` and an exclusions file."""
    root = make_project(config={"state_dir": _STATE, "exclusions": "config/exclusions.json"},
                        files={"config/exclusions.json": _EXCLUSIONS})
    activate(load_config(root))
    return root


def _sentinel(root: Path, pr: str) -> Path:
    """The contract sentinel path for ``pr`` under ``root``."""
    return root / _STATE / "pr-review" / f".phase5_pending_{pr}"


# ---------------------------------------------------------------------------
# Sentinel write helper
# ---------------------------------------------------------------------------

def test_write_sentinel_creates_file_at_expected_path(project, phase4, monkeypatch):
    """Helper writes the sentinel under <project>/<state_dir>/pr-review/."""
    phase4._write_phase5_sentinel("918", project)
    assert _sentinel(project, "918").is_file()


def test_write_sentinel_from_linked_worktree_lands_in_main_checkout(project, phase4, tmp_path):
    """A fixer arming from a linked worktree writes where the main checkout's Stop hook reads."""
    wt = tmp_path / "wt"
    git(project, "worktree", "add", "-q", "--detach", str(wt))
    activate(load_config(wt))
    phase4._write_phase5_sentinel("918", wt)
    assert _sentinel(project, "918").is_file()
    assert not _sentinel(wt, "918").exists()


def test_write_sentinel_filename_is_phase5_pending_pr(project, phase4):
    """Filename format: literal .phase5_pending_<PR-as-given>; only the sentinel pattern is pinned."""
    phase4._write_phase5_sentinel("ABC123", project)
    expected = _sentinel(project, "ABC123")
    assert sorted(expected.parent.glob(".phase5_pending_*")) == [expected]


def test_write_sentinel_content_first_line_is_pr_number(project, phase4):
    """Sentinel content's first line is the PR number (audit trail of which PR armed it)."""
    phase4._write_phase5_sentinel("42", project)
    lines = _sentinel(project, "42").read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "42"


def test_write_sentinel_content_second_line_is_unix_timestamp(project, phase4):
    """Sentinel content's second line is the unix write-time the Stop hook ages it by."""
    before = int(time.time())
    phase4._write_phase5_sentinel("42", project)
    after = int(time.time())
    lines = _sentinel(project, "42").read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2, f"sentinel must have at least 2 lines; got {lines!r}"
    assert before <= int(lines[1]) <= after


def test_write_sentinel_third_line_is_arming_session_id(project, phase4, monkeypatch):
    """Line 3 records the arming session so the Stop hook blocks only that session."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-owner")
    phase4._write_phase5_sentinel("42", project)
    lines = _sentinel(project, "42").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3, f"expected PR, write-time, session; got {lines!r}"
    assert lines[2] == "sess-owner"


def test_write_sentinel_without_session_env_writes_two_lines(project, phase4, monkeypatch):
    """No CLAUDE_CODE_SESSION_ID: the two-line shape, an unowned sentinel that blocks every session."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    phase4._write_phase5_sentinel("42", project)
    assert len(_sentinel(project, "42").read_text(encoding="utf-8").splitlines()) == 2


def test_write_sentinel_whitespace_session_env_writes_two_lines(project, phase4, monkeypatch):
    """A whitespace-only CLAUDE_CODE_SESSION_ID collapses to no owner: the two-line shape."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "   ")
    phase4._write_phase5_sentinel("42", project)
    assert len(_sentinel(project, "42").read_text(encoding="utf-8").splitlines()) == 2


def test_write_sentinel_ignores_claude_project_dir(project, phase4, monkeypatch, tmp_path):
    """The sentinel lands under the given project root (resolved like the hooks resolve it: the git top
    level of the working directory), never under CLAUDE_PROJECT_DIR."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(elsewhere))
    phase4._write_phase5_sentinel("99", project)
    assert _sentinel(project, "99").is_file()
    assert not (elsewhere / _STATE).exists()


def test_write_sentinel_creates_parent_dirs_if_missing(project, phase4):
    """Helper does not error if <state_dir>/pr-review/ does not pre-exist."""
    assert not (project / _STATE).exists()
    phase4._write_phase5_sentinel("777", project)
    assert _sentinel(project, "777").is_file()


def test_project_resolves_the_cwd_git_top_level(project, phase4, monkeypatch):
    """``_project`` activates the configuration of the repo the working directory is in."""
    nested = project / "config"
    monkeypatch.chdir(nested)
    root, cfg = phase4._project()
    assert root == project.resolve() and cfg.state_dir == _STATE


# ---------------------------------------------------------------------------
# argv parser
# ---------------------------------------------------------------------------

def test_parse_argv_detects_second_run_flag_anywhere(phase4):
    """--second-run is detected regardless of position in argv."""
    for argv in (["phase4_branch_safety.py", "--second-run", "918"],
                 ["phase4_branch_safety.py", "918", "--second-run"]):
        second_run, pr_number, _exclusions_fixture = phase4._parse_argv(argv)
        assert second_run is True, f"flag not detected in {argv!r}"
        assert pr_number == "918", f"pr_number wrong in {argv!r}: {pr_number!r}"


def test_parse_argv_default_no_flag(phase4):
    """Without --second-run, second_run is False and pr_number is the lone arg."""
    second_run, pr_number, _exclusions_fixture = phase4._parse_argv(["phase4_branch_safety.py", "918"])
    assert second_run is False
    assert pr_number == "918"


def test_parse_argv_returns_none_pr_when_no_args(phase4):
    """When argv has no positional args, pr_number is None."""
    second_run, pr_number, _exclusions_fixture = phase4._parse_argv(["phase4_branch_safety.py"])
    assert second_run is False
    assert pr_number is None


def test_parse_argv_returns_none_pr_when_only_flag(phase4):
    """When argv has the flag but no PR number, pr_number is None."""
    argv = ["phase4_branch_safety.py", "--second-run"]
    second_run, pr_number, _exclusions_fixture = phase4._parse_argv(argv)
    assert second_run is True
    assert pr_number is None


def test_parse_argv_rejects_extra_positional(phase4):
    """Gatekeeper contract: a second positional could send Phase 4 against the wrong PR. Fail fast."""
    with pytest.raises(ValueError, match="positional"):
        phase4._parse_argv(["phase4_branch_safety.py", "918", "921"])


def test_parse_argv_rejects_unknown_flag(phase4):
    """Unknown -- flags are arg-shape errors; running silently invites typos like --secondrun."""
    with pytest.raises(ValueError, match="unknown flag"):
        phase4._parse_argv(["phase4_branch_safety.py", "--bogus", "918"])


def test_parse_argv_default_exclusions_fixture_is_none(phase4):
    """When --exclusions-fixture is omitted, _parse_argv returns None: the configured file governs."""
    _second_run, _pr_number, exclusions_fixture = phase4._parse_argv(["phase4_branch_safety.py", "1122"])
    assert exclusions_fixture is None


def test_parse_argv_explicit_exclusions_fixture(phase4):
    """When --exclusions-fixture is passed, _parse_argv returns the explicit value."""
    custom = "custom/path/excludes.json"
    _second_run, _pr_number, exclusions_fixture = phase4._parse_argv(
        ["phase4_branch_safety.py", "--exclusions-fixture", custom, "1122"]
    )
    assert exclusions_fixture == custom


def test_exclusions_default_is_the_configured_file(project, phase4):
    """No flag: the project's configured ``exclusions`` path; a flag wins."""
    cfg = load_config(project)
    assert phase4._exclusions_for(None, cfg) == "config/exclusions.json"
    assert phase4._exclusions_for("x.json", cfg) == "x.json"


# ---------------------------------------------------------------------------
# clean-tree check
# ---------------------------------------------------------------------------

def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_clean_tree_ignores_excluded_changes(project, phase4):
    """Changes matching the configured exclusions leave the tree clean."""
    _write(project, "build/out.txt")
    _write(project, "run.log")
    check = phase4._check_clean_tree(project, "config/exclusions.json")
    assert check["result"] == "OK (empty after exclusions)"
    assert "build/" in check["stdout"] and check["filtered_stdout"] == ""
    assert check["exclusions_fixture"] == "config/exclusions.json"


def test_clean_tree_stops_on_other_changes(project, phase4):
    """A change outside the exclusions is a STOP naming the path."""
    _write(project, "src/a.py")
    check = phase4._check_clean_tree(project, "config/exclusions.json")
    assert check["result"].startswith("STOP: working tree has non-exempt changes")
    assert "?? src/" in check["filtered_stdout"]


def test_clean_tree_without_exclusions_counts_every_change(make_project, phase4):
    """No exclusions configured: every change counts."""
    root = make_project(config={})
    _write(root, "build/out.txt")
    check = phase4._check_clean_tree(root, None)
    assert check["result"].startswith("STOP") and check["exclusions_fixture"] == "(none configured)"


def test_clean_tree_missing_exclusions_file_stops(project, phase4):
    """A named exclusions file that does not exist is a STOP, never a silent pass."""
    check = phase4._check_clean_tree(project, "config/missing.json")
    assert check["result"].startswith("STOP: exclusions")


@pytest.mark.parametrize("config_text", ["{not json", '{"no_such_key": 1}'])
def test_main_reports_a_bad_harness_config_as_fail(make_project, phase4, monkeypatch, capsys, config_text):
    """A malformed or schema-invalid harness.json is a ``FAIL: harness config`` line and exit 1."""
    root = make_project(files={".claude/harness.json": config_text})
    monkeypatch.chdir(root)
    meta = {"headRefName": "main", "first_sha": "a", "last_sha": "b", "baseRefName": "main"}
    monkeypatch.setattr(phase4, "_gh_pr_metadata", lambda pr: meta)
    assert phase4.main(["phase4_branch_safety.py", "7"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("FAIL: harness config: ") and "Traceback" not in err
