# Plan 0001: Bubble memos

> Rendered by `plan.py render` from `0001_Bubble_memos_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-10-29
**Spec:** `E:/automation/operator-straps/docs/superpowers/specs/2026-10-29-bubble-memo-design.md`
**Branch:** 1095-bubble-memos -> main
**Base commit:** `439db20`
**Frozen:** 2026-10-29 at `439db20`
**Execution model:** staged: library and exclusion first, then driver, agents and skill, then the mod; registration last

## Decisions

- **D1** Which bubbles does a memo cover? Chosen: `bubbles-plus-pending` (The review JSON's bubbles plus the pending fixer bubbles pr_review.py bubbles lists). Rejected: `bubbles-only` (Only the review JSON's bubbles, so the skill would have to run after closeout). Developer 2026-10-29: fixer bubbles reach bubbles only at closeout, after the Step 5 decision pause.
- **D2** Where does decision stamping run? Chosen: `mod` (A TypeScript mod, bubble-stamp, modelled on pr-review-watch). Rejected: `skill-step` (A scripted step of the skill or of closeout). Developer 2026-10-29: stamping is a ts-based mod, not a step after review closeout.
- **D3** What wakes the mod? Chosen: `events` (tool.call (driver shell calls, Edit/Write of the review JSON) plus turn.complete, with an mtime gate). Rejected: `poll` (A $.clock.every timer polling the review JSON). Developer 2026-10-29: tool plus turn.complete triggers.
- **D4** How is the memo index and stamp shaped? Chosen: `one-table-final-rows` (One index table with a Status column; entries never move; a stamp is final for a row). Rejected: `moving-sections` (Open and Decided sections; a stamp moves the entry). Developer 2026-10-29 confirmed the three format calls.
- **D5** Which models run the memo work? Chosen: `model-split` (Main session as is; opus investigators for flagged entries; reviewer opus when any entry is flagged, else sonnet, printed by the script). Rejected: `opus-everywhere` (Opus for the main session and every agent). Developer 2026-10-29 agreed with the split.
- **D6** How do the agents get their context? Chosen: `scripted-init-record` (A short prompt; first call is a script that prints the brief; last call is a script that validates and writes the report and prints the return block). Rejected: `prompt-carried` (The dispatcher writes the whole brief into the prompt). Developer 2026-10-29: minimal passed context; git and file discovery scripted.
- **D7** How does bubble_memo.py reach the pending fixer bubbles that pr_review.py computes? Chosen: `extract-to-lib` (Move closed_ids, fixer_bubbles and pending_bubbles into harness_lib/review_bubbles.py; pr_review.py imports them under the same names). Rejected: `import-script` (bubble_memo.py imports the scripts/pr_review.py module). Developer 2026-10-29: extract into harness_lib/review_bubbles.py; pr_review.py imports the names it already calls.
- **D8** Where do the agents' briefs and reports live? Chosen: `scratch-subfolder` (<artifacts.scratch>/bubble_memo/<PR>/ (inside the existing run-scratch exclusion)). Rejected: `state-dir` (<state_dir>/bubble-memo/<PR>/). Developer 2026-10-29: agreed with the recommendation.
- **D9** How many reviewer rounds does the skill run? Chosen: `one-round` (One reviewer round, a second only after an accuracy finding). Rejected: `until-clean` (Repeat review until a round returns no findings). Developer 2026-10-29: agreed with the recommendation.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| flagged entry rule | id starts with C, or the issue's file/files (or the entry's References) name more than one distinct path | spec Decision 2 | - |
| investigator model | opus | spec Decision 8 | model-split |
| reviewer model rule | opus when any entry is flagged, else sonnet | spec Decision 8 | model-split |
| bubble reason cap | 200 characters | plugins/harness/schemas/PR_REVIEW.schema.json:181 | - |
| agent scratch folder | <artifacts.scratch>/bubble_memo/<PR>/{briefs,facts,findings} | spec Section 1 (init, record) | scratch-subfolder |
| closing statuses the mod stamps | RESOLVED, CLOSED_NO_ACTION | plugins/harness/lib/harness_lib/review_merge.py:56 | one-table-final-rows |
| mod trigger scripts | pr_review.py, review_edit.py | spec Section 4 triggers | events |
| harness plugin version | 0.40.0 | plugins/harness/.claude-plugin/plugin.json:3 | - |
| pr-review-watch plugin version | 0.4.2 | plugins/pr-review-watch/.claude-plugin/plugin.json:3 | - |
| bubble-stamp first version | 0.1.0 | spec Constraints (Releases) | - |

## Formats

- **dispatch row**: `agent=harness:bubble-memo-investigator model=opus`, copied from `plugins/harness/scripts/pr_review.py:567`
- **return block**: `---
SIGNAL: DONE
AGENT_ROLE: investigator
OUTPUT: <path>
---`, copied from `plugins/harness/lib/harness_lib/review_models.py:410`
- **snapshot evidence**: `1a2b3c4 (working-tree snapshot; developer commits) - kept lenient equality`, copied from `plugins/harness/lib/harness_lib/review_edit.py:396`
- **review file name**: `1514_Feature_x.json`, copied from `plugins/pr-review-watch/hooks/bubbles.ts:100`
- **driver script in a shell command**: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" bubbles --pr 1514`, copied from `plugins/pr-review-watch/hooks/tracker.ts:67`
- **edited file path of an Edit or Write call**: `{ tool: 'Edit', file_path: '/repo/docs/PR_REVIEWS/1514_Feature_x.json' }`, copied from `plugins/todo-watch/hooks/checks.ts:204`

