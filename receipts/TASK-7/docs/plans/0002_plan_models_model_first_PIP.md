# Plan 0002: plan models model first

> Rendered by `plan.py render` from `0002_plan_models_model_first_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-10-30
**Spec:** `docs/superpowers/specs/2026-10-29-plan-models-design.md`
**Branch:** none -> main
**Base commit:** `6429938`
**Frozen:** 2026-10-30 at `6429938`
**Execution model:** serial

## Decisions

- **D1** How does an agent hand the driver a plan? Chosen: `whole-plan-write` (load, model_copy(update=..., deep=True), write the whole plan). Rejected: `piecewise-add` (add_item and add_decision style methods). The developer chose it; add_* methods come later on top of load and write.
- **D2** Which validator does plan.py use, and what does the schema hook use? Chosen: `models-in-plan-py` (plan.py validates through the models; the hook validates against a schema JSON). Rejected: `schema-everywhere` (every consumer validates against the schema JSON). The developer chose the models as the truth; drift tests keep the generated schema in step.
- **D3** What happens to prAttributes.schema.json? Chosen: `retire-no-stub` (delete it; the hook reports an unresolvable pinned $ref). Rejected: `keep-stub` (keep a stub file so old pinned copies still resolve). The developer chose no stub; the hook stops hiding the unresolvable reference.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| schema message cut | 200 | plugins/harness/lib/harness_lib/plan_doc.py:111 | - |
| plugin version after the change | 0.42.0 | plugins/harness/.claude-plugin/plugin.json:3 | retire-no-stub |
| pydantic series in requirements-dev.txt | pydantic>=2.14,<2.15 | requirements-dev.txt:4 | models-in-plan-py |

## Formats

- **authoring heredoc command line**: `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib" sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" - <<'EOF'`, copied from `plugins/harness/scripts/pr_review.py:715`
- **schema problem line**: `schema: items/0/tests/0/red: Input should be 'ImportError'`, copied from `plugins/harness/lib/harness_lib/plan_doc.py:111`

## Sweeps

- **S1** `prAttributes`: `docs/plans/0002_plan_models_model_first_ActionPlan.json` (keep), `docs/plans/0002_plan_models_model_first_PIP.md` (keep), `docs/superpowers/specs/2026-10-29-plan-models-design.md` (keep), `plugins/harness/lib/harness_lib/validation/schema_registry.py` (rewrite), `plugins/harness/schemas/ActionPlan.schema.json` (rewrite), `plugins/harness/schemas/PLANS_PIP_Template.md` (rewrite), `plugins/harness/schemas/README.md` (rewrite), `tests/fixtures/plan_models/ActionPlan.draft07.schema.json` (keep), `tests/hooks/test_hooks_schema_validation.py` (rewrite), `tests/schemas/test_agent_schemas.py` (rewrite), `tests/schemas/test_validation_helpers.py` (rewrite)
- **S2** `MUTABLE_(TOP|ITEM)`: `docs/PR_REVIEWS/0117_New_Skill_write-plan.json` (keep), `docs/plans/0002_plan_models_model_first_ActionPlan.json` (keep), `docs/plans/0002_plan_models_model_first_PIP.md` (keep), `docs/superpowers/specs/2026-10-29-plan-models-design.md` (keep), `plugins/harness/lib/harness_lib/plan_doc.py` (rewrite), `plugins/harness/scripts/plan.py` (rewrite), `plugins/harness/skills/write-plan/SKILL.md` (rewrite)

## Tasks

### PM-1: Enums module (stdlib only)

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/plan_enums.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_doc.py:22` holds `DONE = frozenset({"COMPLETE", "CLOSED_NO_ACTION"})`
- `plugins/harness/lib/harness_lib/plan_lanes.py:17` holds `OPEN = ("PENDING", "IN_PROGRESS", "BLOCKED")`
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:15-16` holds `DONE = frozenset({"COMPLETE", "CLOSED_NO_ACTION"}) OPEN = frozenset({"PENDING", "IN_PROGRESS"})`

Add harness_lib/plan_enums.py: StrEnum classes ItemStatus, ModelName, RedException, Priority and MarkdownSync with the JSON strings of a plan file as values, plus the frozensets DONE, LANE_OPEN (PENDING, IN_PROGRESS, BLOCKED) and RULES_OPEN (PENDING, IN_PROGRESS). Standard library imports only: todo_sync must not gain a pydantic import.

- [x] Test `tests/lib/test_plan_enums.py::test_member_values_are_the_json_strings_of_a_plan_file` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_enums.py::test_a_member_prints_as_its_value` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_enums.py::test_a_member_equals_and_hashes_as_its_string` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_enums.py::test_the_status_sets_keep_the_membership_the_code_had` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_enums.py::test_the_module_imports_only_the_standard_library` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0002 PM-1 --sha <sha>`

