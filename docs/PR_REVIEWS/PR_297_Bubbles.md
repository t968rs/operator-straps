# PR #297 Bubbles: Feature(freeze_git): `archive/<stem>/r<N>` archive plumbing

- **Scope:** Issues bubbled for decision in the review of PR #297, review file docs/PR_REVIEWS/0297_Featurefreeze_git_archivestemrN_archive_plumbing.json, head e8c749f.
- **Verified against:** branch 2162-skill-tag-archive, HEAD 21457909a67a89cf6ebc4f5e9354c49eeb36b69a, 2026-11-16, uncommitted fixes included.
- **Sources:** adversarial pr-review run pr297_20261117T044227Z (reviewers, code refuters, findings refuters) and the wave 3 fixer bubble on M1.
- **Not bubbled:** the 20 issues the fix waves resolved; none were refuted.

## Index

| ID | Class | Status | Decision | Tracked in |
|----|-------|--------|----------|------------|
| I1 | architectural_ambiguity | Open | - | - |
| I4 | architectural_ambiguity | Open | - | - |
| M1 | needs_follow_up | Open | - | - |

## Entries

### I1. Plan id 1021 collides with strap fixture plan-1021; the B11 green R-14 ran with two plans 1021

- **Class:** architectural_ambiguity
- **Description:** This PR's plan took id 1021, which the write-plan strap fixture `plan-1021` (already on main) also uses, so a scenario tree built from this branch holds two plans with that id.
- **References:** `docs/plans/strap/write-plan/SkillSpec.json:579-637` (B11 scenarios name plan 1021 and fixture plan-1021), `docs/plans/strap/write-plan/SkillSpec.json:1118-1123` (R-14 reply quotes the refusal), `docs/plans/strap/write-plan/fixtures/plan-1021/docs/plans/1021_strap_round_reopen_ActionPlan.json:2`, `docs/plans/1021_Plan_Tagging_Single_Aggregate_Tag_Folds_the_Rest_ActionPlan.json:2`, `plugins/harness/lib/harness_lib/plan_doc.py:83-90` (find_plan refuses more than one match)
- **Current behavior:** `find_plan` globs `<id>_*_ActionPlan.json` and raises `2 plans 1021` when the fixture's `1021_strap_round_reopen` sits beside this branch's `1021_Plan_Tagging_...`. R-14 (B11 green) recorded exactly that refusal, so `PLAN lanes 1021` never ran in that scenario and the runner read the plan JSON by hand.
- **When:** A strap scenario for write-plan B11 is built from a commit that holds this branch's plan 1021, which is any commit on this branch after the plan was added.
- **Chain:**
  1. the scenario builder lays fixture plan-1021 over a tree that already holds docs/plans/1021_Plan_Tagging_..._ActionPlan.json
  2. the runner calls a PLAN command with id 1021
  3. find_plan matches two files and raises `2 plans 1021`
  4. the green ran on a broken tree, so R-14 does not prove B11
  ```
  scenario tree (fixture 1021 + branch plan 1021) -> PLAN lanes 1021 -> find_plan: 2 hits -> refusal -> R-14 green on a broken tree
  ```
- **Expected behavior per fix:**
    - (a) Re-key the plan-1021 fixture to an id no live plan holds (for example 9021) in a strap reopen of write-plan, update the B11 scenario text that names 1021, rerun the B11 green and refreeze; the plan 1021 tags and receipts stay as they are. -> the scenario tree holds the fixture under a new id; B11 greens resolve it without a collision.
    - (b) Make plan id allocation count the plan ids under every strap spec's fixtures/ folder so a new plan never takes a fixture's id, and record the R-14 collision as a known limitation in the round-4 notes until the fixture is re-keyed. -> new plans skip fixture ids; this PR collision stays until the fixture or the plan moves.
    - (c) At the next write-plan reopen, renumber the fixture plan to an id no real plan can take (for example 9021) in the fixture file names, plan_id and the scenario task text, then redraw the affected greens. -> same end state as (a), deferred to the next reopen.
    - (d) Alternatively, have the fixture overlay remove the real docs/plans/1021_* files from the scenario tree. -> find_plan sees only the fixture plan in the tree; the real plan keeps 1021.
    - (e) Renumber the fixture plan to an id outside the live sequence (for example 9021: file name, plan_id and the scenario task texts) through a write-plan strap round, then re-run the B11 greens on the new fixture. -> same end state as (a).
    - (f) Make the scenario-tree builder remove each real docs/plans/<id>_* file whose id a fixture plan reuses, so a fixture plan's id is always unique inside its tree. -> general form of (d): no fixture id can collide in any tree.
