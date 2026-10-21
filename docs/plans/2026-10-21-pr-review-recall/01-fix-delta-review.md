# 01 - Review the fix delta before closeout

Repository: `E:/automation/operator-straps`. Read `CLAUDE.md` there first. Index: `00-INDEX.md` beside this file.
Land prompts 05, 03 and 02 first: this change reuses their brief sections and the `ripple:` lines.

## Goal

Today `pr-review` reviews the PR once (Phase 2), then lets fixers edit, then certifies READY TO MERGE on a tree
whose fix edits no reviewer has seen. Add one reviewer pass over **the fix delta** (everything changed since
`build_head`) after the last fix wave and before `closeout` may finish the pass. Its findings join the review as
new ids through the existing post-build fold path, get one more wave, and then `closeout` runs.

## Evidence

PR #1625's run ended `READY TO MERGE - 17 of 17 findings resolved`. Its fix waves had introduced six new defects
that PR #1627's review of the same tree then found (I3, M1, M2, M6, M8, M13, plus parts of M9 and M12). The fix
delta was `git diff 8f4f06cd9 c9b1fdb76` in `E:/automation/toolboxes/floodplain_development`: about 250 lines
across 14 files, small enough for one reviewer. See `02-fixer-registry-ripple.md` (Evidence) for the cause of each.

Paths: `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1625_0019_unit_ft_flavor.json`,
`.../1627_Feature_UnitOfMeasureDraft.in_flavor_of_foot-flavor_matching.json`.

## Current code

- Phase 5 flow in `plugins/harness/scripts/pr_review.py`: `:1749` `_cmd_waves`, `:1803` `_cmd_bubbles`, `:1872`
  `_cmd_closeout` (`:1880` `changed_paths(repo, build_head)` returns changed and created sets; `:1888` sets the
  phase to `done` or `fix`), `:1946` `phase5_line`.
- Post-build fold: `:1154` `_cmd_fold`, `:1229` `fold_after_build`, `:1186` `appended_review`, `:1199`
  `OPEN_PASS_PHASES`, `:1208` `fold_next`. A fold inside an open pass keeps the phase and prints
  `next: waves (new ids only), then closeout`.
- Reviewer brief helpers: `:721` `reviewer_brief`, `:637` `scope_section`, `:657` `lens_section`, `:688`
  `rules_section`, `:707` `record_section`, `:563` `dispatch_row`; budgeted diff in
  `lib/harness_lib/pr_capture.py:292` `budgeted_diff` (merge base and head), which needs a working-tree variant
  against `build_head` here.
- Sentinel: the schema hook (`plugins/harness/hooks/validate_pr_json_schema.py`, Layer 3) clears the Phase 5
  sentinel after a review write whose ids are all dispositioned. Every `closeout` write runs it. A gate that only
  prints a problem after writing would let the sentinel clear; the gate must refuse **before** any write.
- SKILL.md Phase 5 "Order enforcement" steps 0-8; `operating_rules.md` "Phase 5 flow".

## Requirements

1. New config keys (four-place rule in `CLAUDE.md`):
   - `review.fix_delta_review` (boolean, default `true`);
   - `review.fix_delta_model` (string, default `opus`; `haiku` rejected by the schema, as the reviewer model floor
     forbids it).
2. New subcommand `delta --pr <N>`. Valid only after `build` with `pre_fix_time` populated and at least one
   fixer report or `--resolved` edit in the run. It:
   - computes the delta: paths changed since `build_head` (commits, working tree, untracked; reuse
     `changed_paths`), minus excluded and review-directory paths;
   - writes `diffs/delta_<n>.diff` (budgeted, against `build_head`, working tree included; new files listed as
     "new file, N lines - read it", like Phase 2 briefs) and `briefs/delta_<n>.md`;
   - records the pass in `plan.json` (`delta_passes`: `[{"id": "delta_<n>", "paths": {path: blob}, "state":
     "dispatched"}]`, blob = `git hash-object` of the working-tree file, or `deleted`);
   - prints one dispatch row: `agent=harness:pr-reviewer model=<review.fix_delta_model>`, agent id `delta_<n>`.
3. The delta brief carries: the delta scope and read method (working tree); every issue resolved so far with its
   fixer's `what` text and files; every `ripple:` hit fixer reports recorded (prompt 02); the default sub-lens; the
   test-design clause when tests are in the delta (prompt 05); the registry-entry section for touched tests
   (prompt 03); and this lens, as a new entry in `schemas/catalogs/CrossCuttingLensCatalog.json` (name
   `fix-delta`, its `scope_template` holding the text, so it is editable data, not code):
   - Does each fix resolve its issue as the issue states it, at every call site the issue names?
   - Did the fix leave a stale summary line, docstring, registry entry, sibling doc or design record?
   - Did a new or changed test land without its registry targets or summary?
   - Did the fix guard one site of a pattern and leave its siblings?
   - Was a point-in-time document (executed plan, dated design record) rewritten in place?
   - Does a renamed test or class still test what its name says?
   - Do not re-report issues already in the review.