## Sweeps

- **S1** `five TypeScript m[o]ds`: `CLAUDE.md` (rewrite), `docs/superpowers/specs/2026-10-29-bubble-memo-design.md` (keep)

## Tasks

### BM-1: Exclude *_Bubbles.md by default

**Status:** COMPLETE | **Model:** haiku | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/default_exclusions.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/default_exclusions.py:38` holds `(DEFAULT_EXCLUSIONS, "this file, seeded by the harness"),`
- `plugins/harness/lib/harness_lib/default_exclusions.py:66` holds `return merged + [p for p in harness_patterns(cfg) if p not in merged]`

In default_exclusions.py add the row ("*_Bubbles.md", "bubble memos (point-in-time snapshots)") to _entries, before the row for the seeded file. harness_patterns and with_harness_patterns then carry it with no further change. Do not touch the module docstring's claims beyond naming the memos among the machine-generated paths.

- [x] Test `tests/lib/test_default_exclusions_bubbles.py::test_default_patterns_carry_the_memo_pattern` fails with AssertionError, then passes
- [x] Test `tests/lib/test_default_exclusions_bubbles.py::test_the_pattern_matches_a_memo_in_any_folder` fails with AssertionError, then passes
- [x] Test `tests/lib/test_default_exclusions_bubbles.py::test_a_seeded_file_holds_the_pattern` fails with AssertionError, then passes
- [x] Test `tests/lib/test_default_exclusions_bubbles.py::test_an_older_seeded_list_gains_it_in_memory` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/lib/test_default_exclusions.py tests/lib/test_review_plan.py -q`: passed, no failures (the existing exclusion consumers still hold)
- [x] Record the commit: `plan.py record 0001 BM-1 --sha <sha>`

**Evidence:** commit c6457e2: 4 test node(s) passed

- `c6457e2706ee6a32168e41911af05d016fc33228`
- `tree 5fc72cc386dc16dc4f6061d25c2eb8cf990a5567`
- `python -m pytest -q tests/lib/test_default_exclusions_bubbles.py::test_default_patterns_carry_the_memo_pattern tests/lib/test_default_exclusions_bubbles.py::test_the_pattern_matches_a_memo_in_any_folder tests/lib/test_default_exclusions_bubbles.py::test_a_seeded_file_holds_the_pattern tests/lib/test_default_exclusions_bubbles.py::test_an_older_seeded_list_gains_it_in_memory`

