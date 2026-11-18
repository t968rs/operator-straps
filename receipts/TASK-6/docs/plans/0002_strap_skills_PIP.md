# Plan 0002: strap skills

> Rendered by `plan.py render` from `0002_strap_skills_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-10-30
**Spec:** `docs/superpowers/specs/2026-10-29-strap-skills-design.md`
**Branch:** none -> main
**Base commit:** `697dce2`
**Frozen:** 2026-10-30 at `bc23bb3`
**Execution model:** serial

## Decisions

- **D1** How is strap-skills built? Chosen: `A-standalone` (strap.py plus harness_lib/strap_* modules). Rejected: `B-plan-kind` (A SkillSpec as a kind of ActionPlan), `C-two-drivers` (Generic scenario.py plus a thin strap.py). Developer 2026-10-29.
- **D2** How do agents author the spec? Chosen: `piecewise` (Named operations (add_*, update_*, record_run, grade)). Rejected: `whole-write` (load + model_copy + write of the whole spec). Author's call in the approved design: no API path can rewrite driver-owned fields.
- **D3** How does scaffold find the target plugin source tree? Chosen: `plugin-json-name` (The project dir whose .claude-plugin/plugin.json name matches plugin_root()'s). Rejected: `config-key` (A new harness.json key), `literal` (Hard-coded plugins/harness). No config key (design constraint) and no project path in plugin code.
- **D4** How does an agent run the api heredoc? Chosen: `driver-api` (strap.py api <name> reads Python on stdin with the api bound, config activated). Rejected: `pythonpath` (PYTHONPATH=<lib> hpy - with manual activation). Drivers activate, library code reads active(); no PYTHONPATH in skill text.
- **D5** Where do repo-literal bans run for scaffolded skills? Chosen: `repo-contract-test` (Stay in tests/contract/test_no_repo_literals.py, which walks every plugin file). Rejected: `lint` (Copy the ban list into strap_lint). The ban list holds consumer literals; a plugin copy would itself trip the guard. Amends the design's lint list.
- **D6** Where does the no-first/second-person rule apply in lint? Chosen: `description-and-python` (Skill description plus Python comments and docstrings). Rejected: `whole-skill` (The whole SKILL.md body). Harness rule scopes it to comments and docstrings; 12 existing SKILL.md bodies use you/your.
- **D7** Where does the red-exception enum live? Chosen: `own-enum` (strap_models.RedException until #145 lands). Rejected: `plan-models` (Import plan_models' enum). #145 is not implemented; spec leaves it to the builder.
- **D8** Can the session record a run through api? Chosen: `d8-adopted` (No: api binds strap_api.__all__ without record_run; green needs a result for every scenario check). Rejected: `d8-as-drafted` (record_run bound; green over present results). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D9** How many runs per (behavior, scenario, arm, hash)? Chosen: `d9-adopted` (One: run reprints an unrecorded run). Rejected: `d9-as-drafted` (run mints a new run each call). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D10** Can a drawn behavior's scenarios change? Chosen: `d10-adopted` (No: scenarios/kind/type locked after a draw). Rejected: `d10-as-drafted` (editable until freeze). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D11** What baseline does an edit run, and what does new refuse? Chosen: `d11-adopted` (new refuses an existing skill; --edit refuses a missing one; --edit --base REF; skill absent at base means baseline without skill). Rejected: `d11-as-drafted` (base = HEAD only, no refusals). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments. Needed by the STR-11 self-gate.
- **D12** What does freeze refuse? Chosen: `d12-adopted` (Each condition listed with its problem text; all-dropped may freeze; grader from spec.judge). Rejected: `d12-as-drafted` (unspecified conditions). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D13** Is mechanical red recorded? Chosen: `d13-adopted` (red sets state RED; freeze reruns the nodes expecting a pass). Rejected: `d13-as-drafted` (red writes nothing). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D14** What does the content hash cover for a new skill? Chosen: `d14-adopted` (scaffold persists parts; add_part in api; run/freeze need a skill_md part). Rejected: `d14-as-drafted` (parts never written). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D15** Which scenario does run target after a retest? Chosen: `d15-adopted` (--scenario or first must_pass/latest draw lacking the arm on the current hash; void draws leave must_pass). Rejected: `d15-as-drafted` (unspecified). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D16** Who grades a --judge spec? Chosen: `d16-adopted` (judge only; session grade refused). Rejected: `d16-as-drafted` (either). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D17** How are agent-role scenarios checked? Chosen: `d17-adopted` (check requires agents/<role>.md; init injects it). Rejected: `d17-as-drafted` (unchecked). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D18** When is a skill invocable for lint? Chosen: `d18-adopted` ($ARGUMENTS in body or argument-hint present; quotes stripped; fixed prefix message). Rejected: `d18-as-drafted` ($ARGUMENTS only). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments. pr-sum has a hint and no $ARGUMENTS.
- **D19** How do scaffolded skills run their api heredoc? Chosen: `d19-adopted` (Generic scripts/skill_api.py binding a module's __all__; strap.py api delegates to it). Rejected: `d19-as-drafted` (per-skill drivers). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D20** Where does a run keep its tree? Chosen: `d20-adopted` (Run.tree and Run.start; init prints record-run with --repo). Rejected: `d20-as-drafted` (unspecified). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments.
- **D21** Scope calls recorded Chosen: `d21-adopted` (Normalized quotes in grade; digest detects hand edits only; scaffold emits 4 parts, EDIT writes missing parts only; all-or-nothing render; find_plugin_dir skips worktrees). Rejected: `d21-as-drafted` (design wording). Plan review 2026-10-30 (workflow review-plan-0002); see docs/plans/0002/CONTRACT.md amendments. Amends the design's verbatim-quote validator and scaffold list.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| MIN_SCENARIOS | 2 | spec decision 4 | - |
| MIN_DISCIPLINE_PRESSURES | 3 | spec Models (Scenario validators) | - |
| reps per arm per draw | 1 | spec decision 4 | - |
| runner and judge model | sonnet | spec Agents | - |
| DESCRIPTION_MAX | 1024 | spec Lint | - |
| harness version after release | 0.42.0 | plugin.json 0.41.1 + minor | - |
| pydantic pin | 2.14.1 | o-s env; drift test is byte-exact | - |

## Formats

- **dispatch row**: `agent=harness:strap-scenario-runner model=sonnet`, copied from `plugins/harness/scripts/bubble_memo.py:197`

## Sweeps

- **S1** `_skill_parts`: `docs/PR_REVIEWS/0094_Fixcommit-msg_pass_the_developers_--base_to_the_fork_and_keep_sav.json` (keep), `docs/superpowers/specs/2026-10-29-strap-skills-design.md` (keep), `tests/skills/test_branch_commit_msg_skill_contract.py` (keep), `tests/skills/test_bubble_memo_skill_contract.py` (keep), `tests/skills/test_c_msg_skill_contract.py` (keep), `tests/skills/test_skill_guidance_tail_contract.py` (keep)

## Tasks

### STR-0: Point artifacts.plans at docs/plans

**Status:** COMPLETE | **Model:** haiku | **Depends on:** none
**Files:** `.claude/harness.json`

**Anchors:**
- `.claude/harness.json:4` holds `"exclusions": ".claude/pr_review_exclusions.json",`

Add "artifacts": {"plans": "docs/plans"} to .claude/harness.json (an existing key; deep-merged over the defaults). The tracked plans live in docs/plans/, and the default docs/PLANS only resolves there on a case-insensitive filesystem.

- [x] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/plan.py check 0002`: check [ok] | plan 0002
- [x] Record the commit: `plan.py record 0002 STR-0 --sha <sha>`

**Evidence:** commit ca918b7

- `ca918b74eab5597f53b497c68a74bbe9de30c9d0`
- `tree e3db5a78301281e7396cc185b10eb1fcc031dbf3`

### STR-1: strap_models: enums, models, driver-owned metadata, digest, load/dump, schema_text

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** STR-0
**Files:** `plugins/harness/lib/harness_lib/strap_models.py`

