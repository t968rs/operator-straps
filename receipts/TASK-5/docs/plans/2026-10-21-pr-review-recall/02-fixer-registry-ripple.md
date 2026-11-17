# 02 - Fixers: registry requests, a final registry wave, and a ripple checklist

Repository: `E:/automation/operator-straps`. Read `CLAUDE.md` there first. Index: `00-INDEX.md` beside this file.

## Goal

Two fixer-side gaps let a fix wave introduce new defects:

1. **Registry ownership.** The registry is one shared file. A fixer that adds or changes a test usually does not
   own it, so the entry goes stale (missing targets, stale summary), or the fixer that does own it cannot make the
   edit because the matching test-file change belongs to another fixer.
2. **No ripple step.** A fixer changes a body, deletes a symbol or adds a caller, and leaves the docstring summary
   line, sibling docs, design records or helper docstrings that describe the old state.

Fix (1) with **registry requests**: a fixer that does not own the registry records what the entry needs, and
`waves` plans one final, serial **registry wave** that applies every request. Fix (2) with a **ripple checklist**
in the fixer rules and a `ripple` list in the fix report for hits outside the fixer's file set.

## Evidence

Every item below was introduced by a PR #1625 fix wave and found by PR #1627's review of the same tree:

| #1627 id | Cause in the #1625 wave |
|---|---|
| I3 | The I3 fixer added a US-foot test to `test_spatial_ops_local.py`; the registry was not in its file set, so the entry's targets never gained the modules the test depends on. |
| M13 | The same fixer changed `refresh_sq_ft_field`'s body (skip the index on `Shape_Area`) and left the summary line promising an unconditional index. |
| M12 (part) | The same fixer guarded one indexing call site; a sibling site in another phase kept the old exposure. |
| M1, M2, M8 | The M11 fixer deleted `_get_esri_unit`. It rewrote helper names in place in a dated design record (M1), left the executed plan saying the helper is kept (M2), and renamed a test class that no longer tests the calculator (M8). |
| M6 | The M6 fixer's new test calls `_make_polygon_fc`, whose docstring lists its callers; the list went stale. |

And in PR #1627's own wave, the fixer that owned the registry could not add the targets (I3, M5) because the
registry orphan guard needs the test source to name each target, and those test files belonged to other fixers.
Both bubbled as `fixer_failed`, and the main session finished them by hand.

Paths: `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1625_0019_unit_ft_flavor.json`,
`.../1627_Feature_UnitOfMeasureDraft.in_flavor_of_foot-flavor_matching.json`, and the #1627 run's fixer reports
under `E:/automation/toolboxes/floodplain_development/docs/_scratch/pr_review/1627/pr1627_20261021T202444Z/fixes/`
(`w1_fix_1.json` holds the two `fixer_failed` bubbles).

## Current code

- Fix report models: `plugins/harness/lib/harness_lib/review_models.py:254` `FixEntry`, `:292` `FixBubble`, `:308`
  `FixReport`, `:487` `record_fixes`, `:513` `load_fix_reports`.
- Wave planning: `lib/harness_lib/review_merge.py:550` `_widening` (adds registry *tests* targeting a unit's files,
  never the registry file), `:575` `_units`, `:638` `plan_waves`.
- Driver: `plugins/harness/scripts/pr_review.py:1749` `_cmd_waves`, `:1794` `widened_waves`, `:1523`
  `wave_inputs`, `:1498` `_follow_up`, `:1706` `fixer_brief`, `:1667` `_fixer_rules`, `:1655` `_tests_block`.
- Closeout: `pr_review.py:1872` `_cmd_closeout`, `:1896` `closeout_review`; `review_merge.py:967`
  `apply_closeout`, `:819` `_coverage_problem`, `:1021` `resolvable_hints`, `:1064` `remaining_parts`.
- Config: `tests.registry`, `tests.registry_names`.

## Requirements

### Registry requests

1. `FixEntry` gains `registry: Tuple[RegistryRequest, ...] = ()`. `RegistryRequest` (new frozen model) holds
   `test` (repo path of the test file), `register` (bool, true when the test has no entry yet), `add_targets`
   (tuple of repo paths), and `summary_note` (one line on what the summary must now say; may be empty). Validate
   paths with the existing `repo_path` helper. An entry may carry requests with an empty `files` list only if it
   also has `no_change` or `files`; keep the existing at-least-one-file rule.