### BM-2: Extract the pending-fixer-bubble helpers into a library module

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/review_bubbles.py`, `plugins/harness/scripts/pr_review.py`

**Anchors:**
- `plugins/harness/scripts/pr_review.py:945` holds `def closed_ids(doc: Mapping[str, object]) -> Set[str]:`
- `plugins/harness/scripts/pr_review.py:1489` holds `def fixer_bubbles(run: Path) -> List[Tuple[str, rm.FixBubble]]:`
- `plugins/harness/scripts/pr_review.py:1494` holds `def pending_bubbles(doc: Mapping[str, object], run: Path) -> List[Tuple[str, rm.FixBubble]]:`
- `plugins/harness/scripts/pr_review.py:1473` holds `if args.id in closed_ids(doc):`
- `plugins/harness/scripts/pr_review.py:1881` holds `pending_lines(pending_bubbles(doc, run))`
- `plugins/harness/lib/harness_lib/review_models.py:513` holds `def load_fix_reports(directory: Path) -> Tuple[FixReport, ...]:`

Create harness_lib/review_bubbles.py holding closed_ids, fixer_bubbles and pending_bubbles, moved verbatim from scripts/pr_review.py (same signatures and behavior). pr_review.py imports the three names from it and drops the local definitions, so its call sites (closed_ids at the Phase 5 summary and the closeout paths, pending_bubbles in the bubbles and waves commands) keep working unchanged. pending_lines stays in pr_review.py. No behavior change; tests/scripts/test_pr_review_driver.py is the regression guard.

- [x] Test `tests/lib/test_review_bubbles.py::test_closed_ids_follow_the_latest_resolution` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_bubbles.py::test_fixer_bubbles_pair_each_bubble_with_its_fixer` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_bubbles.py::test_fixer_bubbles_of_a_run_without_reports_are_empty` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_bubbles.py::test_pending_bubbles_skip_ids_the_review_already_holds` fails with ImportError, then passes
- [x] Run `python -m pytest tests/scripts/test_pr_review_driver.py -q -k bubbles`: passed, no failures (pr_review.py bubbles and waves still print the pending lines)
- [x] Record the commit: `plan.py record 0001 BM-2 --sha <sha>`

**Evidence:** commit c6457e2: 4 test node(s) passed

- `c6457e2706ee6a32168e41911af05d016fc33228`
- `tree 5fc72cc386dc16dc4f6061d25c2eb8cf990a5567`
- `python -m pytest -q tests/lib/test_review_bubbles.py::test_closed_ids_follow_the_latest_resolution tests/lib/test_review_bubbles.py::test_fixer_bubbles_pair_each_bubble_with_its_fixer tests/lib/test_review_bubbles.py::test_fixer_bubbles_of_a_run_without_reports_are_empty tests/lib/test_review_bubbles.py::test_pending_bubbles_skip_ids_the_review_already_holds`

### BM-3: Library: memo format, scaffold, check, facts and reviewer model

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/bubble_memo.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/config.py:177` holds `def path(self, rel: str) -> Path:`
- `plugins/harness/lib/harness_lib/review_merge.py:55` holds `TIERS = ("critical", "important", "minor")`
- `plugins/harness/lib/harness_lib/review_merge.py:56` holds `CLOSED_STATUSES = ("RESOLVED", "CLOSED_NO_ACTION")`
- `plugins/harness/lib/harness_lib/review_edit.py:72` holds `def load_review(path: Union[str, Path]) -> Doc:`
- `plugins/harness/schemas/PR_REVIEW.schema.json:181` holds `"maxLength": 200,`

Create harness_lib/bubble_memo.py, pure (no config reads at import time; the root is an argument). Anchors as constants: MEMO_SUFFIX, INDEX_HEADER, STATUS_OPEN, STATUS_DECIDED, DECISION_OPEN, DECISION_PREFIX, ENTRY_PREFIX, STUB. Functions: memo_name(pr); currently_bubbled(doc, pending) -> Bubbled(id, cls, reason) (bubbles in order, then pending pairs not already present; class from bubble_up, else the pending pair, else 'unclassified'); flagged_ids(doc, ids) and needs_chain; reviewer_model(flagged); scaffold_memo(doc, bubbled); add_missing(text, doc, bubbled) -> (text, added) that appends entries and index rows and never edits existing text; parse_index and entry_blocks; check_memo(text, bubbled, doc, root) -> (problems, notes) with the rules of spec Section 1 (check) and problem lines formatted '<ID>: <what>'; Facts (pydantic) with validate_facts(raw, issue, root) that refuses an empty field, a fix_effects count different from the issue's fix list, and any reference whose file or line is not on disk; apply_facts(text, facts) that replaces only the flagged entry's References, Current behavior, When, Chain, flow and Expected-behavior stubs. Entry layout: spec 'Memo format'; a reference is a backticked path:line or path:start-end; an expected-behavior line is '- (a) <fix text> -> <effect>'. Python 3.11, Optional/Union, functions under 50 lines, no first or second person in comments.

- [x] Test `tests/lib/test_bubble_memo.py::test_the_anchors_are_pinned` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_flagged_means_critical_or_several_files` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_currently_bubbled_adds_pending_fixer_bubbles_once` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_an_unlisted_class_reads_unclassified` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_scaffold_writes_index_rows_headings_and_stubs` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_references_without_lines_are_stubbed` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_only_flagged_entries_carry_chain_and_flow` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_parse_index_reads_the_scaffolded_rows` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_add_missing_appends_new_entries_and_leaves_old_text_alone` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_add_missing_with_everything_present_changes_nothing` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_filled_memo_passes` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_unfilled_stubs_fail` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_bubbled_id_without_an_entry_fails` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_flagged_entry_without_a_chain_fails` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_an_entry_citing_two_files_needs_a_chain_even_when_the_json_names_one` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_line_past_the_end_of_the_file_fails` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_missing_file_fails` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_dropped_fix_option_fails` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_stale_id_is_a_note_not_a_problem` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_a_decided_id_is_neither_problem_nor_note` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_valid_facts_pass` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_invalid_facts_are_refused` fails with ImportError, then passes
- [x] Test `tests/lib/test_bubble_memo.py::test_apply_facts_fills_the_flagged_entry_but_not_prose` fails with ImportError, then passes
- [x] Run `python -m ruff check plugins/harness/lib/harness_lib/bubble_memo.py --no-cache`: All checks passed
- [x] Record the commit: `plan.py record 0001 BM-3 --sha <sha>`

