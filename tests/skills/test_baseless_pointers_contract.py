"""Guard test: every claim-making pointer in the plugins leads to ``harness:baseless``.

post-forcepush's verification step, its report and its common-mistakes row, the session rules' claim-making
rule and the parallel2 README's evidence row each named an outside verification skill. A project without
that plugin could not finish post-forcepush, and the rules sent every session to a skill that may be absent.
The last test walks the plugins' text files (markdown, Python, TypeScript, JSON and the like) so a new
pointer to the outside skill fails here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

WALK_ROOTS = ("plugins/",)
_REPO = Path(__file__).resolve().parents[2]
_PLUGINS = _REPO / "plugins"
_HARNESS = _PLUGINS / "harness"
_FORCEPUSH = _HARNESS / "skills" / "post-forcepush" / "SKILL.md"
_RULES = _HARNESS / "rules" / "HARNESS_RULES.md"
_PARALLEL2_README = _HARNESS / "skills" / "parallel2" / "README.md"
_OUTSIDE = re.compile(r"verification[-_ ]before[-_ ]completion", re.I)
_TEXT_SUFFIXES = frozenset({".md", ".py", ".ts", ".tsx", ".js", ".json", ".tmpl", ".sh", ".css"})


def _section(text: str, heading: str) -> str:
    found = re.search(rf"^## {re.escape(heading)}.*?(?=^## |\Z)", text, re.M | re.S)
    assert found, f"no section starting {heading!r}"
    return found.group(0)


def test_post_forcepush_step_six_invokes_baseless() -> None:
    step = _section(_FORCEPUSH.read_text(encoding="utf-8"), "Step 6")
    assert "`harness:baseless`" in step, "Step 6 does not name the bundled skill"
    assert "Skill tool" in " ".join(step.split()), "Step 6 no longer invokes a skill"


def test_post_forcepush_report_and_mistakes_name_baseless() -> None:
    text = _FORCEPUSH.read_text(encoding="utf-8")
    item = re.search(r"^5\. .*\(Step 6\)", text, re.M)
    assert item and "`harness:baseless`" in item.group(0), "report item 5 does not name the bundled skill"
    rows = [line for line in text.splitlines() if line.startswith("| Skipping")]
    assert rows and all("`harness:baseless`" in row for row in rows), "the mistakes row names another skill"


def test_the_making_claims_rule_names_baseless() -> None:
    text = _RULES.read_text(encoding="utf-8")
    rule = re.search(r"^- \*\*Making claims:\*\*.*?(?=^- |^## |\Z)", text, re.M | re.S)
    assert rule, "HARNESS_RULES.md has no Making claims rule"
    assert "`harness:baseless`" in rule.group(0)


def test_the_parallel2_evidence_row_names_baseless() -> None:
    rows = [line for line in _PARALLEL2_README.read_text(encoding="utf-8").splitlines()
            if line.startswith("| W4 |")]
    assert rows, "the parallel2 README has no W4 row"
    assert all("`harness:baseless`" in row for row in rows)


def _text_lines(path: Path) -> List[str]:
    """Return the file's lines, or none for a file that is not UTF-8 text."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


def test_no_live_pointer_to_the_outside_verification_skill() -> None:
    hits: List[str] = []
    for path in sorted(_PLUGINS.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        for number, line in enumerate(_text_lines(path), 1):
            if _OUTSIDE.search(line):
                hits.append(f"{path.relative_to(_REPO).as_posix()}:{number}")
    assert not hits, f"pointers to the outside verification skill remain: {hits}"