2. Fixer rules (`_fixer_rules`) gain: when a fix adds or changes a test and the fixer's file set does not hold the
   registry file, do not bubble; record a `registry` request on that issue's entry. When the project's registry
   requires every target to be named in the test source (say this generically: "when the project's registry
   rules require it"), add that reference in the test file the fixer owns, in the same edit.
3. Fixer briefs show the `registry` field in the `FIXED` example of the `record_fixes` heredoc.
4. `closeout`: an issue whose accepted entries carry registry requests resolves only when a registry-wave entry
   for that id is accepted. Until then it gets a problem `<id>: registry request pending; run waves` (and a
   matching `hint:` line). Existing resolution and coverage rules are otherwise unchanged.
5. A bare `waves` after such a closeout plans exactly one fixer (`model` `haiku`, one wave, after every other
   wave) that owns the registry file(s) and every test file named in the requests. Its brief lists the requests
   grouped by test, the issue ids they belong to, the project's registry guard tests (`review.registry_guards`)
   as its test commands, and the rule: apply every request through the project's registry tooling when the
   project documents one (CLAUDE.md or a skill), else edit the file directly; never drop a request silently,
   bubble `fixer_failed` with the guard output instead.
6. A fixer whose file set already holds the registry edits it directly and records no request.
7. `waves --ids` keeps planning ids whole; it never plans a registry wave unless the named ids carry pending
   requests.

### Ripple checklist

8. `_fixer_rules` gains a short checklist the fixer runs after each edit:
   - a changed body: re-read the function's docstring summary line and any docstring in the file set that names
     the function, and update them;
   - a deleted or renamed symbol: search the repository for the name; edit hits inside the file set; record hits
     outside it in the entry's new `ripple` list;
   - a new caller of an existing helper: re-read that helper's docstring;
   - point-in-time documents (executed plans, dated design records, changelogs) are not rewritten in place; add a
     dated superseded note instead, or record a `ripple` hit.
9. `FixEntry` gains `ripple: Tuple[str, ...] = ()`: `path` or `path:line` strings outside the fixer's set that the
   fix made stale. `closeout` prints each as `ripple: <id>: <path[:line]>` after the Phase 5 line (not a problem,
   not blocking). Prompt 01's delta reviewer consumes these lines; keep them stable and parseable.

### Docs

10. SKILL.md Phase 5 Rule 2 (file sets) and Rule 5 (closeout) describe registry requests, the registry wave and
    `ripple` lines. `operating_rules.md` "Phase 5 flow" gets the same in one bullet each.
    `plugins/harness/agents/pr-fixer.md` gets the ripple checklist and the request rule in its own words.
11. `pr-team` uses its own fixer agent (`plugins/harness/agents/pr-team-fixer.md`); add the ripple checklist there
    and note that registry requests are `pr-review`-only for now.

## Tests

Red first:

- `tests/lib/test_review_models.py`: `RegistryRequest` validation (paths normalized, unknown keys rejected),
  `FixEntry.registry` and `FixEntry.ripple` round-trip through `record_fixes` / `load_fix_reports`.
- `tests/lib/test_review_merge.py`: closeout leaves an id with a pending request unresolved with the problem text;
  a registry-wave entry resolves it; a fixer that owns the registry needs no request; ripple strings reach the
  printed lines.
- `tests/scripts/test_pr_review_driver.py`: `waves` after such a closeout plans one registry fixer last, owning the
  registry and the requested test files, with the guard commands; the fixer brief carries the ripple checklist and
  the `registry` example; `waves --ids` behavior per requirement 7.

Commands:

- `python -m pytest tests/lib/test_review_models.py -q`
- `python -m pytest tests/lib/test_review_merge.py -q`
- `python -m pytest tests/lib/test_review_edit_closeout.py -q`
- `python -m pytest tests/scripts/test_pr_review_driver.py -q`
- `python -m pytest tests/scripts/test_pr_review_deferral.py -q`
- `python -m pytest tests/skills/test_pr_review_skill_contract.py -q`
- `python -m pytest tests/contract/test_no_repo_literals.py -q`
- `python -m ruff check <changed files>`

## Out of scope

Reviewing the fix delta (prompt 01). Any consuming project's registry editor (the registry fixer finds it from
the project's own instructions).

## Done

Changed files listed; commands green with counts; a sample registry-wave brief from a test fixture pasted in the
report.