Create plugins/harness/lib/harness_lib/strap_models.py exactly per docs/plans/0002/CONTRACT.md section strap_models: str Enums, constants, extra=forbid models with the listed validators, driver-owned fields marked with Field(json_schema_extra={'driver_owned': True}), DRIVER_OWNED_TOP/DRIVER_OWNED_BEHAVIOR derived from that metadata, driver_digest over the driver-owned fields (behavior states keyed by id, excluding driver_digest), load_spec, dump_spec, schema_text with $schema then $id first. No import of other harness_lib modules.

- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[SpecMode-members0]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[BehaviorKind-members1]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[JudgmentType-members2]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[Pressure-members3]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[PartKind-members4]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[CheckKind-members5]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[ReplyAct-members6]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[GradeValue-members7]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[Grader-members8]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[Arm-members9]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[BehaviorState-members10]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[DrawReason-members11]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_enum_members_and_values[RedException-members12]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_constants` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_scenario_rejects[over0]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_scenario_rejects[over1]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_scenario_rejects[over2]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_scenario_rejects[over3]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_scenario_accepts_checks_only` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_judged_item_rejects_unclear[expect_baseline]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_judged_item_rejects_unclear[expect_green]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc0]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc1]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc2]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc3]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc4]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc5]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_rejects[doc6]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_accepts_two_pressures_outside_discipline` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over0-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over1-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over2-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over3-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_run_recorded_sha_validator` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_run_tree_and_start_default_empty` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_run_accepts_tree_and_start` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_grade_rejects_blank_quote` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_rejects_bad_name[Demo]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_rejects_bad_name[demo_skill]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_rejects_bad_name[-demo]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_rejects_bad_name[demo-]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_rejects_bad_name[demo--x]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_rejects_bad_name[]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_base_iff_edit` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_referential_checks[over0]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_referential_checks[over1]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_referential_checks[over2]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_referential_checks[over3]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_referential_checks[over4]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_referential_checks[over5]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_spec_accepts_known_references` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_driver_owned_tuples_derive_from_metadata` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_driver_digest_stable_and_self_excluding` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_driver_digest_sensitivity` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_dump_and_load_round_trip` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_load_spec_errors` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_models.py::test_schema_text_header` fails with ImportError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/lib/harness_lib/strap_models.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-1 --sha <sha>`

**Evidence:** commit a676163: 57 test node(s) passed

- `a676163a4f2f910d280e06b352d55eb96280a2b6`
- `tree 181cf2c65478adbaf24be997f9dbd9c5d3a44c50`
- `python -m pytest -q tests/lib/test_strap_models.py::test_enum_members_and_values[SpecMode-members0] tests/lib/test_strap_models.py::test_enum_members_and_values[BehaviorKind-members1] tests/lib/test_strap_models.py::test_enum_members_and_values[JudgmentType-members2] tests/lib/test_strap_models.py::test_enum_members_and_values[Pressure-members3] tests/lib/test_strap_models.py::test_enum_members_and_values[PartKind-members4] tests/lib/test_strap_models.py::test_enum_members_and_values[CheckKind-members5] tests/lib/test_strap_models.py::test_enum_members_and_values[ReplyAct-members6] tests/lib/test_strap_models.py::test_enum_members_and_values[GradeValue-members7] tests/lib/test_strap_models.py::test_enum_members_and_values[Grader-members8] tests/lib/test_strap_models.py::test_enum_members_and_values[Arm-members9] tests/lib/test_strap_models.py::test_enum_members_and_values[BehaviorState-members10] tests/lib/test_strap_models.py::test_enum_members_and_values[DrawReason-members11] tests/lib/test_strap_models.py::test_enum_members_and_values[RedException-members12] tests/lib/test_strap_models.py::test_constants tests/lib/test_strap_models.py::test_scenario_rejects[over0] tests/lib/test_strap_models.py::test_scenario_rejects[over1] tests/lib/test_strap_models.py::test_scenario_rejects[over2] tests/lib/test_strap_models.py::test_scenario_rejects[over3] tests/lib/test_strap_models.py::test_scenario_accepts_checks_only tests/lib/test_strap_models.py::test_judged_item_rejects_unclear[expect_baseline] tests/lib/test_strap_models.py::test_judged_item_rejects_unclear[expect_green] tests/lib/test_strap_models.py::test_behavior_rejects[doc0] tests/lib/test_strap_models.py::test_behavior_rejects[doc1] tests/lib/test_strap_models.py::test_behavior_rejects[doc2] tests/lib/test_strap_models.py::test_behavior_rejects[doc3] tests/lib/test_strap_models.py::test_behavior_rejects[doc4] tests/lib/test_strap_models.py::test_behavior_rejects[doc5] tests/lib/test_strap_models.py::test_behavior_rejects[doc6] tests/lib/test_strap_models.py::test_behavior_accepts_two_pressures_outside_discipline tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over0-True] tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over1-False] tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over2-False] tests/lib/test_strap_models.py::test_behavior_dropped_iff_reason[over3-False] tests/lib/test_strap_models.py::test_run_recorded_sha_validator tests/lib/test_strap_models.py::test_run_tree_and_start_default_empty tests/lib/test_strap_models.py::test_run_accepts_tree_and_start tests/lib/test_strap_models.py::test_grade_rejects_blank_quote tests/lib/test_strap_models.py::test_spec_rejects_bad_name[Demo] tests/lib/test_strap_models.py::test_spec_rejects_bad_name[demo_skill] tests/lib/test_strap_models.py::test_spec_rejects_bad_name[-demo] tests/lib/test_strap_models.py::test_spec_rejects_bad_name[demo-] tests/lib/test_strap_models.py::test_spec_rejects_bad_name[demo--x] tests/lib/test_strap_models.py::test_spec_rejects_bad_name[] tests/lib/test_strap_models.py::test_spec_base_iff_edit tests/lib/test_strap_models.py::test_spec_referential_checks[over0] tests/lib/test_strap_models.py::test_spec_referential_checks[over1] tests/lib/test_strap_models.py::test_spec_referential_checks[over2] tests/lib/test_strap_models.py::test_spec_referential_checks[over3] tests/lib/test_strap_models.py::test_spec_referential_checks[over4] tests/lib/test_strap_models.py::test_spec_referential_checks[over5] tests/lib/test_strap_models.py::test_spec_accepts_known_references tests/lib/test_strap_models.py::test_driver_owned_tuples_derive_from_metadata tests/lib/test_strap_models.py::test_driver_digest_stable_and_self_excluding tests/lib/test_strap_models.py::test_driver_digest_sensitivity tests/lib/test_strap_models.py::test_dump_and_load_round_trip tests/lib/test_strap_models.py::test_load_spec_errors tests/lib/test_strap_models.py::test_schema_text_header`

### STR-2: strap_runs: content hash, seeded draws, check evaluation, quotes, pass rule, retest pool

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** STR-1
**Files:** `plugins/harness/lib/harness_lib/strap_runs.py`

Create plugins/harness/lib/harness_lib/strap_runs.py per docs/plans/0002/CONTRACT.md section strap_runs. Imports: stdlib and strap_models only (the module stays skill-agnostic so it can be lifted into a generic A/B tester later). baseline_failed is 'any item matches its baseline expectation'; green_passed is 'every check held and every judged item graded equal to expect_green'; grades are filtered by run id and item index.