**Evidence:** commit c6457e2: 23 test node(s) passed

- `c6457e2706ee6a32168e41911af05d016fc33228`
- `tree 5fc72cc386dc16dc4f6061d25c2eb8cf990a5567`
- `python -m pytest -q tests/lib/test_bubble_memo.py::test_the_anchors_are_pinned tests/lib/test_bubble_memo.py::test_flagged_means_critical_or_several_files tests/lib/test_bubble_memo.py::test_currently_bubbled_adds_pending_fixer_bubbles_once tests/lib/test_bubble_memo.py::test_an_unlisted_class_reads_unclassified tests/lib/test_bubble_memo.py::test_scaffold_writes_index_rows_headings_and_stubs tests/lib/test_bubble_memo.py::test_references_without_lines_are_stubbed tests/lib/test_bubble_memo.py::test_only_flagged_entries_carry_chain_and_flow tests/lib/test_bubble_memo.py::test_parse_index_reads_the_scaffolded_rows tests/lib/test_bubble_memo.py::test_add_missing_appends_new_entries_and_leaves_old_text_alone tests/lib/test_bubble_memo.py::test_add_missing_with_everything_present_changes_nothing tests/lib/test_bubble_memo.py::test_a_filled_memo_passes tests/lib/test_bubble_memo.py::test_unfilled_stubs_fail tests/lib/test_bubble_memo.py::test_a_bubbled_id_without_an_entry_fails tests/lib/test_bubble_memo.py::test_a_flagged_entry_without_a_chain_fails tests/lib/test_bubble_memo.py::test_an_entry_citing_two_files_needs_a_chain_even_when_the_json_names_one tests/lib/test_bubble_memo.py::test_a_line_past_the_end_of_the_file_fails tests/lib/test_bubble_memo.py::test_a_missing_file_fails tests/lib/test_bubble_memo.py::test_a_dropped_fix_option_fails tests/lib/test_bubble_memo.py::test_a_stale_id_is_a_note_not_a_problem tests/lib/test_bubble_memo.py::test_a_decided_id_is_neither_problem_nor_note tests/lib/test_bubble_memo.py::test_valid_facts_pass tests/lib/test_bubble_memo.py::test_invalid_facts_are_refused tests/lib/test_bubble_memo.py::test_apply_facts_fills_the_flagged_entry_but_not_prose`

### BM-4: Driver: scaffold, init, record, apply, check

**Status:** PENDING | **Model:** sonnet | **Depends on:** BM-2, BM-3
**Files:** `plugins/harness/scripts/bubble_memo.py`

**Anchors:**
- `plugins/harness/scripts/plan.py:69` holds `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))`
- `plugins/harness/scripts/plan.py:484` holds `def main(argv: Optional[Sequence[str]] = None) -> int:`
- `plugins/harness/lib/harness_lib/review_models.py:356` holds `return _pr_dir(pr, repo) / run_id`
- `plugins/harness/lib/harness_lib/review_models.py:347` holds `def run_dir(pr: int, repo: Optional[Path] = None, run_id: Optional[str] = None) -> Path:`

