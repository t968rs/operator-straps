"""strap-skills documents ``strap.py reopen`` (plan 1014, DOC-1).

The SKILL.md runs ``reopen`` through the launcher in a fence, says how to pick its base and that earlier
behaviors are gated again; the repo README's strap-skills row names the command.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "plugins" / "harness" / "skills" / "strap-skills" / "SKILL.md"
LAUNCH = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" reopen <name>'


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _fenced_launch(text: str) -> bool:
    fenced = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            fenced = not fenced
        elif fenced and line.startswith(LAUNCH):
            return True
    return False


def test_skill_runs_reopen_through_the_launcher() -> None:
    assert _fenced_launch(_text(SKILL)), "no fenced reopen command"


def test_skill_names_the_round_rules() -> None:
    body = _flat(_text(SKILL))
    assert "**Reopen for new behaviors.**" in body
    start = body.index("**Reopen for new behaviors.**")
    end = body.index("13. **Hand off.**", start)
    section = body[start:end]
    assert "--base" in section and "rounds" in section, "reopen paragraph lacks --base or rounds"
    assert re.search(r"earlier behaviors[^.]*gated again", section), "earlier behaviors are not re-gated"


def test_readme_strap_row_names_reopen() -> None:
    row = next((line for line in _text(REPO_ROOT / "README.md").splitlines() if "`strap-skills`" in line), "")
    assert row, "README has no strap-skills row"
    assert "`reopen`" in row
