"""Stop hook: block session end while a Phase 5 sentinel is hot.

Sentinel location: ``<main checkout>/<state_dir>/pr-review/.phase5_pending_<PR>``, where the project is
resolved from the Stop payload's ``cwd`` (else the process cwd), a linked worktree maps to its main
checkout, and ``state_dir`` comes from the project's harness config. An unusable config (or git missing
from PATH) never disarms the gate: the scan falls back to the config's raw ``state_dir`` when readable,
else the plugin default, and to the payload ``cwd`` as the project root.
- Line 1: PR identifier (any string).
- Line 2 (optional): unix-int write-time timestamp.
- Line 3 (optional): id of the session that armed it (CLAUDE_CODE_SESSION_ID).

Sentinels are written by phase4_branch_safety.py --second-run on
all-checks-pass and cleared by validate_pr_json_schema.py Layer 3 on
Phase 5 closeout. Stale sentinels (older than ``MAX_AGE_SECONDS``) are
auto-ignored with a warning so an abandoned review cannot block all
future Stop events indefinitely.

A hot sentinel blocks only the session that armed it: the stopping
session's ``session_id`` (Stop-hook stdin) is compared with line 3. Other
sessions stop with a stderr notice. When either id is unknown (a two-line
sentinel, or stdin without ``session_id``) the block holds, so a missing
id fails closed rather than disarming the gate.

A changed id fails open: a session started by ``/clear``, a forked resume,
or a new terminal is a different owner, so the conversation that continues
the review is spared. Re-running ``phase4_branch_safety.py --second-run <PR>``
from the continuing session re-arms the sentinel under its id.

Enforcement uses the Claude Code Stop-hook decision contract: a hot
sentinel emits ``{"decision": "block", "reason": ...}`` on stdout and
exits 0, which the harness feeds back to the model. A bare exit 1 (or any
non-2 code) is surfaced only to the user and never reaches the model, so it
cannot block a stop; exit 2 is the alternate blocking path used elsewhere.
The ``stop_hook_active`` flag on stdin breaks the otherwise-unbounded block
loop when closeout never clears the sentinel.

Stdlib plus the plugin's ``harness_lib``; no assumptions about bash, POSIX
utilities, or PATH; cross-platform by construction.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.config import CONFIG_REL, DEFAULTS_PATH, ConfigError, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.validation.artifact_names import (  # noqa: E402
    SENTINEL_GLOB as _SENTINEL_GLOB,
    SENTINEL_PREFIX as _SENTINEL_PREFIX,
    phase5_sentinel_dir,
    sentinel_dir_under,
)

MAX_AGE_SECONDS = 86400  # 24 hours


@dataclass(frozen=True)
class SentinelClassification:
    """Outcome of scanning a sentinel directory.

    hot_pr / hot_path are populated when a sentinel younger than
    max_age_seconds blocks the stopping session. foreign_prs lists hot
    sentinels armed by another session, seen before the blocking one (if
    any). stale_messages collects per-file warnings for sentinels older
    than max_age_seconds (informational, not blocking).
    """
    hot_pr: Optional[str] = None
    hot_path: Optional[Path] = None
    stale_messages: Tuple[str, ...] = ()
    foreign_prs: Tuple[str, ...] = ()


def _read_lines(path: Path) -> List[str]:
    """Return the sentinel's lines (CRLF tolerated), or [] when unreadable."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _write_time_from(lines: List[str]) -> Optional[int]:
    """Return the unix-int write-time on line 2, or None when absent, blank, or non-numeric."""
    if len(lines) < 2:
        return None
    candidate = lines[1].strip()
    return int(candidate) if candidate.isdigit() else None


def _owner_from(lines: List[str]) -> Optional[str]:
    """Return the arming session id on line 3, or None for an unowned sentinel."""
    if len(lines) < 3:
        return None
    return lines[2].strip() or None


def blocks_session(owner: Optional[str], session_id: Optional[str]) -> bool:
    """Whether a hot sentinel armed by ``owner`` blocks ``session_id``.

    Spares the stopping session only when both ids are known and differ.
    """
    return owner is None or session_id is None or owner == session_id


def _age_basis(sentinel: Path, lines: List[str], messages: List[str]) -> Optional[int]:
    """Line-2 write-time, else mtime; None (with a message appended) when neither reads."""
    write_time = _write_time_from(lines)
    if write_time is not None:
        return write_time
    try:
        return int(sentinel.stat().st_mtime)
    except OSError:
        if not sentinel.exists():
            messages.append(f"Phase 5 sentinel disappeared mid-scan: {sentinel}; skipping")
        else:
            messages.append(
                f"Phase 5 sentinel age check: cannot read mtime for {sentinel}; skipping"
            )
        return None


