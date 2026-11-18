# 03 - Registry entries of touched tests: always shown, always checked

Repository: `E:/automation/operator-straps`. Read `CLAUDE.md` there first. Index: `00-INDEX.md` beside this file.

## Goal

When a PR adds or edits a test file that has a registry entry (`tests.registry` / `tests.registry_names`), every
reviewer whose scope holds that test or the registry sees the entry's **current text at the PR head**, and is
told to check it against the test. The budgeted diff may still summarize the registry hunk, but the entries
themselves are never summarized away.

## Evidence

In PR #1625's run, the registry diff was summarized in both the `tests` and the `roast` briefs:
`E:/automation/toolboxes/floodplain_development/docs/_scratch/pr_review/1625/pr1625_20261021T185921Z/briefs/tests.md:23-24`
("Summarized or omitted in the diff ... testRegistry.json"). The reviewers caught the stale entries for the
`geometry_fields` tests (#1625 I2, M4) and missed the same defect on sibling entries. PR #1627's run then found:

- **M4**: the `test_calculate_geometry.py` / `test_calculate_geometry_local.py` summaries omitted the flavor
  classes the PR added (`TestSrFlavorMatching`, `TestFootFlavorFollowsSr`).
- **M5**: the new contract test's `test_target_paths` omitted `unit_refs.py`, which its parametrization reads.
- **I3** (from a fix wave, not catchable at first review): `test_spatial_ops_local.py` gained a test whose
  dependencies were not in its targets.

## Current code

- Registry access: `plugins/harness/scripts/pr_review.py:1539` `_registry_rows`, `:1549` `registry_entries`
  (reads `tests[].file` and `tests[].properties.test_target_paths`; that is the shape the plugin already assumes).
- Brief assembly: `pr_review.py:637` `scope_section`, `:688` `rules_section`, `:721` `reviewer_brief`, `:728`
  `write_briefs`.
- Diff budget: `plugins/harness/lib/harness_lib/pr_capture.py:292` `budgeted_diff`, which uses
  `harness_lib/commit_diff.py:73` `plan_reads` (paths past the block budget become `summary`).
- Config: `tests.registry` and `tests.registry_names` in `plugins/harness/config/defaults.json`; the dataclass in
  `lib/harness_lib/config.py`.
- Reviewer briefs read the tree with `Read` when `tree_at_head`, else `git show <head_sha>:<path>`; the excerpt
  must be read at the PR head the same way (`pr_capture` helpers already do head reads; reuse them).

## Requirements

1. At `capture`, collect the **touched registered tests**: every PR path (status A or M, not D) that is a test path
   (`active().tests.is_test_path`) and has a registry entry at the PR head. A registry file that the PR does not
   touch is still read at the head when a touched test has an entry in it.
2. For every slot whose scope holds a touched registered test or a registry file, the brief gains a section
   `## Registry entries of touched tests` listing, per test: the test path, the entry's `summary` when the entry
   has a string `summary` key, its `test_target_paths`, and whether the PR diff changed that entry (yes / no).
   Render the entry fields as a fenced JSON block per test, so long summaries stay intact.
3. The same section ends with the instruction: for each entry, check that the summary describes the test classes
   the PR adds or changes, and that every module the test imports or names in its docstring as a dependency is a
   target; flag a missing target or a stale summary as a finding on the registry file (`also`: the test file).
4. A touched registered test whose entry the PR did not change is listed first, marked `entry unchanged in this
   PR`, because that is the likeliest stale case.
5. A touched test with no registry entry, when a registry is configured, is listed as `not registered`.
6. No consuming-project names: the code reads only configured keys and the `tests[].file` /
   `properties.test_target_paths` / optional `summary` shape.
7. Keep `budgeted_diff` unchanged; the excerpt is the guarantee, not the diff.
8. Mirror the requirement in `plugins/harness/skills/pr-review/SKILL.md` ("Prompt and brief contract": what the
   brief carries). `pr-team` builds its own briefs in `plugins/harness/agents/pr-team-orchestrator.md`: add one
   sentence there telling the orchestrator to include the same section (it can call the new helper through
   `pr_review.py`; if that is not wired today, state the gap in the report instead of building it).

## Tests

Red first, in `tests/scripts/test_pr_review_driver.py`, using `make_project` (`tests/conftest.py`) to build a
project with a registry:

- a touched test with an unchanged entry: the brief lists it first with `entry unchanged in this PR`;
- a touched test whose entry changed: listed with `changed: yes`;
- an unregistered touched test: `not registered`;
- a slot without tests or registry in scope: no section;
- an entry without `summary`: rendered without it, no error.

Commands:

- `python -m pytest tests/scripts/test_pr_review_driver.py -q`
- `python -m pytest tests/skills/test_pr_review_skill_contract.py -q`
- `python -m pytest tests/contract/test_no_repo_literals.py -q`
- `python -m ruff check plugins/harness/scripts/pr_review.py tests/scripts/test_pr_review_driver.py`

## Out of scope

Wave planning and fixer ownership of the registry (prompt 02). Mechanical import-vs-target analysis (the
reviewer does that from the excerpt).

## Done

Changed files listed; commands green with counts; one sample brief section pasted in the report (from a test
fixture, not a real project).
