#!/usr/bin/env python3
"""PreToolUse (PowerShell) entry point: the PowerShell hooks decided in one interpreter launch.

Runs ``guard_locked`` (a write onto a Locked plan or strap file, or into the freeze ledger) before
``powershell_allow_shapes`` (an allow for a fully allowlisted pipeline). A deny outranks every allow, so the
first non-None output is the one Claude Code's merge of separate launches would have produced. A hook that
raises counts as no decision (a note goes to stderr), as its separate launch would have, so the later hook
still decides. The composed scripts stay runnable on their own.

Unparseable input prints nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _locked(payload: Any) -> Optional[str]:
    import guard_locked

    return guard_locked.decide(payload)


def _allow_shapes(payload: Any) -> Optional[str]:
    import powershell_allow_shapes

    return powershell_allow_shapes.decide(payload)


HOOK_ORDER: Tuple[Callable[[Any], Optional[str]], ...] = (_locked, _allow_shapes)


def _guarded(hook: Callable[[Any], Optional[str]], payload: Any) -> Optional[str]:
    """One hook's decision, or None when its import or ``decide`` raises."""
    try:
        return hook(payload)
    except Exception as exc:  # noqa: BLE001 - per-hook fault isolation
        print(f"powershell_pretool: {hook.__name__} failed: {exc!r}", file=sys.stderr)
        return None


def decide(payload: Any) -> Optional[str]:
    """A deny, else an allow, else None for no decision."""
    for hook in HOOK_ORDER:
        output = _guarded(hook, payload)
        if output:
            return output
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    output = decide(payload)
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
