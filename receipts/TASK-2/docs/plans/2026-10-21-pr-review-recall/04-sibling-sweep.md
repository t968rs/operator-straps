# 04 - Sibling sweep before `build`

Repository: `E:/automation/operator-straps`. Read `CLAUDE.md` there first. Index: `00-INDEX.md` beside this file.

## Goal

After `merge` (and any `amend`), one more reviewer pass takes the draft's findings as **patterns** and searches the
whole reviewable scope for other instances of each pattern that no draft issue covers yet. Its findings join the
draft before `build`, so a defect class found once is fixed everywhere in the same review.

## Evidence

PR #1625's run found the pattern and stopped at the first instance:

- #1625 **I2**: "Registry targets omit the flavor-rule modules the geometry-field tests now pin". It covered the two
  `geometry_fields` entries. The contract test entry had the same gap (`unit_refs.py`): PR #1627 **M5**.
- #1625 **M4**: "Registry summaries state the flavor behavior this PR inverted". It covered the
  `geometry_fields` summaries. The `calculate_geometry` summaries had the same staleness: PR #1627 **M4**.
- #1625 **I3**: "Phase 2 small-feature path now indexes and queries Shape_Area". The fix guarded one indexing call
  site; the Phase 7 `_refresh_indices` path had the same exposure: part of PR #1627 **M12**.

Review JSONs: `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1625_0019_unit_ft_flavor.json` and
`.../1627_Feature_UnitOfMeasureDraft.in_flavor_of_foot-flavor_matching.json`.

## Current code

- `plugins/harness/scripts/pr_review.py:858` `_cmd_merge` (writes `draft.json`), `:891` `_cmd_amend`, `:1390`
  `_cmd_build` (refuses a draft missing a folded source: `:1304` `unmerged_sources`).
- Brief building: `:721` `reviewer_brief`, `:728` `write_briefs`, `:563` `dispatch_row`, `:707` `record_section`.
- Folded sources: `:1139` `fold_entry`, `:1133` `with_folded`; `FOLD_KINDS` at `:225`.
- Merging: `lib/harness_lib/review_merge.py:231` `merge_findings` (auto-merges findings on one file within 3
  lines), `:251` `merge_candidates`.
- SKILL.md Phase 3 "Order enforcement" steps 0-5 and the atomic-close rule (no user-facing text before `build`).

## Requirements

1. New subcommand `sweep --pr <N>`, valid after `merge` and before `build` (refused after `build`, like `amend`).
   It writes `briefs/sweep.md` and prints one dispatch row: `agent=harness:pr-reviewer model=sonnet`, agent id
   `sweep`. Sonnet because the task is pattern search over known findings, not open review; `haiku` never
   reviews (SKILL.md "Model floor").
2. The sweep brief carries: the full reviewable scope (the OVERALL slot's paths and read method), every draft
   issue as `id | file:lines | name | summary`, and the instruction: for each issue, state the defect as a
   pattern, search every in-scope path for other instances, and record only instances no draft issue already
   covers; each new finding's `summary` starts with `Sibling of <id>:`. It also carries the ownership clause, the
   severity rules and the `record` heredoc for slot `sweep`, built with the existing helpers.
3. The sweep's report is a folded source: `sweep` registers `{"source": "sweep", "kind": "adhoc", ...}` in
   `plan.json` `folded` when it writes the brief, so `merge --force` picks the report up and `build` refuses a
   draft without it (existing `unmerged_sources` rule).
4. New config key `review.sibling_sweep` (boolean, default `true`), four-place rule. When `true` and the draft has
   at least one issue, `build` refuses until a `sweep` source is merged, with a `problem:` line naming the step.
   `build --no-sweep` overrides once and records the waiver in `plan.json`. A draft with zero issues needs no
   sweep.
5. `merge --force` after the sweep keeps existing ids stable where it can: ids are assigned per severity by file,
   first line, name today. Check whether a sweep finding can renumber an existing id; if it can, either number
   sweep findings after the highest existing id per severity (as post-build `fold` does), or document that ids are
   provisional until `build`. Pick the first unless it breaks a test you cannot fix; say which in the report.
6. SKILL.md Phase 3 order becomes: `merge` -> `amend` (when needed) -> `sweep` + dispatch its row -> `merge
   --force` -> `amend` again only for the new ids -> `build`. Keep the atomic-close rule: dispatching the sweep row
   and waiting for it emits no user-facing text. Update `operating_rules.md` "Grading and verifying findings" with
   one line on grading sweep findings (same blast-radius rule).
7. `pr-team` is out of scope; add one line to its SKILL.md noting the sweep is `pr-review`-only for now.

## Tests

Red first:

- `tests/scripts/test_pr_review_driver.py`: `sweep` before `merge` refused; after `build` refused; brief lists
  every draft issue and the OVERALL scope; `plan.json` registers the folded source; `build` refuses without the
  sweep when enabled; `--no-sweep` waiver recorded; zero-issue draft builds without a sweep; `merge --force`
  includes the sweep finding.
- `tests/lib/test_review_merge.py`: the id-stability rule chosen in requirement 5.
- `tests/skills/test_pr_review_skill_contract.py`: extend for the new Phase 3 step if it pins the order.

Commands:

- `python -m pytest tests/scripts/test_pr_review_driver.py -q`
- `python -m pytest tests/lib/test_review_merge.py -q`
- `python -m pytest tests/skills/test_pr_review_skill_contract.py -q`
- the config tests that pin defaults and the key table (run each by file)
- `python -m ruff check <changed files>`

## Out of scope

Sweeping after `build` (prompt 01 covers fix-wave deltas). Changing the auto-merge distance.

## Done

Changed files listed; commands green with counts; the new Phase 3 order quoted in the report.