def evaluate_sentinels(
    sentinel_dir: Path,
    *,
    session_id: Optional[str] = None,
    _now: Optional[int] = None,
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> SentinelClassification:
    """Classify every .phase5_pending_<PR> sentinel under sentinel_dir.

    Resolution order: prefer the unix-int write-time stamped on line 2
    of each sentinel (immune to incidental mtime touches by backup
    tools, IDE indexers, ``git checkout``); fall back to mtime when
    line 2 is missing or unparseable.

    The first hot sentinel that blocks ``session_id`` (sorted glob order,
    deterministic; see ``blocks_session``) is returned with its PR id and
    path. Hot sentinels armed by another session are collected in
    ``foreign_prs``; stale ones as informational messages.

    ``_now`` is injectable for testability only; defaults to ``int(time.time())``
    at call time.
    """
    if _now is None:
        _now = int(time.time())
    stale_messages: List[str] = []
    foreign_prs: List[str] = []
    for sentinel in sorted(sentinel_dir.glob(_SENTINEL_GLOB)):
        pr = sentinel.name[len(_SENTINEL_PREFIX):]
        lines = _read_lines(sentinel)
        age_basis = _age_basis(sentinel, lines, stale_messages)
        if age_basis is None:
            continue
        if _now - age_basis >= max_age_seconds:
            stale_messages.append(
                f"Phase 5 sentinel for PR #{pr} is stale (>24h); ignoring. "
                f"Manual cleanup: delete {sentinel}"
            )
        elif blocks_session(_owner_from(lines), session_id):
            return SentinelClassification(
                hot_pr=pr, hot_path=sentinel, stale_messages=tuple(stale_messages),
                foreign_prs=tuple(foreign_prs),
            )
        else:
            foreign_prs.append(pr)
    return SentinelClassification(
        stale_messages=tuple(stale_messages), foreign_prs=tuple(foreign_prs)
    )


def _stop_payload_from_stdin() -> Dict[str, Any]:
    """Return the Stop-hook stdin payload as a dict.

    Claude Code feeds Stop hooks a JSON object on stdin carrying
    ``session_id`` and ``stop_hook_active``. Absent, unreadable, empty,
    non-JSON, or non-object stdin returns {}: no session id (the block
    holds) and no loop-break flag, the enforcement-preserving default.
    When pytest stdin is unpatched, read returns empty or raises; both
    resolve to {}.
    """
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _session_id_from(payload: Dict[str, Any]) -> Optional[str]:
    """Return the stopping session's id, or None when absent or blank."""
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()
    return None


def _block_reason(pr: str) -> str:
    """The block text fed back to the model; it steers to closeout, never to deleting the sentinel."""
    return (
        f"Phase 5 sentinel hot for PR #{pr} -- pr-review Phase 5 closeout has not "
        f"completed. Dispatch the remaining fixes / write post_review_resolutions; "
        f"the validate_pr_json_schema hook clears the sentinel at closeout. If this "
        f"session is not running pr-review for PR #{pr}, leave the sentinel in place "
        f"and ask the developer."
    )


def _resolve_project(start: Path) -> Path:
    """``project_root(start)``; when git cannot run, ``start`` itself, with a stderr notice."""
    try:
        return project_root(start)
    except OSError as exc:
        print(f"git unavailable ({exc}); treating {start} as the project root", file=sys.stderr)
        return start.resolve()


def _raw_state_dir(project: Path) -> Optional[str]:
    """``state_dir`` read straight from the project's harness.json, when it parses and holds a string."""
    try:
        raw = json.loads((project / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = raw.get("state_dir") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def _default_state_dir() -> str:
    """The plugin default ``state_dir`` from ``config/defaults.json``."""
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))["state_dir"]


def _sentinel_dir_for(payload: Dict[str, Any]) -> Path:
    """Sentinel directory of the project holding the payload's ``cwd`` (else the process cwd).

    An unusable harness config does not disarm the gate: the scan falls back to the config's raw
    ``state_dir`` when readable, else the plugin default, with a stderr notice.
    """
    cwd = payload.get("cwd")
    project = _resolve_project(Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd()))
    try:
        return phase5_sentinel_dir(activate(load_config(project)))
    except ConfigError as exc:
        fallback = sentinel_dir_under(project, _raw_state_dir(project) or _default_state_dir())
        print(f"harness config unusable ({exc}); scanning {fallback} for Phase 5 sentinels", file=sys.stderr)
        return fallback


def _print_notices(result: SentinelClassification) -> None:
    """Stale-sentinel warnings and other-session notices, on stderr."""
    for msg in result.stale_messages:
        print(msg, file=sys.stderr)
    for pr in result.foreign_prs:
        print(
            f"Phase 5 pending for PR #{pr} in another session. Do not delete it. If this "
            f"session continues that review, re-run phase4_branch_safety.py --second-run "
            f"{pr} here to take ownership.",
            file=sys.stderr,
        )


def main() -> int:
    """Stop-hook entry point; returns 0 always.

    Enforcement is via the JSON decision contract, NOT the exit code: a hot
    sentinel emits ``{"decision": "block", "reason": ...}`` on stdout (exit 0),
    which Claude Code feeds back to the model as a reason to keep going. A
    bare non-zero exit is only surfaced to the user and never reaches the
    model, so it cannot enforce anything.

    Allow-stop paths (exit 0, no decision emitted):
    - no hot sentinel, or the sentinel dir absent (an unusable harness config falls back to
      its raw ``state_dir`` else the plugin default, so a config typo never disarms the gate);
    - every hot sentinel was armed by another session (stderr notice);
    - hot sentinel but ``stop_hook_active`` already set on stdin (loop-break).

    Stale-sentinel warnings, other-session notices, the loop-break notice,
    and the unusable-config notice print to stderr; stdout is reserved for
    the JSON decision so the harness can parse it cleanly.
    """
    payload = _stop_payload_from_stdin()
    sentinel_dir = _sentinel_dir_for(payload)
    if not sentinel_dir.is_dir():
        return 0
    result = evaluate_sentinels(sentinel_dir, session_id=_session_id_from(payload))
    _print_notices(result)
    if result.hot_pr is None:
        return 0
    if bool(payload.get("stop_hook_active", False)):
        print(
            f"Phase 5 sentinel hot for PR #{result.hot_pr}, but stop_hook_active "
            f"is set -- allowing stop to avoid a block loop. Delete "
            f"{result.hot_path} manually if Phase 5 closeout did not run.",
            file=sys.stderr,
        )
        return 0
    json.dump({"decision": "block", "reason": _block_reason(result.hot_pr)}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
