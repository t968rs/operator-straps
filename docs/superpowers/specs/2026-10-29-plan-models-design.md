# write-plan: model-first ActionPlan (issue 145)

Status: revised after an adversarial review (5 lenses, 63 findings, 5 refuted). The developer chose the
approach and the Decisions below; every entry under "Calls made by the author" awaits the developer's read.

## Intent

An ActionPlan is defined twice today: `plugins/harness/schemas/ActionPlan.schema.json` (hand-written, draft-07)
and the dict-handling code in `plan_doc.py`, `plan_checks.py`, `plan_render.py`, `plan_lanes.py`, `plan_red.py`
and `scripts/plan.py` (raw `Mapping[str, Any]`, string literals for statuses and `red` names). Nothing ties
the two together.

The plan becomes pydantic models. Agents write a plan by running a Python snippet that builds model objects,
so authoring is filling in a form, not editing JSON and comparing it to a schema or an example. The JSON
schema becomes a generated artifact of the models.

## Goals

- `harness_lib/plan_enums.py` (stdlib only) holds the enums as `enum.StrEnum`: item status, implementing model,
  `red` exception, priority, markdown sync status, plus the two "open status" sets that exist today
  (`plan_lanes.OPEN`: PENDING, IN_PROGRESS, BLOCKED; `todo_sync/rules_plans.OPEN`: PENDING, IN_PROGRESS) and
  `DONE`. `harness_lib/plan_models.py` holds the `BaseModel` classes and imports the enums.
- `ActionPlan.schema.json` is generated from `ActionPlan.model_json_schema()` as draft 2020-12 with no adapter,
  never edited by hand. `plan_models.schema_text()` returns it with `$schema` (2020-12) and `$id` added in the
  form `schemas/README.md` requires; the repo-only `tools/gen_plan_schema.py` writes it (`--check` for drift).
- `prAttributes.schema.json` is retired; `PrAttributes(BaseModel)` lives in `plan_models`.
- `check`, `freeze`, `record`, `lanes`, `render` and `red` load the plan into `ActionPlan` and work on
  attributes, not dict keys.
- Authoring API, `harness_lib/plan_api.py`: `load(plan, repo=)` returns an `ActionPlan`; `write(plan, repo=)`
  validates it, saves it (JSON and PIP) and returns the re-validated `ActionPlan`. Authoring is always `load`
  (the skeleton `plan.py new` wrote), `model_copy(update=..., deep=True)`, `write`. Both functions are driver
  entry points: they activate the project named by `repo` (default: the working directory) themselves;
  everything below them reads `active()`.
- Heredoc form (a quoted heredoc does not expand `${CLAUDE_PLUGIN_ROOT}`, so the path goes on the command
  line): `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib" sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" - <<'EOF'`, then
  `from harness_lib.plan_models import ...` and `from harness_lib import plan_api`. The builder verifies that
  `hpy` forwards stdin `-` and `PYTHONPATH`; `plan.py new` prints the command line it expects.
- The freeze-digest exclusions `MUTABLE_TOP` / `MUTABLE_ITEM` become `Annotated` field metadata (a marker class
  that never reaches the generated schema); `plan_doc` derives its two lists from the model fields.
- On-disk plans keep loading: the models accept and reject the same plan documents as the hand-written schema.

## `write` contract

1. Validates before writing anything: dump the plan, re-validate the dump with `ActionPlan.model_validate`
   (validating the instance itself validates nothing in pydantic v2), then run `plan_checks.duplicate_problems`.
   Problems are reported together, each with its full path (item index included).
2. Writes nothing on a refusal. On success both files are rendered in memory first, then the JSON, then the PIP.
3. Refuses an unknown plan id (`plan.py new` allocates ids) and a plan whose `plan_id`, `base_commit` or
   `frozen` differs from the file on disk (`new` and `freeze` own them).
