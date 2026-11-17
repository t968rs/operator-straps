"""Guard test for I12 (a): canonical_prompt_template.md is the single source-of-truth
for the per-agent prompt body. SKILL.md and dispatch_plan.schema.json may NOT
inline a competing template body.
"""

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
TEMPLATE_PATH = PLUGIN_ROOT / "skills" / "pr-team" / "canonical_prompt_template.md"
SKILL_PATH = PLUGIN_ROOT / "skills" / "pr-team" / "SKILL.md"

DISALLOWED_INLINE_MARKERS = (
    "AGENT_ID: {id}",
    "AGENT_ROLE: {agent_role}",
    "PROMPT_FILE: {prompt_file_path}",
    "OUTPUT_FILE: {output_file_path}",
    "RETURN_CONTRACT: {return_contract_path}",
    "RUN_ID: {run_id}",
)


def test_canonical_template_file_exists():
    assert TEMPLATE_PATH.exists(), (
        f"canonical_prompt_template.md missing at {TEMPLATE_PATH}. "
        "Single-source contract requires this file to be present."
    )


def test_canonical_template_still_holds_template_body():
    """Guards against silent regression: if someone deletes the template body from
    canonical_prompt_template.md, SKILL.md's 'reference by path' assertion would pass
    trivially while the canonical file no longer holds the template. The canonical
    file's purpose is to BE the single source of truth referenced elsewhere — it
    must always contain the verbatim template body markers."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    missing = [marker for marker in DISALLOWED_INLINE_MARKERS if marker not in text]
    assert not missing, (
        f"canonical_prompt_template.md is missing template body markers: {missing!r}. "
        "The canonical file MUST contain the verbatim template body — its purpose is "
        "to be the single source of truth referenced by SKILL.md and the agent definitions."
    )


def test_skill_md_references_canonical_template_by_path():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "canonical_prompt_template.md" in text, (
        "SKILL.md does not reference canonical_prompt_template.md by path. "
        "I12 contract requires SKILL.md to reference, not inline."
    )


def test_skill_md_does_not_inline_template_body():
    text = SKILL_PATH.read_text(encoding="utf-8")
    leaked = [marker for marker in DISALLOWED_INLINE_MARKERS if marker in text]
    assert not leaked, (
        f"SKILL.md inlines template body markers that must live only in "
        f"canonical_prompt_template.md: {leaked!r}. Remove the inlined block."
    )