- **Recommendation:** Move the branch plan, the newer one, since the write-plan rule keeps a plan already on the base branch in place; pair it with (b) later so a new plan never takes a fixture id again.
- **Decision:** open

### I4. An archive hides the `off-history:` relink cue

- **Class:** architectural_ambiguity
- **Description:** Once an archive reaches a plan's base, `check` stops warning that the base has left HEAD's history, so a rebase after an archive gives no cue to relink.
- **References:** `plugins/harness/lib/harness_lib/plan_lock.py:622-635` (_base_lines: kept = fg.reaches(...) gates both the off-history line (631) and the untagged line (633)), `plugins/harness/lib/harness_lib/plan_lock.py:526-527` (_on_head is merge-base --is-ancestor sha HEAD, the only HEAD-history test), `plugins/harness/lib/harness_lib/plan_lock.py:530-533` (relink_target refuses only when the base is on HEAD; archive state is not consulted), `plugins/harness/lib/harness_lib/plan_lock.py:14-17` (module docstring: check prints no untagged: or off-history: line for a base an archive reaches), `plugins/harness/lib/harness_lib/plan_lock.py:702-724` (check_lines docstring repeats the suppression; body reads tips via fg.archive_tips and calls _base_lines with them), `plugins/harness/lib/harness_lib/freeze_git.py:386-393` (fg.reaches: True when obj is equal to or an ancestor of any archive tip), `plugins/harness/scripts/plan.py:38-39` (check help names 'off-history: <sha7> (base r1)' as the cue for relink), `plugins/harness/scripts/plan.py:132-136` (relink help: run after a rebase when base_commit is off HEAD's history), `plugins/harness/scripts/plan.py:139-150` (archive help: archive parents include every base; untagged:, off-history: and tree lines skip an object an archive reaches (the fix option's cited plan.py:145-148 now sits at 147-150)), `tests/scripts/test_plan_archive_check.py:1-7` (plan 1021 TASK-3 test docstring: no off-history: line for a base the archive reaches), `tests/scripts/test_plan_archive_check.py:56-67` (test archives, rewrites the base off HEAD, then asserts check prints no tag:/push:/untagged:/off-history: line), `docs/plans/1021/tests/tests/scripts/test_plan_archive_check.py:6` (frozen plan 1021 copy of the same test states the off-history suppression), `tests/scripts/test_plan_lock.py:248` (unarchived case: check prints off-history: for a rewritten base)
- **Current behavior:** `_base_lines` computes `kept = fg.reaches(repo, tips, base)` and emits `off-history:` only when the base is neither reached by an archive tip nor an ancestor of HEAD; the same `kept` flag also suppresses `untagged:`. So once an archive reaches the base, `check` prints no `off-history:` line even when the base is not on HEAD's history. The module docstring, the `_base_lines` and `check_lines` docstrings, plan.py's `archive` help text and the plan 1021 test `test_a_rewritten_base_the_archive_reaches_is_quiet` all state or assert this suppression. Meanwhile plan.py's `check` help still calls `off-history:` the cue for `relink`, and `relink_target` decides only by `_on_head`, so relink still applies to that base.
- **When:** A plan with a `base_commit` has been archived (the archive commit takes every base as a parent, so `fg.reaches` returns True for that base), and a later rebase or history rewrite drops `base_commit` from HEAD's ancestry without a `relink`. `check` (or any path through `check_lines`) then reaches `_base_lines` with non-empty `tips` from `fg.archive_tips`.
- **Chain:**
  1. check_lines reads the archive tips with fg.archive_tips(repo, stem) and passes them to _base_lines
  2. _base_lines sets kept = fg.reaches(repo, tips, base), which is True because the archive commit has the base as a parent (merge-base --is-ancestor base tip)
  3. the off-history expression `[] if kept or _on_head(repo, base) else [...]` short-circuits on kept, so _on_head is never consulted
  4. no `off-history:` line is emitted although `merge-base --is-ancestor base HEAD` would fail after the rewrite
  5. the user gets no relink cue, though relink_target (which tests only _on_head) would still accept the base for relinking
  ```
  rebase rewrites base -> check_lines -> fg.archive_tips -> _base_lines: kept = fg.reaches(tips, base) is True -> off-history skipped via `kept or _on_head` -> no relink cue
  ```