**Evidence:** commit cecb005: 5 test node(s) passed

- `cecb005e8e09ea04f3e6139aad5252398ce69221`
- `tree 09144726079118be9714cecc3992e33db93fc63d`
- `python -m pytest -q tests/lib/test_plan_enums.py::test_member_values_are_the_json_strings_of_a_plan_file tests/lib/test_plan_enums.py::test_a_member_prints_as_its_value tests/lib/test_plan_enums.py::test_a_member_equals_and_hashes_as_its_string tests/lib/test_plan_enums.py::test_the_status_sets_keep_the_membership_the_code_had tests/lib/test_plan_enums.py::test_the_module_imports_only_the_standard_library`

### PM-2: Pydantic models and the pre-migration fixtures

**Status:** COMPLETE | **Model:** opus | **Depends on:** PM-1
**Files:** `plugins/harness/lib/harness_lib/plan_models.py`, `tests/fixtures/plan_models/ActionPlan.draft07.schema.json`, `tests/fixtures/plan_models/prAttributes.draft07.schema.json`, `tests/fixtures/plan_models/0001_Minimal_ActionPlan.json`, `tests/fixtures/plan_models/0001_Minimal_PIP.md`, `tests/fixtures/plan_models/0002_Full_ActionPlan.json`, `tests/fixtures/plan_models/0002_Full_PIP.md`, `tests/fixtures/plan_models/0003_Inflight_ActionPlan.json`, `tests/fixtures/plan_models/0003_Inflight_PIP.md`, `tests/fixtures/plan_models/expected.json`

**Anchors:**
- `plugins/harness/schemas/ActionPlan.schema.json:294` holds `"enum": ["haiku", "sonnet", "opus"],`
- `plugins/harness/schemas/ActionPlan.schema.json:353` holds `"enum": ["ImportError", "AttributeError", "AssertionError", "NotImplementedError", "TypeError"],`
- `plugins/harness/schemas/prAttributes.schema.json:12-16` holds `"pr": { "type": [ "integer", "string" ],`

Add harness_lib/plan_models.py: the ActionPlan model tree (ActionPlan, ActionItem, Anchor, Command, PlannedTest, Decision, DecisionOption, Value, PlanFormat, Sweep, DeferredTopic, Context, Frozen, PrAttributes), the Mutable marker, mutable_top, mutable_item, schema_dict and schema_text. Follow the spec's Calls: extras allow or forbid per model (never ignore), required stays required, optional-not-nullable fields get a non-None default, dates stay str, pr is a strict int or str behind a before-validator, python-re regex engine. Commit the fixtures under tests/fixtures/plan_models/: the two pre-migration draft-07 schemas, three plan documents with their golden PIPs and expected.json of digests, all produced by the code as it is before PM-3.

- [x] Test `tests/lib/test_plan_models.py::test_every_model_allows_or_forbids_extras_and_matches_patterns_like_jsonschema` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_a_field_the_old_schema_required_has_no_default` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_mutable_fields_are_the_freeze_digest_exclusions` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_a_marker_never_reaches_the_generated_schema` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_absent_optional_fields_read_as_the_old_code_read_a_missing_key` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_date_fields_stay_strings_whatever_they_hold` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_pr_accepts_an_int_or_a_string` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_pr_rejects_anything_else_with_one_error` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_schema_text_declares_the_dialect_and_the_repository_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_the_generated_schema_refers_to_no_sibling_file` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models_differential.py::test_the_generated_schema_is_a_valid_draft_2020_12_schema` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models_differential.py::test_old_schema_generated_schema_and_models_agree` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models_differential.py::test_the_corpus_holds_documents_of_both_verdicts` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0002 PM-2 --sha <sha>`

**Evidence:** commit 2f8eb34: 13 test node(s) passed

