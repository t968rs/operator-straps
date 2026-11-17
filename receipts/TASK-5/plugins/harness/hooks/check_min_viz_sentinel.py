"""Stop and SubagentStop hook: block the arming session from ending while a ``--min-viz`` sentinel is armed.

``pr_sum.py capture --level 3 --min-viz`` writes ``<main checkout>/<state_dir>/pr-sum/.minviz_pending_<PR>``
(layout in ``harness_lib.min_viz_sentinel``); ``pr_sum.py build`` clears it once the draft holds the required
diagram blocks. While it exists, the arming session cannot stop: the hook emits the Stop-hook decision
``{"decision": "block", "reason": ...}`` on stdout and exits 0, the contract ``check_phase5_sentinel.py``
documents. The project comes from the payload ``cwd``, a linked worktree maps to its main checkout, and an
unusable harness config falls back to the raw or default ``state_dir``, so a config typo never disarms the
gate.

Allow-stop paths: no sentinel; a sentinel armed by another session (stderr notice; a sentinel with no owner,
or a payload with no ``session_id``, blocks); a sentinel older than ``MAX_AGE_SECONDS`` (stderr notice);
``stop_hook_active`` already set (loop break, stderr notice).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_phase5_sentinel import (  # noqa: E402
    _default_state_dir,
    _raw_state_dir,
    _resolve_project,
    _session_id_from,
    _stop_payload_from_stdin,
)
from harness_lib.config import ConfigError, activate, load_config  # noqa: E402
from harness_lib.min_viz_sentinel import (  # noqa: E402
    SENTINEL_GLOB,
    SENTINEL_PREFIX,
    sentinel_dir_under,
)

MAX_AGE_SECONDS = 86400  # 24 hours


@dataclass(frozen=True)
class Armed:
    """The sentinel that blocks the stopping session: PR number, required block count, file."""

    pr: str
    minimum: int
    path: Path


def _lines(path: Path) -> List[str]:
    """The sentinel's lines (CRLF tolerated); empty when unreadable."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _field(lines: List[str], index: int) -> str:
    """Stripped line ``index``, or an empty string when the sentinel is shorter."""
    return lines[index].strip() if len(lines) > index else ""


def _written_at(path: Path, lines: List[str]) -> Optional[int]:
    """The line-2 write time, else the file mtime; None when neither reads."""
    stamp = _field(lines, 1)
    if stamp.isdigit():
        return int(stamp)
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def _blocks(owner: str, session_id: Optional[str]) -> bool:
    """Whether a sentinel armed by ``owner`` blocks ``session_id``; unknown ids fail closed."""
    return not owner or session_id is None or owner == session_id


def _minimum(lines: List[str]) -> int:
    """The required block count on line 4; 0 when absent or malformed."""
    value = _field(lines, 3)
    return int(value) if value.isdigit() else 0


def find_armed(
        sentinel_dir: Path, session_id: Optional[str], notices: List[str], now: Optional[int] = None,
) -> Optional[Armed]:
    """First hot sentinel (sorted order) that blocks ``session_id``; skipped ones add a stderr notice."""
    now = int(time.time()) if now is None else now
    for path in sorted(sentinel_dir.glob(SENTINEL_GLOB)):
        pr, lines = path.name[len(SENTINEL_PREFIX):], _lines(path)
        written = _written_at(path, lines)
        if written is None:
            continue
        if now - written >= MAX_AGE_SECONDS:
            notices.append(f"--min-viz sentinel for PR #{pr} is stale (>24h); ignoring. Delete {path}")
        elif _blocks(_field(lines, 2), session_id):
            return Armed(pr, _minimum(lines), path)
        else:
            notices.append(f"--min-viz pending for PR #{pr} in another session; leave {path} in place")
    return None


def _block_reason(armed: Armed) -> str:
    """Block text fed back to the model; it steers to ``build``, never to deleting the sentinel."""
    need = f"at least {armed.minimum} diagram blocks" if armed.minimum else "its diagram blocks"
    return (
        f"pr-sum --min-viz is armed for PR #{armed.pr} and the summary is not built. Add {need} (fenced, "
        f"over 200 characters, with an arrow) to the draft, then run pr_sum.py build on the skeleton; a "
        f"successful build clears this gate. If this session is not writing that summary, leave the "
        f"sentinel in place and ask the developer."
    )


def _sentinel_dir_for(payload: Dict[str, Any]) -> Path:
    """Sentinel directory of the project holding the payload's ``cwd`` (else the process cwd)."""
    cwd = payload.get("cwd")
    project = _resolve_project(Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd()))
    try:
        cfg = activate(load_config(project))
    except ConfigError as exc:
        fallback = sentinel_dir_under(project, _raw_state_dir(project) or _default_state_dir())
        print(f"harness config unusable ({exc}); scanning {fallback} for --min-viz sentinels",
              file=sys.stderr)
        return fallback
    return sentinel_dir_under(cfg.project_root, cfg.state_dir)


def main() -> int:
    """Hook entry point; returns 0 always, enforcing through the JSON decision contract."""
    payload = _stop_payload_from_stdin()
    sentinel_dir = _sentinel_dir_for(payload)
    if not sentinel_dir.is_dir():
        return 0
    notices: List[str] = []
    armed = find_armed(sentinel_dir, _session_id_from(payload), notices)
    for notice in notices:
        print(notice, file=sys.stderr)
    if armed is None:
        return 0
    if bool(payload.get("stop_hook_active", False)):
        print(
            f"--min-viz sentinel hot for PR #{armed.pr}, but stop_hook_active is set -- allowing stop to "
            f"avoid a block loop. Delete {armed.path} manually if the summary will not be built.",
            file=sys.stderr,
        )
        return 0
    json.dump({"decision": "block", "reason": _block_reason(armed)}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