- **Expected behavior per fix:**
    - (a) Compute `off-history:` from `_on_head` alone (`lines = [] if _on_head(repo, base) else [...]`), keep `kept` only in the `untagged:` condition, and update the `_base_lines`, `check_lines` and module docstrings and plan.py:145-148 to say only `untagged:` is suppressed. -> check prints `off-history: <sha7> (base r1)` for any base off HEAD's history whether or not an archive reaches it, while an archive still silences `untagged:` for the base. The test at tests/scripts/test_plan_archive_check.py:56-67 (and its frozen copy under docs/plans/1021) would then see an off-history: line and fail its `loud(...) == []` assertion, so it and the plan 1021 TASK-3 statement would need changing too.
- **Recommendation:** Apply (a). `off-history:` and `untagged:` answer different questions: an archive answers "is it tagged", not "is it on HEAD". The reversal needs a design change to the plan (DesignEvolution entry, `plan_api.write`, refreeze) and an edit to the frozen TASK-3 test.
- **Decision:** open

### M1. Plan 1021 records branch 1162-plan-skill-tag-archive; the PR head branch is 2162-skill-tag-archive

- **Class:** needs_follow_up
- **Description:** The frozen plan records a branch name the PR does not use, and its STR-2 action still asks for a green of B10, which the strap spec has dropped.
- **References:** `docs/plans/1021_Plan_Tagging_Single_Aggregate_Tag_Folds_the_Rest_ActionPlan.json:6` (branch), `docs/plans/1021_Plan_Tagging_Single_Aggregate_Tag_Folds_the_Rest_ActionPlan.json:386-388` (STR-2 action names B9, B10 and B11), `docs/plans/1021/DesignEvolution.json:4` (branch_lineage), `docs/plans/strap/write-plan/SkillSpec.json:525` (B10), `docs/plans/strap/write-plan/SkillSpec.json:575` (B10 state dropped)
- **Current behavior:** The plan JSON has `branch` set to `1162-plan-skill-tag-archive` and the DesignEvolution catalog has `branch_lineage` set to `main-->1162-plan-skill-tag-archive`, while the PR head is `2162-skill-tag-archive`. STR-2 tells the executor to run greens of B9, B10 and B11, but B10 is `dropped` in the strap spec, so that step cannot be done as written.
- **When:** A reader or a tool follows the plan's branch field to find its work, or an executor carries out STR-2 literally.
- **Chain:**
  1. the plan JSON and the DesignEvolution catalog name branch 1162-plan-skill-tag-archive
  2. the work landed on 2162-skill-tag-archive (PR #297)
  3. STR-2's action lists B10 among the greens to run
  4. the strap spec marks B10 dropped, so `strap.py run write-plan B10 --arm green` has nothing to run
  ```
  plan.branch (1162-...) != PR head (2162-...); STR-2 action -> green B10 -> SkillSpec B10 state dropped -> step not executable as written
  ```
- **Expected behavior per fix:**
    - (a) Set `branch` to 2162-skill-tag-archive through plan_api.write (an unlock/refreeze on the frozen plan, with the developer's OK) and render, and update branch_lineage in DesignEvolution.json through evolution_api. -> the plan, its page and the catalog name 2162-skill-tag-archive; a new freeze entry stamps the change.
    - (b) If the branch was renamed after the plan was frozen, add a DesignEvolution note recording the rename instead of refreezing. -> the plan stays as frozen; the catalog explains the mismatch.
    - (c) Correct the branch at the plan's next refreeze through plan_api.write and re-render the PIP; leave the frozen JSON untouched until then. -> the mismatch remains until some later refreeze.
    - (d) Record both corrections as a DesignEvolution change (evolution_api.add) citing STR-2 and the branch rename, so the frozen plan stays untouched. -> the plan text is unchanged; the catalog records both corrections.
    - (e) Or rename the branch to match the plan before merge. -> the branch is 1162-plan-skill-tag-archive again; STR-2 still names B10.
- **Recommendation:** Apply (a), and drop B10 from the STR-2 action in the same write and refreeze, with a DesignEvolution entry recording both changes.
- **Decision:** open