- `2f8eb3429fd2f29639646b2e3e550884d16ac959`
- `tree 768901904a6321290e1d2a19bbd61247bc1cf19f`
- `python -m pytest -q tests/lib/test_plan_models.py::test_every_model_allows_or_forbids_extras_and_matches_patterns_like_jsonschema tests/lib/test_plan_models.py::test_a_field_the_old_schema_required_has_no_default tests/lib/test_plan_models.py::test_mutable_fields_are_the_freeze_digest_exclusions tests/lib/test_plan_models.py::test_a_marker_never_reaches_the_generated_schema tests/lib/test_plan_models.py::test_absent_optional_fields_read_as_the_old_code_read_a_missing_key tests/lib/test_plan_models.py::test_date_fields_stay_strings_whatever_they_hold tests/lib/test_plan_models.py::test_pr_accepts_an_int_or_a_string tests/lib/test_plan_models.py::test_pr_rejects_anything_else_with_one_error tests/lib/test_plan_models.py::test_schema_text_declares_the_dialect_and_the_repository_id tests/lib/test_plan_models.py::test_the_generated_schema_refers_to_no_sibling_file tests/lib/test_plan_models_differential.py::test_the_generated_schema_is_a_valid_draft_2020_12_schema tests/lib/test_plan_models_differential.py::test_old_schema_generated_schema_and_models_agree tests/lib/test_plan_models_differential.py::test_the_corpus_holds_documents_of_both_verdicts`

### PM-3: Plan library modules read the models

**Status:** COMPLETE | **Model:** opus | **Depends on:** PM-2
**Files:** `plugins/harness/lib/harness_lib/plan_doc.py`, `plugins/harness/lib/harness_lib/plan_checks.py`, `plugins/harness/lib/harness_lib/plan_render.py`, `plugins/harness/lib/harness_lib/plan_lanes.py`, `plugins/harness/lib/harness_lib/plan_red.py`, `tests/lib/test_plan_doc.py`, `tests/lib/test_plan_checks.py`, `tests/lib/test_plan_checks_cycles.py`, `tests/lib/test_plan_lanes.py`, `tests/lib/test_plan_red.py`, `tests/lib/test_plan_render.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_doc.py:109` holds `validator = jsonschema.validators.validator_for(schema)(schema, registry=schema_registry(cfg))`
- `plugins/harness/lib/harness_lib/plan_doc.py:117` holds `fixed = {k: v for k, v in plan.items() if k not in MUTABLE_TOP}`
- `plugins/harness/lib/harness_lib/plan_lanes.py:34` holds `return [item for item in plan.get("items") or [] if item.get("status") in OPEN]`
- `plugins/harness/lib/harness_lib/plan_red.py:192` holds `results.append(RedResult(str(item["id"]), node, str(test["red"]), classify(output, node)))`
- `plugins/harness/lib/harness_lib/plan_render.py:15` holds `from harness_lib.plan_doc import DONE, PLAN_SUFFIX, items_of`
- `plugins/harness/lib/harness_lib/plan_checks.py:15` holds `from harness_lib.plan_doc import items_of, planned_tests_dir`

Migrate plan_doc, plan_checks, plan_render, plan_lanes and plan_red from Mapping[str, Any] to ActionPlan attributes. plan_doc: load_plan and parse_plan return ActionPlan and raise PlanError holding schema: lines; schema_problems(raw) validates a raw dict (no cfg); plan_dict applies the dump policy (written when set or different from the default, then model_dump mode json, on a deep copy); dump_plan and save_plan take the model; frozen_digest hashes plan_dict minus the mutable fields; items_of and item_by_id read plan.items; MUTABLE_TOP and MUTABLE_ITEM derive from plan_models; DONE comes from plan_enums. Error lines: path from loc joined with a slash, one line per path, messages joined, cut at 200. plan_lanes uses LANE_OPEN, plan_render and plan_red use the enums. Migrate the six existing lib test files: their plan helpers build models, ids and values the models reject become valid ones, a test that needs an invalid plan validates a raw dict. Copy the planned test files from docs/plans/0002/tests to their repo paths first.

