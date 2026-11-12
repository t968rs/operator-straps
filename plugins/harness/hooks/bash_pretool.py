#!/usr/bin/env python3
"""PreToolUse (Bash) entry point: the Bash hooks decided in one interpreter launch.

``bash_discipline.py``, ``bash_allow_shapes.py`` and ``approve_python_c.py`` used to be three registered
commands, each a separate launch, whose outputs Claude Code merged by precedence (deny over allow over no
decision). This script reads the payload once and runs their ``decide`` functions in the order that makes
the merge cheap. ``guard_locked`` runs first: it only denies (a write onto a Locked or ledger file), and a
deny outranks every allow the later hooks give. A discipline deny ends the run next; a ``python -c``
approval ends it after that, because the allow-shapes hook could only add the same decision. The single
printed output is the one the merge would have produced. A hook that raises counts as no decision (a note
goes to stderr), as its separate launch would have, so the later hooks still decide. The composed scripts
stay runnable on their own.

Unparseable input prints nothing. The deny hook honors its plugin option exactly as it does standalone.
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


def _discipline(payload: Any) -> Optional[str]:
    import bash_discipline

    return bash_discipline.decide(payload)


def _python_c(payload: Any) -> Optional[str]:
    import approve_python_c

    return approve_python_c.decide(payload)


def _allow_shapes(payload: Any) -> Optional[str]:
    import bash_allow_shapes

    return bash_allow_shapes.decide(payload)


HOOK_ORDER: Tuple[Callable[[Any], Optional[str]], ...] = (_locked, _discipline, _python_c, _allow_shapes)


def _guarded(hook: Callable[[Any], Optional[str]], payload: Any) -> Optional[str]:
    """One hook's decision, or None when its import or ``decide`` raises.

    Separate launches isolated each hook's failure; the guard keeps that, so one hook's exception leaves the
    later hooks free to decide.
    """
    try:
        return hook(payload)
    except Exception as exc:  # noqa: BLE001 - per-hook fault isolation
        print(f"bash_pretool: {hook.__name__} failed: {exc!r}", file=sys.stderr)
        return None


def decide(payload: Any) -> Optional[str]:
    """The hook output for ``payload``: a deny, else an allow, else None for no decision."""
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
