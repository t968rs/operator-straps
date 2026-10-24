"""Behavior of plugins/harness/hooks/session_rules.py and the size of the rules it injects."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest
from harness_lib.commit_txt import CHANGE_ROUTE

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "harness"
HOOK = PLUGIN / "hooks" / "session_rules.py"
RULES = PLUGIN / "rules" / "HARNESS_RULES.md"
OPTION = "CLAUDE_PLUGIN_OPTION_INJECT_RULES"
RULES_LIMIT = 10000


def _run(option: Optional[str], payload: str = '{"hook_event_name": "SessionStart", "source": "startup"}'):
    env = {k: v for k, v in os.environ.items() if k != OPTION}
    if option is not None:
        env[OPTION] = option
    return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
                          env=env, encoding="utf-8")


def test_rules_file_stays_under_limit() -> None:
    assert len(RULES.read_text(encoding="utf-8")) < RULES_LIMIT


def test_rules_keep_drafted_commit_messages() -> None:
    text = " ".join(RULES.read_text(encoding="utf-8").replace("`", "").split())
    assert "A drafted commit message is final as saved." in text
    assert "a canned message included" in text
    assert CHANGE_ROUTE in text, "the rule's change routes drift from the receipt and the hook"


def test_saved_text_is_the_proposed_message() -> None:
    text = " ".join(RULES.read_text(encoding="utf-8").split())
    assert "is the proposed commit message wherever an instruction asks for one" in text


def test_rules_carry_no_project_specific_literals() -> None:
    text = RULES.read_text(encoding="utf-8")
    banned = (
        r"fpm|arcpy|floodplain|FPM_PY|scripts/__tests__|testRegistry|gh_workflows|agent_scripts"
        r"|\.claude/hooks"
    )
    assert re.search(banned, text, re.IGNORECASE) is None


@pytest.mark.parametrize("option", [None, "true", "1"])
def test_injects_rules_as_additional_context(option: Optional[str]) -> None:
    done = _run(option)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert out["additionalContext"] == RULES.read_text(encoding="utf-8")


@pytest.mark.parametrize("option", ["false", "FALSE", " false "])
def test_option_false_injects_nothing(option: str) -> None:
    done = _run(option)
    assert done.returncode == 0
    assert done.stdout == ""


def test_unparseable_payload_still_injects() -> None:
    done = _run(None, payload="")
    assert done.returncode == 0
    assert json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