- [x] Test `tests/lib/test_strap_runs.py::test_content_hash_matches_formula` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_content_hash_ignores_input_order` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_content_hash_changes_with_one_byte` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_content_hash_missing_file_uses_marker` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_draw_scenario_is_seeded_choice_in_declared_order` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_draw_scenario_never_returns_excluded` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_draw_scenario_exhausted_pool_raises` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_new_seed_is_32_bit_int` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[changed-hit]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[changed-miss]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[unchanged-hit]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[unchanged-miss]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[present-hit]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[present-miss]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[absent-hit]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[absent-miss]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[head]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[matches-hit]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[matches-miss]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[lacks-hit]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[lacks-miss]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_head_moved_breaks_head_unchanged` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_evaluate_checks_indexes_follow_input_order` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[redirecting   there-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[Decision belongs\nto bubble-stamp-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[  memo.\n\tDecision  -True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[redirecting elsewhere-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_item_matches_bool_and_grade` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_baseline_failed_when_any_item_matches_baseline[False-present-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_baseline_failed_when_any_item_matches_baseline[True-present-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_baseline_failed_when_any_item_matches_baseline[False-absent-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_baseline_failed_ignores_other_runs_grades` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[True-present-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[False-present-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[True-absent-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[True-unclear-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_missing_grade_fails` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_needs_complete_check_results[none]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_needs_complete_check_results[wrong_index]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_needs_complete_check_results[extra_index]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_green_passed_judged_only_scenario` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_baseline_failed_ignores_missing_results[present-False]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_baseline_failed_ignores_missing_results[absent-True]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_must_pass_failed_greens_without_retest` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_must_pass_adds_latest_retest_draw` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_must_pass_skips_void_retest_draw[void]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_must_pass_skips_void_retest_draw[failed]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_must_pass_skips_void_retest_draw[unrecorded]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_runs.py::test_strap_runs_imports_only_strap_models_and_stdlib` fails with ImportError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/lib/harness_lib/strap_runs.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-2 --sha <sha>`

**Evidence:** commit 236e62c: 49 test node(s) passed

- `236e62c82928203a8bbf8535caae79da898706b4`
- `tree 3d3454d00d2d9ce2175edc562d618587de2f32e1`
- `python -m pytest -q tests/lib/test_strap_runs.py::test_content_hash_matches_formula tests/lib/test_strap_runs.py::test_content_hash_ignores_input_order tests/lib/test_strap_runs.py::test_content_hash_changes_with_one_byte tests/lib/test_strap_runs.py::test_content_hash_missing_file_uses_marker tests/lib/test_strap_runs.py::test_draw_scenario_is_seeded_choice_in_declared_order tests/lib/test_strap_runs.py::test_draw_scenario_never_returns_excluded tests/lib/test_strap_runs.py::test_draw_scenario_exhausted_pool_raises tests/lib/test_strap_runs.py::test_new_seed_is_32_bit_int tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[changed-hit] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[changed-miss] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[unchanged-hit] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[unchanged-miss] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[present-hit] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[present-miss] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[absent-hit] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[absent-miss] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[head] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[matches-hit] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[matches-miss] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[lacks-hit] tests/lib/test_strap_runs.py::test_evaluate_checks_holds_when_fact_equals_arm_expectation[lacks-miss] tests/lib/test_strap_runs.py::test_evaluate_checks_head_moved_breaks_head_unchanged tests/lib/test_strap_runs.py::test_evaluate_checks_indexes_follow_input_order tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[redirecting   there-True] tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[Decision belongs\nto bubble-stamp-True] tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[  memo.\n\tDecision  -True] tests/lib/test_strap_runs.py::test_quote_found_normalizes_whitespace[redirecting elsewhere-False] tests/lib/test_strap_runs.py::test_item_matches_bool_and_grade tests/lib/test_strap_runs.py::test_baseline_failed_when_any_item_matches_baseline[False-present-False] tests/lib/test_strap_runs.py::test_baseline_failed_when_any_item_matches_baseline[True-present-True] tests/lib/test_strap_runs.py::test_baseline_failed_when_any_item_matches_baseline[False-absent-True] tests/lib/test_strap_runs.py::test_baseline_failed_ignores_other_runs_grades tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[True-present-True] tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[False-present-False] tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[True-absent-False] tests/lib/test_strap_runs.py::test_green_passed_requires_every_item[True-unclear-False] tests/lib/test_strap_runs.py::test_green_passed_missing_grade_fails tests/lib/test_strap_runs.py::test_green_passed_needs_complete_check_results[none] tests/lib/test_strap_runs.py::test_green_passed_needs_complete_check_results[wrong_index] tests/lib/test_strap_runs.py::test_green_passed_needs_complete_check_results[extra_index] tests/lib/test_strap_runs.py::test_green_passed_judged_only_scenario tests/lib/test_strap_runs.py::test_baseline_failed_ignores_missing_results[present-False] tests/lib/test_strap_runs.py::test_baseline_failed_ignores_missing_results[absent-True] tests/lib/test_strap_runs.py::test_must_pass_failed_greens_without_retest tests/lib/test_strap_runs.py::test_must_pass_adds_latest_retest_draw tests/lib/test_strap_runs.py::test_must_pass_skips_void_retest_draw[void] tests/lib/test_strap_runs.py::test_must_pass_skips_void_retest_draw[failed] tests/lib/test_strap_runs.py::test_must_pass_skips_void_retest_draw[unrecorded] tests/lib/test_strap_runs.py::test_strap_runs_imports_only_strap_models_and_stdlib`

### STR-3: skill_parts moves into harness_lib; strap_lint for skills and Python parts

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** STR-1
**Files:** `plugins/harness/lib/harness_lib/skill_parts.py`, `tests/lib/_skill_parts.py`, `plugins/harness/lib/harness_lib/strap_lint.py`

**Anchors:**
- `tests/lib/_skill_parts.py:12` holds `def skill_parts(path: Path) -> Tuple[Dict[str, str], str]:`
- `tests/skills/test_skill_guidance_tail_contract.py:21` holds `_POINTER = "${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md"`

Move the parser of tests/lib/_skill_parts.py to plugins/harness/lib/harness_lib/skill_parts.py unchanged (same AssertionError on a file without frontmatter) and reduce tests/lib/_skill_parts.py to a re-export (sweep S1: the four test files importing it keep working unchanged). Create plugins/harness/lib/harness_lib/strap_lint.py per docs/plans/0002/CONTRACT.md section strap_lint: lint_skill mirrors the rules of tests/skills/test_skill_guidance_tail_contract.py for invocable skills; lint_python scans comments and docstrings only (tokenize/ast, not line regexes). No repo-literal ban list in the plugin (D5).

- [x] Test `tests/lib/test_strap_lint.py::test_skill_parts_parses_keys_and_body` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_skill_parts_rejects_missing_frontmatter` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_clean_invocable_skill_has_no_problems` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_missing_skill_md_is_the_only_problem` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_frontmatter_name_must_match_folder` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_description_prefix_message_is_fixed` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_description_rules[too-long]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_description_rules[you]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_description_rules[your]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_description_rules[we]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_description_rules[I]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_quoted_frontmatter_values_pass[single-quoted-description]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_quoted_frontmatter_values_pass[double-quoted-description]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_quoted_frontmatter_values_pass[double-quoted-name]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_mismatched_quotes_are_not_stripped` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_missing_description_is_flagged` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_is_invocable_classification[arguments-in-body]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_is_invocable_classification[hint-only]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_is_invocable_classification[neither]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_is_invocable_on_shipped_skill[pr-sum]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_is_invocable_on_shipped_skill[spatialist]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_invocable_argument_rules[hint-missing]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_invocable_argument_rules[hint-lacks-guidance]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_invocable_argument_rules[reference-missing]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_hint_only_skill_with_reference_is_clean` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_hint_only_skill_lacking_reference_flagged` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_fenced_arguments_line_is_flagged` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_knowledge_skill_without_hint_is_clean` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[script]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[skill]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[agent]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[harness-lib]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_named_harness_lib_module_resolves` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_bare_interpreter_in_fence_is_flagged[python -m demo]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_bare_interpreter_in_fence_is_flagged[python3 -m demo]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[Anthropic]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[OpenAI]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[ChatGPT]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[Gemini]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[Claude]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_product_and_variable_spellings_pass` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[module-docstring]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[inline-comment]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[function-docstring]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[line-comment]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[class-docstring]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_lint_python_ignores_code_and_string_literals` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint.py::test_shipped_write_plan_skill_is_clean` fails with ImportError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/lib/harness_lib/skill_parts.py plugins/harness/lib/harness_lib/strap_lint.py tests/lib/_skill_parts.py`: All checks passed!
- [x] Run `python -m pytest tests/skills/test_c_msg_skill_contract.py tests/skills/test_bubble_memo_skill_contract.py tests/skills/test_branch_commit_msg_skill_contract.py tests/skills/test_skill_guidance_tail_contract.py -q`: passed, no failures
- [x] Record the commit: `plan.py record 0002 STR-3 --sha <sha>`

**Evidence:** commit f3e5501: 48 test node(s) passed

- `f3e5501c653200a5b23791e8a13e550c6fc6dcf2`
- `tree 2637b2bc961e9ecbca7197ce896e8d7f2b02c881`
- `python -m pytest -q tests/lib/test_strap_lint.py::test_skill_parts_parses_keys_and_body tests/lib/test_strap_lint.py::test_skill_parts_rejects_missing_frontmatter tests/lib/test_strap_lint.py::test_clean_invocable_skill_has_no_problems tests/lib/test_strap_lint.py::test_missing_skill_md_is_the_only_problem tests/lib/test_strap_lint.py::test_frontmatter_name_must_match_folder tests/lib/test_strap_lint.py::test_description_prefix_message_is_fixed tests/lib/test_strap_lint.py::test_description_rules[too-long] tests/lib/test_strap_lint.py::test_description_rules[you] tests/lib/test_strap_lint.py::test_description_rules[your] tests/lib/test_strap_lint.py::test_description_rules[we] tests/lib/test_strap_lint.py::test_description_rules[I] tests/lib/test_strap_lint.py::test_quoted_frontmatter_values_pass[single-quoted-description] tests/lib/test_strap_lint.py::test_quoted_frontmatter_values_pass[double-quoted-description] tests/lib/test_strap_lint.py::test_quoted_frontmatter_values_pass[double-quoted-name] tests/lib/test_strap_lint.py::test_mismatched_quotes_are_not_stripped tests/lib/test_strap_lint.py::test_missing_description_is_flagged tests/lib/test_strap_lint.py::test_is_invocable_classification[arguments-in-body] tests/lib/test_strap_lint.py::test_is_invocable_classification[hint-only] tests/lib/test_strap_lint.py::test_is_invocable_classification[neither] tests/lib/test_strap_lint.py::test_is_invocable_on_shipped_skill[pr-sum] tests/lib/test_strap_lint.py::test_is_invocable_on_shipped_skill[spatialist] tests/lib/test_strap_lint.py::test_invocable_argument_rules[hint-missing] tests/lib/test_strap_lint.py::test_invocable_argument_rules[hint-lacks-guidance] tests/lib/test_strap_lint.py::test_invocable_argument_rules[reference-missing] tests/lib/test_strap_lint.py::test_hint_only_skill_with_reference_is_clean tests/lib/test_strap_lint.py::test_hint_only_skill_lacking_reference_flagged tests/lib/test_strap_lint.py::test_fenced_arguments_line_is_flagged tests/lib/test_strap_lint.py::test_knowledge_skill_without_hint_is_clean tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[script] tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[skill] tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[agent] tests/lib/test_strap_lint.py::test_unresolved_reference_is_flagged[harness-lib] tests/lib/test_strap_lint.py::test_named_harness_lib_module_resolves tests/lib/test_strap_lint.py::test_bare_interpreter_in_fence_is_flagged[python -m demo] tests/lib/test_strap_lint.py::test_bare_interpreter_in_fence_is_flagged[python3 -m demo] tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[Anthropic] tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[OpenAI] tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[ChatGPT] tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[Gemini] tests/lib/test_strap_lint.py::test_vendor_name_is_flagged[Claude] tests/lib/test_strap_lint.py::test_product_and_variable_spellings_pass tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[module-docstring] tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[inline-comment] tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[function-docstring] tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[line-comment] tests/lib/test_strap_lint.py::test_lint_python_flags_person_in_comments[class-docstring] tests/lib/test_strap_lint.py::test_lint_python_ignores_code_and_string_literals tests/lib/test_strap_lint.py::test_shipped_write_plan_skill_is_clean`

### STR-4: strap_api: factories and piecewise operations with driver-owned guard

**Status:** COMPLETE | **Model:** opus | **Depends on:** STR-1, STR-2
**Files:** `plugins/harness/lib/harness_lib/strap_api.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/config.py:177` holds `def path(self, rel: str) -> Path:`

Create plugins/harness/lib/harness_lib/strap_api.py per docs/plans/0002/CONTRACT.md section strap_api: StrapError(ValueError), spec_path from active().artifacts.plans, new_* factories accepting enum members or string values, add_behavior / update_behavior / drop_behavior / add_scenario / record_run / grade. Each op: load, compare stored driver_digest with driver_digest(loaded) before changing, apply, re-validate through model_dump + model_validate, recompute driver_digest, write dump_spec only after validation. grade uses strap_runs.quote_found. __all__ per D8 (record_run excluded); D10 lock; D14 add_part; D16 judge grades.

- [x] Test `tests/lib/test_strap_api.py::test_spec_path_under_configured_plans` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_strap_error_is_value_error` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_factories_build_validated_models` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_factories_reject_invalid[judgment-no-type]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_factories_reject_invalid[mechanical-with-type]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_factories_reject_invalid[scenario-empty]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_factories_reject_invalid[judged-unclear]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_factories_reject_invalid[test-no-node]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_add_behavior_assigns_b1_b2_and_writes` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_add_scenario_ids_unique_across_spec` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_update_behavior_changes_authored_field` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_update_behavior_refuses_driver_owned_field` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_update_behavior_refuses_frozen_spec` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_drop_behavior_sets_state_and_redigests` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_record_run_sets_reply_sha_and_redigests` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_record_run_refuses_recorded_run` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_appends_with_normalized_quote` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_refusals[unrecorded-run]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_refusals[item-past-end]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_refusals[item-negative]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_refusals[quote-missing]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_refusals[judge-on-session-spec]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_grade_refuses_second_grade_of_item` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_judge_grade_accepted_on_judge_spec` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_hand_edited_draws_refused[add_behavior]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_hand_edited_draws_refused[update_behavior]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_hand_edited_draws_refused[record_run]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_failed_operation_writes_nothing[update-breaks-behavior]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_failed_operation_writes_nothing[add-unvalidated-behavior]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_failed_operation_writes_nothing[scenario-unknown-behavior]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_all_lists_exactly_the_api_names` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_all_omits_driver_names[record_run]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_all_omits_driver_names[driver_digest]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_all_omits_driver_names[dump_spec]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_update_drawn_behavior_locked[scenarios]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_update_drawn_behavior_locked[kind]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_update_drawn_behavior_locked[type]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_add_scenario_on_drawn_behavior` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_add_part_appends_and_writes` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_add_part_refuses_duplicate_path` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_api.py::test_session_grade_refused_on_judge_spec` fails with ImportError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/lib/harness_lib/strap_api.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-4 --sha <sha>`

**Evidence:** commit b4db0ed: 41 test node(s) passed

- `b4db0ed75d464fd6f0e9c3d24727522f6cd514c7`
- `tree 70db9aea43c6361e5d28b7fdbf864ad951bc94df`
- `python -m pytest -q tests/lib/test_strap_api.py::test_spec_path_under_configured_plans tests/lib/test_strap_api.py::test_strap_error_is_value_error tests/lib/test_strap_api.py::test_factories_build_validated_models tests/lib/test_strap_api.py::test_factories_reject_invalid[judgment-no-type] tests/lib/test_strap_api.py::test_factories_reject_invalid[mechanical-with-type] tests/lib/test_strap_api.py::test_factories_reject_invalid[scenario-empty] tests/lib/test_strap_api.py::test_factories_reject_invalid[judged-unclear] tests/lib/test_strap_api.py::test_factories_reject_invalid[test-no-node] tests/lib/test_strap_api.py::test_add_behavior_assigns_b1_b2_and_writes tests/lib/test_strap_api.py::test_add_scenario_ids_unique_across_spec tests/lib/test_strap_api.py::test_update_behavior_changes_authored_field tests/lib/test_strap_api.py::test_update_behavior_refuses_driver_owned_field tests/lib/test_strap_api.py::test_update_behavior_refuses_frozen_spec tests/lib/test_strap_api.py::test_drop_behavior_sets_state_and_redigests tests/lib/test_strap_api.py::test_record_run_sets_reply_sha_and_redigests tests/lib/test_strap_api.py::test_record_run_refuses_recorded_run tests/lib/test_strap_api.py::test_grade_appends_with_normalized_quote tests/lib/test_strap_api.py::test_grade_refusals[unrecorded-run] tests/lib/test_strap_api.py::test_grade_refusals[item-past-end] tests/lib/test_strap_api.py::test_grade_refusals[item-negative] tests/lib/test_strap_api.py::test_grade_refusals[quote-missing] tests/lib/test_strap_api.py::test_grade_refusals[judge-on-session-spec] tests/lib/test_strap_api.py::test_grade_refuses_second_grade_of_item tests/lib/test_strap_api.py::test_judge_grade_accepted_on_judge_spec tests/lib/test_strap_api.py::test_hand_edited_draws_refused[add_behavior] tests/lib/test_strap_api.py::test_hand_edited_draws_refused[update_behavior] tests/lib/test_strap_api.py::test_hand_edited_draws_refused[record_run] tests/lib/test_strap_api.py::test_failed_operation_writes_nothing[update-breaks-behavior] tests/lib/test_strap_api.py::test_failed_operation_writes_nothing[add-unvalidated-behavior] tests/lib/test_strap_api.py::test_failed_operation_writes_nothing[scenario-unknown-behavior] tests/lib/test_strap_api.py::test_all_lists_exactly_the_api_names tests/lib/test_strap_api.py::test_all_omits_driver_names[record_run] tests/lib/test_strap_api.py::test_all_omits_driver_names[driver_digest] tests/lib/test_strap_api.py::test_all_omits_driver_names[dump_spec] tests/lib/test_strap_api.py::test_update_drawn_behavior_locked[scenarios] tests/lib/test_strap_api.py::test_update_drawn_behavior_locked[kind] tests/lib/test_strap_api.py::test_update_drawn_behavior_locked[type] tests/lib/test_strap_api.py::test_add_scenario_on_drawn_behavior tests/lib/test_strap_api.py::test_add_part_appends_and_writes tests/lib/test_strap_api.py::test_add_part_refuses_duplicate_path tests/lib/test_strap_api.py::test_session_grade_refused_on_judge_spec`

### STR-4.1: Generic skills_api launcher (scripts/skill_api.py)

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** STR-4
**Files:** `plugins/harness/scripts/skill_api.py`

Create plugins/harness/scripts/skill_api.py per docs/plans/0002/CONTRACT.md D19: --repo, module, optional name; activate the config once, import harness_lib.<module>, bind its __all__ (refuse a module without one), bind name, exec stdin; any exception becomes problem: <Name>: <message>, exit 1. strap_api defines __all__ per D8.

- [x] Test `tests/scripts/test_skill_api.py::test_binds_every_all_name` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api.py::test_binds_name_and_execs_stdin` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api.py::test_record_run_unbound_is_name_error` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api.py::test_exception_becomes_problem_line` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api.py::test_refuses_module_without_all` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api.py::test_refusal_does_not_exec_stdin` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api.py::test_activates_project_config` fails with AssertionError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/scripts/skill_api.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-4.1 --sha <sha>`

**Evidence:** commit ed3093b: 7 test node(s) passed

- `ed3093bce50bd0bb4c08b9cbc3571e900b8bbdf0`
- `tree 2b9014140777c3136eed23cd7836f8aa26248de4`
- `python -m pytest -q tests/scripts/test_skill_api.py::test_binds_every_all_name tests/scripts/test_skill_api.py::test_binds_name_and_execs_stdin tests/scripts/test_skill_api.py::test_record_run_unbound_is_name_error tests/scripts/test_skill_api.py::test_exception_becomes_problem_line tests/scripts/test_skill_api.py::test_refuses_module_without_all tests/scripts/test_skill_api.py::test_refusal_does_not_exec_stdin tests/scripts/test_skill_api.py::test_activates_project_config`

### STR-5: Generated SkillSpec.schema.json and its repo-only generator

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** STR-1
**Files:** `tools/gen_skillspec_schema.py`, `plugins/harness/schemas/SkillSpec.schema.json`, `requirements-dev.txt`, `plugins/harness/schemas/README.md`

**Anchors:**
- `requirements-dev.txt:4` holds `pydantic>=2.5`
- `plugins/harness/schemas/README.md:22` holds `## Files`

Create tools/gen_skillspec_schema.py per docs/plans/0002/CONTRACT.md section gen_skillspec_schema (--path, --check, CRLF folding, puts plugins/harness/lib on sys.path). Run it to write plugins/harness/schemas/SkillSpec.schema.json; never hand-edit that file. The schema must pass tests/schemas/test_schema_meta_valid.py ($id convention). Pin pydantic==2.14.1 in requirements-dev.txt (the drift test is byte-exact). Add a SkillSpec.schema.json entry under Files in plugins/harness/schemas/README.md (generated, never hand-edited, driver_owned markers), per its update protocol.

- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_committed_schema_equals_schema_text` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_schema_text_leads_with_draft_and_id` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_committed_schema_id_names_its_location` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_schema_text_is_indented_json_with_trailing_newline` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_schema_text_is_meta_valid_draft_2020_12` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_schema_marks_driver_owned_top_fields` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_dump_spec_validates_against_committed_schema` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_committed_schema_rejects_invalid_document` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_tool_check_exits_zero_for_in_sync_copy` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_tool_check_accepts_crlf_checkout` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_tool_check_exits_one_on_drift_and_leaves_file` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_tool_check_exits_one_on_missing_file` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_tool_writes_schema_text` fails with ImportError, then passes
- [x] Test `tests/schemas/test_skillspec_schema_drift.py::test_tool_check_defaults_to_committed_schema` fails with ImportError, then passes
- [x] Run `python tools/gen_skillspec_schema.py`: exit 0
- [x] Run `python tools/gen_skillspec_schema.py --check`: exit 0, no output
- [x] Run `python -m pytest tests/schemas/test_schema_meta_valid.py -q`: passed, no failures
- [x] Run `python -m ruff check --no-cache tools/gen_skillspec_schema.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-5 --sha <sha>`

**Evidence:** commit 8556677: 14 test node(s) passed

- `85566773b667dced890f4b220bb0ab8db814d41b`
- `tree c66754600e9913883dbb5b35d9eb3d06d6ffe0e4`
- `python -m pytest -q tests/schemas/test_skillspec_schema_drift.py::test_committed_schema_equals_schema_text tests/schemas/test_skillspec_schema_drift.py::test_schema_text_leads_with_draft_and_id tests/schemas/test_skillspec_schema_drift.py::test_committed_schema_id_names_its_location tests/schemas/test_skillspec_schema_drift.py::test_schema_text_is_indented_json_with_trailing_newline tests/schemas/test_skillspec_schema_drift.py::test_schema_text_is_meta_valid_draft_2020_12 tests/schemas/test_skillspec_schema_drift.py::test_schema_marks_driver_owned_top_fields tests/schemas/test_skillspec_schema_drift.py::test_dump_spec_validates_against_committed_schema tests/schemas/test_skillspec_schema_drift.py::test_committed_schema_rejects_invalid_document tests/schemas/test_skillspec_schema_drift.py::test_tool_check_exits_zero_for_in_sync_copy tests/schemas/test_skillspec_schema_drift.py::test_tool_check_accepts_crlf_checkout tests/schemas/test_skillspec_schema_drift.py::test_tool_check_exits_one_on_drift_and_leaves_file tests/schemas/test_skillspec_schema_drift.py::test_tool_check_exits_one_on_missing_file tests/schemas/test_skillspec_schema_drift.py::test_tool_writes_schema_text tests/schemas/test_skillspec_schema_drift.py::test_tool_check_defaults_to_committed_schema`

### STR-6: Templates and strap_scaffold

**Status:** COMPLETE | **Model:** opus | **Depends on:** STR-3, STR-4, STR-4.1
**Files:** `plugins/harness/skills/strap-skills/templates/skill_md.tmpl`, `plugins/harness/skills/strap-skills/templates/models.tmpl`, `plugins/harness/skills/strap-skills/templates/api.tmpl`, `plugins/harness/skills/strap-skills/templates/contract_test.tmpl`, `plugins/harness/lib/harness_lib/strap_scaffold.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/project.py:50` holds `def plugin_root() -> Path:`

Create plugins/harness/skills/strap-skills/templates/skill_md.tmpl, models.tmpl, api.tmpl, contract_test.tmpl and plugins/harness/lib/harness_lib/strap_scaffold.py per docs/plans/0002/CONTRACT.md section strap_scaffold. find_plugin_dir matches the plugin.json name (D3), so no plugin path is hard-coded. Templates are string.Template texts that render to the intended harness structure: models (str Enum + BaseModel, extra=forbid), api (new_* factories plus load/validate/save ops raising a ValueError subclass), a contract test that imports the models, and a SKILL.md with the arguments paragraph, Rules, Steps, an api heredoc, a judgment table. Rendered Python passes lint_python and compiles; rendered SKILL.md passes lint_skill except the description stub. StrapError comes from strap_api. skill_md.tmpl's heredoc launches scripts/skill_api.py (D19); api.tmpl defines __all__.

- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_returns_the_matching_manifest` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_node_modules` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_hidden_dirs[claude]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_hidden_dirs[dot]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_linked_worktrees` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_refuses_no_match` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_find_plugin_dir_refuses_two_matches` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_planned_parts_judgment_only_minimal` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_planned_parts_mechanical_adds_models_and_api` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_planned_parts_keeps_author_parts` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_planned_parts_lists_a_present_part_once` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_planned_parts_contract_under_first_root` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_templates_ship_with_the_plugin` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_render_parts_new_writes_every_planned_part` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_render_parts_new_refusal_writes_nothing[skill_md]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_render_parts_new_refusal_writes_nothing[api]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_render_parts_new_refusal_writes_nothing[contract]` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_render_parts_edit_writes_only_missing_parts` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_skill_md_description_stub` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_files_carry_the_title` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_skill_md_lints_to_prefix_only` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_skill_md_launches_skill_api` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_api_module_defines_all` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_python_passes_lint_python` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_python_compiles` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold.py::test_rendered_files_carry_no_template_placeholder` fails with ImportError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/lib/harness_lib/strap_scaffold.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-6 --sha <sha>`

**Evidence:** commit de5df51: 26 test node(s) passed

- `de5df51fa988583eb6b3d1c991834de0c352dc9e`
- `tree 3f9720ea46f5e09cebdbeee111c6704d1f28e112`
- `python -m pytest -q tests/lib/test_strap_scaffold.py::test_find_plugin_dir_returns_the_matching_manifest tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_node_modules tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_hidden_dirs[claude] tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_hidden_dirs[dot] tests/lib/test_strap_scaffold.py::test_find_plugin_dir_skips_linked_worktrees tests/lib/test_strap_scaffold.py::test_find_plugin_dir_refuses_no_match tests/lib/test_strap_scaffold.py::test_find_plugin_dir_refuses_two_matches tests/lib/test_strap_scaffold.py::test_planned_parts_judgment_only_minimal tests/lib/test_strap_scaffold.py::test_planned_parts_mechanical_adds_models_and_api tests/lib/test_strap_scaffold.py::test_planned_parts_keeps_author_parts tests/lib/test_strap_scaffold.py::test_planned_parts_lists_a_present_part_once tests/lib/test_strap_scaffold.py::test_planned_parts_contract_under_first_root tests/lib/test_strap_scaffold.py::test_templates_ship_with_the_plugin tests/lib/test_strap_scaffold.py::test_render_parts_new_writes_every_planned_part tests/lib/test_strap_scaffold.py::test_render_parts_new_refusal_writes_nothing[skill_md] tests/lib/test_strap_scaffold.py::test_render_parts_new_refusal_writes_nothing[api] tests/lib/test_strap_scaffold.py::test_render_parts_new_refusal_writes_nothing[contract] tests/lib/test_strap_scaffold.py::test_render_parts_edit_writes_only_missing_parts tests/lib/test_strap_scaffold.py::test_rendered_skill_md_description_stub tests/lib/test_strap_scaffold.py::test_rendered_files_carry_the_title tests/lib/test_strap_scaffold.py::test_rendered_skill_md_lints_to_prefix_only tests/lib/test_strap_scaffold.py::test_rendered_skill_md_launches_skill_api tests/lib/test_strap_scaffold.py::test_rendered_api_module_defines_all tests/lib/test_strap_scaffold.py::test_rendered_python_passes_lint_python tests/lib/test_strap_scaffold.py::test_rendered_python_compiles tests/lib/test_strap_scaffold.py::test_rendered_files_carry_no_template_placeholder`

### STR-7: scripts/strap.py driver

**Status:** COMPLETE | **Model:** opus | **Depends on:** STR-2, STR-4, STR-4.1, STR-6
**Files:** `plugins/harness/scripts/strap.py`, `tests/contract/test_root_separation.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_red.py:213` holds `def make_tree(repo: Path, base: str, root: Path) -> Path:`
- `plugins/harness/lib/harness_lib/plan_red.py:223` holds `def drop_tree(repo: Path, tree: Path) -> None:`
- `plugins/harness/lib/harness_lib/plan_red.py:185` holds `def run_red(plan: Mapping[str, Any], tree: Path, python: str) -> List[RedResult]:`
- `plugins/harness/lib/harness_lib/plan_red.py:75` holds `def overlay(sources: Mapping[str, Path], tree: Path) -> List[str]:`
- `plugins/harness/lib/harness_lib/plan_red.py:196` holds `def red_problems(results: Sequence[RedResult]) -> List[str]:`
- `plugins/harness/lib/harness_lib/config.py:191` holds `def resolve_worktree_root(self) -> Path:`

Create plugins/harness/scripts/strap.py per docs/plans/0002/CONTRACT.md section strap.py: argparse with --repo, activate(load_config(project_root(repo))) once in main, one problem: line per defect and exit 1 (an exception raised by code run through `api` becomes problem: lines too). Reuse plan_red make_tree, overlay, run_red, red_problems, drop_tree for `red` and for scenario trees; worktrees under cfg.resolve_worktree_root(). Dispatch rows follow the bubble_memo row format (F1). Every write of a driver-owned field recomputes driver_digest. Functions under 50 lines. Amendments D8-D20 apply (api via skill_api, run reuse, new refusals and --edit --base, freeze conditions, red state, scaffold persists parts, run targeting and retest, agent roles, Run.tree/start, --repo in init). Add the 'strap new' case to tests/contract/test_root_separation.py.

- [x] Test `tests/scripts/test_strap_driver.py::test_new_writes_the_spec_and_prints_the_done_line` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_on_an_existing_spec_resumes` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_edit_records_base_and_parts` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_refuses_an_existing_skill` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_edit_refuses_a_missing_skill` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_edit_records_the_given_base` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_edit_refuses_a_non_ancestor_base` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_new_refuses_a_judge_change_once_grades_exist` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_check_passes_a_sound_spec` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_check_lists_open_behavior_short_of_scenarios` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_check_refuses_hand_edited_driver_owned_field` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_check_refuses_a_non_canonical_file` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_check_refuses_a_role_without_an_agent_file` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_draw_refuses_a_behavior_with_one_scenario` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_draw_appends_one_initial_draw_never_redraws` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_run_refuses_no_draw_and_early_green` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_run_prints_the_runner_row_and_builds_the_tree` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_run_twice_before_record_reuses_the_run` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_run_refuses_second_recorded_run_same_arm` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_init_brief_ends_with_record_run` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_init_baseline_of_new_skill_omits_the_skill` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_init_green_carries_skill_with_abs_paths` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_init_includes_the_role_agent_body` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_record_run_stores_reply_and_drops_tree` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_retest_refuses_without_failed_green` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_freeze_refuses_a_behavior_that_never_ran` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_freeze_stamps_hash_and_grader` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_api_runs_stdin_code_with_name_bound` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_api_reports_refused_operation_as_problem` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_driver.py::test_api_cannot_call_record_run` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_passes_on_failing_baseline_and_green` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_judge_spec_stamps_grader_judge` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_an_already_frozen_spec` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_a_part_change_after_green` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_an_unclear_grade` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_an_ungraded_judged_item` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_a_baseline_that_did_not_fail` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_short_or_undrawn[1]` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_short_or_undrawn[2]` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_run_and_freeze_refuse_no_skill_md_part` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_an_unrepassed_must_pass` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_red_records_state_red_on_mechanical` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_mechanical_red_not_recorded` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_refuses_failing_planned_tests` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_freeze_passes_a_mechanical_behavior` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_scaffold_prints_paths_bump_and_parts` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_judge_row_refused_on_a_non_judge_spec` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_judge_row_lists_ungraded_recorded_runs` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_retest_draws_anew_and_run_targets_failed` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_strap_gate.py::test_retest_refuses_an_exhausted_pool` fails with AssertionError, then passes
- [x] Test `tests/contract/test_root_separation.py::test_entry_point_writes_nothing_under_plugins[strap new]` fails with AssertionError, then passes
- [x] Run `python -m ruff check --no-cache plugins/harness/scripts/strap.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-7 --sha <sha>`

**Evidence:** commit b12c88f: 51 test node(s) passed

- `b12c88f41a7c4f521ef87d8bc36d10da34d8312c`
- `tree 321d5bc9c4f89e7fba26cab9d963f86c5a30941b`
- `python -m pytest -q tests/scripts/test_strap_driver.py::test_new_writes_the_spec_and_prints_the_done_line tests/scripts/test_strap_driver.py::test_new_on_an_existing_spec_resumes tests/scripts/test_strap_driver.py::test_new_edit_records_base_and_parts tests/scripts/test_strap_driver.py::test_new_refuses_an_existing_skill tests/scripts/test_strap_driver.py::test_new_edit_refuses_a_missing_skill tests/scripts/test_strap_driver.py::test_new_edit_records_the_given_base tests/scripts/test_strap_driver.py::test_new_edit_refuses_a_non_ancestor_base tests/scripts/test_strap_driver.py::test_new_refuses_a_judge_change_once_grades_exist tests/scripts/test_strap_driver.py::test_check_passes_a_sound_spec tests/scripts/test_strap_driver.py::test_check_lists_open_behavior_short_of_scenarios tests/scripts/test_strap_driver.py::test_check_refuses_hand_edited_driver_owned_field tests/scripts/test_strap_driver.py::test_check_refuses_a_non_canonical_file tests/scripts/test_strap_driver.py::test_check_refuses_a_role_without_an_agent_file tests/scripts/test_strap_driver.py::test_draw_refuses_a_behavior_with_one_scenario tests/scripts/test_strap_driver.py::test_draw_appends_one_initial_draw_never_redraws tests/scripts/test_strap_driver.py::test_run_refuses_no_draw_and_early_green tests/scripts/test_strap_driver.py::test_run_prints_the_runner_row_and_builds_the_tree tests/scripts/test_strap_driver.py::test_run_twice_before_record_reuses_the_run tests/scripts/test_strap_driver.py::test_run_refuses_second_recorded_run_same_arm tests/scripts/test_strap_driver.py::test_init_brief_ends_with_record_run tests/scripts/test_strap_driver.py::test_init_baseline_of_new_skill_omits_the_skill tests/scripts/test_strap_driver.py::test_init_green_carries_skill_with_abs_paths tests/scripts/test_strap_driver.py::test_init_includes_the_role_agent_body tests/scripts/test_strap_driver.py::test_record_run_stores_reply_and_drops_tree tests/scripts/test_strap_driver.py::test_retest_refuses_without_failed_green tests/scripts/test_strap_driver.py::test_freeze_refuses_a_behavior_that_never_ran tests/scripts/test_strap_driver.py::test_freeze_stamps_hash_and_grader tests/scripts/test_strap_driver.py::test_api_runs_stdin_code_with_name_bound tests/scripts/test_strap_driver.py::test_api_reports_refused_operation_as_problem tests/scripts/test_strap_driver.py::test_api_cannot_call_record_run tests/scripts/test_strap_gate.py::test_freeze_passes_on_failing_baseline_and_green tests/scripts/test_strap_gate.py::test_freeze_judge_spec_stamps_grader_judge tests/scripts/test_strap_gate.py::test_freeze_refuses_an_already_frozen_spec tests/scripts/test_strap_gate.py::test_freeze_refuses_a_part_change_after_green tests/scripts/test_strap_gate.py::test_freeze_refuses_an_unclear_grade tests/scripts/test_strap_gate.py::test_freeze_refuses_an_ungraded_judged_item tests/scripts/test_strap_gate.py::test_freeze_refuses_a_baseline_that_did_not_fail tests/scripts/test_strap_gate.py::test_freeze_refuses_short_or_undrawn[1] tests/scripts/test_strap_gate.py::test_freeze_refuses_short_or_undrawn[2] tests/scripts/test_strap_gate.py::test_run_and_freeze_refuse_no_skill_md_part tests/scripts/test_strap_gate.py::test_freeze_refuses_an_unrepassed_must_pass tests/scripts/test_strap_gate.py::test_red_records_state_red_on_mechanical tests/scripts/test_strap_gate.py::test_freeze_refuses_mechanical_red_not_recorded tests/scripts/test_strap_gate.py::test_freeze_refuses_failing_planned_tests tests/scripts/test_strap_gate.py::test_freeze_passes_a_mechanical_behavior tests/scripts/test_strap_gate.py::test_scaffold_prints_paths_bump_and_parts tests/scripts/test_strap_gate.py::test_judge_row_refused_on_a_non_judge_spec tests/scripts/test_strap_gate.py::test_judge_row_lists_ungraded_recorded_runs tests/scripts/test_strap_gate.py::test_retest_draws_anew_and_run_targets_failed tests/scripts/test_strap_gate.py::test_retest_refuses_an_exhausted_pool tests/contract/test_root_separation.py::test_entry_point_writes_nothing_under_plugins[strap new]`

### STR-8: Agents strap-scenario-runner and strap-judge

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** STR-7
**Files:** `plugins/harness/agents/strap-scenario-runner.md`, `plugins/harness/agents/strap-judge.md`, `tests/contract/test_no_repo_literals.py`, `plugins/pr-review-watch/hooks/contract.ts`, `plugins/pr-review-watch/.claude-plugin/plugin.json`

**Anchors:**
- `plugins/pr-review-watch/hooks/contract.ts:124` holds `'harness:todo-editor',`
- `plugins/pr-review-watch/.claude-plugin/plugin.json:3` holds `"version": "0.4.2",`
- `tests/contract/test_no_repo_literals.py:17` holds `TEXT_SUFFIXES = {".py", ".md", ".json", ".jsonl", ".ts", ".tsx", ".sh", ".txt", ".yaml", ".yml"}`

Create plugins/harness/agents/strap-scenario-runner.md and strap-judge.md per CONTRACT section Agents, modeled on plugins/harness/agents/bubble-memo-investigator.md: description with examples, model sonnet, fixed tools; runner: first action init through hpy, work only inside TREE, exactly one record-run heredoc, a session-role scenario ends by stating the Agent(...) call it would make (spec decision 12), stop conditions, reply = printed block verbatim. Judge: grade through `strap.py api` with grade(..., grader="judge") and a verbatim quote per item; never edits files. init and record-run lines carry --repo (D20). Add 'harness:strap-judge' and 'harness:strap-scenario-runner' in sorted order to DEFINED_AGENTS in plugins/pr-review-watch/hooks/contract.ts and bump pr-review-watch 0.4.2 -> 0.4.3. In tests/contract/test_no_repo_literals.py add .tmpl to TEXT_SUFFIXES and the two ids to BARE_AGENT.

- [x] Test `tests/skills/test_strap_agents_contract.py::test_frontmatter_matches_the_contract[strap-scenario-runner]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_frontmatter_matches_the_contract[strap-judge]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_body_launches_the_driver_through_hpy[strap-scenario-runner]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_body_launches_the_driver_through_hpy[strap-judge]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_body_names_no_bare_agent_id[strap-scenario-runner]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_body_names_no_bare_agent_id[strap-judge]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_inits_first_and_records_last` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_command_carries_repo[init]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_command_carries_repo[record-run]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_records_exactly_one_run_by_heredoc` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_works_only_inside_the_tree` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_reply_is_the_printed_block_verbatim` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_session_role_ends_at_agent_call` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_runner_states_stop_conditions` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_judge_grades_through_the_api_as_judge` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_judge_quotes_each_item_verbatim` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_agents_contract.py::test_judge_never_edits_files` fails with AssertionError, then passes
- [x] Test `tests/contract/test_no_repo_literals.py::test_templates_are_scanned` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/contract/test_no_repo_literals.py tests/mods/test_pr_review_watch_usage_contract.py -q`: passed, no failures
- [x] Run `claude plugin test plugins/pr-review-watch`: tests pass
- [x] Record the commit: `plan.py record 0002 STR-8 --sha <sha>`

**Evidence:** commit 25d26a0: 18 test node(s) passed

- `25d26a02f6fdfa3c33552d3a36c2e1cee59ca3d6`
- `tree 34bc6336f950668ce72870661c071816ac5e5392`
- `python -m pytest -q tests/skills/test_strap_agents_contract.py::test_frontmatter_matches_the_contract[strap-scenario-runner] tests/skills/test_strap_agents_contract.py::test_frontmatter_matches_the_contract[strap-judge] tests/skills/test_strap_agents_contract.py::test_body_launches_the_driver_through_hpy[strap-scenario-runner] tests/skills/test_strap_agents_contract.py::test_body_launches_the_driver_through_hpy[strap-judge] tests/skills/test_strap_agents_contract.py::test_body_names_no_bare_agent_id[strap-scenario-runner] tests/skills/test_strap_agents_contract.py::test_body_names_no_bare_agent_id[strap-judge] tests/skills/test_strap_agents_contract.py::test_runner_inits_first_and_records_last tests/skills/test_strap_agents_contract.py::test_runner_command_carries_repo[init] tests/skills/test_strap_agents_contract.py::test_runner_command_carries_repo[record-run] tests/skills/test_strap_agents_contract.py::test_runner_records_exactly_one_run_by_heredoc tests/skills/test_strap_agents_contract.py::test_runner_works_only_inside_the_tree tests/skills/test_strap_agents_contract.py::test_runner_reply_is_the_printed_block_verbatim tests/skills/test_strap_agents_contract.py::test_runner_session_role_ends_at_agent_call tests/skills/test_strap_agents_contract.py::test_runner_states_stop_conditions tests/skills/test_strap_agents_contract.py::test_judge_grades_through_the_api_as_judge tests/skills/test_strap_agents_contract.py::test_judge_quotes_each_item_verbatim tests/skills/test_strap_agents_contract.py::test_judge_never_edits_files tests/contract/test_no_repo_literals.py::test_templates_are_scanned`

### STR-9: strap-skills SKILL.md and its classification in the guidance-tail guard

**Status:** COMPLETE | **Model:** opus | **Depends on:** STR-6, STR-7, STR-8
**Files:** `plugins/harness/skills/strap-skills/SKILL.md`, `tests/skills/test_skill_guidance_tail_contract.py`

**Anchors:**
- `tests/skills/test_skill_guidance_tail_contract.py:26` holds `"pr-team", "roast-my-code", "sync-gh-todo", "todo-edit", "write-plan",`

Create plugins/harness/skills/strap-skills/SKILL.md per CONTRACT section Skill and the design: arguments paragraph citing ${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md, Rules (Iron Law, draws final, recorded runs final, content hash, quotes verified, mechanical vs judgment split), numbered Steps (new -> classify behaviors via the api heredoc -> check -> red -> scaffold -> fill parts -> draw -> run/record-run per arm with runner dispatch -> grade (session) or judge-row -> retest loop -> freeze), the one api heredoc, a judgment table (classification, scenario pressures, tempts, checks vs judged). Add strap-skills to _INVOCABLE in tests/skills/test_skill_guidance_tail_contract.py.

- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_frontmatter_name_and_description` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_argument_hint_is_the_contract_hint` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_split_rule_cited_and_no_fenced_raw_arguments` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_every_strap_command_goes_through_the_launcher` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_every_driver_subcommand_is_named` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_both_agents_dispatched_with_an_explicit_model` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_exactly_one_api_heredoc` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_a_judgment_table` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_lint_skill_finds_no_problem` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[skill_md.tmpl]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[models.tmpl]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[api.tmpl]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[contract_test.tmpl]` fails with AssertionError, then passes
- [x] Test `tests/skills/test_skill_guidance_tail_contract.py::test_every_skill_is_classified` fails with AssertionError, then passes
- [x] Run `python -m ruff check --no-cache tests/lib/test_strap_models.py tests/lib/test_strap_runs.py tests/lib/test_strap_api.py tests/lib/test_strap_lint.py tests/lib/test_strap_scaffold.py tests/scripts/test_strap_driver.py tests/scripts/test_strap_gate.py tests/scripts/test_skill_api.py tests/schemas/test_skillspec_schema_drift.py tests/skills/test_strap_agents_contract.py tests/skills/test_strap_skills_skill_contract.py`: All checks passed!
- [x] Record the commit: `plan.py record 0002 STR-9 --sha <sha>`

**Evidence:** commit c185829: 14 test node(s) passed

- `c185829de330951b3858a7e30540523b52084efb`
- `tree 38a5663373d5066a5c67d3de594cfe92fdfaef51`
- `python -m pytest -q tests/skills/test_strap_skills_skill_contract.py::test_frontmatter_name_and_description tests/skills/test_strap_skills_skill_contract.py::test_argument_hint_is_the_contract_hint tests/skills/test_strap_skills_skill_contract.py::test_split_rule_cited_and_no_fenced_raw_arguments tests/skills/test_strap_skills_skill_contract.py::test_every_strap_command_goes_through_the_launcher tests/skills/test_strap_skills_skill_contract.py::test_every_driver_subcommand_is_named tests/skills/test_strap_skills_skill_contract.py::test_both_agents_dispatched_with_an_explicit_model tests/skills/test_strap_skills_skill_contract.py::test_exactly_one_api_heredoc tests/skills/test_strap_skills_skill_contract.py::test_a_judgment_table tests/skills/test_strap_skills_skill_contract.py::test_lint_skill_finds_no_problem tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[skill_md.tmpl] tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[models.tmpl] tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[api.tmpl] tests/skills/test_strap_skills_skill_contract.py::test_scaffold_template_ships[contract_test.tmpl] tests/skills/test_skill_guidance_tail_contract.py::test_every_skill_is_classified`

### STR-10: Release: README row and plugin version

**Status:** COMPLETE | **Model:** haiku | **Depends on:** STR-9
**Files:** `README.md`, `plugins/harness/.claude-plugin/plugin.json`

**Anchors:**
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.41.1",`

Add a README.md table row for `harness`: `strap-skills` after the write-plan row (what it makes: a harness-shaped skill with models, api, driver where earned, agents, contract test; checks: draw final, Iron Law at freeze, quotes verified, content-hash retest). Bump plugins/harness/.claude-plugin/plugin.json version 0.41.1 -> 0.42.0.

- [x] Run `claude plugin validate --strict plugins/harness`: validation passes
- [x] Run `python -m pytest tests/skills/test_strap_skills_skill_contract.py -q`: passed, no failures (run by hand; STR-10 has no test nodes)
- [x] Record the commit: `plan.py record 0002 STR-10 --sha <sha>`

**Evidence:** commit c121a4d

- `c121a4d4864159486aeff2aa45741bab2fa65c4c`
- `tree 0b04e10625c9b0c7d2416351ba14fcb16e59c078`

### STR-11: Self-gate: strap-skills through its own gate

**Status:** PENDING | **Model:** opus | **Depends on:** STR-10
**Files:** `docs/plans/strap/strap-skills/SkillSpec.json`, `plugins/harness/skills/strap-skills/SKILL.md`, `plugins/harness/agents/strap-scenario-runner.md`, `plugins/harness/agents/strap-judge.md`

From a session started with `claude --plugin-dir <worktree>/plugins/harness` (spec decision 13), run /harness:strap-skills strap-skills --edit --base 697dce285549 (D11: SKILL.md is absent at the plan base, so every baseline runs without the skill). Classify its judgment behaviors (at least: the session never reruns a recorded arm; it grades only with a quote; it uses a dispatch row verbatim with its model), two scenarios each, draw, baseline and green through harness:strap-scenario-runner, grade, retest each failed green after a SKILL.md fix, freeze. Acceptance: the frozen spec holds at least one non-dropped judgment behavior with a failing baseline and a passing green.

- [ ] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py check strap-skills`: check [ok] (spec frozen: frozen is set)
- [ ] Record the commit: `plan.py record 0002 STR-11 --sha <sha>`

**Evidence:** 