4. `delta --pr <N> --fold`, after the reviewer returns, folds `findings/delta_<n>.json` through the post-build
   fold path (`fold_after_build`), credited `delta_<n> (adhoc)`, marks the pass `folded` (zero findings:
   `clean`), and prints the fold's added rows and `next:` line. A missing report is a problem naming the row to
   re-dispatch. Severity comes from the reviewer (post-build folds do not `amend`), so the delta brief repeats the
   severity rules and the blast-radius grading line from `operating_rules.md`.
5. `closeout` gains a pre-write gate. When `review.fix_delta_review` is true and some path changed since
   `build_head` has a current blob that no `folded` / `clean` delta pass recorded, `closeout` refuses before
   writing, with `problem: fix delta not reviewed: <k> path(s); run delta` and the printed line
   `Phase 5 [blocked] | fix delta not reviewed | verdict: <v> | next: delta`. Exception that bounds the loop: when
   the latest pass is `folded` and every path still unreviewed changed only after that fold (the delta pass's own
   fix wave), `closeout` proceeds and prints, after the Phase 5 line, `unreviewed fix delta: <paths>` so the
   developer sees it. One delta pass per Phase 5 pass, never a chain.
6. `delta` and `closeout --resolved` interplay: a `--resolved` edit counts as fix delta like a fixer edit.
7. Re-entry after a post-closeout `fold` (SKILL.md "After a post-build fold"): the new pass's edits need their own
   delta pass; the blob bookkeeping handles this without special cases. Verify with a test.
8. `review.fix_delta_review: false` restores today's behavior exactly (no gate, no `delta` requirement).
9. SKILL.md Phase 5 "Order enforcement": add a step between the last wave (with bubble answers folded) and
   `closeout`: `delta` -> dispatch its row -> `delta --fold` -> `waves` for new ids (if any) -> dispatch ->
   `closeout`. No user-facing text in that step. Update Rule 4 ("continue until input genuinely needed") and the
   terminal step to mention the `unreviewed fix delta` line. Add one rationalization row to
   `schemas/fixtures/pr-review/rationalization_table.json` ("The fixes are small, the delta review is ceremony" ->
   "Six of fifteen findings in the second review of one tree came from fix waves nobody reviewed"), following the
   fixture's schema and eviction policy. `operating_rules.md` "Phase 5 flow" gets one bullet.
10. `pr-team`: out of scope. Add one line to its SKILL.md noting the delta pass is `pr-review`-only for now.

## Tests

Red first:

- `tests/scripts/test_pr_review_driver.py`:
  - `delta` before `build` refused; with no fix edits refused; writes brief, diff and `plan.json` pass record;
    prints the row with the configured model;
  - the brief holds the resolved issues with `what` text, `ripple:` hits, the `fix-delta` lens text, and the
    registry section when a touched test is registered;
  - `delta --fold` appends issues with fresh ids credited `delta_1 (adhoc)`; zero findings marks `clean`;
    missing report is a problem;
  - `closeout` refuses before writing while the delta is unreviewed (assert the review file is byte-unchanged and
    the sentinel file still exists);
  - after `delta --fold` and a follow-up wave, `closeout` proceeds and prints `unreviewed fix delta:` for the
    follow-up wave's paths;
  - re-entry after a post-closeout fold requires a new delta pass;
  - `review.fix_delta_review: false`: `closeout` behaves as today.
- `tests/schemas/` test for the catalog entry, if one validates `CrossCuttingLensCatalog.json`; and the
  rationalization fixture test (`tests/schemas/test_pr_review_fixture_schemas.py`).
- `tests/skills/test_pr_review_skill_contract.py` for the new Phase 5 step if it pins the order.

Commands:

- `python -m pytest tests/scripts/test_pr_review_driver.py -q`
- `python -m pytest tests/lib/test_review_merge.py -q`
- `python -m pytest tests/schemas/test_pr_review_fixture_schemas.py -q`
- `python -m pytest tests/skills/test_pr_review_skill_contract.py -q`
- `python -m pytest tests/hooks/test_hooks_schema_validation.py -q`
- `python -m pytest tests/hooks/test_check_phase5_sentinel_hook.py -q`
- the config tests that pin defaults and the key table (run each by file)
- `python -m pytest tests/contract/test_no_repo_literals.py -q`
- `python -m pytest tests/contract/test_root_separation.py -q`
- `python -m ruff check <changed files>`
- Mod mirror: if `pr-review-watch` reads either new key, mirror its default in that mod's `hooks/config.ts` and
  run `tests/mods/test_pr_review_watch_config_mirror.py`.

## Out of scope

Sweeping before `build` (prompt 04). Reviewing deltas from commits the developer makes after closeout.

## Done

Changed files listed; commands green with counts; the new SKILL.md step and a sample delta brief (from a test
fixture) pasted in the report; the plugin version bump done if this is the last of the six to merge.
