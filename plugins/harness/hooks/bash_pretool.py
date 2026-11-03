#!/usr/bin/env python3
"""PreToolUse (Bash) entry point: the three Bash hooks decided in one interpreter launch.

``bash_discipline.py``, ``bash_allow_shapes.py`` and ``approve_python_c.py`` used to be three registered
commands, each a separate launch, whose outputs Claude Code merged by precedence (deny over allow over no
decision). This script reads the payload once and runs the same three ``decide`` functions in the order
that makes the merge cheap: a discipline deny ends the run, because a deny outranks every allow; a
``python -c`` approval ends it next, because the allow-shapes hook could only add the same decision. The
single printed output is the one the merge would have produced. The three scripts stay runnable on their own.

Unparseable input prints nothing. The deny hook honors its plugin option exactly as it does standalone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))


def decide(payload: Any) -> Optional[str]:
    """The hook output for ``payload``: a deny, else an allow, else None for no decision."""
    import bash_discipline

    denial = bash_discipline.decide(payload)
    if denial:
        return denial
    import approve_python_c

    approval = approve_python_c.decide(payload)
    if approval:
        return approval
    import bash_allow_shapes

    return bash_allow_shapes.decide(payload)


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
