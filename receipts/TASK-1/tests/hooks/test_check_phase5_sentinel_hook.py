"""Behavioral tests for the plugin's ``hooks/check_phase5_sentinel.py`` Stop hook.

Sentinels live at ``<project>/<state_dir>/pr-review/.phase5_pending_<PR>``; the project is resolved from
the Stop payload's ``cwd`` (else the process cwd). Stop hook responsibilities (one assertion per test):
- exit 0 + silent when no sentinel files present (allow stop)
- exit 0 + JSON {"decision": "block", ...} on stdout when a recent (<24h)
  sentinel is present (enforcement is via the decision contract, not the
  exit code — a bare non-zero exit never reaches the model)
- exit 0 + no block when stop_hook_active is set on stdin (loop-break)
- exit 0 + warning when only stale (>24h) sentinels are present (allow with cleanup hint)
- prefer hot over stale when mixed
- deterministically select which sentinel blocks (first hot sentinel in sorted
  glob order that blocks the stopping session) when multiple hot sentinels are present
- fall back to mtime when the sentinel has no line-2 timestamp
- block only the arming session: a line-3 owner spares other sessions, which
  get a stderr notice and a foreign_prs entry
- unowned sentinel (no line 3) or unknown stopping session (no session_id)
  fails closed and blocks
- stale (>24h) sentinels are ignored for blocking, owned or not

Most tests call the Python API directly (evaluate_sentinels + main); one runs the hook as a
subprocess with a Stop payload against a ``make_project`` project.
"""
from __future__ import annotations

import json
import importlib.util
import io
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import pytest

from conftest import PLUGIN_ROOT, git
from harness_lib.config import load_config
from harness_lib.validation.artifact_names import phase5_sentinel_dir


# Resolve the production hook module by absolute path. Move-NOT-resilient by
# design: if the file moves, _load_hook_module raises FileNotFoundError
# rather than silently scanning zero sources (which would falsely pass).
_HOOK_MODULE_PATH = PLUGIN_ROOT / "hooks" / "check_phase5_sentinel.py"