- [x] Test `tests/lib/test_plan_models.py::test_load_returns_the_model_and_dumps_the_file_back_unchanged` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_a_loaded_fixture_keeps_the_freeze_digest_the_old_code_computed` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_the_digest_ignores_execution_fields_and_sees_every_other_field` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_an_in_place_append_to_a_list_that_was_never_set_is_written` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_a_field_left_at_its_default_is_not_written` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_reopening_removes_completed_from_the_file` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_dumping_does_not_mark_the_plan_it_was_given` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_the_pip_of_a_loaded_fixture_is_the_one_the_old_renderer_wrote` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_schema_problems_name_the_json_path_and_print_a_defect_once` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_schema_problems_of_a_valid_plan_are_empty` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_a_long_message_is_cut_at_two_hundred_characters` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_an_invalid_file_raises_a_plan_error_holding_the_schema_lines` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_parse_plan_reports_text_that_is_not_a_plan_object` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_models.py::test_the_digest_exclusions_of_plan_doc_come_from_the_models` fails with ImportError, then passes
- [x] Run `python -m pytest tests/lib/test_plan_doc.py tests/lib/test_plan_checks.py tests/lib/test_plan_checks_cycles.py tests/lib/test_plan_lanes.py tests/lib/test_plan_red.py tests/lib/test_plan_render.py -q`: every test passes
- [x] Record the commit: `plan.py record 0002 PM-3 --sha <sha>`

**Evidence:** commit 211dec6: 14 test node(s) passed

- `211dec68b52ea58a2ee4a53ebd967d65be68a83f`
- `tree 972847661da04d8b531ab6227b18ea1329f150e5`
- `python -m pytest -q tests/lib/test_plan_models.py::test_load_returns_the_model_and_dumps_the_file_back_unchanged tests/lib/test_plan_models.py::test_a_loaded_fixture_keeps_the_freeze_digest_the_old_code_computed tests/lib/test_plan_models.py::test_the_digest_ignores_execution_fields_and_sees_every_other_field tests/lib/test_plan_models.py::test_an_in_place_append_to_a_list_that_was_never_set_is_written tests/lib/test_plan_models.py::test_a_field_left_at_its_default_is_not_written tests/lib/test_plan_models.py::test_reopening_removes_completed_from_the_file tests/lib/test_plan_models.py::test_dumping_does_not_mark_the_plan_it_was_given tests/lib/test_plan_models.py::test_the_pip_of_a_loaded_fixture_is_the_one_the_old_renderer_wrote tests/lib/test_plan_models.py::test_schema_problems_name_the_json_path_and_print_a_defect_once tests/lib/test_plan_models.py::test_schema_problems_of_a_valid_plan_are_empty tests/lib/test_plan_models.py::test_a_long_message_is_cut_at_two_hundred_characters tests/lib/test_plan_models.py::test_an_invalid_file_raises_a_plan_error_holding_the_schema_lines tests/lib/test_plan_models.py::test_parse_plan_reports_text_that_is_not_a_plan_object tests/lib/test_plan_models.py::test_the_digest_exclusions_of_plan_doc_come_from_the_models`

### PM-4: plan_api: load and write

**Status:** COMPLETE | **Model:** opus | **Depends on:** PM-3
**Files:** `plugins/harness/lib/harness_lib/plan_api.py`

**Anchors:**
- `plugins/harness/scripts/plan.py:95-102` holds `def locate(repo: Path, ref: str) -> Path:`
- `plugins/harness/lib/harness_lib/review_models.py:77` holds `def config_for(repo: Optional[Union[str, Path]] = None) -> HarnessConfig:`

Add harness_lib/plan_api.py: load(plan, repo=None) and write(plan, repo=None), both driver entry points that activate the project named by repo (default: the working directory) with load_config(project_root(repo)). load finds the plan by id (padded or not) or path, validates it through plan_doc.load_plan and stores the hash of the file bytes on the plan's private _loaded_hash. write follows the spec's write contract: dump with plan_dict, re-validate the dump, run plan_checks.duplicate_problems, refuse an unknown plan id, a changed base_commit or frozen, a file changed since load, a plan that was not loaded, an extra key at the plan or item level the file does not already carry, and (frozen plan only) any change to an execution field; collect every problem, write nothing on a refusal; render both texts first, then save the JSON, then the PIP; return the re-validated plan.

- [x] Test `tests/lib/test_plan_api.py::test_load_finds_a_plan_by_id_padded_or_not_and_by_path` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_load_refuses_a_plan_that_does_not_validate` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_load_names_an_unknown_plan` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_saves_the_json_and_the_pip_and_returns_the_validated_plan` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_keeps_the_extra_keys_the_file_already_carries` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_saves_an_in_place_append_to_a_list_never_set` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_an_invalid_plan_with_full_paths_and_writes_nothing` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_a_duplicate_item_id` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_a_plan_id_with_no_file` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_to_change_the_base_commit_or_the_freeze_record` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_a_copy_loaded_before_the_file_changed` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_a_plan_that_was_not_loaded` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_refuses_a_misspelled_field_on_the_plan_or_an_item` fails with ImportError, then passes
- [x] Test `tests/lib/test_plan_api.py::test_write_on_a_frozen_plan_refuses_execution_fields_and_saves_a_design_edit` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0002 PM-4 --sha <sha>`

