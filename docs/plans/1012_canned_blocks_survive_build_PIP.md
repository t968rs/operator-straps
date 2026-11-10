# Plan 1012: canned blocks survive build

> Rendered by `plan.py render` from `1012_canned_blocks_survive_build_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-10
**Spec:** none
**Branch:** 1150-canned-messages -> main
**Base commit:** `5a8ef39`
**Frozen:** no
**Execution model:** serial

## Decisions

- **D1** Shape of the project canned-set key Chosen: `list` (top-level canned_messages: list of {patterns, message}). Rejected: `map` (object mapping message -> patterns). Mirrors LOOKUP (patterns -> message) and commit_buckets (ordered list of objects); order is the precedence, which an object cannot carry reliably.
- **D2** Precedence of project sets against the plugin LOOKUP Chosen: `project-first` (project sets tried before LOOKUP). Rejected: `plugin-first` (LOOKUP tried before project sets). A project can then replace a built-in message for the same files; the built-in sets still answer when no project set covers the change.
- **D3** Where build puts a canned path that appeared after capture Chosen: `fold` (join the block already carrying that canned message, else a new canned block at the end; pending: block 1). Rejected: `ignore` (leave it out of the TXT and skip it in coverage). The TXT then lists every changed file, so the developer stages the regenerated file with its fixed message; ignoring it would leave an unlisted change behind.
- **D4** A canned path in the skeleton that vanished before build Chosen: `drop` (drop it; drop a block left empty). Rejected: `fail` (keep the 'matches nothing' problem). Same rule as an appearance: a canned file's churn has no effect on the run.

## Sweeps

- **S1** `get_canned_message`: `docs/PR_REVIEWS/0090_Featurecommit-msg_add_canned_messages_for_pre-determined_change_sets.json` (historical review record), `docs/PR_REVIEWS/0094_Fixcommit-msg_pass_the_developers_--base_to_the_fork_and_keep_sav.json` (historical review record), `docs/PR_REVIEWS/0160_c-msg_performance.json` (historical review record), `docs/PR_REVIEWS/0164_Featuremerge-commit-msg_merge_commit_msg.py_stdin_build.json` (historical review record), `docs/TODO/RepoToDo.json` (TODO prose; no code), `plugins/harness/lib/harness_lib/canned_messages.py` (definition; gains extra=, plus project_canned_message (TASK-2)), `plugins/harness/scripts/branch_commit_msg.py` (five call sites switch to project_canned_message (TASK-2)), `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py` (render call site switches to project_canned_message (TASK-2)), `tests/lib/test_canned_messages.py` (built-in LOOKUP tests; unchanged signature default keeps them)

## Tasks

### TASK-1: canned_messages config key

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/config/defaults.json`, `plugins/harness/config/harness.schema.json`, `plugins/harness/lib/harness_lib/config.py`, `README.md`, `tests/lib/test_config_canned_messages.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/config.py:196-197` holds `strap: StrapConfig plugins: Tuple[Tuple[str, str], ...]`
- `plugins/harness/lib/harness_lib/config.py:323-326` holds `runlogs=_runlogs(m["runlogs"]), docstrings=_docstrings(m["docstrings"]),`
- `plugins/harness/lib/harness_lib/config.py:388-390` holds `def _docstrings(d: Dict[str, Any]) -> DocstringsConfig:`
- `plugins/harness/config/defaults.json:64-66` holds `"docstrings": { "line_length": 110 },`

Add top-level `canned_messages` (default []) in four places: defaults.json; harness.schema.json (array of objects, additionalProperties false, required patterns + message, patterns minItems 1 of non-empty strings, message minLength 1); config.py: frozen dataclass CannedSet(patterns: Tuple[str, ...], message: str), HarnessConfig.canned_messages: Tuple[CannedSet, ...] = () as the last field, builder _canned_messages(raw) raising ConfigError('canned_messages...') on any malformed shape (the check without jsonschema), wired in _build; README key table row.

- [ ] Test `tests/lib/test_config_canned_messages.py::test_project_sets_load_in_order` fails with ImportError, then passes
- [ ] Test `tests/lib/test_config_canned_messages.py::test_a_malformed_set_fails_the_load` fails with ImportError, then passes
- [ ] Test `tests/lib/test_config_canned_messages.py::test_a_malformed_set_fails_without_jsonschema` fails with ImportError, then passes
- [ ] Test `tests/lib/test_config_canned_messages.py::test_a_non_list_value_fails_without_jsonschema` fails with ImportError, then passes
- [ ] Test `tests/lib/test_config_canned_messages.py::test_the_default_is_no_project_sets` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1012 TASK-1 --sha <sha>` or `--staged`

**Evidence:** not started

### TASK-2: project canned sets reach every canned lookup

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-1
**Files:** `plugins/harness/lib/harness_lib/canned_messages.py`, `plugins/harness/scripts/branch_commit_msg.py`, `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py`, `tests/scripts/test_project_canned_messages.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/canned_messages.py:54` holds `def get_canned_message(changed_files: Iterable[str]) -> Optional[str]:`
- `plugins/harness/scripts/branch_commit_msg.py:305` holds `return message or get_canned_message(paths) or ""`
- `plugins/harness/scripts/branch_commit_msg.py:353` holds `return "canned" if message == get_canned_message(paths) else "carried"`
- `plugins/harness/scripts/branch_commit_msg.py:598` holds `canned = get_canned_message(commit.files)`
- `plugins/harness/scripts/branch_commit_msg.py:828` holds `print(get_canned_message(paths) or "canned: none")`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:275` holds `canned = get_canned_message(files)`

