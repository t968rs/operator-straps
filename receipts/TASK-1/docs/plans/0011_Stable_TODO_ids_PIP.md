# Plan 0011: Stable TODO ids

> Rendered by `plan.py render` from `0011_Stable_TODO_ids_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-09
**Spec:** `https://github.com/t968rs/operator-straps/issues/243`
**Branch:** none -> 1142-auto-title-pr
**Base commit:** `a635405`
**Frozen:** 2026-11-09 at `5be1608`
**Execution model:** serial

## Decisions

- **D1** What does a TODO item id look like once it no longer follows rank? Chosen: `random` (todo- plus 4 random characters, collision-checked). Rejected: `rank` (TODO-<rank>, renumbered on every structural edit (today)), `counter` (letters from a stored counter (todo-aaf)), `date` (creation date plus a count (todo-261109-2)). Issue 243: renumbering broke references outside the rewrite set. Counter and date ids collide when two worktrees add items at once; a random code does not, and carries no position.
- **D2** How is a retired id kept from being drawn again? Chosen: `retired_list` (catalog-level retired_ids list; new draws skip live and retired). Rejected: `none` (collision check against live ids only). A reused id makes every stale reference point at an unrelated item, the failure issue 243 reports; the list grows by one per retirement.
- **D3** Which ids do the parts of a split get? Chosen: `all_new` (every part gets a new id; the original is retired and its prose listed). Rejected: `first_part_keeps` (the first part inherits the original id). Inheriting the id guesses which part a reference meant; a listed dangling id is honest.
- **D4** How far does the one-time switch-over rewrite old TODO-NNN references? Chosen: `leave_history_with_map` (live files only; plans, reviews, snapshots and commit messages stay as history; the old->new map is stored). Rejected: `rewrite_all` (every file naming an old id, history included). History records describe the catalog when written and some are already stale; rewriting them with the current map turns stale references into confidently wrong ones.
- **D5** Where does the old->new map live? Chosen: `catalog_legacy_ids` (top-level legacy_ids object in the catalog). Rejected: `separate_file` (a map file beside the catalog). Schema-validated, travels with the catalog, needs no new path or config key.
- **D6** Upper- or lower-case prefix and code? Chosen: `lower` (todo-k7qf). Rejected: `upper` (TODO-K7QF). Developer's call; also keeps new ids disjoint from the TODO-NNN pattern and from TODO: comments. Commands accept any case.
- **D7** What happens to a catalog that still holds TODO-NNN ids? Chosen: `one_finding_and_refuse` (check reports one T6 finding naming migrate-ids; retire, split, add and refresh refuse). Rejected: `per_item_errors` (schema and T6 report every id). One actionable line instead of a capped flood of pattern errors.
- **D8** Which marketplace release does this change suggest? Chosen: `minor` (harness 0.64.0 -> 0.65.0, extend docs/RELEASES/v0.7.0.md). Rejected: `major` (the catalog format change counts as breaking across the marketplace). Developer's call 2026-11-09: the switch is one command with a dry run and nothing is renamed or removed; harness 0.64.0 -> 0.65.0 joins the pending v0.7.0 notes.
- **D9** Which codes may the generator draw? Chosen: `digit_and_letter` (at least one digit and at least one letter). Rejected: `any_code` (any 4 characters of the 31-character alphabet). Without a digit the generator can draw todo-sync, a name already in use; without a letter a code reads as a number.
- **D10** How does migrate-ids draw the new ids? Chosen: `seeded_draw` (each legacy item's draw seeded from its old id and title). Rejected: `system_draw` (SystemRandom, as add and split draw). Review A4: two worktrees that each run the switch must agree, and the dry run must show the ids the real run writes; add and split keep the random draw of D1.
- **D11** Where does a split record its parts? Chosen: `split_ids` (top-level split_ids: retired id -> part ids, in spec order). Rejected: `retired_only` (retired_ids alone; the parts appear only in that run's report). Review A9: references the scan cannot see (issue comments, notes, other branches) still resolve: resolve_ids answers 'todo-sp7t was split into todo-a, todo-b'.
- **D12** What does migrate-ids do on a catalog that already holds legacy_ids? Chosen: `reapply_map` (rewrite remaining live references through the stored map; new legacy ids join it; a key already mapped refuses). Rejected: `refuse` ('nothing to migrate' once the items are stable). Reviews A1, A5, B5: a partial write, a git failure or a branch merged after the switch leaves TODO-NNN references only the stored map resolves; a key already mapped means an older harness renumbered the catalog, which a fresh map would hide.
- **D13** Which files outside the catalog does migrate-ids rewrite by default? Chosen: `all_live` (every live file; history, --exclude paths and the catalog schema skipped). Rejected: `opt_in` (catalog and companions only; other files only with --include). Developer's call 2026-11-09 (one last rewrite of every reference); review A6's opt-in default declined: the dry run lists every file first, --exclude (by path component) removes any, and the catalog schema file is never rewritten.
- **D14** When does this repository's own catalog switch? Chosen: `after_release` (after harness 0.65.0 is released and installed wherever todo_sync runs here). Rejected: `in_branch` (on this branch, before the release). Review A1: sessions here run the published plugin, whose add and refresh renumber stable ids back to TODO-<rank>; the switch waits for the release (deferred_to_future_plans).

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| code length | 4 | conversation 2026-11-09 (option A) | random |
| alphabet | 23456789abcdefghjkmnpqrstuvwxyz (31 characters: no 0, 1, i, l, o) | conversation 2026-11-09 | random, lower |
| drawable codes | 639584 (31^4 - 23^4 - 8^4) | arithmetic on the alphabet | digit_and_letter |
| history paths the switch-over and reference scans skip | artifacts.plans, artifacts.reviews, artifacts.commit_messages, artifacts.summaries, artifacts.scratch, each artifacts.planning_prefixes entry, todo.snapshots.dir | plugins/harness/lib/harness_lib/todo_sync/retire.py:218-225 plus review A8 (plugins/harness/config/defaults.json:17-23) | leave_history_with_map |
| fixture ids | todo-p4rs, todo-sp7t, todo-c4ch (were TODO-001, TODO-002, TODO-003) | tests/fixtures/todo_sync/TodoCatalog.min.json | random, lower |

## Formats

- **stable item id**: `todo-k7qf`, copied from `plugins/harness/schemas/catalogs/TodoCatalog.schema.json:80-83`
- **legacy item id (parsed only by migrate-ids and the resolution hint)**: `TODO-017`, copied from `plugins/harness/lib/harness_lib/todo_sync/retire.py:25`
- **legacy_ids catalog object**: `{"migrated": "2026-11-09", "map": {"TODO-017": "todo-k7qf"}}`, copied from `plugins/harness/schemas/catalogs/TodoCatalog.schema.json:17`
- **retire/split report line the todo-editor agent works**: `dangling: items/todo-c4ch/summary names retired todo-p4rs`, copied from `plugins/harness/lib/harness_lib/todo_sync/retire.py:283`
- **reference line for a file outside the catalog**: `reference (not rewritten): docs/notes.md:1:See todo-p4rs.`, copied from `plugins/harness/lib/harness_lib/todo_sync/retire.py:284`
- **split_ids catalog object**: `{"todo-sp7t": ["todo-k7qf", "todo-m3x9"]}`, copied from `plugins/harness/schemas/catalogs/TodoCatalog.schema.json:17`
- **split flag line the todo-editor agent works (B7)**: `dangling: items/todo-c4ch/summary names split todo-sp7t (parts todo-k7qf, todo-m3x9)`, copied from `plugins/harness/lib/harness_lib/todo_sync/retire.py:283`

## Sweeps

- **S1** `TODO-(NNN|MMM|<rank>|\{|\\d|\[0-9\])`: `docs/PROVENANCE.md` (history record, left as written (D4)), `docs/PR_REVIEWS/0026_Impl_updates.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0089_1071_sync_gh_issues.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0235_1133_add_todo.json` (history record, left as written (D4)), `plugins/harness/agents/todo-editor.md` (SKL-1 rewrites the id format), `plugins/harness/lib/harness_lib/todo_sync/reshape.py` (RSH-1 drops todo_id and the probe id), `plugins/harness/lib/harness_lib/todo_sync/retire.py` (RSH-1 drops ID_RE, _SHORT, todo_id once reshape stops importing them; IDS-1 owns LEGACY_RE), `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py` (CAT-1 drops the TODO-<rank> check), `plugins/harness/schemas/README.md` (CAT-1), `plugins/harness/schemas/catalogs/TodoCatalog.schema.json` (CAT-1), `plugins/harness/skills/todo-edit/SKILL.md` (SKL-1), `tests/lib/test_todo_sync_add_note.py` (RSH-1 (the added-item head line pattern at :86))
- **S2** `[Rr]enumber`: `README.md` (DOC-1), `docs/PROVENANCE.md` (history record, left as written (D4)), `docs/PR_REVIEWS/0082_featharness_add_amend-commit-msg_to_amend_a_drafted_commit_breakdown.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0089_1071_sync_gh_issues.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0096_repo-todo_artifacts_ignore.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0148_1101_writing_plans_rewrite.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0158_1105_bug_pr_review.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0202_Featurebubble-memo_run_the_memo_reviewer_only_on_request.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0235_1133_add_todo.json` (history record, left as written (D4)), `plugins/harness/agents/todo-editor.md` (SKL-1), `plugins/harness/lib/harness_lib/commit_regroup.py` (unrelated: commit block numbering), `plugins/harness/lib/harness_lib/review_merge.py` (unrelated: review issue ids), `plugins/harness/lib/harness_lib/strap_api.py` (unrelated: scenario ids), `plugins/harness/lib/harness_lib/todo_sync/reshape.py` (RSH-1), `plugins/harness/lib/harness_lib/todo_sync/retire.py` (RET-1), `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py` (CAT-1 (T6 fix text)), `plugins/harness/scripts/branch_commit_msg.py` (unrelated: commit block numbering), `plugins/harness/scripts/pr_review.py` (unrelated: review issue ids), `plugins/harness/scripts/todo_sync.py` (DRV-1), `plugins/harness/skills/amend-commit-msg/SKILL.md` (unrelated: commit blocks), `plugins/harness/skills/branch-commit-msg/SKILL.md` (unrelated: commit blocks), `plugins/harness/skills/branch-commit-msg/txt_format.md` (unrelated: commit blocks), `plugins/harness/skills/pr-review/SKILL.md` (unrelated: review issue ids), `plugins/harness/skills/pr-review/operating_rules.md` (unrelated: review issue ids), `plugins/harness/skills/sync-gh-todo/SKILL.md` (SKL-1), `plugins/harness/skills/todo-edit/SKILL.md` (SKL-1), `plugins/harness/skills/write-plan/SKILL.md` (unrelated: plan ids), `tests/lib/test_todo_sync_retire.py` (RET-1), `tests/scripts/test_branch_commit_msg.py` (unrelated: commit blocks), `tests/scripts/test_todo_sync.py` (DRV-1), `tests/skills/test_sync_gh_todo_skill_contract.py` (SKL-1 (Renumbered reply field)), `tests/skills/test_todo_edit_skill_contract.py` (SKL-1 (Renumbered reply field))
- **S3** `\b(remap_text|companion_edits|write_edits|todo_id|normalize_id|other_references|_renumber)\b`: `docs/PR_REVIEWS/0026_Impl_updates.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0089_1071_sync_gh_issues.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0096_repo-todo_artifacts_ignore.json` (history record, left as written (D4)), `docs/PR_REVIEWS/0235_1133_add_todo.json` (history record, left as written (D4)), `docs/TODO/RepoToDo.json` (close-candidate evidence prose naming other_references; the deferred switch-over (D14) rewrites ids only), `plugins/harness/lib/harness_lib/todo_sync/reshape.py` (RSH-1: imports from retire change; write_edits stays a module-level name), `plugins/harness/lib/harness_lib/todo_sync/retire.py` (RET-1 reshapes other_references; RSH-1 removes remap_text, companion_edits, todo_id, normalize_id once reshape stops importing them), `plugins/harness/schemas/catalogs/TodoCatalog.schema.json` (the $defs name todo_id stays (CAT-1 changes its pattern)), `tests/lib/test_todo_sync_file_issue.py` (swaps reshape.write_edits at :159; RSH-1 keeps the name), `tests/lib/test_todo_sync_retire.py` (RET-1)

## Tasks

### IDS-1: Stable id module: format, generator, resolution

**Status:** COMPLETE | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/todo_sync/ids.py`, `plugins/harness/lib/harness_lib/todo_sync/errors.py`, `plugins/harness/lib/harness_lib/todo_sync/__init__.py`, `tests/lib/test_todo_sync_ids.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/todo_sync/__init__.py:38-39` holds `class TodoSyncError(ValueError):`
- `plugins/harness/lib/harness_lib/todo_sync/__init__.py:24-26` holds `from harness_lib.todo_sync import rules_plans as rp`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:25-26` holds `ID_RE = re.compile(r"\bTODO-\d{3,}\b") _SHORT = re.compile(r"(?i)(?:TODO-)?0*([1-9]\d*)")`

1. New todo_sync/errors.py holds `class TodoSyncError(ValueError)` (moved from __init__.py:38-39); __init__.py imports it from errors before the rules imports and keeps it in __all__, so every `from harness_lib.todo_sync import TodoSyncError` keeps working. 2. New todo_sync/ids.py (imports TodoSyncError from errors, never from the package): PREFIX = 'todo-', ALPHABET = '23456789abcdefghjkmnpqrstuvwxyz', CODE_LENGTH = 4; ID_RE, the word-bounded lowercase id with lookaheads requiring at least one digit and one letter; LEGACY_RE = \bTODO-[0-9]{3,}\b (copied from retire.py:25, whose own ID_RE stays until RSH-1); MIGRATE_HINT = 'the catalog still uses rank-tied TODO-NNN ids; run todo_sync.py migrate-ids --dry-run, then without --dry-run'. Functions: is_id(text) (fullmatch); is_legacy(catalog) (any item id fullmatching LEGACY_RE); taken_ids(catalog) (item ids plus retired_ids); new_id(taken, rng=None) (draws CODE_LENGTH rng.choice(ALPHABET) characters, redraws until is_id and not taken; default random.SystemRandom()); canonical(raw) (strip whitespace and one trailing ',' or ';', lower-case, add the prefix when missing; None unless is_id); mentions(text, ids) (the ids from `ids`, in their order, that `text` names case-insensitively on word bounds: the one matcher retire, split and the companion scans share); resolve_ids(catalog, raws) (canonical ids in input order without repeats, or one TodoSyncError joining every problem with '; ': a raw that reads as an old id (TODO-007, 007 or 7) reads 'TODO-007 is a rank-tied id from before migrate-ids: it meant todo-xxxx (<the live item's title>) as of <legacy_ids.migrated>; older references may name another item', with '(retired)' in place of the title when the id is in retired_ids, or 'TODO-007 is a rank-tied id from before migrate-ids: no legacy_ids entry'; an empty list 'name at least one TODO id'; a retired code 'todo-xxxx was retired', or 'todo-xxxx was split into todo-a, todo-b' when split_ids holds it; unknown codes 'no such item(s) in the catalog: ...'; anything else 'not a TODO id: ... (use todo-k7qf or k7qf)'); require_stable(catalog, verb) raises TodoSyncError(f'{verb}: {MIGRATE_HINT}') on a legacy catalog.

- [x] Test `tests/lib/test_todo_sync_ids.py::test_new_ids_match_the_format_and_avoid_taken` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_new_id_redraws_codes_without_a_digit_or_letter_and_taken_codes` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_is_id_rejects_words_numbers_lookalikes_and_case` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_canonical_accepts_any_case_and_a_bare_code` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_id_re_finds_ids_in_prose_only_on_word_bounds` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_resolve_names_the_legacy_mapping` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_resolve_names_the_parts_of_a_split_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_resolve_refuses_retired_unknown_and_malformed_ids` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_mentions_match_any_case_on_word_bounds` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_taken_ids_hold_live_and_retired` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_require_stable_names_migrate_ids` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_ids.py::test_todo_sync_error_is_one_class` fails with ImportError, then passes
- [x] Record it: `plan.py record 0011 IDS-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 6ef37d8: 12 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `6ef37d8`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/lib/test_todo_sync_ids.py::test_new_ids_match_the_format_and_avoid_taken tests/lib/test_todo_sync_ids.py::test_new_id_redraws_codes_without_a_digit_or_letter_and_taken_codes tests/lib/test_todo_sync_ids.py::test_is_id_rejects_words_numbers_lookalikes_and_case tests/lib/test_todo_sync_ids.py::test_canonical_accepts_any_case_and_a_bare_code tests/lib/test_todo_sync_ids.py::test_id_re_finds_ids_in_prose_only_on_word_bounds tests/lib/test_todo_sync_ids.py::test_resolve_names_the_legacy_mapping tests/lib/test_todo_sync_ids.py::test_resolve_names_the_parts_of_a_split_id tests/lib/test_todo_sync_ids.py::test_resolve_refuses_retired_unknown_and_malformed_ids tests/lib/test_todo_sync_ids.py::test_mentions_match_any_case_on_word_bounds tests/lib/test_todo_sync_ids.py::test_taken_ids_hold_live_and_retired tests/lib/test_todo_sync_ids.py::test_require_stable_names_migrate_ids tests/lib/test_todo_sync_ids.py::test_todo_sync_error_is_one_class`

### CAT-1: Catalog format: schema, fixtures, T1 and T6, init

**Status:** COMPLETE | **Model:** opus | **Depends on:** IDS-1
**Files:** `plugins/harness/schemas/catalogs/TodoCatalog.schema.json`, `plugins/harness/schemas/README.md`, `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py`, `plugins/harness/lib/harness_lib/todo_sync/scaffold.py`, `tests/fixtures/todo_sync/TodoCatalog.min.json`, `tests/fixtures/todo_sync/TodoCatalog.legacy.json`, `tests/lib/_todo_helpers.py`, `tests/lib/test_todo_sync_rules_todo.py`, `tests/schemas/test_todo_catalog_schema.py`, `tests/lib/test_todo_sync_scaffold.py`, `tests/lib/test_todo_sync_ranking.py`

**Anchors:**
- `plugins/harness/schemas/catalogs/TodoCatalog.schema.json:80-84` holds `"todo_id": { "type": "string", "pattern": "^TODO-[0-9]{3,}$",`
- `plugins/harness/schemas/catalogs/TodoCatalog.schema.json:645-653` holds `"description": "TODO-NNN, numbered by rank."`
- `plugins/harness/schemas/catalogs/TodoCatalog.schema.json:62` holds `Ranked work items, ordered by rank (TODO-001 first).`
- `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py:131-145` holds `def t6_ids_and_ranks(src: Sources) -> List[Finding]:`
- `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py:142-144` holds `elif item_id != f"TODO-{pos:03d}":`
- `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py:56-61` holds `errors = sorted(validator.iter_errors(src.todo.data),`
- `plugins/harness/lib/harness_lib/todo_sync/scaffold.py:65-67` holds `the tie breakers apply in order, so ids and ranks are`
- `plugins/harness/lib/harness_lib/todo_sync/scaffold.py:91` holds `"items": [], "trackers": [], "close_candidates": [],`
- `tests/lib/_todo_helpers.py:24` holds `MIN_CATALOG = json.loads((FIXTURES / "todo_sync" / "TodoCatalog.min.json").read_text(encoding="utf-8"))`
- `plugins/harness/schemas/README.md:184` holds `` unique ids equal to `TODO-<rank>` ``

1. Schema: $defs.todo_id takes the stable pattern ^todo-(?=[2-9a-hjkmnp-z]*[2-9])(?=[2-9a-hjkmnp-z]*[a-hjkmnp-z])[2-9a-hjkmnp-z]{4}$ with a description (random, stable, never reused; order lives in rank); new $defs.legacy_todo_id ^TODO-[0-9]{3,}$; optional top-level retired_ids (array of todo_id, uniqueItems), legacy_ids (object, additionalProperties false, required migrated (format date) and map (object, propertyNames legacy_todo_id, values todo_id)) and split_ids (object, propertyNames todo_id, values arrays of todo_id with minItems 2 and uniqueItems: the parts a split gave a retired id, in spec order); rewrite the descriptions at :5 (T6 checks unique ids absent from retired_ids and the split_ids records, not TODO-<rank>), :62, :647 and :652. 2. plugins/harness/schemas/README.md:180-184 says the same. 3. rules_todo.py: T1 drops the pattern errors whose instance fullmatches ids.LEGACY_RE when ids.is_legacy(catalog), leaving the catalog to T6. T6 on a legacy catalog returns one error finding (message names migrate-ids, fix 'Run todo_sync.py migrate-ids --dry-run, then without --dry-run.') plus its duplicate-id findings, which migrate-ids needs cleared first; on a stable catalog it reports duplicate ids ('id X appears N times'), an item id listed in retired_ids ('id X is in retired_ids'), a split_ids key missing from retired_ids ('split id X is not in retired_ids'), a part that is neither an item nor retired ('split id X names part Y, neither an item nor retired'), and ranks that do not run 1..n in item order; the id == TODO-<rank> check (:142-144) goes. 4. scaffold.py: starter_catalog writes "retired_ids": [] after close_candidates; the notes sentence 'so ids and ranks are reproducible from the item fields alone' becomes 'so ranks are reproducible from the item fields alone; ids never change'. 5. Fixtures: copy tests/fixtures/todo_sync/TodoCatalog.min.json unchanged to TodoCatalog.legacy.json; in the min fixture rename TODO-001 -> todo-p4rs, TODO-002 -> todo-sp7t, TODO-003 -> todo-c4ch everywhere (ids, links, trackers, close candidates, prose) and add "retired_ids": []. 6. tests/lib/_todo_helpers.py: ID1, ID2, ID3 = the three fixture ids; LEGACY_CATALOG loaded from the legacy fixture, with the literal file name "TodoCatalog.legacy.json" in the code (tools/select_tests.py maps a fixture change to its readers only through that literal). 7. Copy the planned test files. CAT-1 through DRV-1 land as one staged unit: between them the driver and its tests are red by design (reshape still probes with TODO-001 until RSH-1).

- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t6_accepts_ids_that_do_not_follow_rank` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t6_flags_duplicate_and_retired_ids` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t6_still_checks_ranks_run_1_to_n` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t6_reports_a_legacy_catalog_once` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t1_leaves_legacy_ids_to_t6` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t6_keeps_the_duplicate_check_on_a_legacy_catalog` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_rules_todo.py::test_t6_checks_split_ids` fails with ImportError, then passes
- [x] Test `tests/schemas/test_todo_catalog_schema.py::test_todo_id_pattern_takes_stable_codes_only` fails with ImportError, then passes
- [x] Test `tests/schemas/test_todo_catalog_schema.py::test_retired_and_legacy_ids_validate` fails with ImportError, then passes
- [x] Test `tests/schemas/test_todo_catalog_schema.py::test_legacy_ids_rejects_a_bad_map` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_scaffold.py::test_starter_catalog_has_no_retired_ids_yet` fails with AssertionError, then passes
- [x] Test `tests/lib/test_todo_sync_ranking.py::test_fixture_order_follows_the_scores` fails with ImportError, then passes
- [x] Record it: `plan.py record 0011 CAT-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 3c451fe: 12 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `3c451fe`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/lib/test_todo_sync_rules_todo.py::test_t6_accepts_ids_that_do_not_follow_rank tests/lib/test_todo_sync_rules_todo.py::test_t6_flags_duplicate_and_retired_ids tests/lib/test_todo_sync_rules_todo.py::test_t6_still_checks_ranks_run_1_to_n tests/lib/test_todo_sync_rules_todo.py::test_t6_reports_a_legacy_catalog_once tests/lib/test_todo_sync_rules_todo.py::test_t1_leaves_legacy_ids_to_t6 tests/lib/test_todo_sync_rules_todo.py::test_t6_keeps_the_duplicate_check_on_a_legacy_catalog tests/lib/test_todo_sync_rules_todo.py::test_t6_checks_split_ids tests/schemas/test_todo_catalog_schema.py::test_todo_id_pattern_takes_stable_codes_only tests/schemas/test_todo_catalog_schema.py::test_retired_and_legacy_ids_validate tests/schemas/test_todo_catalog_schema.py::test_legacy_ids_rejects_a_bad_map tests/lib/test_todo_sync_scaffold.py::test_starter_catalog_has_no_retired_ids_yet tests/lib/test_todo_sync_ranking.py::test_fixture_order_follows_the_scores`

### RET-1: retire: record retired ids, re-rank, rewrite nothing

**Status:** COMPLETE | **Model:** opus | **Depends on:** IDS-1, CAT-1
**Files:** `plugins/harness/lib/harness_lib/todo_sync/retire.py`, `tests/lib/test_todo_sync_retire.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:54-73` holds `def retire_items(catalog: Dict[str, Any], ids: Iterable[str]) -> Retirement:`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:185-194` holds `edits, dangling = companion_edits(cfg, out.renames, notes)`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:197-208` holds `def load_catalog(cfg: HarnessConfig, verb: str) -> Tuple[str, Dict[str, Any]]:`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:218-225` holds `def other_references(cfg: HarnessConfig, edited: Iterable[str]) -> Tuple[str, ...]:`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:295-296` holds `argv = ["git", "-C", str(cfg.project_root), "grep", "--untracked", "-n", "-I", "-E", "TODO-[0-9]{3,}",`
- `plugins/harness/scripts/todo_sync.py:208` holds `print("\n".join(summary_lines(apply_retirement(cfg, args.ids, args.dry_run), args.dry_run)))`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:292-302` holds `except (OSError, subprocess.TimeoutExpired): return ()`
- `plugins/harness/lib/harness_lib/todo_sync/reshape.py:33-35` holds `normalize_id, other_references, recount, remap_text, todo_id,`

1. retire.py imports the id module as `from harness_lib.todo_sync import ids as todo_ids` (retire_items and apply_retirement take a parameter named ids, which shadows a bare `ids` import). It deletes _rewrite_catalog and keeps ID_RE, _SHORT, todo_id, normalize_id, remap_text and companion_edits, which reshape.py imports until RSH-1 deletes them; retire's own paths stop calling them. 2. load_catalog(cfg, verb, stable=True) calls todo_ids.require_stable(data, verb) when stable is true (migrate-ids passes False). 3. retire_items(catalog, ids): require_stable; gone = todo_ids.resolve_ids; drop the items; unlink as today (_ordered, _drop_links); ranks 1..n in the kept order; append the retired ids, in catalog order, to catalog['retired_ids'] (created when absent); recount; dangling lists every catalog string naming a gone id through todo_ids.mentions (case-insensitive) as '<json path> names retired <id>', item paths reading 'items/<id>/...', skipping the top-level id records retired_ids, legacy_ids and split_ids; no other string changes. Retirement loses renames. 4. history_paths(cfg) -> repo-relative posix paths without a trailing '/': artifacts.plans, artifacts.reviews, artifacts.commit_messages, artifacts.summaries, artifacts.scratch, each artifacts.planning_prefixes entry, and todo.snapshots.dir when set. 5. companion_mentions(cfg, notes) -> '<rel>:<line> <note>' for each research-catalog or stub line naming an id in notes (todo_ids.mentions); nothing is rewritten. 6. git_grep(cfg, args) runs `git -C <root> grep <args>` (timeout 60 s) and returns its stdout lines; exit 1 means none; an OSError, a timeout or an exit of 2 or more raises TodoSyncError('git grep failed: <reason>') with the OSError text, 'timed out after 60 s', or git's first stderr line. other_references(cfg, ids) -> 'path:line:text' from git_grep with --untracked -n -I -i -F -w and one -e per id and no exclude pathspecs: lines under the catalog, the companions and history_paths are dropped in Python (a long pathspec list overruns the Windows command line); () when ids is empty or the project root holds no .git. 7. apply_retirement writes only the catalog (write_edits(cfg, text, {})), then scans; a TodoSyncError from other_references leaves references () and sets scan_error. RetireResult loses rewritten and gains scan_error: Optional[str] = None; summary_lines drops the renumbered and rewrote lines and prints 'reference scan failed: <scan_error>'. 8. RetireResult.dangling holds the catalog lines first, then companion_mentions ('<rel>:<line> names retired <id>'); summary_lines prints each as 'dangling: ...'.

- [x] Test `tests/lib/test_todo_sync_retire.py::test_retire_records_the_id_and_keeps_every_other_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_retire_reranks_without_renaming` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_retired_ids_accumulate` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_a_retired_id_left_in_prose_is_reported_not_rewritten` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_dangling_skips_the_id_records` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_retire_names_a_retired_or_old_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_retire_refuses_a_legacy_catalog` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_companion_mentions_are_listed_not_rewritten` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_other_references_name_only_the_retired_ids` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_history_paths_include_commit_messages` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_retire.py::test_a_failed_reference_scan_is_reported` fails with ImportError, then passes
- [x] Record it: `plan.py record 0011 RET-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 25297a9: 11 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `25297a9`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/lib/test_todo_sync_retire.py::test_retire_records_the_id_and_keeps_every_other_id tests/lib/test_todo_sync_retire.py::test_retire_reranks_without_renaming tests/lib/test_todo_sync_retire.py::test_retired_ids_accumulate tests/lib/test_todo_sync_retire.py::test_a_retired_id_left_in_prose_is_reported_not_rewritten tests/lib/test_todo_sync_retire.py::test_dangling_skips_the_id_records tests/lib/test_todo_sync_retire.py::test_retire_names_a_retired_or_old_id tests/lib/test_todo_sync_retire.py::test_retire_refuses_a_legacy_catalog tests/lib/test_todo_sync_retire.py::test_companion_mentions_are_listed_not_rewritten tests/lib/test_todo_sync_retire.py::test_other_references_name_only_the_retired_ids tests/lib/test_todo_sync_retire.py::test_history_paths_include_commit_messages tests/lib/test_todo_sync_retire.py::test_a_failed_reference_scan_is_reported`

### ENT-1: add-todo and sync-gh-todo refuse a legacy catalog before any dispatch

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** IDS-1, CAT-1
**Files:** `plugins/harness/scripts/add_todo.py`, `plugins/harness/lib/harness_lib/todo_sync/issues.py`, `tests/scripts/test_add_todo.py`, `tests/lib/test_todo_sync_issues.py`

**Anchors:**
- `plugins/harness/scripts/add_todo.py:45-51` holds `def _ready(cfg: HarnessConfig) -> None:`
- `plugins/harness/lib/harness_lib/todo_sync/issues.py:118-121` holds `def find_untracked(cfg: HarnessConfig) -> List[Dict[str, Any]]:`

Refuse a legacy catalog before any agent is dispatched. scripts/add_todo.py _ready (:45-51): after the catalog-exists check, parse the catalog and call ids.require_stable(data, 'add-todo'); a TodoSyncError becomes Refused with its text (exit 1, 'problem: add-todo: ...'); an unparseable catalog is left to the later add, as today. issues.find_untracked (:118-126): after _require_folder, call ids.require_stable on the loaded catalog (Sources(cfg).todo.data) with the verb 'untracked', before open_issues, so gh is never called and no sync-gh-todo agent drafts an item the script will refuse. Copy the planned test files.

- [x] Test `tests/scripts/test_add_todo.py::test_driver_refuses_a_legacy_catalog_before_the_dispatch` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_issues.py::test_find_untracked_refuses_a_legacy_catalog_before_gh` fails with ImportError, then passes
- [x] Record it: `plan.py record 0011 ENT-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 9f4f315: 2 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `9f4f315`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/scripts/test_add_todo.py::test_driver_refuses_a_legacy_catalog_before_the_dispatch tests/lib/test_todo_sync_issues.py::test_find_untracked_refuses_a_legacy_catalog_before_gh`

### RSH-1: split, add and refresh keep ids; only ranks move

**Status:** COMPLETE | **Model:** opus | **Depends on:** RET-1
**Files:** `plugins/harness/lib/harness_lib/todo_sync/reshape.py`, `tests/lib/test_todo_sync_reshape.py`, `tests/lib/test_todo_sync_add.py`, `tests/lib/test_todo_sync_add_note.py`, `plugins/harness/lib/harness_lib/todo_sync/retire.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/todo_sync/reshape.py:33-35` holds `from harness_lib.todo_sync.retire import (ID_RE, REFERENCE_CAP, companion_edits, dump_like, load_catalog,`
- `plugins/harness/lib/harness_lib/todo_sync/reshape.py:178` holds `probe = {**item, "id": "TODO-001", "rank": 1, "priority": _PLACEHOLDER_PRIORITY}`
- `plugins/harness/lib/harness_lib/todo_sync/reshape.py:334-351` holds `def _renumber(data: Dict[str, Any], orig_id: Optional[str], first: Optional[str]) -> Reshape:`
- `plugins/harness/lib/harness_lib/todo_sync/reshape.py:495-507` holds `def _apply(cfg: HarnessConfig, verb: str, fn: Callable[[Dict[str, Any]], Reshape],`
- `plugins/harness/lib/harness_lib/todo_sync/reshape.py:505` holds `write_edits(cfg, dump_like(out.catalog, raw), edits)`
- `tests/lib/test_todo_sync_file_issue.py:159` holds `monkeypatch.setattr(reshape, "write_edits", locked)`
- `plugins/harness/scripts/todo_sync.py:202` holds `result = apply_add(cfg, args.spec, args.dry_run, file_issues=args.file_issue)`

1. Imports from retire shrink to REFERENCE_CAP, companion_mentions, dump_like, load_catalog, other_references, recount, walk_strings, write_edits; the id module comes in as todo_ids. write_edits stays a module-level name in reshape (tests/lib/test_todo_sync_file_issue.py:159 swaps it). Then retire.py loses ID_RE, _SHORT, todo_id, normalize_id, remap_text and companion_edits, which nothing imports any more. 2. _renumber, _rewrite, _where, _record go; _rerank(data) rescores, sorts by expected_order, sets rank to the position and recounts, returning the rescored ids and the (id, old rank, new rank) moves in new-rank order; items added and split parts made in the same call are left out of both (they had no rank). 3. split_item(catalog, raw_id, parts, rng=None): require_stable; the original resolves through todo_ids.resolve_ids; each part gets todo_ids.new_id over taken_ids (the original included); links, tracker and close candidates as today; the original id joins retired_ids and split_ids[orig] holds the part ids in spec order (split_ids created when absent); every catalog string naming it (todo_ids.mentions, case-insensitive, skipping retired_ids, legacy_ids and split_ids) is flagged '<json path> names split <orig> (parts <a>, <b>)' and left as written. 4. add_items(catalog, specs, today=None, rng=None): each new item gets todo_ids.new_id; the placeholder add-new-N ids go. 5. refresh_items: _rerank only. 6. Reshape loses renames and gains reranked; ReshapeResult loses rewritten and gains scan_error (as RetireResult). _apply loads with require_stable, writes only the catalog through write_edits(cfg, text, {}), lists companion_mentions and other_references for a split's original id, and records a failed scan in scan_error. 7. _check_item's probe id becomes a valid stable id (todo-2a2a). 8. apply_split and apply_add take rng=None and pass it on. 9. summary_lines: 're-ranked N item(s): <id> <old>-><new>, ...' replaces the renumbered line; split flags print as 'dangling: ...'; a dry run that draws ids adds the line 'note: new ids are drawn at random; the real run draws its own'; a failed scan prints 'reference scan failed: <reason>'. 10. _append keeps a sorted id list sorted (an empty list counts as sorted), so unblocks, child_todo_ids and related_todo_ids stay in the order the schema describes.

- [x] Test `tests/lib/test_todo_sync_reshape.py::test_split_gives_parts_new_ids_and_retires_the_original` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_reshape.py::test_split_inherits_links_tracker_and_close_candidates` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_reshape.py::test_split_prose_naming_the_original_is_flagged_not_rewritten` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_reshape.py::test_split_flags_skip_the_id_records` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_reshape.py::test_split_never_draws_a_live_retired_or_original_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_reshape.py::test_split_refuses_a_legacy_catalog` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_reshape.py::test_refresh_reranks_without_renaming` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_add.py::test_added_items_get_new_ids_and_every_other_id_stays` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_add.py::test_low_value_item_lands_last` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_add.py::test_apply_add_writes_the_catalog_and_dry_run_does_not` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_add.py::test_add_never_draws_a_retired_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_add.py::test_dry_run_says_its_ids_are_provisional` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_add_note.py::test_note_head_line_names_a_stable_id` fails with ImportError, then passes
- [x] Run `python -m pytest tests/lib/test_todo_sync_file_issue.py -q`: passed
- [x] Record it: `plan.py record 0011 RSH-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 1fee038: 13 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `1fee038`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/lib/test_todo_sync_reshape.py::test_split_gives_parts_new_ids_and_retires_the_original tests/lib/test_todo_sync_reshape.py::test_split_inherits_links_tracker_and_close_candidates tests/lib/test_todo_sync_reshape.py::test_split_prose_naming_the_original_is_flagged_not_rewritten tests/lib/test_todo_sync_reshape.py::test_split_flags_skip_the_id_records tests/lib/test_todo_sync_reshape.py::test_split_never_draws_a_live_retired_or_original_id tests/lib/test_todo_sync_reshape.py::test_split_refuses_a_legacy_catalog tests/lib/test_todo_sync_reshape.py::test_refresh_reranks_without_renaming tests/lib/test_todo_sync_add.py::test_added_items_get_new_ids_and_every_other_id_stays tests/lib/test_todo_sync_add.py::test_low_value_item_lands_last tests/lib/test_todo_sync_add.py::test_apply_add_writes_the_catalog_and_dry_run_does_not tests/lib/test_todo_sync_add.py::test_add_never_draws_a_retired_id tests/lib/test_todo_sync_add.py::test_dry_run_says_its_ids_are_provisional tests/lib/test_todo_sync_add_note.py::test_note_head_line_names_a_stable_id`

### MIG-1: migrate-ids: the one-time switch with a legacy map

**Status:** COMPLETE | **Model:** opus | **Depends on:** IDS-1, CAT-1, RET-1
**Files:** `plugins/harness/lib/harness_lib/todo_sync/migrate.py`, `tests/lib/test_todo_sync_migrate.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:228-235` holds `def dump_like(data: Dict[str, Any], raw: str) -> str:`
- `plugins/harness/lib/harness_lib/todo_sync/retire.py:238-247` holds `def _companions(cfg: HarnessConfig) -> List[str]:`
- `plugins/harness/lib/harness_lib/todo_sync/report.py:89` holds `def write_atomic(path: Path, text: str) -> Path:`
- `plugins/harness/lib/harness_lib/todo_sync/rules_todo.py:31-34` holds `def _schema(src: Sources) -> Any:`
- `plugins/harness/lib/harness_lib/config.py:435-441` holds `schema = _if_present(root, _in_folder(folder, t["catalog_schema"], "todo/catalog_schema"),`

New todo_sync/migrate.py (the id module as todo_ids). migrate_catalog(catalog, today, rng=None) -> Migration(catalog, mapping, unmapped): (a) refusals: no legacy item id and no legacy_ids, 'nothing to migrate: every item id is already stable'; duplicate legacy item ids, 'duplicate legacy id(s): TODO-002, ...; give each item its own id first'; a legacy item id already a key of legacy_ids.map, '<id> is already in legacy_ids (migrated <date>); an older harness may have renumbered the catalog: restore it from git'. (b) Each legacy item id, in item order, draws todo_ids.new_id over the taken ids; with rng None each draw is seeded from sha256 of '<old id>\0<title>' (random.Random over the first 8 bytes), so two checkouts of one catalog, and a dry run and its real run, give the same map; a passed rng is used as is. (c) The full map is the stored legacy_ids.map plus the new entries; every catalog string outside legacy_ids is rewritten through it in one pass (no chained renames). A link-list entry (depends_on, unblocks, child_todo_ids, related_todo_ids) with no mapping is dropped and listed '<json path of the list> dropped TODO-NNN, no live item'; any other string keeps it, listed '<json path> names TODO-NNN, no live item' (item paths read items/<new id>/...). A link list sorted before the rewrite is sorted after it. (d) retired_ids is set to [] when absent; legacy_ids = {migrated: the stored date, else today; map: the stored entries plus the new ones}; mapping holds only the new entries (empty on a rerun). apply_migration(cfg, dry_run=False, exclude=(), today=None, rng=None) -> MigrateResult(migration, rewritten ((rel, hits), ...), unmapped ('rel:line names TODO-NNN'), skipped ((rel, reason), ...), schema_problem: Optional[str]): loads with load_catalog(cfg, 'migrate-ids', stable=False); the files are the companions plus retire.git_grep(--untracked -l -I -E 'TODO-[0-9]{3,}') (a git failure raises before anything is written) minus the catalog, the configured catalog schema (cfg.todo.catalog_schema), retire.history_paths and every exclude; an exclude matches by path component after posix() and dropping a trailing '/' ('vendor' skips vendor/x.md, never vendored.md). Every file is read and strictly decoded before any write; a file that is not UTF-8 is skipped ('not UTF-8'); rewrites go through the full map and keep bytes and line endings; old ids with no mapping stay and are listed. When cfg.todo.catalog_schema is set, the migrated catalog is validated against that schema (its declared draft, as T1 does); a failure sets schema_problem '<schema rel> rejects the migrated catalog (<first error, cut to 200 characters>); replace it with the harness catalogs/TodoCatalog.schema.json or update its id pattern, then rerun'. A dry run reports it; a real run raises it before writing. A real run writes the catalog first (dump_like, write_atomic, only when its text changed), then each file through the module-level write_file(path, data); a file that fails raises TodoSyncError naming every file not written ('not written: a, b; rerun migrate-ids to finish through the stored map'). A dry run writes nothing. summary_lines(result, dry_run): '[would migrate|migrated] N item(s) to stable ids', one 'id TODO-NNN -> todo-xxxx' line per new entry, '[would rewrite|rewrote] <rel> (<n> reference(s))', 'unmapped: ...' (capped at REFERENCE_CAP), 'skipped: <rel> (<reason>)', 'schema: <schema_problem>', 'history left as written: <paths>', and on a real run 'next: todo_sync.py render, then todo_sync.py check'.

- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_gives_every_item_a_stable_id_and_keeps_the_map` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_rewrites_links_and_prose_in_one_pass` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_lists_old_ids_with_no_live_item` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_refuses_a_stable_catalog` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_apply_rewrites_companions_and_live_files` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_apply_leaves_history_and_excluded_paths` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_apply_dry_run_writes_nothing` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_apply_skips_a_file_that_is_not_utf8` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrated_catalog_passes_check` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migration_ids_are_reproducible` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_refuses_duplicate_legacy_ids` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_refuses_a_key_already_in_the_map` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_migrate_adds_new_legacy_ids_to_the_stored_map` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_apply_never_rewrites_the_catalog_schema` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_a_project_schema_that_rejects_stable_ids_refuses` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_a_failed_git_grep_writes_nothing` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_a_failed_file_write_leaves_the_map_for_a_rerun` fails with ImportError, then passes
- [x] Test `tests/lib/test_todo_sync_migrate.py::test_rerun_applies_the_stored_map_to_live_files` fails with ImportError, then passes
- [x] Record it: `plan.py record 0011 MIG-1 --sha <sha>` or `--staged`

**Evidence:** staged tree c0a6e55: 18 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `c0a6e55`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/lib/test_todo_sync_migrate.py::test_migrate_gives_every_item_a_stable_id_and_keeps_the_map tests/lib/test_todo_sync_migrate.py::test_migrate_rewrites_links_and_prose_in_one_pass tests/lib/test_todo_sync_migrate.py::test_migrate_lists_old_ids_with_no_live_item tests/lib/test_todo_sync_migrate.py::test_migrate_refuses_a_stable_catalog tests/lib/test_todo_sync_migrate.py::test_apply_rewrites_companions_and_live_files tests/lib/test_todo_sync_migrate.py::test_apply_leaves_history_and_excluded_paths tests/lib/test_todo_sync_migrate.py::test_apply_dry_run_writes_nothing tests/lib/test_todo_sync_migrate.py::test_apply_skips_a_file_that_is_not_utf8 tests/lib/test_todo_sync_migrate.py::test_migrated_catalog_passes_check tests/lib/test_todo_sync_migrate.py::test_migration_ids_are_reproducible tests/lib/test_todo_sync_migrate.py::test_migrate_refuses_duplicate_legacy_ids tests/lib/test_todo_sync_migrate.py::test_migrate_refuses_a_key_already_in_the_map tests/lib/test_todo_sync_migrate.py::test_migrate_adds_new_legacy_ids_to_the_stored_map tests/lib/test_todo_sync_migrate.py::test_apply_never_rewrites_the_catalog_schema tests/lib/test_todo_sync_migrate.py::test_a_project_schema_that_rejects_stable_ids_refuses tests/lib/test_todo_sync_migrate.py::test_a_failed_git_grep_writes_nothing tests/lib/test_todo_sync_migrate.py::test_a_failed_file_write_leaves_the_map_for_a_rerun tests/lib/test_todo_sync_migrate.py::test_rerun_applies_the_stored_map_to_live_files`

### DRV-1: Driver: migrate-ids subcommand and stable-id help

**Status:** COMPLETE | **Model:** opus | **Depends on:** RET-1, RSH-1, MIG-1
**Files:** `plugins/harness/scripts/todo_sync.py`, `tests/scripts/test_todo_sync.py`, `tests/scripts/test_todo_sync_intake.py`, `tests/contract/test_root_separation.py`

**Anchors:**
- `plugins/harness/scripts/todo_sync.py:123-131` holds `ret = sub.add_parser("retire", parents=[common], help="Remove finished items and renumber the rest.")`
- `plugins/harness/scripts/todo_sync.py:194-215` holds `def _dispatch(cfg: HarnessConfig, args: argparse.Namespace) -> int:`
- `tests/contract/test_root_separation.py:194-196` holds `"todo_sync retire": lambda r, t: (_todo_args(r, "retire", "1"), None),`

scripts/todo_sync.py: new subcommand 'migrate-ids [--dry-run] [--exclude PATH]...', --exclude repeatable (action='append', default []), help 'Give every item a stable id once and rewrite live references; a rerun finishes through the stored map', dispatching to migrate.apply_migration and printing migrate.summary_lines; retire and split id help 'Item ids: todo-k7qf or k7qf (any case).'; retire help 'Remove finished items and record their ids as retired.'; split help 'Replace one item with parts that get new ids.'; refresh help 'Rescore and re-rank every item.'; the module docstring's retire, split, refresh and add sections describe stable ids (no renumbering, no id rewrites, retired_ids, split_ids, the reference list naming only the retired or split id), and a new migrate-ids section (dry run, repeatable --exclude, the project schema check, the rerun through the stored map). test_root_separation: retire and split cases use ID1 and ID2; a new 'todo_sync migrate-ids' case runs on the legacy fixture. MUST_EXIT_ZERO gains todo_sync retire, split, refresh and migrate-ids, so a refusal no longer passes the snapshot check vacuously.

- [x] Test `tests/scripts/test_todo_sync.py::test_retire_keeps_ids_and_lists_references` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_retire_skips_plan_review_and_commit_message_records` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_retire_skips_the_configured_record_folders` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_split_dry_run_writes_nothing` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_split_retires_the_original_and_flags_prose` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_refresh_reranks_after_a_hand_edit` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_operations_refuse_a_legacy_catalog` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_migrate_ids_dry_run_writes_nothing` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_migrate_ids_rewrites_live_files_and_keeps_history` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync.py::test_render_then_t2_is_clean` fails with ImportError, then passes
- [x] Test `tests/scripts/test_todo_sync_intake.py::test_add_prints_the_new_stable_id` fails with ImportError, then passes
- [x] Test `tests/contract/test_root_separation.py::test_entry_point_writes_nothing_under_plugins[todo_sync migrate-ids]` fails with ImportError, then passes
- [x] Test `tests/contract/test_root_separation.py::test_migrate_ids_writes_the_map_into_the_project_catalog` fails with ImportError, then passes
- [x] Record it: `plan.py record 0011 DRV-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 0e56ecb: 13 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `0e56ecb`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/scripts/test_todo_sync.py::test_retire_keeps_ids_and_lists_references tests/scripts/test_todo_sync.py::test_retire_skips_plan_review_and_commit_message_records tests/scripts/test_todo_sync.py::test_retire_skips_the_configured_record_folders tests/scripts/test_todo_sync.py::test_split_dry_run_writes_nothing tests/scripts/test_todo_sync.py::test_split_retires_the_original_and_flags_prose tests/scripts/test_todo_sync.py::test_refresh_reranks_after_a_hand_edit tests/scripts/test_todo_sync.py::test_operations_refuse_a_legacy_catalog tests/scripts/test_todo_sync.py::test_migrate_ids_dry_run_writes_nothing tests/scripts/test_todo_sync.py::test_migrate_ids_rewrites_live_files_and_keeps_history tests/scripts/test_todo_sync.py::test_render_then_t2_is_clean tests/scripts/test_todo_sync_intake.py::test_add_prints_the_new_stable_id tests/contract/test_root_separation.py::test_entry_point_writes_nothing_under_plugins[todo_sync migrate-ids] tests/contract/test_root_separation.py::test_migrate_ids_writes_the_map_into_the_project_catalog`

### DOC-1: README: stable ids and migrate-ids

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `README.md`, `tests/skills/test_todo_stable_id_prose.py`

**Anchors:**
- `README.md:402-409` holds `removes finished items: ids follow rank (rule T6), so it renumbers`
- `README.md:421-427` holds `item per spec entry, scores it, renumbers the rest, recounts`
- `README.md:436-442` holds `insert, score, renumber, recount; refuses a recorded issue`
- `README.md:454-460` holds `insert as a note (or --file-issue), score, renumber, recount`
- `README.md:405-411` holds `` `/harness:todo-edit --retire 1, 3 [--delete-retired] | --split 001 | --refresh` ``

README.md: the add-todo and sync-gh-todo rows (:33-34) say the script scores and ranks (no renumbering); the todo-sync paragraphs (:404-409, :425) describe stable ids, retired_ids and split_ids, the reference list naming only a retired or split id, and give the /harness:todo-edit example with stable ids (--retire todo-k7qf, m3x9 [--delete-retired] | --split todo-sp7t | --refresh). One paragraph names todo_sync.py migrate-ids: dry run first, history left as written, the legacy_ids map, a repeatable --exclude matched by path component, the project's own RepoToDo.schema.json (or the file todo.catalog_schema names) updated from the harness catalogs/TodoCatalog.schema.json first, every install that runs todo_sync on the project updated to this release first (an older harness renumbers stable ids back on its next add or refresh), and a rerun finishing a partial switch through the stored map; that paragraph holds the phrase 'every install' and the name 'RepoToDo.schema.json'. The flow blocks (:440, :458) read 'insert, score, rank, recount'.

- [x] Test `tests/skills/test_todo_stable_id_prose.py::test_readme_todo_text_never_renumbers` fails with AssertionError, then passes
- [x] Test `tests/skills/test_todo_stable_id_prose.py::test_readme_documents_migrate_ids` fails with AssertionError, then passes
- [x] Test `tests/skills/test_todo_stable_id_prose.py::test_readme_has_no_rank_number_examples` fails with AssertionError, then passes
- [x] Record it: `plan.py record 0011 DOC-1 --sha <sha>` or `--staged`

**Evidence:** staged tree f347833: 3 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `f347833`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/skills/test_todo_stable_id_prose.py::test_readme_todo_text_never_renumbers tests/skills/test_todo_stable_id_prose.py::test_readme_documents_migrate_ids tests/skills/test_todo_stable_id_prose.py::test_readme_has_no_rank_number_examples`

### SKL-1: todo-edit, todo-editor and sync-gh-todo prose, strapped

**Status:** COMPLETE | **Model:** opus | **Depends on:** DRV-1
**Files:** `plugins/harness/skills/todo-edit/SKILL.md`, `plugins/harness/agents/todo-editor.md`, `plugins/harness/skills/sync-gh-todo/SKILL.md`, `tests/skills/test_todo_edit_skill_contract.py`, `tests/skills/test_sync_gh_todo_skill_contract.py`, `docs/plans/strap/todo-edit/SkillSpec.json`

**Anchors:**
- `plugins/harness/skills/todo-edit/SKILL.md:9-12` holds `Ids in the catalog equal their rank (rule T6), so every structural edit renumbers items`
- `plugins/harness/agents/todo-editor.md:225` holds `Renumbered: <old->new, ... | none>`
- `plugins/harness/skills/sync-gh-todo/SKILL.md:18` holds `` `todo_sync.py add` inserts the items and renumbers ``
- `tests/skills/test_todo_edit_skill_contract.py:18` holds `_REPLY_FIELDS = ("Operation", "Result", "Renumbered",`
- `tests/skills/test_sync_gh_todo_skill_contract.py:22` holds `_REPLY_FIELDS = ("Operation", "Result", "Renumbered",`

Run harness:strap-skills steps 5-12 on docs/plans/strap/todo-edit/SkillSpec.json (opened with `strap.py new todo-edit --edit`, base = this plan's base; parts: the SKILL.md, the contract test and the agent plugins/harness/agents/todo-editor.md). Mechanical behaviors, tested in tests/skills/test_todo_edit_skill_contract.py: B1 the agent reply has 'Retired ids:' where 'Renumbered:' was; B2 the skill passes ids as typed (the script canonicalizes, a trailing comma included) and its description and examples use todo-xxxx ids; B3 no prose says ids equal rank or that edits renumber; B4 the agent never hand-edits id, rank, retired_ids, legacy_ids or split_ids; B5 the agent relays a migrate-ids refusal with the full launcher command (sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" migrate-ids --dry-run) and stops, never running migrate-ids; B7 the agent's split step works the 'dangling: <where> names split <orig> (parts <a>, <b>)' lines, rewording each sentence to the part (or parts) it meant, with part ids taken from the real run's report (the dry run's are provisional). Judgment behavior, drawn and run: B6 the session dispatches stable ids as typed. sync-gh-todo SKILL.md:18 'inserts the items and renumbers' becomes 'inserts and ranks the items'; tests/skills/test_sync_gh_todo_skill_contract.py:22 takes 'Retired ids' in _REPLY_FIELDS.

- [x] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" plugins/harness/scripts/strap.py check todo-edit`: check [ok]
- [x] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" plugins/harness/scripts/strap.py freeze todo-edit`: freeze [done] | todo-edit
- [x] Run `python -m pytest tests/skills/test_sync_gh_todo_skill_contract.py tests/skills/test_todo_edit_skill_contract.py -q`: passed
- [x] Record it: `plan.py record 0011 SKL-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 955d813

**Recorded:** 2026-11-09, staged, tree `955d813`

### SKL-2: add-todo refreeze over the changed todo-editor agent

**Status:** CLOSED_NO_ACTION | **Model:** opus | **Depends on:** SKL-1
**Files:** `docs/plans/strap/add-todo/SkillSpec.json`

**Anchors:**
- `docs/plans/strap/add-todo/SkillSpec.json:30` holds `"path": "plugins/harness/agents/todo-editor.md"`

docs/plans/strap/add-todo/SkillSpec.json lists plugins/harness/agents/todo-editor.md as a part (:30), so SKL-1 stales its frozen hash. Run the add-todo judgment greens B4 and B6 (B5 is dropped) on the new hash per harness:strap-skills step 12, grade them, and, with the developer's OK (given 2026-11-09), refreeze.

- [x] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" plugins/harness/scripts/strap.py freeze add-todo --refreeze`: freeze [done] | add-todo
- [x] Record it: `plan.py record 0011 SKL-2 --sha <sha>` or `--staged`

**Evidence:** add-todo greens run on this repo's own catalog, still TODO-NNN until MIG-2 (after 0.65.0 ships, D14); the ENT-1 legacy refusal stops the row first, so green R-8 (B4 SC-2, hash 17b57844ce19) failed on the environment, not the skill. add-todo stays frozen at 5422c856e8fa and check prints stale; after MIG-2 a follow-up changes an add-todo part (the R-8 slot on this hash is spent), reruns the B4 and B6 greens and refreezes (developer decision 2026-11-09).

**Recorded:** 2026-11-09, closed

### REL-1: Version bump and release notes

**Status:** COMPLETE | **Model:** haiku | **Depends on:** IDS-1, CAT-1, RET-1, RSH-1, MIG-1, DRV-1, ENT-1, DOC-1, SKL-1, SKL-2
**Files:** `plugins/harness/.claude-plugin/plugin.json`, `docs/RELEASES/v0.7.0.md`

**Anchors:**
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.64.0",`

Bump plugins/harness/.claude-plugin/plugin.json 0.64.0 -> 0.65.0 (D8: minor). In docs/RELEASES/v0.7.0.md set the harness row's Now to 0.65.0 and add one change line: stable todo-xxxx ids (issue 243), retired_ids and split_ids, migrate-ids with the legacy_ids map and a rerun through it, the reference list naming only retired or split ids, and the order to follow: update every install that runs todo_sync on a project, and its own RepoToDo.schema.json, before running migrate-ids there.

- [x] Run `claude plugin validate --strict plugins/harness`: passed
- [x] Run `ruff check --no-cache plugins tests tools`: All checks passed!
- [x] Record it: `plan.py record 0011 REL-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 4a6ef75

**Recorded:** 2026-11-09, staged, tree `4a6ef75`