4. Refuses when the file on disk changed since `load` (the loaded text's hash rides on a private attribute):
   a stale copy would otherwise overwrite what `record` wrote in between.
5. On a frozen plan it refuses any change to the execution fields (item `status`, `evidence`,
   `verification_references`; plan `completed`, `markdown_sync_status`, `markdown_last_updated`): only `record`
   sets them. Any other edit saves, and `check` then reports "changed after freeze" until `freeze --refreeze`.
6. Refuses an extra key at the plan or item level that the file on disk does not already carry (a typo such as
   `dependancies` or `modle` would otherwise be stored under `extra="allow"`).

## Non-goals

- `add_item(...)`, `add_decision(...)` and similar piecewise methods; later, on top of `load` / `write`.
- Changing what `check`, `red`, `freeze` and `record` verify against the tree, or the PIP's content.
- Changing the on-disk file name or format: `<id>_<Title>_ActionPlan.json`, indented JSON.
- Making `prAttributes` path patterns (`docs/PR_REVIEWS/...`) configurable; they carry over unchanged.

## Anti-goals (failure even if tests pass)

- A frozen plan on disk reports "changed after freeze" because load and dump dropped a key, added a default,
  rewrote a value (a date, `pr: 1.0`) or reformatted an enum. The digest of a loaded-and-dumped plan equals the
  digest of its raw JSON.
- Two sources of truth again: a hand-edited schema, or an enum repeated as a literal in the plan modules.
- A silent drop: no model in `plan_models` uses pydantic's default `extra="ignore"`.
- The generated schema and the models disagreeing: the hook (JSON schema) accepting what `plan.py` (models)
  rejects, or the reverse, on a plan the hand schema judged.

## Constraints

- Python 3.11; `Optional[X]` / `Union[X, Y]`; functions under 50 lines; pydantic is an allowed dependency.
- Plugins stay generic; data goes to the project; `plugin_root()` is read-only.
- Library code reads `active()` inside functions. `todo_sync` stays stdlib-only and keeps reading raw dicts.
- `plan.py` and `plan_api` import pydantic: each reports a missing pydantic as `pr_review.py:137-162` does.
- No new config key is expected.

## Approaches considered

1. **Models generate the schema; runtime stays dict-based.** Small diff. Rejected: agents would still hand-edit
   JSON, which is what is to be removed.
2. **Full model-first (chosen).** Agents build objects; every consumer reads attributes; one validator.
3. **Models validate at the `plan.py` boundary only.** Two validators that can disagree. Rejected.

## Decisions (the developer's)

- Whole-plan `write` after `load` + `model_copy`; piecewise `add_*` later.
- The models are the truth. The schema hook and any consumer outside `plan.py` keep validating against a schema
  JSON, honouring a project's pinned copy as today. `plan.py` validates through the models. Cheap drift tests
  keep the committed schema and the models in agreement.
- Draft 2020-12; `PrAttributes` is a model.
- Retiring `prAttributes.schema.json`: no stub file. The hook reports a pinned schema whose `$ref` cannot be
  resolved (an error naming the schema and the reference) instead of exiting 0 as a setup error. The
  `plan.py check` break for a project that pinned a looser `prAttributes` is accepted and noted in the
  `schemas/README.md` migration note.

## Calls made by the author (awaiting the developer's read)

Model shape
- **Extras.** `ActionPlan`, `ActionItem`, `Context`, `Frozen`, `DeferredTopic` and `PrAttributes` use
  `extra="allow"` (the hand schema never sets `additionalProperties: false` there). `Anchor`, `Command`,
  `PlannedTest`, `Decision`, `DecisionOption`, `Value`, `PlanFormat` and `Sweep` use `extra="forbid"`. A test
  asserts every model in the module is one of the two.
- **Required stays required.** A field the hand schema requires has no default in the model (`status`,
  `evidence`, `title`, `action`, `id`, `plan_id`, `plan_created`, `execution_model`, `items`, ...). A field that
  is optional but not nullable in the hand schema is a plain typed field with a default that is not `None`
  (`model`, `files`, `anchors`); a nullable one is `Optional[...]`, so the generated schema emits `anyOf`
  with `null` only where the hand schema allowed it.
- **Dates are `str`.** The hand schema's `format: date` is annotation only (no format checker runs), so typing
  fields `date` would reject plans that load today and rewrite values. Date fields are `str` with
  `json_schema_extra={"format": "date"}`.
- **`pr` is `Union[StrictInt, StrictStr]`.** Lax coercion would turn `true` or `1.0` into `1`.
- **Regex engine.** Every model sets `regex_engine="python-re"`, so patterns behave like jsonschema's
  `re.search` (a `$` before a trailing newline).
- **Enums are `StrEnum`**, not `str, Enum`: on 3.11 `str()` and f-strings of a `(str, Enum)` member print
  `Status.COMPLETE`, which breaks `red` matching and the PIP. The issue text said `str, Enum`.
- **Priority** gets its own enum (it is a plan field, not `review_models.Severity`, which coerces letters).

Dump and mutation
- **Dump policy.** A field is written when it was set or when its value differs from its default
  (`plan_api.dump_plan`, then `model_dump(mode="json")`). `exclude_unset` alone drops an in-place append to a
  list that was never set. File bytes are not preserved: key order follows the declaration order, extras follow
  the declared keys. The digest is unaffected (`frozen_digest` sorts keys).
- **Reopen.** `record` removes `completed` on reopen (`model_fields_set.discard`), as `plan.pop` does today.
- **Mutation.** Models are not frozen; drivers mutate a loaded copy and save. `model_copy` is shallow, so the
  skill says `deep=True`.

Behavior
- **Every command validates.** `render`, `red`, `lanes` and `record` now refuse an invalid plan with the
  `schema:` lines; today only `check` and `freeze` do. This is a behavior change, stated in the migration note.
  Repair path for a plan that fails to load: the one sanctioned hand edit, followed by `plan.py check`.
- **Error lines.** `schema:` problems keep `<json path>: <message>`. The path joins pydantic's `loc` with `/`
  after dropping union-member tags; errors sharing a path become one line with their messages joined by
  `"; "`, truncated at 200 characters (a union field would otherwise print two lines per defect).
  Constructors in a heredoc raise pydantic's `ValidationError` with a path relative to the model being built;
  `write` reports full paths.
- **Pinned schema in `plan.py`.** `plan.py` ignores a pinned `ActionPlan.schema.json`; the hook uses it. No
  "differs" warning: every pin made before this change is draft-07, so it would fire forever.
- **Generation.** The drift test compares parsed JSON (not bytes: Windows checkouts use CRLF). `tools/gen_plan_schema.py`
  is a repo-only tool, never a plugin driver. A test names it so `tools/select_tests.py` selects it.
  `requirements-dev.txt` bounds pydantic to the minor series the schema was generated with.
- **`todo_sync`** imports only `plan_enums` and keeps reading raw dicts; the two open-status sets stay distinct.
- **Skill and docs.** `skills/write-plan/SKILL.md` step 3 becomes the heredoc, states that plan JSON is never
  hand-edited (status changes only through `record`), and gains a "Common mistakes" section (hand-editing,
  setting a status by hand, guessing a `red` exception, copying a SHA instead of `{base}`, `model_copy` without
  `deep=True`). `schemas/README.md` steps 2-3 and the plan and `prAttributes` sections, `PLANS_PIP_Template.md`
  and the schema README's dialect note are updated; the README states the schema is generated by
  `tools/gen_plan_schema.py`. `HARNESS_RULES.md:72-75` covers plans no plan-writing skill owns and stays.
- **Hand-editing is a rule, not a guard.** A "file equals its model dump" guard was rejected: the dump
  includes defaults, so existing plans would gain keys and frozen digests would shift. Detectors stay: the
  hook on file writes (it does not see a `plan_api` write: that path validates itself), strict validation in
  every command, the digest after freeze.
- **Release.** Bump the harness plugin version (0.41.1 to 0.42.0); there is no changelog file, so the migration
  note lives in `schemas/README.md`.
- **Tests build plans through model constructors.** The issue's "tests pass unchanged apart from imports"
  becomes "apart from imports and the plan-building helpers". Tests that need an invalid plan validate a raw
  dict. Ids and values the hand schema rejects (`A`, `GHOST`, `model=None`) are rewritten to valid ones.

## Verification

Run by file, never by directory. The first three guard the migration and are written before the models.

- `tests/fixtures/plan_models/`: the pre-migration hand schema pair (`ActionPlan.draft07.schema.json`,
  `prAttributes.draft07.schema.json`), plus plan documents covering every shape (extras at top, item, context,
  frozen, deferred and pr_attributes level; an explicit null for every nullable field; `pr` as int and string;
  dates in odd forms), each with a digest computed by today's `plan_doc.frozen_digest`, and a golden PIP
  rendered by today's `render_pip`.
- `tests/lib/test_plan_models_differential.py`: a corpus of valid and invalid plan documents gets the same
  accept or reject from the pre-migration schema (jsonschema), the generated schema (jsonschema) and the models.
- `tests/lib/test_plan_models.py`: enum and extras policy; every model's `extra` is allow or forbid; digest of
  load-then-dump equals the fixture digest; golden PIP equals `render_pip` of the loaded plan; error lines keep
  the form, one line per defect incl. a union field; `MUTABLE_TOP` / `MUTABLE_ITEM` derive from metadata.
- `tests/lib/test_plan_api.py`: load/write round trip; each refusal of the `write` contract, with nothing
  written; an in-place list append survives; reopen drops `completed`.
- `tests/contract/test_plan_schema_generated.py`: committed schema equals `schema_text()` (parsed JSON);
  `prAttributes.schema.json` is gone; the plan modules (`plan_doc`, `plan_checks`, `plan_render`, `plan_lanes`,
  `plan_red`, `scripts/plan.py`, `todo_sync/rules_plans.py`) hold no quoted status or model literal.
- Migrated: `tests/lib/test_plan_doc.py`, `test_plan_checks.py`, `test_plan_checks_cycles.py`,
  `test_plan_lanes.py`, `test_plan_red.py`, `test_plan_render.py`, `test_todo_sync_rules_plans.py`,
  `tests/scripts/test_plan_driver.py`, `tests/schemas/test_agent_schemas.py`,
  `tests/schemas/test_validation_helpers.py`, `tests/schemas/test_schema_meta_valid.py`,
  `tests/hooks/test_hooks_schema_validation.py` (incl. the unresolvable-`$ref` report), and the skill-guidance
  tests that read `write-plan`.
- `tests/scripts/test_plan_missing_pydantic.py` (modelled on `test_pr_review_missing_pydantic.py`).
- `tests/contract/test_root_separation.py`: `CASES` gains `plan.py new` and a `plan_api.write` run;
  `tests/contract/test_no_repo_literals.py` stays green.

## Left to the builder

- Module layout inside `plan_models` and `plan_api`; enum member names that are not strings in the code today
  (the JSON values are fixed: `PENDING`, `IN_PROGRESS`, `COMPLETE`, `CLOSED_NO_ACTION`, `BLOCKED`; `haiku`,
  `sonnet`, `opus`; `critical`, `important`, `minor`; the five `red` exceptions).
- Flags of `tools/gen_plan_schema.py` beyond `--check`; the exact pydantic bound in `requirements-dev.txt`.
- Order of migration across the consumers and tests; how `plan_red`, `plan_lanes` and `plan_render` type
  their parameters.