Create scripts/bubble_memo.py following plan.py's shape: sys.path insert of ../lib, argparse with --repo and subcommands, main(argv) returning 0 or 1, one 'problem: ...' line per defect on stderr, activate(load_config(project_root(...))) once. Commands per spec Section 1: scaffold --pr N (reads the newest <NNNN>_*.json for N from artifacts.reviews, the pending fixer bubbles through review_bubbles when a pr-review run exists and falls back to bubbles alone when it does not; creates or extends <artifacts.reviews>/PR_<N>_Bubbles.md; prints a 'scaffold [done]' line, the added and flagged ids and one investigator dispatch row per newly added flagged id; prints 'nothing currently bubbled' and writes no memo when the set is empty); init --pr N --id ID --role investigator and init --pr N --role reviewer (print the brief and save it under the agent scratch folder; git facts via read-only git, excerpts from the working tree, the exact record command); record --pr N [--id ID] --role investigator|reviewer (JSON on stdin; validate through the library, refuse off-disk references, write facts/<ID>.json or findings/<N>.json, print the fenced return block with SIGNAL: DONE); apply --pr N; check --pr N (exit 1 with '<ID>: <what>' problem lines, 'note:' lines never fail; when clean print 'check [ok]' and the reviewer dispatch row with model from reviewer_model and a 'Memo: <abs path>' prompt line). Dispatch rows: agent=<type> model=<m>, then PR, ISSUE (investigator), FILES (comma-separated), CONTEXT (one line, name plus class plus reason) and an optional Developer guidance line. The prompt never carries RUN_ID or AGENT_ID header lines.

- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_scaffold_covers_bubbles_and_pending_fixer_bubbles` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_scaffold_prints_one_investigator_row_per_flagged_id` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_scaffold_rerun_changes_nothing` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_scaffold_without_anything_bubbled_writes_no_memo` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_a_missing_review_is_a_problem` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_check_fails_on_stubs_and_passes_once_filled` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_check_prints_the_reviewer_row_with_the_model_rule` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_init_prints_the_brief_and_saves_it` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_record_writes_facts_and_prints_the_return_block` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_record_refuses_a_reference_off_disk` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_apply_writes_facts_into_the_entry_and_leaves_prose_stubs` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_reviewer_init_lists_every_entry` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_bubble_memo_driver.py::test_reviewer_record_validates_findings` fails with ImportError, then passes
- [ ] Run `python -m ruff check plugins/harness/scripts/bubble_memo.py --no-cache`: All checks passed
- [ ] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/bubble_memo.py --help`: usage text listing scaffold, init, record, apply and check
- [ ] Record the commit: `plan.py record 0001 BM-4 --sha <sha>`

**Evidence:** 

### BM-5: Agents: investigator and reviewer, and the usage-log list

**Status:** PENDING | **Model:** sonnet | **Depends on:** BM-4
**Files:** `plugins/harness/agents/bubble-memo-investigator.md`, `plugins/harness/agents/bubble-memo-reviewer.md`, `plugins/pr-review-watch/hooks/contract.ts`

**Anchors:**
- `plugins/pr-review-watch/hooks/contract.ts:121` holds `export const DEFINED_AGENTS = [`
- `plugins/pr-review-watch/hooks/contract.ts:122` holds `'harness:messenger', 'harness:pr-fixer',`
- `plugins/harness/agents/pr-reviewer.md:24` holds `tools: Read, Grep, Glob, Bash`
- `tests/mods/test_pr_review_watch_usage_contract.py:87` holds `assert ts_string_array(contract_ts, "DEFINED_AGENTS") == defined`

Create agents/bubble-memo-investigator.md and agents/bubble-memo-reviewer.md in pr-reviewer's shape: frontmatter name equal to the file stem, tools 'Read, Grep, Glob, Bash', a fallback model (investigator opus, reviewer sonnet; the dispatcher passes the model each printed row names), examples. Body: the prompt is a few header lines (PR, ISSUE, FILES, CONTEXT, Memo for the reviewer, optional Developer guidance); the first action is the `init` call exactly as the prompt's launcher writes it (sh hpy bubble_memo.py init ...); work from its output; run `record` exactly once; reply with the printed block verbatim and nothing else; 'Never write files', 'Read-only git' (show, diff, log, status, merge-base, rev-parse, ls-files, grep only), one command per Bash call, stop with 'problem:' lines when init fails or record fails three times. Investigator: trace the issue through the cited code and report current behavior, when it triggers, chain, flow, opened references and one effect per fix option; it does not write a recommendation or memo prose. Reviewer: accuracy (references exist and say what the entry claims, claims agree with the code, expected behavior follows from each fix, nothing contradicts the review JSON) and clarity and simplicity (ordinary words, one claim per bullet, nothing repeated, the recommendation stated once); findings are {id, kind, what, suggested}. Add both names to DEFINED_AGENTS in pr-review-watch's contract.ts in sorted order (they sort before harness:messenger).

- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_frontmatter_is_read_only[bubble-memo-investigator]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_frontmatter_is_read_only[bubble-memo-reviewer]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_init_comes_first_record_last[bubble-memo-investigator]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_init_comes_first_record_last[bubble-memo-reviewer]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_reply_is_the_record_block[bubble-memo-investigator]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_reply_is_the_record_block[bubble-memo-reviewer]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_never_writes_read_only_git[bubble-memo-investigator]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_never_writes_read_only_git[bubble-memo-reviewer]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_usage_log_knows_the_agent[bubble-memo-investigator]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_usage_log_knows_the_agent[bubble-memo-reviewer]` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_the_reviewer_names_both_lenses` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_agents_contract.py::test_the_investigator_reports_facts_not_prose` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/mods/test_pr_review_watch_usage_contract.py -q`: passed (DEFINED_AGENTS equals the agent files on disk)
- [ ] Record the commit: `plan.py record 0001 BM-5 --sha <sha>`

**Evidence:** 

### BM-6: Skill: bubble-memo

**Status:** PENDING | **Model:** sonnet | **Depends on:** BM-4, BM-5
**Files:** `plugins/harness/skills/bubble-memo/SKILL.md`, `tests/skills/test_skill_guidance_tail_contract.py`

**Anchors:**
- `plugins/harness/skills/write-plan/SKILL.md:4` holds `argument-hint: "<title> [--spec PATH] [--base BRANCH] [--no-fetch] [-- <guidance>]"`
- `tests/skills/test_skill_guidance_tail_contract.py:23` holds `_INVOCABLE = [`

