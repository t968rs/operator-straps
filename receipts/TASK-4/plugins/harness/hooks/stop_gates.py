#!/usr/bin/env python3
"""Stop entry point: the Phase 5 gate and the ``--min-viz`` gate decided in one interpreter launch.

``check_phase5_sentinel.py`` and ``check_min_viz_sentinel.py`` used to be two registered Stop commands, each
a separate launch that read the payload, resolved the project with git and loaded the harness config. This
script reads the payload once, resolves ``<main checkout>/<state_dir>`` once (``state_root_for``: the raw
``state_dir``, no schema validation) and runs each gate's ``decide`` against it. Each gate prints its own
notices to stderr. When both gates block, the one printed decision carries both reasons, so neither is lost.
A gate that raises counts as no decision (a note goes to stderr), as its separate launch would have, so the
other gate still decides. The composed scripts stay runnable on their own; ``SubagentStop`` still runs
``check_min_viz_sentinel.py`` alone.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_min_viz_sentinel  # noqa: E402
import check_phase5_sentinel  # noqa: E402

Gate = Callable[[Dict[str, Any], Path], Optional[str]]

HOOK_ORDER: Tuple[Gate, ...] = (check_phase5_sentinel.decide, check_min_viz_sentinel.decide)


def _guarded(gate: Gate, payload: Dict[str, Any], state_root: Path) -> Optional[str]:
    """One gate's block reason, or None when it raises (a note goes to stderr)."""
    try:
        return gate(payload, state_root)
    except Exception as exc:  # noqa: BLE001 - per-gate fault isolation
        print(f"stop_gates: {gate.__module__}.{gate.__name__} failed: {exc!r}", file=sys.stderr)
        return None


def decide(payload: Dict[str, Any], state_root: Path) -> Optional[str]:
    """The joined block reasons of every gate that blocks, or None to allow the stop."""
    reasons = [reason for reason in (_guarded(gate, payload, state_root) for gate in HOOK_ORDER) if reason]
    return "\n\n".join(reasons) or None


def main() -> int:
    """Hook entry point; returns 0 always, enforcing through the JSON decision contract."""
    payload = check_phase5_sentinel._stop_payload_from_stdin()
    reason = decide(payload, check_phase5_sentinel.state_root_for(payload))
    if reason:
        check_phase5_sentinel.emit_block(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
