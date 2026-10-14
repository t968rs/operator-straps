#!/usr/bin/env python3
"""SessionStart hook: add the harness rules (``rules/HARNESS_RULES.md``) to the session context.

Disabled when the plugin option ``inject_rules`` is ``false`` (``CLAUDE_PLUGIN_OPTION_INJECT_RULES`` set to
``false`` or ``0``). The payload is not consulted; a missing rules file injects nothing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

OPTION_ENV = "CLAUDE_PLUGIN_OPTION_INJECT_RULES"
RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "HARNESS_RULES.md"


def enabled() -> bool:
    """False only when the plugin option is explicitly ``false`` or ``0``."""
    return os.environ.get(OPTION_ENV, "").strip().lower() not in {"false", "0"}


def rules_text() -> Optional[str]:
    """The rules file content, or None when it is missing or unreadable."""
    try:
        return RULES_PATH.read_text(encoding="utf-8")
    except OSError:
        return None


def main() -> int:
    text = rules_text() if enabled() else None
    if text:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