def _load_hook_module():
    """Import the hook module from its absolute path.

    The hooks directory is intentionally not a Python package (no __init__.py),
    so a normal import would fail. importlib.util handles the bare-file case.
    """
    if not _HOOK_MODULE_PATH.exists():
        raise FileNotFoundError(
            f"Hook module not found at {_HOOK_MODULE_PATH}; "
            f"check the path or whether the file was moved."
        )
    # Use a namespaced spec name so cls.__module__ on the loaded
    # dataclasses reads as `_test_check_phase5_sentinel`, NOT the
    # production import name `check_phase5_sentinel`. This both
    # (a) avoids collision with a future real `import check_phase5_sentinel`
    # and (b) keeps dataclass forward-ref resolution working — `dataclasses`
    # looks up sys.modules[cls.__module__] during class construction, and
    # `from __future__ import annotations` in the loaded module makes that
    # lookup mandatory. The spec name and the sys.modules key MUST match.
    spec = importlib.util.spec_from_file_location(
        "_test_check_phase5_sentinel", str(_HOOK_MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Could not build module spec for {_HOOK_MODULE_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module. Lifetime: registered for the lifetime
    # of the test process; safe because no production code imports this
    # name (the underscore prefix marks it as internal).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load_hook_module()


@pytest.fixture
def sentinel_dir(tmp_path: Path) -> Path:
    """A fresh sentinel directory under tmp_path."""
    d = tmp_path / ".claude" / "state" / "harness" / "pr-review"
    d.mkdir(parents=True)
    return d


def _now() -> int:
    """Frozen-now helper. Tests pass `_now=_now()` to evaluate_sentinels so
    the result does not race the system clock between sentinel mtime
    capture and the call site. The leading underscore on the parameter
    name is the production code's signal that injection is test-only."""
    return int(time.time())


# ---------------------------------------------------------------------------
# evaluate_sentinels — pure-function classification tests (the spec)
# ---------------------------------------------------------------------------


def test_empty_dir_classifies_as_no_hot(sentinel_dir):
    """Empty sentinel directory: no hot PR, no stale messages."""
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr is None
    assert result.hot_path is None
    assert result.stale_messages == ()


def test_recent_sentinel_classified_as_hot(sentinel_dir):
    """A sentinel younger than max_age_seconds is the hot PR."""
    sentinel = sentinel_dir / ".phase5_pending_42"
    sentinel.touch()
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr == "42"
    assert result.hot_path == sentinel
    assert result.stale_messages == ()


def test_stale_sentinel_emits_warning_no_block(sentinel_dir):
    """A sentinel older than max_age_seconds yields a warning, not a block."""
    sentinel = sentinel_dir / ".phase5_pending_777"
    sentinel.touch()
    twenty_five_hours_ago = _now() - 25 * 3600
    os.utime(sentinel, (twenty_five_hours_ago, twenty_five_hours_ago))
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr is None
    assert any("777" in msg and "stale" in msg.lower()
               for msg in result.stale_messages)


def test_mixed_hot_and_stale_classifies_hot(sentinel_dir):
    """Hot wins over stale when both present."""
    hot = sentinel_dir / ".phase5_pending_HOT"
    stale = sentinel_dir / ".phase5_pending_STALE"
    hot.touch()
    stale.touch()
    twenty_five_hours_ago = _now() - 25 * 3600
    os.utime(stale, (twenty_five_hours_ago, twenty_five_hours_ago))
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr == "HOT"
    assert result.hot_path == hot


def test_multiple_hot_picks_first_deterministically(sentinel_dir):
    """Two hot sentinels: classification picks one deterministically (sorted order)."""
    (sentinel_dir / ".phase5_pending_100").touch()
    (sentinel_dir / ".phase5_pending_200").touch()
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr in ("100", "200")
    # Sorted glob order: 100 sorts before 200, so 100 wins deterministically.
    assert result.hot_pr == "100"


def test_old_content_timestamp_classifies_stale_despite_recent_mtime(sentinel_dir):
    """Line-2 unix-int timestamp wins over mtime — stale direction.

    External tools that bump mtime (backup utilities, IDE indexers,
    `git checkout`) cannot reset the age window of an orphaned sentinel
    when the write-time is stamped inside the file content.
    """
    sentinel = sentinel_dir / ".phase5_pending_OLDSTAMP"
    twenty_five_hours_ago = _now() - 25 * 3600
    sentinel.write_text(
        f"OLDSTAMP\n{twenty_five_hours_ago}\n", encoding="utf-8"
    )
    # mtime is freshly NOW (write_text just wrote). If the implementation
    # used mtime, the sentinel would be hot. Using content timestamp -> stale.
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr is None
    assert any("OLDSTAMP" in msg and "stale" in msg.lower()
               for msg in result.stale_messages)


def test_recent_content_timestamp_classifies_hot_despite_old_mtime(sentinel_dir):
    """Inverse direction: recent write-time wins over old mtime."""
    sentinel = sentinel_dir / ".phase5_pending_FRESHSTAMP"
    recent = _now() - 60
    sentinel.write_text(
        f"FRESHSTAMP\n{recent}\n", encoding="utf-8"
    )
    forty_eight_hours_ago = _now() - 48 * 3600
    os.utime(sentinel, (forty_eight_hours_ago, forty_eight_hours_ago))
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr == "FRESHSTAMP"


def test_crlf_content_timestamp_old_classifies_stale(sentinel_dir):
    """CRLF line endings on the write-time stamp parse correctly."""
    sentinel = sentinel_dir / ".phase5_pending_OLDCRLF"
    twenty_five_hours_ago = _now() - 25 * 3600
    sentinel.write_bytes(
        f"OLDCRLF\r\n{twenty_five_hours_ago}\r\n".encode("utf-8")
    )
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr is None
    assert any("OLDCRLF" in msg and "stale" in msg.lower()
               for msg in result.stale_messages)


def test_crlf_content_timestamp_recent_classifies_hot(sentinel_dir):
    """CRLF line endings on a recent write-time stamp also parse correctly."""
    sentinel = sentinel_dir / ".phase5_pending_FRESHCRLF"
    recent = _now() - 60
    sentinel.write_bytes(
        f"FRESHCRLF\r\n{recent}\r\n".encode("utf-8")
    )
    forty_eight_hours_ago = _now() - 48 * 3600
    os.utime(sentinel, (forty_eight_hours_ago, forty_eight_hours_ago))
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr == "FRESHCRLF"


def test_legacy_format_falls_back_to_mtime_hot(sentinel_dir):
    """Pre-Cycle-6 sentinels (PR-only content, no line 2) fall back to mtime.

    Backward compat: a sentinel from an earlier version of
    phase4_branch_safety.py has no write-time stamp. The classifier
    must treat the missing line-2 as 'use mtime' rather than as an error.
    """
    sentinel = sentinel_dir / ".phase5_pending_LEGACY"
    sentinel.write_text("LEGACY", encoding="utf-8")  # no line 2
    # Recent mtime (just written) -> classifies as hot via fallback.
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr == "LEGACY"


def test_invalid_line2_falls_back_to_mtime(sentinel_dir):
    """A non-numeric line 2 (corrupted sentinel) falls back to mtime.

    Robustness: rather than treating an unparseable line 2 as a
    hard error, the classifier silently falls back to mtime. Same
    failure mode as a missing line 2.
    """
    sentinel = sentinel_dir / ".phase5_pending_GARBAGE"
    sentinel.write_text("GARBAGE\nnot_a_number\n", encoding="utf-8")
    result = hook.evaluate_sentinels(sentinel_dir, _now=_now())
    assert result.hot_pr == "GARBAGE"  # recent mtime via fallback


# ---------------------------------------------------------------------------
# Session ownership (Issue #1560): line 3 names the arming session
# ---------------------------------------------------------------------------


def _owned(sentinel_dir: Path, pr: str, owner: str) -> Path:
    """Write a hot three-line sentinel armed by ``owner``."""
    sentinel = sentinel_dir / f".phase5_pending_{pr}"
    sentinel.write_text(f"{pr}\n{_now() - 60}\n{owner}\n", encoding="utf-8")
    return sentinel


def test_owned_sentinel_blocks_its_own_session(sentinel_dir):
    """The arming session stays blocked."""
    sentinel = _owned(sentinel_dir, "42", "sess-owner")
    result = hook.evaluate_sentinels(sentinel_dir, session_id="sess-owner", _now=_now())
    assert result.hot_pr == "42"
    assert result.hot_path == sentinel
    assert result.foreign_prs == ()


def test_owned_sentinel_spares_other_session(sentinel_dir):
    """A different session gets no block; the PR is reported as foreign instead."""
    _owned(sentinel_dir, "42", "sess-owner")
    result = hook.evaluate_sentinels(sentinel_dir, session_id="sess-other", _now=_now())
    assert result.hot_pr is None
    assert result.foreign_prs == ("42",)


def test_unowned_sentinel_blocks_any_session(sentinel_dir):
    """A two-line sentinel names no owner: fail closed, as before #1560."""
    (sentinel_dir / ".phase5_pending_42").write_text(f"42\n{_now() - 60}\n", encoding="utf-8")
    result = hook.evaluate_sentinels(sentinel_dir, session_id="sess-other", _now=_now())
    assert result.hot_pr == "42"


def test_unknown_stopping_session_blocks_on_owned_sentinel(sentinel_dir):
    """No session_id on stdin: ownership cannot be ruled out, so the block holds."""
    _owned(sentinel_dir, "42", "sess-owner")
    result = hook.evaluate_sentinels(sentinel_dir, session_id=None, _now=_now())
    assert result.hot_pr == "42"


def test_foreign_sentinel_does_not_mask_own(sentinel_dir):
    """Another session's sentinel sorting first must not hide this session's own."""
    _owned(sentinel_dir, "100", "sess-other")
    own = _owned(sentinel_dir, "200", "sess-owner")
    result = hook.evaluate_sentinels(sentinel_dir, session_id="sess-owner", _now=_now())
    assert result.hot_pr == "200"
    assert result.hot_path == own
    assert result.foreign_prs == ("100",)


def test_stale_owned_sentinel_still_stale(sentinel_dir):
    """The 24 h rule applies before ownership: a stale owned sentinel never blocks.

    The non-owner call is the one that exposes ordering: an ownership-first check
    would add the abandoned sentinel to foreign_prs and print a 'Do not delete it.' notice.
    """
    sentinel = sentinel_dir / ".phase5_pending_42"
    sentinel.write_text(f"42\n{_now() - 25 * 3600}\nsess-owner\n", encoding="utf-8")
    result = hook.evaluate_sentinels(sentinel_dir, session_id="sess-owner", _now=_now())
    assert result.hot_pr is None
    assert result.foreign_prs == ()
    assert any("stale" in msg.lower() for msg in result.stale_messages)
    other = hook.evaluate_sentinels(sentinel_dir, session_id="sess-other", _now=_now())
    assert other.hot_pr is None
    assert other.foreign_prs == ()
    assert any("stale" in msg.lower() for msg in other.stale_messages)


def test_whitespace_owner_line_collapses_to_unowned(sentinel_dir):
    """A whitespace-only line 3 strips to None, so the sentinel fails closed for any session."""
    (sentinel_dir / ".phase5_pending_42").write_text(
        f"42\n{_now() - 60}\n   \n", encoding="utf-8"
    )
    result = hook.evaluate_sentinels(sentinel_dir, session_id="sess-other", _now=_now())
    assert result.hot_pr == "42"
    assert result.foreign_prs == ()


def test_blank_stdin_session_id_is_unknown(monkeypatch):
    """A whitespace-only stdin session_id strips to None, so the block holds."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "  "})))
    assert hook._session_id_from(hook._stop_payload_from_stdin()) is None


# ---------------------------------------------------------------------------
# main() — entry-point integration tests (exit code + stderr)
# ---------------------------------------------------------------------------


def _project_with_sentinel_dir(make_project, config: Optional[dict] = None) -> Tuple[Path, Path]:
    """A throwaway project plus its (created) sentinel directory per its harness config."""
    project = make_project(config=config)
    pr_dir = phase5_sentinel_dir(load_config(project))
    pr_dir.mkdir(parents=True)
    return project, pr_dir


def _run_main(
    monkeypatch, project_dir: Path, capsys, stdin_payload: str = ""
) -> Tuple[int, str, str]:
    """Invoke hook.main() with the process cwd inside project_dir.

    Returns (exit_code, stdout, stderr). Uses monkeypatch so the cwd and
    stdin changes do not bleed into other tests. stdin_payload is fed to the
    hook as the Stop-hook stdin JSON (empty string -> first stop attempt, the
    enforcement-preserving default); a payload without ``cwd`` resolves the
    project from the process cwd.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_payload))
    rc = hook.main()
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_main_no_sentinels_exits_zero(make_project, monkeypatch, capsys):
    """Empty project: main() exits 0 silently."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    rc, _stdout, stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    assert stderr == ""


def test_main_hot_sentinel_emits_block_decision(make_project, monkeypatch, capsys):
    """Hot sentinel: main() exits 0 and emits a block decision on stdout.

    Enforcement is the JSON decision, not the exit code — a non-zero exit
    is surfaced only to the user and never reaches the model. stdout must
    be pure JSON so the harness can parse the decision; the reason names
    the PR and the abort path.
    """
    project, pr_dir = _project_with_sentinel_dir(make_project)
    (pr_dir / ".phase5_pending_42").touch()
    rc, stdout, _stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    decision = json.loads(stdout)
    assert decision["decision"] == "block"
    assert "Phase 5 sentinel hot" in decision["reason"]
    assert "42" in decision["reason"]


def test_main_hot_sentinel_stop_hook_active_allows_stop(make_project, monkeypatch, capsys):
    """Hot sentinel + stop_hook_active on stdin: allow stop (loop-break).

    Without this escape a sentinel that Phase 5 closeout never clears would
    block every stop forever. exit 0, no block decision on stdout, stderr
    carries the manual-cleanup hint.
    """
    project, pr_dir = _project_with_sentinel_dir(make_project)
    (pr_dir / ".phase5_pending_42").touch()
    payload = json.dumps({"stop_hook_active": True})
    rc, stdout, stderr = _run_main(monkeypatch, project, capsys, stdin_payload=payload)
    assert rc == 0
    assert stdout == ""
    assert "stop_hook_active" in stderr
    assert "42" in stderr


def test_main_other_session_stops_with_notice(make_project, monkeypatch, capsys):
    """An unrelated session stops normally; stderr warns it off the sentinel (Issue #1560)."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    _owned(pr_dir, "42", "sess-owner")
    payload = json.dumps({"session_id": "sess-other", "stop_hook_active": False})
    rc, stdout, stderr = _run_main(monkeypatch, project, capsys, stdin_payload=payload)
    assert rc == 0
    assert stdout == ""
    assert "Phase 5 pending for PR #42 in another session. Do not delete it." in stderr


def test_main_owning_session_is_blocked(make_project, monkeypatch, capsys):
    """The arming session gets the block decision."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    _owned(pr_dir, "42", "sess-owner")
    payload = json.dumps({"session_id": "sess-owner", "stop_hook_active": False})
    rc, stdout, _stderr = _run_main(monkeypatch, project, capsys, stdin_payload=payload)
    assert rc == 0
    decision = json.loads(stdout)
    assert decision["decision"] == "block"
    assert "42" in decision["reason"]


def test_main_blank_stdin_session_id_blocks_owned_sentinel(make_project, monkeypatch, capsys):
    """A whitespace-only session_id is unknown, so an owned sentinel still blocks."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    _owned(pr_dir, "42", "sess-owner")
    payload = json.dumps({"session_id": "  ", "stop_hook_active": False})
    rc, stdout, _stderr = _run_main(monkeypatch, project, capsys, stdin_payload=payload)
    assert rc == 0
    decision = json.loads(stdout)
    assert decision["decision"] == "block"
    assert "42" in decision["reason"]


def test_main_block_reason_does_not_invite_deletion(make_project, monkeypatch, capsys):
    """The block reason steers to closeout; deleting the sentinel disarms the gate."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    _owned(pr_dir, "42", "sess-owner")
    payload = json.dumps({"session_id": "sess-owner"})
    _rc, stdout, _stderr = _run_main(monkeypatch, project, capsys, stdin_payload=payload)
    reason = json.loads(stdout)["reason"]
    assert "delete" not in reason.lower()
    assert "closeout" in reason


def test_main_missing_sentinel_dir_exits_zero(make_project, monkeypatch, capsys):
    """Project without a ``<state_dir>/pr-review`` directory: main() exits 0 silently.

    The classifier is only invoked once the directory exists; absence
    means no Phase 5 work has ever started, which is the same as
    'no hot sentinels'.
    """
    project = make_project()
    rc, stdout, stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    assert stdout == ""
    assert stderr == ""


def test_main_reads_project_from_payload_cwd(make_project, tmp_path, monkeypatch, capsys):
    """The payload's ``cwd`` names the project even when the process runs elsewhere."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    (pr_dir / ".phase5_pending_42").touch()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    payload = json.dumps({"cwd": str(project), "session_id": "s"})
    rc, stdout, _stderr = _run_main(monkeypatch, elsewhere, capsys, stdin_payload=payload)
    assert rc == 0
    assert json.loads(stdout)["decision"] == "block"


def test_sentinel_armed_in_linked_worktree_blocks_main_checkout(make_project, tmp_path, monkeypatch, capsys):
    """Sentinels are per repository: one armed from a linked worktree gates a stop in the main checkout."""
    project = make_project()
    wt = tmp_path / "wt"
    git(project, "worktree", "add", "-q", "--detach", str(wt))
    pr_dir = phase5_sentinel_dir(load_config(wt))
    assert pr_dir == phase5_sentinel_dir(load_config(project))
    pr_dir.mkdir(parents=True)
    (pr_dir / ".phase5_pending_42").touch()
    for cwd in (project, wt):
        payload = json.dumps({"cwd": str(cwd), "session_id": "s"})
        _rc, stdout, _stderr = _run_main(monkeypatch, tmp_path, capsys, stdin_payload=payload)
        assert json.loads(stdout)["decision"] == "block"


def test_main_follows_configured_state_dir(make_project, monkeypatch, capsys):
    """A ``state_dir`` override moves the scanned directory; the default location is ignored."""
    project, pr_dir = _project_with_sentinel_dir(make_project, config={"state_dir": "var/harness"})
    assert pr_dir == project / "var" / "harness" / "pr-review"
    default_dir = project / ".claude" / "state" / "harness" / "pr-review"
    default_dir.mkdir(parents=True)
    (default_dir / ".phase5_pending_7").touch()
    rc, stdout, _stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    assert stdout == ""
    (pr_dir / ".phase5_pending_8").touch()
    _rc, stdout, _stderr = _run_main(monkeypatch, project, capsys)
    assert "#8" in json.loads(stdout)["reason"]


def _default_sentinel_dir(project: Path) -> Path:
    d = project / ".claude" / "state" / "harness" / "pr-review"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_main_unusable_config_without_sentinels_allows_stop_with_notice(make_project, monkeypatch, capsys):
    """An invalid ``harness.json`` with nothing armed allows the stop; stderr names the config problem."""
    project = make_project(config={"not_a_harness_key": True})
    rc, stdout, stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    assert stdout == ""
    assert "harness config unusable" in stderr


def test_main_unusable_config_still_blocks_on_default_dir(make_project, monkeypatch, capsys):
    """A config typo does not disarm the gate: the default ``state_dir`` is scanned instead."""
    project = make_project(config={"not_a_harness_key": True})
    (_default_sentinel_dir(project) / ".phase5_pending_42").touch()
    rc, stdout, _stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    assert json.loads(stdout)["decision"] == "block"


def test_main_unusable_config_keeps_its_readable_state_dir(make_project, monkeypatch, capsys):
    """An invalid config that still names a string ``state_dir`` is scanned at that location."""
    project = make_project(config={"not_a_harness_key": True, "state_dir": "var/harness"})
    custom = project / "var" / "harness" / "pr-review"
    custom.mkdir(parents=True)
    (custom / ".phase5_pending_9").touch()
    rc, stdout, _stderr = _run_main(monkeypatch, project, capsys)
    assert rc == 0
    assert "#9" in json.loads(stdout)["reason"]


def test_main_missing_git_still_blocks(make_project, monkeypatch, capsys):
    """Without git on PATH the payload ``cwd`` is taken as the project root; the gate holds."""
    import harness_lib.project as project_mod

    def _no_git(base):
        raise FileNotFoundError(2, "git not found")

    monkeypatch.setattr(project_mod, "_git_toplevel", _no_git)
    project, pr_dir = _project_with_sentinel_dir(make_project)
    (pr_dir / ".phase5_pending_42").touch()
    payload = json.dumps({"cwd": str(project), "session_id": "s"})
    rc, stdout, stderr = _run_main(monkeypatch, project, capsys, stdin_payload=payload)
    assert rc == 0
    assert json.loads(stdout)["decision"] == "block"
    assert "git not found" in stderr


def test_hook_subprocess_blocks_owning_session(make_project):
    """End to end: the hook file run as a child process with a Stop payload emits the block decision."""
    project, pr_dir = _project_with_sentinel_dir(make_project)
    _owned(pr_dir, "42", "sess-owner")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYDEVD_", "PYCHARM_"))}
    env.pop("CLAUDE_PROJECT_DIR", None)
    payload = {"cwd": str(project), "hook_event_name": "Stop", "session_id": "sess-owner",
               "stop_hook_active": False}
    done = subprocess.run([sys.executable, str(_HOOK_MODULE_PATH)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, check=False)
    assert done.returncode == 0, done.stderr
    decision = json.loads(done.stdout)
    assert decision["decision"] == "block"
    assert "42" in decision["reason"]