Create skills/bubble-memo/SKILL.md modelled on write-plan: frontmatter name bubble-memo, a 'Use when ...' description, argument-hint ending in '-- <guidance>'; the body points at ${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md for the split rule and passes guidance to agents only as the 'Developer guidance:' line. Every command is a fenced line starting with sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py". Flow per spec Section 2: scaffold (empty set: say so and stop); dispatch the printed investigator rows in one message under harness:parallel2, each row's model as printed; apply; fill the remaining TODO(fill) (non-flagged entries in full, Description and Recommendation everywhere) from the code at the cited lines and record the verified-against header (HEAD SHA, 'uncommitted fixes included'); check until clean; dispatch the reviewer row check printed; apply its findings by hand; check again; hand the memo path to the developer. Add bubble-memo to _INVOCABLE in the guidance-tail contract test (the planned copy under this plan's tests folder already has it).

- [ ] Test `tests/skills/test_skill_guidance_tail_contract.py::test_every_skill_is_classified` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_skill_contract.py::test_frontmatter_and_guidance_tail` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_skill_contract.py::test_split_rule_cited_no_raw_arguments` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_skill_contract.py::test_every_driver_command_goes_through_the_launcher` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_skill_contract.py::test_the_loop_runs_the_driver_commands_in_order` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_skill_contract.py::test_agents_are_dispatched_by_the_printed_rows` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_bubble_memo_skill_contract.py::test_the_skill_keeps_prose_and_the_snapshot_rule` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/skills/test_skill_guidance_tail_contract.py -q`: passed (every invocable skill takes the guidance tail, bubble-memo included)
- [ ] Record the commit: `plan.py record 0001 BM-6 --sha <sha>`

**Evidence:** 

### BM-7: Mod core: config mirror, root rule, review reading, memo parse and stamp

**Status:** PENDING | **Model:** sonnet | **Depends on:** BM-3
**Files:** `plugins/bubble-stamp/hooks/config.ts`, `plugins/bubble-stamp/hooks/config.test.ts`, `plugins/bubble-stamp/hooks/root.ts`, `plugins/bubble-stamp/hooks/root.test.ts`, `plugins/bubble-stamp/hooks/review.ts`, `plugins/bubble-stamp/hooks/review.test.ts`, `plugins/bubble-stamp/hooks/memo.ts`, `plugins/bubble-stamp/hooks/memo.test.ts`

**Anchors:**
- `plugins/pr-review-watch/hooks/config.ts:10` holds `export const DEFAULT_REVIEWS = 'docs/PR_REVIEWS'`
- `plugins/pr-review-watch/hooks/config.ts:47` holds `export const readConfig = (text: string): WatchConfig => {`
- `plugins/pr-review-watch/hooks/root.ts:19` holds `export const rootCandidates = (`
- `plugins/pr-review-watch/hooks/bubbles.ts:57` holds `const CLOSING_STATUSES: readonly unknown[] = ['RESOLVED', 'CLOSED_NO_ACTION']`
- `plugins/pr-review-watch/hooks/bubbles.ts:60` holds `const closedOf = (doc: Record<string, unknown>): string[] => {`
- `plugins/pr-review-watch/hooks/bubbles.ts:99` holds `export const reviewFileFor = (pr: number, entries: readonly Listed[]): Listed | undefined => {`
- `tests/mods/_mods_helpers.py:15` holds `def ts_string(source: str, name: str) -> str:`

Create plugins/bubble-stamp/hooks/config.ts (DEFAULT_REVIEWS = 'docs/PR_REVIEWS' and a readConfig of artifacts.reviews, copied from pr-review-watch's config.ts shape), root.ts (copy of the project-root rule), review.ts (closedOf and reviewFileFor ported from pr-review-watch's bubbles.ts, plus the latest resolution per id with its status, date and evidence), and memo.ts (pure): the anchor constants as single-line single-quoted exports (INDEX_HEADER, STATUS_OPEN, STATUS_DECIDED, DECISION_OPEN, DECISION_PREFIX, ENTRY_PREFIX, MEMO_SUFFIX) matching harness_lib.bubble_memo exactly; parseMemo (index rows and entry boundaries, undefined when the anchors are missing); openIds; and stampMemo(text, resolutions) applying the spec stamp rule: only Open rows with a RESOLVED or CLOSED_NO_ACTION latest resolution, Status to Decided, Decision cell '<STATUS> <date>: <evidence>' on one line with | escaped, Tracked in from the first #<n> or 7-40 hex SHA in the evidence else '-', and the entry's Decision line; nothing else changes; a second run changes nothing. Write config.test.ts, root.test.ts, review.test.ts and memo.test.ts first (red), using the engine's testing helpers as phase5Scan.test.ts does.

- [ ] Test `tests/mods/test_bubble_stamp_config_mirror.py::test_the_mirrored_reviews_folder_equals_defaults_json` fails with AssertionError, then passes
- [ ] Test `tests/mods/test_bubble_stamp_config_mirror.py::test_the_mirror_equals_an_unconfigured_project` fails with AssertionError, then passes
- [ ] Test `tests/mods/test_bubble_stamp_anchors_contract.py::test_the_mod_anchor_equals_the_library_anchor` fails with ImportError, then passes
- [ ] Test `tests/mods/test_bubble_stamp_anchors_contract.py::test_a_rendered_memo_carries_every_anchor_the_mod_reads` fails with ImportError, then passes
- [ ] Run `claude plugin test plugins/bubble-stamp`: the config, root, review and memo tests pass; exit code 0
- [ ] Record the commit: `plan.py record 0001 BM-7 --sha <sha>`

**Evidence:** 

### BM-8: Mod engine glue: hooks, state, manifest, README

**Status:** PENDING | **Model:** sonnet | **Depends on:** BM-7
**Files:** `plugins/bubble-stamp/hooks/stamp.ts`, `plugins/bubble-stamp/hooks/stamp.test.ts`, `plugins/bubble-stamp/hooks/watch.ts`, `plugins/bubble-stamp/hooks/register.ts`, `plugins/bubble-stamp/hooks/hooks.json`, `plugins/bubble-stamp/.claude-plugin/plugin.json`, `plugins/bubble-stamp/tsconfig.json`, `plugins/bubble-stamp/.gitignore`, `plugins/bubble-stamp/types/index.d.ts`, `plugins/bubble-stamp/README.md`

**Anchors:**
- `plugins/pr-review-watch/hooks/register.ts:7` holds `export const register: Register = on => {`
- `plugins/pr-review-watch/hooks/watch.ts:45` holds `export async function resolveWatch($: EngineInterface): Promise<Watch | undefined> {`
- `plugins/pr-review-watch/hooks/tracker.ts:570` holds `on('tool.call', { tool: 'Bash' }, async ($, e, next) => {`
- `plugins/pr-review-watch/hooks/tracker.ts:576` holds `on('tool.call', { tool: 'PowerShell' }, async ($, e, next) => {`
- `plugins/pr-review-watch/hooks/tracker.ts:585` holds `on('turn.complete', async ($, e, next) => {`
- `plugins/pr-review-watch/hooks/tracker.ts:592` holds `on('session.start', async ($, e, next) => {`
- `plugins/pr-review-watch/hooks/tracker.ts:262` holds `await Promise.resolve($.ui.toast(text)).catch(noop)`
- `plugins/pr-review-watch/.claude-plugin/plugin.json:8` holds `"types": "./types/index.d.ts"`
- `plugins/pr-review-watch/.gitignore:2` holds `.claude-plugin/types/`

Create stamp.ts (engine glue, function declarations where `$` is passed, every host call guarded with .catch so every hook fails open), watch.ts (resolveWatch as in pr-review-watch, returning the project root and config, no sentinel root), register.ts (export const register: Register = on => registerStamp(on)), hooks/hooks.json ({"modules": ["./register.ts"]}), .claude-plugin/plugin.json (name bubble-stamp, version 0.1.0, types ./types/index.d.ts), tsconfig.json (extends ./.claude-plugin/types/tsconfig.json), .gitignore (.claude-plugin/types/), types/index.d.ts (PluginState entry 'bubble-stamp' with the active-memo map), README.md (activation, triggers, stamp rule, state, known limitations, checks, loading), and stamp.test.ts (red first). Behavior per spec Section 4: active memos listed from <artifacts.reviews> on session.start and whenever a trigger shows an unknown memo; triggers are tool.call on Bash and PowerShell whose command names pr_review.py or review_edit.py, tool.call on Edit and Write whose file_path is an active memo's review JSON, and turn.complete; each trigger stats the review JSON and reads it only when the mtime moved; the memo is re-read just before the write and written only when the text changed; an unreadable memo is never overwritten; one toast names the ids stamped.

- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_the_mod_manifest_and_hooks` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_the_mod_has_a_readme` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_engine_scaffolding[tsconfig]` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_engine_scaffolding[gitignore]` fails with AssertionError, then passes
- [ ] Run `claude plugin validate --strict plugins/bubble-stamp`: validation passes
- [ ] Run `claude plugin test plugins/bubble-stamp`: every mod test passes; exit code 0
- [ ] Record the commit: `plan.py record 0001 BM-8 --sha <sha>`

**Evidence:** 

### BM-9: Register the mod and the skill; bump versions

**Status:** PENDING | **Model:** sonnet | **Depends on:** BM-5, BM-6, BM-8
**Files:** `.claude-plugin/marketplace.json`, `.github/workflows/ci.yml`, `README.md`, `CLAUDE.md`, `plugins/harness/.claude-plugin/plugin.json`, `plugins/pr-review-watch/.claude-plugin/plugin.json`

**Anchors:**
- `.claude-plugin/marketplace.json:44` holds `"name": "todo-watch"`
- `.github/workflows/ci.yml:126` holds `plugins/todo-watch; do claude plugin test "$p"; done`
- `CLAUDE.md:3` holds `scripts) plus five`
- `CLAUDE.md:4` holds `` `todo-watch`). Layout and install: ``
- `README.md:100` holds `claude plugin install todo-watch@operator-straps`
- `README.md:20` holds `` | Plan multi-step work from a spec | `harness`: `write-plan` | ``
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.39.1",`
- `plugins/pr-review-watch/.claude-plugin/plugin.json:3` holds `"version": "0.4.1",`

Add the bubble-stamp entry to .claude-plugin/marketplace.json after todo-watch; add bubble-stamp to the CI mod-test loop in ci.yml; add README rows (the mods table row for bubble-stamp, the harness skills table row for bubble-memo, the install line and, if the activation notes list mods, one for bubble-stamp); CLAUDE.md: the mod count in the first paragraph becomes six, the list gains bubble-stamp, and the config-mirror sentence names bubble-stamp; bump harness to 0.40.0 and pr-review-watch to 0.4.2 (its contract.ts changed). .claude/settings.json enables the published marketplace and is left alone until the mod is published.

- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_the_marketplace_lists_the_mod` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_ci_runs_the_mod_tests` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_the_readme_documents_and_installs_the_mod` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_claude_md_counts_six_mods` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_the_harness_version_moved_past_the_old_one` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_bubble_stamp_registration.py::test_pr_review_watch_moved_past_its_old_version` fails with AssertionError, then passes
- [ ] Run `claude plugin validate --strict .`: validation passes for the marketplace
- [ ] Record the commit: `plan.py record 0001 BM-9 --sha <sha>`

**Evidence:** 
