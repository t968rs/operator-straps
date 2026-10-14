"""Guard test pinning the pr-review SKILL.md YAML `description` to CSO doctrine.

Per superpowers:writing-skills, a skill description must specify ONLY the
triggering condition ("Use when ..."), never a workflow summary of what the
skill does. This test pins compression 1 from the 1096-SKILL-pr_review_05
SKILL.md compression sweep: the description starts with "Use when", omits
workflow-summary verbs that signal a CSO trap, and stays under 500 chars.
"""
import re
from pathlib import Path
from typing import Optional

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL_MD = _PLUGIN_ROOT / "skills" / "pr-review" / "SKILL.md"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_DESCRIPTION_RE = re.compile(
    r"^description:\s*(.+?)(?=\n[A-Za-z_]+:\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Verbs/phrases that mark a workflow summary instead of a triggering condition.
# Substring match, case-insensitive.
_FORBIDDEN_TOKENS = (
    "gathers",
    "consolidates",
    "runs mandatory",
    "then applies",
    "dispatches",
    "delegates to",
    "writes the consolidated",
    "verifies branch safety",
)


def _read_skill() -> str:
    if not _SKILL_MD.exists():
        pytest.fail(f"pr-review SKILL.md missing at {_SKILL_MD}")
    return _SKILL_MD.read_text(encoding="utf-8")


def _extract_description(text: str) -> Optional[str]:
    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        return None
    frontmatter = fm_match.group(1)
    desc_match = _DESCRIPTION_RE.search(frontmatter)
    if not desc_match:
        return None
    return desc_match.group(1).strip()


def test_description_present():
    text = _read_skill()
    assert _FRONTMATTER_RE.match(text), (
        "pr-review SKILL.md is missing YAML frontmatter delimited by '---'."
    )
    desc = _extract_description(text)
    assert desc, (
        "pr-review SKILL.md frontmatter has no `description:` field."
    )


def test_description_starts_with_use_when():
    desc = _extract_description(_read_skill()) or ""
    assert desc.lower().startswith("use when"), (
        "pr-review SKILL.md description must start with 'Use when ...' per "
        "writing-skills CSO doctrine. Got first 80 chars: "
        f"{desc[:80]!r}"
    )


def test_description_has_no_workflow_summary_verbs():
    desc = _extract_description(_read_skill()) or ""
    lower = desc.lower()
    leaks = [tok for tok in _FORBIDDEN_TOKENS if tok in lower]
    assert not leaks, (
        "pr-review SKILL.md description still contains workflow-summary "
        f"tokens {leaks}. Per CSO doctrine the description names triggering "
        "conditions only, not what the skill does. Rewrite as a 'Use "
        "when ...' clause focused on triggers."
    )


def test_description_length_cap():
    desc = _extract_description(_read_skill()) or ""
    assert len(desc) <= 500, (
        f"pr-review SKILL.md description is {len(desc)} chars; the cap is "
        "500. Tighten to a single triggering-condition clause."
    )