**Evidence:** commit f2674a2: 14 test node(s) passed

- `f2674a246d8f6948026f4b76bba0234ca49e9ab8`
- `tree 9429027568d9a7d4794261b5acd27f9c1dc01d28`
- `python -m pytest -q tests/lib/test_plan_api.py::test_load_finds_a_plan_by_id_padded_or_not_and_by_path tests/lib/test_plan_api.py::test_load_refuses_a_plan_that_does_not_validate tests/lib/test_plan_api.py::test_load_names_an_unknown_plan tests/lib/test_plan_api.py::test_write_saves_the_json_and_the_pip_and_returns_the_validated_plan tests/lib/test_plan_api.py::test_write_keeps_the_extra_keys_the_file_already_carries tests/lib/test_plan_api.py::test_write_saves_an_in_place_append_to_a_list_never_set tests/lib/test_plan_api.py::test_write_refuses_an_invalid_plan_with_full_paths_and_writes_nothing tests/lib/test_plan_api.py::test_write_refuses_a_duplicate_item_id tests/lib/test_plan_api.py::test_write_refuses_a_plan_id_with_no_file tests/lib/test_plan_api.py::test_write_refuses_to_change_the_base_commit_or_the_freeze_record tests/lib/test_plan_api.py::test_write_refuses_a_copy_loaded_before_the_file_changed tests/lib/test_plan_api.py::test_write_refuses_a_plan_that_was_not_loaded tests/lib/test_plan_api.py::test_write_refuses_a_misspelled_field_on_the_plan_or_an_item tests/lib/test_plan_api.py::test_write_on_a_frozen_plan_refuses_execution_fields_and_saves_a_design_edit`

### PM-5: plan.py works on the models

**Status:** COMPLETE | **Model:** opus | **Depends on:** PM-3, PM-4
**Files:** `plugins/harness/scripts/plan.py`, `tests/scripts/test_plan_driver.py`, `tests/contract/test_root_separation.py`

**Anchors:**
- `plugins/harness/scripts/plan.py:78` holds `from harness_lib.plan_render import render_pip`
- `plugins/harness/scripts/plan.py:192` holds `schema = pd.schema_problems(plan, active())`
- `plugins/harness/scripts/plan.py:418` holds `plan.pop("completed", None)`
- `plugins/harness/scripts/pr_review.py:137-141` holds `_REQUIRED_MODULES: Tuple[Tuple[str, Optional[str], str], ...] = ( ("pydantic", "model_validator", "pydantic>=2"),`

Migrate scripts/plan.py to ActionPlan: every command loads through plan_doc.load_plan (an invalid plan is refused with the schema: lines, render, red, lanes and record included), attribute access replaces .get and item[...] everywhere, statuses come from plan_enums, record reopens with plan.model_fields_set.discard(completed), skeleton builds the plan through the model, save goes through plan_doc.save_plan. Check for pydantic before the harness_lib imports, in the pr_review.py way, and print one problem line naming pydantic>=2. new prints the authoring command line of the spec (PYTHONPATH, hpy, quoted heredoc) and the lib import. Migrate tests/scripts/test_plan_driver.py and add a plan.py case to tests/contract/test_root_separation.py CASES for new and for a plan_api.write run.

