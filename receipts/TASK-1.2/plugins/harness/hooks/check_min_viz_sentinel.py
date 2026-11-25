"""Stop and SubagentStop hook: block the arming session from ending while a ``--min-viz`` sentinel is armed.

``pr_sum.py capture --level 3 --min-viz`` writes ``<main checkout>/<state_dir>/pr-sum/.minviz_pending_<PR>``
(layout in ``harness_lib.min_viz_sentinel``); ``pr_sum.py build`` clears it once the draft holds the required
diagram blocks. While it exists, the arming session cannot stop: the hook emits the Stop-hook decision
``{"decision": "block", "reason": ...}`` on stdout and exits 0, the contract ``check_phase5_sentinel.py``
documents. The project comes from the payload ``cwd``, a linked worktree maps to its main checkout, and
``state_dir`` is read raw from ``harness.json`` with no schema validation, falling back to the plugin
default, so a config typo never disarms the gate (``check_phase5_sentinel.state_root_for``).

On ``Stop`` the registered command is ``stop_gates.py``, which runs ``decide`` here and in
``check_phase5_sentinel.py`` in one launch; ``SubagentStop`` runs this file on its own.

Allow-stop paths: no sentinel; a sentinel armed by another session (stderr notice; a sentinel with no owner,
or a payload with no ``session_id``, blocks); a sentinel older than ``MAX_AGE_SECONDS`` (stderr notice);
``stop_hook_active`` already set (loop break, stderr notice).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_phase5_sentinel import (  # noqa: E402
    _session_id_from,
    _stop_payload_from_stdin,
    emit_block,
    state_root_for,
)
from harness_lib.min_viz_sentinel import (  # noqa: E402
    SENTINEL_GLOB,
    SENTINEL_PREFIX,
    SENTINEL_SUBDIR,
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


def decide(payload: Dict[str, Any], state_root: Path) -> Optional[str]:
    """The block reason for the stopping session, or None to allow the stop (notices go to stderr)."""
    sentinel_dir = state_root / SENTINEL_SUBDIR
    if not sentinel_dir.is_dir():
        return None
    notices: List[str] = []
    armed = find_armed(sentinel_dir, _session_id_from(payload), notices)
    for notice in notices:
        print(notice, file=sys.stderr)
    if armed is None:
        return None
    if bool(payload.get("stop_hook_active", False)):
        print(
            f"--min-viz sentinel hot for PR #{armed.pr}, but stop_hook_active is set -- allowing stop to "
            f"avoid a block loop. Delete {armed.path} manually if the summary will not be built.",
            file=sys.stderr,
        )
        return None
    return _block_reason(armed)


def main() -> int:
    """Hook entry point; returns 0 always, enforcing through the JSON decision contract."""
    payload = _stop_payload_from_stdin()
    reason = decide(payload, state_root_for(payload))
    if reason:
        emit_block(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
