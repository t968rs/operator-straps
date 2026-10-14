"""Guard tests pinning the pr-review skill cross-artifact contract.

TDD seed for the 1096-SKILL-pr_review_05 restructure. Each test maps to a
finding in docs/PR_REVIEWS/0898_pr_review_skill_move_branch_safety.json and
fails today against the in-flight restructure; landing the restructure means
making each test pass by editing the named artifact in lockstep with
SKILL.md.

Failure model these tests guard against: SKILL.md changes its phase model or
verification_log shape, but sibling artifacts keep describing the old shape.
A future agent reading the stale sibling will follow contradictory
instructions for the same skill.

Tests:
- test_phase_count_consistency_skill_vs_schema_readme  (covers I1)
- test_verification_log_shape_post_forcepush           (covers I2)
- test_verification_log_shape_schema_readme            (covers I3)
- test_caller_contract_phase_anchor                    (covers I4)
- test_base_branch_sanity_in_phase4_check5             (covers I5 — see note)
- test_default_per_file_linear_sub_lens_is_pinned      (covers I6)

Note on I5: the bot reviewer (PR #898 review 4225567946) argued that
base-branch sanity belongs at dispatch time so a wrong-target PR is
caught before reviewer compute is spent. The canonical SKILL.md design
intentionally rejects that argument: the review itself still produces
useful output regardless of base, and the wasteful compute is the
user's call to make. Base-branch sanity therefore lives in Phase 4
Check 5 ("Record base branch — NOT always main") at pre-fix time. This
test pins the canonical location, NOT the bot's preferred location.
The corresponding PR_REVIEW JSON marks I5 CLOSED_NO_ACTION.

Note on I6: the I6 test asserts (a) the literal substring lives somewhere
in SKILL.md and (b) the catalog key default_sub_lenses[*].name is present.
This is the same presence-pinning enforcement model used for I1-I5 in this
file — the tests guard "skill author wrote the words" and "data artifact
carries the matching key", NOT runtime dispatcher behavior. Runtime
enforcement (that bucket reviewers actually run the linear pass) is
asserted by SKILL.md prose alone and audited by reviewers reading the
phase-flow. Tightening to a section-anchored regex would be a future
hardening, not a current gap.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_PHASE_HEADER_RE = re.compile(r"^##\s+Phase\s+(\d+)\b", re.MULTILINE)


def _skill_md(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "pr-review" / "SKILL.md"


def _schema_readme(plugin_root: Path) -> Path:
    return plugin_root / "schemas" / "README.md"


def _post_forcepush(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "post-forcepush" / "SKILL.md"


def _caller_contracts(plugin_root: Path) -> list:
    """Every skill and agent definition of the plugin: the texts a caller of pr-review reads."""
    return sorted((plugin_root / "skills").glob("*/SKILL.md")) + sorted((plugin_root / "agents").glob("*.md"))


def _cross_cutting_catalog(plugin_root: Path) -> Path:
    return plugin_root / "schemas" / "catalogs" / "CrossCuttingLensCatalog.json"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"Required artifact missing: {path}")
    return path.read_text(encoding="utf-8")


def _max_phase(text: str) -> int:
    matches = _PHASE_HEADER_RE.findall(text)
    if not matches:
        return 0
    return max(int(m) for m in matches)


# ---- I1 -------------------------------------------------------------------

def test_phase_count_consistency_skill_vs_schema_readme(plugin_root: Path):
    """Cross-artifact phase-count agreement (I1).

    SKILL.md uses '## Phase N' headers; schema README cites pr-review phases
    inline (e.g., 'Phase 1 — verify envelope ... Phase 2 ... Phase 3'). Both
    must claim the same maximum phase. Today: SKILL.md=5 (or 4),
    README=3 → fails.
    """
    skill_text = _read(_skill_md(plugin_root))
    skill_max = _max_phase(skill_text)
    assert skill_max >= 3, (
        "SKILL.md has no '## Phase N' headers — re-check the skill's "
        "structure before pinning sibling artifacts to it."
    )

    readme_text = _read(_schema_readme(plugin_root))
    readme_phase_mentions = re.findall(r"Phase\s+(\d+)", readme_text)
    readme_max = max((int(p) for p in readme_phase_mentions), default=0)

    assert readme_max == skill_max, (
        f"Phase count drift: SKILL.md describes {skill_max} phases, "
        f"agent-schemas/README.md describes {readme_max}. "
        f"Update README's pr-review block (~line 116-124) to match."
    )


# ---- I2 -------------------------------------------------------------------

def test_verification_log_shape_post_forcepush(plugin_root: Path):
    """post-forcepush must update nested verification_log paths (I2).

    SKILL.md Phase 4 writes `verification_log.pre_fix_time.<check>`. The
    post-forcepush skill currently refreshes `verification_log.<check>` at
    the OLD flat top level — silent no-op refresh against new-schema JSONs.

    This test fails today.
    """
    pf_text = _read(_post_forcepush(plugin_root))

    # The flat references that must be removed.
    flat_refs = [
        "verification_log.pr_metadata_check",
        "verification_log.sha_ancestry_check",
    ]
    leaks = [ref for ref in flat_refs if ref in pf_text]
    assert not leaks, (
        f"post-forcepush/SKILL.md still cites flat verification_log paths "
        f"{leaks}. After PR #898 lands the nested model, these must be "
        f"`verification_log.pre_fix_time.<check>` (or the equivalent "
        f"nested key adopted by the restructure)."
    )

    # And the nested form must be present.
    assert (
        "verification_log.pre_fix_time" in pf_text
        or "verification_log.dispatch_time" in pf_text
    ), (
        "post-forcepush/SKILL.md does not reference the nested "
        "`verification_log.pre_fix_time.*` / `dispatch_time.*` paths "
        "introduced by the pr-review restructure. Update Step 3."
    )


# ---- I3 -------------------------------------------------------------------

def test_verification_log_shape_schema_readme(plugin_root: Path):
    """agent-schemas/README.md must document the nested shape (I3).

    Today the README says verification_log is a flat seven-sub-object set;
    after the restructure it must describe `dispatch_time` and
    `pre_fix_time` as the two top-level groupings.
    """
    readme_text = _read(_schema_readme(plugin_root))

    has_nested_doc = (
        "dispatch_time" in readme_text and "pre_fix_time" in readme_text
    )
    legacy_phrasing = "seven sub-objects" in readme_text or (
        "current_branch_check" in readme_text
        and "dispatch_time" not in readme_text
    )

    assert has_nested_doc and not legacy_phrasing, (
        "agent-schemas/README.md verification_log block (~line 168-174) "
        "still describes the flat seven-sub-object shape and does not "
        "mention `dispatch_time` / `pre_fix_time`. Update it to match "
        "the SKILL.md Phase 1 vs Phase 4 split."
    )


# ---- I4 -------------------------------------------------------------------

def test_caller_contract_phase_anchor(plugin_root: Path):
    """No plugin skill or agent text claims pre-dispatch branch safety (I4).

    pr-review runs branch safety *pre-fix* (Phase 4), not pre-dispatch. A
    caller-facing text saying 'pre-dispatch safety checks' gives agents the
    opposite assumption.
    """
    forbidden = "pre-dispatch safety checks"
    leaks = [p.relative_to(plugin_root).as_posix() for p in _caller_contracts(plugin_root)
             if forbidden in p.read_text(encoding="utf-8")]
    assert not leaks, (
        f"{leaks} still say '{forbidden}'. pr-review moved branch safety "
        "out of dispatch time; say 'pre-fix branch safety verification'."
    )


# ---- I5 -------------------------------------------------------------------

def test_base_branch_sanity_in_phase4_check5(plugin_root: Path):
    """base-branch sanity is the Phase 4 Check 5 gate (I5 — closed-no-action).

    Bot reviewer wanted this at Phase 1; canonical SKILL.md keeps it at
    Phase 4 Check 5. This test pins the SKILL.md design: Phase 4 must
    contain a check that records `baseRefName` and pauses if it is
    anything other than the project's configured base branch.

    Failure of this test means SKILL.md drifted away from the design,
    not that the bot was right.
    """
    text = _read(_skill_md(plugin_root))

    # Find Phase 4 section bounds.
    phase4_match = re.search(
        r"##\s+Phase\s+4[^\n]*\n(.*?)(?=##\s+Phase\s+\d|\Z)",
        text,
        re.DOTALL,
    )
    assert phase4_match, "Could not locate '## Phase 4' section in SKILL.md"
    phase4_block = phase4_match.group(1)

    # Phase 4 must mention baseRefName + recording against the configured base branch.
    has_record_step = (
        re.search(
            r"baseRefName", phase4_block, re.IGNORECASE
        )
        is not None
        and re.search(
            r"configured base branch", phase4_block, re.IGNORECASE
        )
        is not None
    )

    # And it must instruct a pause / confirmation when base is unusual.
    has_pause_instruction = (
        re.search(
            r"(pause|confirm|stop|abort|unusual|other than)",
            phase4_block,
            re.IGNORECASE,
        )
        is not None
    )

    assert has_record_step and has_pause_instruction, (
        "Phase 4 of pr-review/SKILL.md no longer contains the "
        "base-branch sanity check (Check 5: record baseRefName, pause "
        "if not the configured base branch). This is the canonical home of the sanity "
        "gate; SKILL.md must not drop it."
    )


def test_default_per_file_linear_sub_lens_is_pinned(plugin_root: Path):
    """Bucket reviewers must run default linear docstring-vs-code pass.

    The issue fix adds a mandatory default sub-lens to bucket-sort and records
    it in CrossCuttingLensCatalog metadata so scoping docs stay synchronized.
    """
    skill_text = _read(_skill_md(plugin_root))
    assert "linear docstring-vs-code pass" in skill_text, (
        "pr-review SKILL.md is missing the mandatory default per-file linear "
        "docstring-vs-code sub-lens in Phase 2 bucket-sort."
    )

    catalog_path = _cross_cutting_catalog(plugin_root)
    catalog = json.loads(_read(catalog_path))
    default_lenses = catalog.get("default_sub_lenses", [])
    names = {lens.get("name") for lens in default_lenses if isinstance(lens, dict)}
    assert "linear docstring-vs-code pass" in names, (
        "CrossCuttingLensCatalog.json must include default_sub_lenses entry "
        "'per-file-linear-docstring-vs-code' to keep supporting metadata in sync."
    )


# ---- plugin-root literals and shell lens triggers -------------------------

_NON_RAW_ROOT = re.compile(r"(?<![rR])'\$\{CLAUDE_PLUGIN_ROOT\}")


def test_no_plugin_root_in_a_non_raw_python_string(plugin_root: Path):
    """A Windows plugin root (``C:\\Users\\...``) inside a plain Python literal is a ``\\U`` escape error."""
    leaks = [f"{p.relative_to(plugin_root).as_posix()}:{n}" for p in _caller_contracts(plugin_root)
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if _NON_RAW_ROOT.search(line)]
    assert not leaks, f"{leaks}: use r'${{CLAUDE_PLUGIN_ROOT}}' or the pr_review.py `config` subcommand"


def _lens(plugin_root: Path, name: str) -> dict:
    catalog = json.loads(_read(_cross_cutting_catalog(plugin_root)))
    return next(lens for lens in catalog["lenses"] if lens["name"] == name)


def _run_trigger(command: str, cwd: Path, paths: list, env: dict) -> str:
    """Run a lens ``detection_command`` under ``sh`` with ``gh`` replaced by a function printing ``paths``."""
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX sh on PATH")
    fake_gh = "gh() { printf '%s\\n' " + " ".join(f"'{p}'" for p in paths) + "; }; "
    done = subprocess.run([sh, "-c", fake_gh + command], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "PR": "1", **env})
    return done.stdout.strip()


@pytest.mark.parametrize("skills_dir", [None, ".claude/skills"])
def test_per_skill_package_trigger_fires_on_the_configured_skills_dir(plugin_root: Path, make_project,
                                                                      skills_dir):
    """The shell trigger fires for the default ``skills_dir`` (trailing slash) and a slash-less one."""
    from harness_lib.config import load_config
    root = make_project(files={".claude/skills/pr-review/SKILL.md": "# pr-review\n",
                               ".claude/skills/lonely/SKILL.md": "# solo\n",
                               "docs/guide.md": "Run pr-review first.\n"})
    value = skills_dir or load_config(root).skills_dir
    command = _lens(plugin_root, "per-skill-package")["trigger"]["detection_command"]
    paths = [".claude/skills/pr-review/SKILL.md", ".claude/skills/lonely/SKILL.md", ".claude/skillsXpr/a.md"]
    assert _run_trigger(command, root, paths, {"SKILLS_DIR": value}) == "pr-review"


@pytest.mark.parametrize("schemas_dir", ["schemas", "schemas/"])
def test_coordinated_multi_artifact_trigger_counts_schemas_dir_files(plugin_root: Path, tmp_path: Path,
                                                                     schemas_dir: str):
    command = _lens(plugin_root, "coordinated-multi-artifact")["trigger"]["detection_command"]
    paths = ["schemas/a.json", "x/b.schema.json", "src/c.py", "schemasX/d.json"]
    assert _run_trigger(command, tmp_path, paths, {"SCHEMAS_DIR": schemas_dir}) == "2"