- [x] Test `tests/scripts/test_plan_missing_pydantic.py::test_missing_pydantic_is_one_problem_line_and_exit_1` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/scripts/test_plan_driver.py tests/contract/test_root_separation.py -q`: every test passes
- [x] Record the commit: `plan.py record 0002 PM-5 --sha <sha>`

**Evidence:** commit 017696f: 1 test node(s) passed

- `017696fca83e20a6189199dd32438d436304d279`
- `tree e72a1f188acf531463035365b910c3c8279e223d`
- `python -m pytest -q tests/scripts/test_plan_missing_pydantic.py::test_missing_pydantic_is_one_problem_line_and_exit_1`

### PM-6: Generated schema, hook report, todo_sync enums

**Status:** COMPLETE | **Model:** opus | **Depends on:** PM-2, PM-3, PM-5
**Files:** `tools/gen_plan_schema.py`, `plugins/harness/schemas/ActionPlan.schema.json`, `plugins/harness/schemas/prAttributes.schema.json`, `plugins/harness/hooks/validate_pr_json_schema.py`, `plugins/harness/lib/harness_lib/validation/schema_registry.py`, `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py`, `requirements-dev.txt`, `tests/schemas/test_agent_schemas.py`, `tests/schemas/test_validation_helpers.py`, `tests/hooks/test_hooks_schema_validation.py`

**Anchors:**
- `plugins/harness/hooks/validate_pr_json_schema.py:153` holds `except Exception as exc:  # noqa: BLE001 - a setup failure is never a violation`
- `plugins/harness/lib/harness_lib/validation/schema_registry.py:44` holds `resource = Resource.from_contents(load_schema(name, cfg), default_specification=DRAFT202012)`
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:15-16` holds `DONE = frozenset({"COMPLETE", "CLOSED_NO_ACTION"}) OPEN = frozenset({"PENDING", "IN_PROGRESS"})`
- `requirements-dev.txt:4` holds `pydantic>=2.5`

Add tools/gen_plan_schema.py (repo-only: writes plugins/harness/schemas/ActionPlan.schema.json from plan_models.schema_text; --check compares parsed JSON and exits 1 on drift). Generate the schema and delete prAttributes.schema.json. The hook reports an unresolvable pinned $ref (referencing Unresolvable) with an error naming the schema and the reference and exits 1, never as a setup error. todo_sync/rules_plans.py imports DONE and RULES_OPEN from plan_enums, keeps reading raw dicts and stays stdlib-only. Bound pydantic in requirements-dev.txt to the installed series. Update the schema_registry docstring. Rewrite the tests that pinned the draft-07 shape or prAttributes: tests/schemas/test_agent_schemas.py, tests/schemas/test_validation_helpers.py, tests/hooks/test_hooks_schema_validation.py, and keep tests/schemas/test_schema_meta_valid.py and tests/lib/test_todo_sync_rules_plans.py green.

- [x] Test `tests/contract/test_plan_schema_generated.py::test_the_committed_schema_equals_the_one_the_models_generate` fails with ImportError, then passes
- [x] Test `tests/contract/test_plan_schema_generated.py::test_the_generator_tool_finds_no_drift` fails with ImportError, then passes
- [x] Test `tests/contract/test_plan_schema_generated.py::test_the_pr_attributes_schema_file_is_gone` fails with ImportError, then passes
- [x] Test `tests/contract/test_plan_schema_generated.py::test_a_plan_module_spells_no_status_or_model_name_as_a_literal` fails with ImportError, then passes
- [x] Test `tests/contract/test_plan_schema_generated.py::test_the_dev_requirements_bound_pydantic_to_the_series_the_schema_was_generated_with` fails with ImportError, then passes
- [x] Test `tests/hooks/test_hook_unresolvable_ref.py::test_a_pinned_schema_with_an_unresolvable_ref_blocks_and_names_both_files` fails with AssertionError, then passes
- [x] Run `python tools/gen_plan_schema.py`: writes the schema file
- [x] Run `python -m pytest tests/schemas/test_agent_schemas.py tests/schemas/test_validation_helpers.py tests/schemas/test_schema_meta_valid.py tests/hooks/test_hooks_schema_validation.py tests/lib/test_todo_sync_rules_plans.py -q`: every test passes
- [x] Record the commit: `plan.py record 0002 PM-6 --sha <sha>`

**Evidence:** commit 15b79b9: 6 test node(s) passed

- `15b79b9e211f71d177bb9adebf2a1b576992e9e5`
- `tree 8949b42ebf42d91d08208c56833fa36f94cdb24c`
- `python -m pytest -q tests/contract/test_plan_schema_generated.py::test_the_committed_schema_equals_the_one_the_models_generate tests/contract/test_plan_schema_generated.py::test_the_generator_tool_finds_no_drift tests/contract/test_plan_schema_generated.py::test_the_pr_attributes_schema_file_is_gone tests/contract/test_plan_schema_generated.py::test_a_plan_module_spells_no_status_or_model_name_as_a_literal tests/contract/test_plan_schema_generated.py::test_the_dev_requirements_bound_pydantic_to_the_series_the_schema_was_generated_with tests/hooks/test_hook_unresolvable_ref.py::test_a_pinned_schema_with_an_unresolvable_ref_blocks_and_names_both_files`

### PM-7: Skill, schema README and release

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** PM-4, PM-5, PM-6
**Files:** `plugins/harness/skills/write-plan/SKILL.md`, `plugins/harness/schemas/README.md`, `plugins/harness/schemas/PLANS_PIP_Template.md`, `plugins/harness/.claude-plugin/plugin.json`

**Anchors:**
- `plugins/harness/skills/write-plan/SKILL.md:31` holds `` 3. **Write the plan JSON** (Edit or Write on the plan file; before `freeze` this is the authoring path). The ``
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.41.1",`

