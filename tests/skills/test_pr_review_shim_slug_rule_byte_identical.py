"""Guard test pinning the slug-rule transform byte-identical between SKILL.md and orchestrator.md.

SKILL.md asserts: "The canonical authoritative copy of this 4-step transform also lives in
pr-team-orchestrator.md CONSOLIDATE Step 4 (the actual producer). A guard test pins
them byte-identical; if they ever drift, the agent's copy wins."

This test enforces that claim. The extracted slug rule is the run of text starting
at "(1) replace every backtick" through "(5) ... and trim trailing underscores." inclusive.

**Single-occurrence constraint:** the regex extracts EXACTLY ONE match per file. If
a future maintainer copies the slug-rule paragraph into a third location inside either
file (e.g., a docs example, a troubleshooting note, a "see also" section), the test
fails with "expected exactly 1". The fix in that case is to keep ONE canonical copy
per file and reference it from the other locations, not to relax this assertion —
the byte-identity guarantee only holds if both files have exactly one source-of-truth
location each.
"""

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
SKILL_PATH = PLUGIN_ROOT / "skills" / "pr-team" / "SKILL.md"
ORCHESTRATOR_PATH = PLUGIN_ROOT / "agents" / "pr-team-orchestrator.md"

SLUG_RULE_PATTERN = re.compile(
    r"\(1\) replace every backtick.*?and trim trailing underscores\.",
    re.DOTALL,
)


def _extract_slug_rule(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"Required file not found: {path}")
    text = path.read_text(encoding="utf-8")
    matches = SLUG_RULE_PATTERN.findall(text)
    if not matches:
        raise AssertionError(f"Slug-rule block not found in {path}")
    if len(matches) > 1:
        raise AssertionError(f"Slug-rule block appeared {len(matches)} times in {path}; expected exactly 1")
    return matches[0]


def test_slug_rule_byte_identical_skill_vs_orchestrator():
    skill_rule = _extract_slug_rule(SKILL_PATH)
    orchestrator_rule = _extract_slug_rule(ORCHESTRATOR_PATH)
    assert skill_rule == orchestrator_rule, (
        "Slug-rule transform has drifted between SKILL.md and pr-team-orchestrator.md.\n"
        "Per SKILL.md, the agent's copy wins — sync SKILL.md to match orchestrator.md.\n\n"
        f"SKILL.md ({SKILL_PATH}):\n{skill_rule!r}\n\n"
        f"orchestrator.md ({ORCHESTRATOR_PATH}):\n{orchestrator_rule!r}"
    )