canned_messages.py: get_canned_message(changed_files, extra=()) tries each extra CannedSet (patterns, message) before LOOKUP; add project_canned_message(changed_files) reading active().canned_messages inside the function; module docstring drops the 'reads no config' claim for the project half. Switch the call sites to project_canned_message: branch_commit_msg.py _prefilled, message_state, _receipt_line, _cmd_canned; merge_commit_msg.py render.

- [ ] Test `tests/scripts/test_project_canned_messages.py::test_an_extra_set_gives_its_message` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_project_canned_messages.py::test_an_extra_set_wins_over_the_built_in_one` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_project_canned_messages.py::test_a_mix_across_two_sets_has_no_message` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_project_canned_messages.py::test_the_project_lookup_reads_the_active_config` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_project_canned_messages.py::test_capture_prefills_a_project_set_block` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_project_canned_messages.py::test_merge_capture_prefills_a_project_set_prose` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1012 TASK-2 --sha <sha>` or `--staged`

**Evidence:** not started

### TASK-3: build folds canned paths that appear or vanish after capture

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-2
**Files:** `plugins/harness/lib/harness_lib/canned_fold.py`, `plugins/harness/scripts/branch_commit_msg.py`, `tests/scripts/test_branch_commit_msg_canned_fold.py`

**Anchors:**
- `plugins/harness/scripts/branch_commit_msg.py:562-566` holds `document = document_from_payload(payload, notes) if document.pending and document.merge_base != head:`
- `plugins/harness/lib/harness_lib/commit_grouping.py:537` holds `problems.extend(f"{path!r} is in no commit" for path in sorted(captured - set(owners)))`
- `plugins/harness/lib/harness_lib/commit_grouping.py:297` holds `def expand_entry(entry: str, captured: Set[str]) -> Set[str]:`

New harness_lib/canned_fold.py: fold_canned(commits, captured, canned, pending) -> new CommitDict (input untouched). Vanished: a non-glob entry outside `captured` whose path canned() covers drops; an emptied block drops. Appeared: each captured path no entry expands to (expand_entry) and canned([path]) covers, in sorted order, joins block 1 when pending, else the first block whose message equals canned(files + [path]), else a new block at max key + 1 with the canned message. run_build captures once, folds the payload commits with project_canned_message before building the document, and passes the same capture to coverage_problems (a helper keeps run_build under 50 lines).

- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestFoldCanned::test_an_appeared_canned_path_gets_a_new_block` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestFoldCanned::test_an_appeared_canned_path_joins_its_canned_block` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestFoldCanned::test_two_appeared_paths_of_one_set_share_one_new_block` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestFoldCanned::test_a_vanished_canned_path_drops_and_its_empty_block_goes` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestFoldCanned::test_a_pending_document_folds_into_its_one_block` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestFoldCanned::test_the_input_is_not_changed` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestBuildFolds::test_a_canned_file_written_after_capture_builds` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestBuildFolds::test_it_joins_the_canned_block_capture_made` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestBuildFolds::test_a_canned_file_deleted_after_capture_builds` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestBuildFolds::test_another_file_written_after_capture_still_fails` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_branch_commit_msg_canned_fold.py::TestBuildFolds::test_a_pending_build_takes_the_canned_file_into_its_block` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1012 TASK-3 --sha <sha>` or `--staged`

**Evidence:** not started

### TASK-4: skill docs, version bump and release notes

**Status:** PENDING | **Model:** sonnet | **Depends on:** TASK-3
**Files:** `plugins/harness/skills/branch-commit-msg/SKILL.md`, `plugins/harness/skills/amend-commit-msg/SKILL.md`, `plugins/harness/.claude-plugin/plugin.json`

**Anchors:**
- `plugins/harness/skills/branch-commit-msg/SKILL.md:166` holds `` Exit 1: each `problem:` line names a commit and a defect. ``
- `plugins/harness/skills/amend-commit-msg/SKILL.md:63` holds `Exception: a block holding only the files of a canned set`

branch-commit-msg SKILL.md: Step 1 names the canned_messages key beside canned_messages.py; Step 4 says build folds a canned-set path that appeared or vanished after capture. amend-commit-msg SKILL.md: the canned-set exception names the key. Bump harness plugin.json minor; docs/RELEASES/v<next>.md row and lines. c-msg and merge-commit-msg SKILL.md stay as they are (frozen strap specs); their text stays true.

- [ ] Run `python -m pytest tests/skills/test_canned_message_skill_contract.py tests/skills/test_branch_commit_msg_skill_contract.py -q`: passed, no failures
- [ ] Record it: `plan.py record 1012 TASK-4 --sha <sha>` or `--staged`

**Evidence:** not started