Rewrite write-plan SKILL.md step 3 as the load, model_copy(deep=True), write heredoc (the exact command line of the spec), keep the field table naming model fields, state that plan JSON is never edited by hand (status changes only through record) with the single exception of repairing a plan that fails to load, replace the MUTABLE_TOP wording with the model metadata, add a Common mistakes section (hand-editing, a status set by hand, a guessed red exception, a SHA instead of {base}, model_copy without deep=True) and point Related at plan_models. Update schemas/README.md (steps 2-3, the plan and prAttributes sections, the dialect note, a Migration section for the retired prAttributes schema, the hook's unresolvable-ref report and the plan.py validation of render, red, lanes and record) and PLANS_PIP_Template.md; state that ActionPlan.schema.json is generated by tools/gen_plan_schema.py. Bump the harness plugin version to 0.42.0 and add the PROVENANCE note if the file lists these paths.

- [x] Test `tests/skills/test_write_plan_skill_models.py::test_step_three_is_a_heredoc_that_loads_copies_and_writes_the_plan` fails with AssertionError, then passes
- [x] Test `tests/skills/test_write_plan_skill_models.py::test_the_skill_no_longer_tells_the_agent_to_edit_the_plan_json` fails with AssertionError, then passes
- [x] Test `tests/skills/test_write_plan_skill_models.py::test_the_skill_forbids_hand_edits_and_names_the_one_repair_exception` fails with AssertionError, then passes
- [x] Test `tests/skills/test_write_plan_skill_models.py::test_the_skill_has_a_common_mistakes_section` fails with AssertionError, then passes
- [x] Test `tests/skills/test_write_plan_skill_models.py::test_the_skill_names_the_models_module_not_the_hand_written_schema` fails with AssertionError, then passes
- [x] Test `tests/contract/test_plan_schema_generated.py::test_the_schema_readme_names_the_generator_and_no_plan_py_subcommand` fails with ImportError, then passes
- [x] Run `python -m ruff check plugins tests tools --no-cache`: All checks passed
- [x] Run `python -m pytest tests/skills/test_skill_guidance_tail_contract.py tests/schemas/test_schema_meta_valid.py -q`: every test passes
- [x] Record the commit: `plan.py record 0002 PM-7 --sha <sha>`

**Evidence:** commit 0550c05: 6 test node(s) passed

- `0550c053a4d50e0d37e93b3849b0910a71f43623`
- `tree 2091ab24cfeb88cfe1c1e341713b995fa81d6a31`
- `python -m pytest -q tests/skills/test_write_plan_skill_models.py::test_step_three_is_a_heredoc_that_loads_copies_and_writes_the_plan tests/skills/test_write_plan_skill_models.py::test_the_skill_no_longer_tells_the_agent_to_edit_the_plan_json tests/skills/test_write_plan_skill_models.py::test_the_skill_forbids_hand_edits_and_names_the_one_repair_exception tests/skills/test_write_plan_skill_models.py::test_the_skill_has_a_common_mistakes_section tests/skills/test_write_plan_skill_models.py::test_the_skill_names_the_models_module_not_the_hand_written_schema tests/contract/test_plan_schema_generated.py::test_the_schema_readme_names_the_generator_and_no_plan_py_subcommand`
