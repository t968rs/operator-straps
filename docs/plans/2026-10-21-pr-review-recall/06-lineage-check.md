# 06 - Mechanical lineage check at `capture`

Repository: `E:/automation/operator-straps`. Read `CLAUDE.md` there first. Index: `00-INDEX.md` beside this file.

## Goal

`capture` runs a model-free check over the lines the PR adds and records what it finds as a folded findings
source, so `merge` treats it like a reviewer slot. It flags:

1. An added line that names **another open PR** by number (`PR #N`, `#N` in a `PR`/`pull` context, or a
   `.../pull/N` URL), where N is not the PR under review.
2. An added line that names the **head branch of another open PR**.
3. A changed design-evolution catalog (a JSON file under the configured research root whose content validates
   against `schemas/catalogs/DesignEvolutionCatalog.schema.json`, resolved pinned-first as the plugin already
   does) whose `pr` is not the PR under review (`0` included), or whose `branch_lineage` does not end with the
   PR's head branch.

## Evidence

- PR #1627 **M14**: after the developer recreated #1625 as #1627 on a new branch, the spec, the TODO catalog and
  `DesignEvolution.json` still credited "PR #1625" / `0019-unit-ft-flavor`. #1625 was still open, so rule 1 and 2
  would have caught it at `capture`.
- PR #1625 **M1**: `DesignEvolution.json` shipped with `"pr": 0`. Rule 3 would have caught it.

Review JSONs: `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1625_0019_unit_ft_flavor.json`
(M1) and `.../1627_Feature_UnitOfMeasureDraft.in_flavor_of_foot-flavor_matching.json` (M14).

## Current code

- `plugins/harness/scripts/pr_review.py:764` `_cmd_capture`; `:331` `read_metadata` (the one `gh pr view`);
  `:241` `run_gh`.
- Folded sources: `:1154` `_cmd_fold`, `:1139` `fold_entry`, `:1133` `with_folded`; `merge` reads them through
  `:804` `report_sources` / `:820` `source_reports`. A folded source is `findings/<ID>.json` holding the same
  `ReviewerReport` model reviewers write (`lib/harness_lib/review_models.py:228`, written via `record`).
- Added lines per path: `lib/harness_lib/pr_capture.py:272` `file_patches` gives each path's diff text.
- `FOLD_KINDS` (`pr_review.py:225`): `external`, `tests`, `developer`, `adhoc`.

## Requirements

1. New config key `review.lineage_check` (boolean, default `true`). Follow the four-place rule in `CLAUDE.md`
   (`config/defaults.json`, `config/harness.schema.json`, `lib/harness_lib/config.py`, the README key table).
2. When enabled, `capture` makes one extra `gh` call: `gh pr list --state open --json number,headRefName
   --limit 500`. A `gh` failure records the check as `skipped` with the error in `plan.json` and never fails
   `capture`.
3. Scan only added lines (`+` lines, not `+++`) of reviewable paths (after exclusions). Skip the PR's own number
   and head branch. Match branch names as whole tokens.
4. Rule 3 reads the catalog at the PR head (working tree when `tree_at_head`, else `git show`).
5. Each hit becomes one `Finding`: severity `minor`, `fix_kind` `mechanical`, `file` the path, `lines` the
   head-side line number, a `name` like `Names open PR #1625 (head 0019-unit-ft-flavor), not this PR`, a `summary`
   quoting the line, and one `fix` option: retarget to PR #<this> / `<this head>`, or state that the other PR is a
   separate change. Group all hits of one file into one finding with `lines` listing each line.
6. Write the findings as `findings/lineage_check.json` through the same writer `record` uses, and register the
   source in `plan.json` `folded` with kind `adhoc` and source id `lineage_check`, exactly as a pre-build `fold`
   would. No hits: write nothing and register nothing.
7. `capture`'s status line gains `lineage: <n> hit(s)` / `lineage: skipped (<reason>)` / `lineage: off`.
8. SKILL.md: Phase 1 gains a "Check 3 - lineage literals" subsection (what it scans, that it folds a source,
   that it never blocks `capture`), and Phase 3 Step 0 mentions that `lineage_check` arrives already folded.
   `pr-team`: add one sentence to `plugins/harness/agents/pr-team-orchestrator.md` PLAN mode pointing at the same
   check, or report the gap.

## Tests

Red first. Extend `tests/scripts/test_pr_review_driver.py` with a fake `gh` (the file already stubs `run_gh`;
follow its pattern):

- an added doc line naming another open PR number: one finding, `lines` correct, source registered as folded;
- an added line naming another open PR's head branch: one finding;
- the PR's own number and branch: no finding;
- a removed line naming another open PR: no finding;
- a catalog with `"pr": 0`, and one with a `branch_lineage` ending in another branch: one finding each;
- `gh pr list` failing: `capture` exits 0, status line says `skipped`;
- `review.lineage_check: false`: no `gh pr list` call, `lineage: off`;
- `merge` after `capture` includes the lineage finding and credits `lineage_check (adhoc)`.

Commands:

- `python -m pytest tests/scripts/test_pr_review_driver.py -q`
- `python -m pytest tests/lib/test_review_merge.py -q`
- `python -m pytest tests/skills/test_pr_review_skill_contract.py -q`
- the config tests that pin the key table and defaults (find them with
  `python tools/select_tests.py --base main` after the edit; run each by file)
- `python -m pytest tests/contract/test_no_repo_literals.py -q`
- `python -m ruff check <changed files>`

## Out of scope

Rewriting the literals (the fixer does that). Closed or merged PR numbers (citing history is legitimate).

## Done

Changed files listed; commands green with counts; the new SKILL.md subsection quoted in the report.
