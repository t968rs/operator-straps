"""Guard test pinning the deliberate asymmetry in pr-team-fixer.md Step 1:
the fixer's Phase 4 second-run does NOT forward --exclusions-fixture.

The orchestrator first-run forwards the flag (audit trail). The fixer second-run
omits it and relies on the script default. This is intentional under the current
single-fixture regime. If per-PR custom fixtures are introduced, this guard must
be deleted in the same PR that changes the fixer call.
"""

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
FIXER_PATH = PLUGIN_ROOT / "agents" / "pr-team-fixer.md"

SECOND_RUN_CMD = re.compile(
    r'sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hpy" '
    r'"\$\{CLAUDE_PLUGIN_ROOT\}/skills/pr-review/commands/phase4_branch_safety\.py"[^\n]*--second-run[^\n]*'
)


def test_fixer_second_run_omits_exclusions_fixture():
    if not FIXER_PATH.exists():
        raise AssertionError(f"Required file not found: {FIXER_PATH}")
    text = FIXER_PATH.read_text(encoding="utf-8")
    matches = SECOND_RUN_CMD.findall(text)
    assert matches, (
        f"Expected the second-run invocation pattern in {FIXER_PATH} — no phase4_branch_safety.py line "
        "containing --second-run found. "
        "If the call shape changed, update this test or delete it (and the asymmetry note "
        "in pr-team-fixer.md Step 1) per the I7 (b) contract."
    )
    offending = [m for m in matches if "--exclusions-fixture" in m]
    assert not offending, (
        f"The fixer-PLAN second-run invocation now includes --exclusions-fixture: {offending!r}. "
        "If this is intentional (e.g., per-PR custom fixtures are now supported), DELETE this "
        "guard test AND the asymmetry note in pr-team-fixer.md Step 1 in the same PR."
    )
