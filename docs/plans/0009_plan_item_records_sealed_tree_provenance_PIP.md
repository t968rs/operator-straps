# Plan 0009: plan item records sealed tree provenance

> Rendered by `plan.py render` from `0009_plan_item_records_sealed_tree_provenance_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-05
**Spec:** `docs/superpowers/specs/2026-11-05-plan-record-seal-design.md`
**Branch:** 1132-git-tree-plans -> main
**Base commit:** `84cc5bc`
**Frozen:** 2026-11-06 at `84cc5bc`
**Execution model:** parallel2: TASK-1 main session first; plan.py lanes 0009 minus task-1 and task-7 as waves 1-2; TASK-7 main session last

## Decisions

- **D1** What does check prove about an item a record call moved? Chosen: `seal-provenance-verify` (A seal proves record wrote it; tree and commit are provenance only; plan.py verify reruns tests on demand). Rejected: `tree-blobs` (Compare the item's files at HEAD with the recorded tree's blobs (issue proposal)), `commit-or-tree-search` (Keep the commit, fall back to any reachable commit with the recorded tree). Developer, 2026-11-05 design conversation; tree-blobs reports false drift on shared files (0006 shares 52).
- **D2** Which plans still accept the pre-seal record shapes? Chosen: `frozen-marker` (Only plans whose frozen.records is unset (frozen by the old driver); freeze sets SEALED once no legacy item remains). Rejected: `every-plan` (Accept the legacy shape on every plan), `none` (Accept none; old plans must be re-recorded). Spec section Legacy items, approved by the developer 2026-11-05.
- **D3** Does record keep the dependency gate, and what counts as a done dependency? Chosen: `valid-record` (Keep it; a dependency counts only when DONE with a record that passes record_problems). Rejected: `status-only` (Keep it; status DONE alone counts), `drop` (Drop the gate). Spec section Driver changes, approved by the developer 2026-11-05.
- **D4** What does freeze --refreeze do with seal problems? Chosen: `tolerate-seal` (Tolerate seal mismatches on items with a record, print re-record after refreeze lines; a missing record still refuses). Rejected: `refuse` (Refuse every record problem). Spec section Driver changes; refuse deadlocks a refreeze that edits a COMPLETE item's tests.
- **D5** Does record --sha still require the commit to be reachable from HEAD? Chosen: `no-ancestry` (No; the working tree must still match the commit for the item's files). Rejected: `keep-ancestry` (Yes, at record time only). Spec section Driver changes: a staged lane's commit is unreachable from the target, and the working-tree match keeps the record honest.
- **D6** What gate does plan.py lanes use once record is digest-only? Chosen: `valid` (Frozen, digest and record_problems clean (require_valid); lanes writes nothing, so a refusal cannot deadlock). Rejected: `digest-only` (The same digest-only gate as record (spec text)). Review S2, 2026-11-06: digest-only lets a hand-set status drop an item from lanes and dispatch its dependents. Session call, stated to the developer.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| seal | sha256 hex, 64 characters, of canonical JSON (sort_keys, separators (',', ':'), ensure_ascii False) | plugins/harness/lib/harness_lib/plan_doc.py:163 | - |
| legacy COMPLETE references | refs[0] 40 hex, refs[1] 'tree <40 hex>' | plugins/harness/scripts/plan.py:431 | frozen-marker |
| harness plugin version | 0.58.0 -> 0.59.0 | plugins/harness/.claude-plugin/plugin.json:3 | - |
| seal limit | a hand copy of an item's own earlier record passes the seal; accepted like a recomputed hash | review C2, 2026-11-06 | - |
| record scheme in the digest | frozen_digest folds records in only when set; old digests unchanged | review S1, 2026-11-06 | frozen-marker |

## Formats

- **commit record evidence**: `commit abc1234: 1 test node(s) passed`, copied from `plugins/harness/scripts/plan.py:430`
- **legacy verification references**: `["<sha40>", "tree <sha40>", "python -m pytest -q <nodes>"]`, copied from `plugins/harness/scripts/plan.py:431`

## Sweeps

- **S1** `def (completion_problems|record_shape_problem)|require_frozen\(`: `docs/TODO/RepoToDo.json` (TODO prose of issue #225; no code), `plugins/harness/scripts/plan.py` (TASK-3 removes the two functions; require_frozen stays, digest only)
- **S2** `(\.|")verification_references`: `docs/TODO/RepoToDo.json` (TODO prose; no code), `plugins/harness/lib/harness_lib/plan_render.py` (TASK-4: legacy references still render), `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py` (TASK-5: P2 keeps the hex search for legacy items), `plugins/harness/schemas/ActionPlan.schema.json` (TASK-2 regenerates; the property stays), `plugins/harness/schemas/PLANS_PIP_Template.md` (TASK-6 describes the record beside it), `plugins/harness/scripts/plan.py` (TASK-3: record stops writing it, stamp clears it), `tests/fixtures/agent_schemas/0001_sample_ActionPlan.json` (legacy fixture; unchanged), `tests/fixtures/plan_models/0002_Full_ActionPlan.json` (legacy fixture; unchanged), `tests/fixtures/plan_models/0003_Inflight_ActionPlan.json` (legacy fixture; unchanged), `tests/fixtures/plan_models/ActionPlan.draft07.schema.json` (old schema fixture; unchanged), `tests/lib/test_plan_models.py` (TASK-2 adds record to the mutable set), `tests/lib/test_todo_sync_rules_plans.py` (legacy P2 tests; unchanged), `tests/schemas/test_agent_schemas.py` (schema property still present; unchanged), `tests/scripts/test_plan_driver.py` (TASK-3 reads the record instead)

## Tasks

### TASK-1: Strap edit spec for write-plan: mechanical behaviors and parts

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `docs/plans/strap/write-plan/SkillSpec.json`, `docs/plans/strap/write-plan/tests/`

Wave 0, main session (spec writes are serial), before any lane: the parallel2 plan is `plan.py lanes 0009` with task-1 and task-7 dropped, since both run in the main session. The spec is open (`strap.py new write-plan --edit`, base 84cc5bc). Copy every planned test file of this plan from docs/plans/0009/tests/<repo path> to docs/plans/strap/write-plan/tests/<repo path>. Through the strap api heredoc add mechanical behaviors, each with this plan's nodes as new_test(node, red): B1 record seals every status it writes and check refuses a hand-set status, a hand edit and a copied record (test_plan_record_models.py and test_plan_record.py seal nodes, test_plan_record_driver.py::test_check_flags_a_hand_set_status ::test_check_flags_a_hand_edit_of_the_evidence, ::test_lanes_refuses_a_hand_set_status and ::test_deleting_the_record_scheme_by_hand_is_a_plan_change); B2 the record keeps the tested tree and the commit when there was one, and check compares neither with HEAD (driver nodes record_sha_writes, amend, squash, staged_attach, unreachable commit; the render nodes); B3 record --staged records the index, runs the tests on an index snapshot no ref keeps and refuses unstaged item files (driver staged nodes and refuses_both); B4 record never refuses because of a broken seal, records a COMPLETE item again and counts a dependency only with a valid record (driver nodes records_again, broken_seal, hand_set_complete_dependency, legacy_dependency_unlocks); B5 freeze --refreeze tolerates a broken seal on a recorded item and names it, and still refuses a status without a record (driver refreeze nodes); B6 plan.py verify reruns the COMPLETE items' tests at HEAD and writes nothing (driver verify nodes); B7 legacy shapes pass only on a plan frozen without a record scheme (test_plan_record.py legacy nodes, driver legacy nodes, the todo_sync P2 node); B8 SKILL.md states what a record proves (test_write_plan_record_contract.py nodes). add_part: driver plugins/harness/scripts/plan.py; models plugins/harness/lib/harness_lib/plan_models.py; reference plugins/harness/lib/harness_lib/plan_enums.py, plugins/harness/lib/harness_lib/plan_doc.py, plugins/harness/lib/harness_lib/plan_record.py and plugins/harness/lib/harness_lib/plan_render.py; contract_test tests/skills/test_write_plan_record_contract.py (when add_part refuses a kind for a path, use reference). Then strap check and strap red until clean.

- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" check write-plan`: check [ok]
- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" red write-plan`: red [ok]
- [ ] Record the commit: `plan.py record 0009 TASK-1 --sha <sha>`

**Evidence:** not started

### TASK-2: Record models and the plan_record rules

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/plan_enums.py`, `plugins/harness/lib/harness_lib/plan_models.py`, `plugins/harness/lib/harness_lib/plan_doc.py`, `plugins/harness/lib/harness_lib/plan_record.py`, `plugins/harness/schemas/ActionPlan.schema.json`, `tests/contract/test_plan_schema_generated.py`, `tests/lib/test_plan_models.py`, `tests/lib/test_plan_record_models.py`, `tests/lib/test_plan_record.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_models.py:142-148` holds `class Frozen(BaseModel): model_config = _OPEN commit: str = Field(pattern=_SHA40)`
- `plugins/harness/lib/harness_lib/plan_models.py:176-178` holds `verification_references: Annotated[List[str], Mutable()] = Field(default_factory=list)`
- `plugins/harness/lib/harness_lib/plan_models.py:253` holds `def mutable_item() -> Tuple[str, ...]:`
- `plugins/harness/lib/harness_lib/plan_enums.py:56` holds `DONE: FrozenSet[ItemStatus] = frozenset({ItemStatus.COMPLETE, ItemStatus.CLOSED_NO_ACTION})`
- `plugins/harness/lib/harness_lib/plan_api.py:114` holds `changed = [key for key in pd.MUTABLE_ITEM if before is not None`
- `plugins/harness/lib/harness_lib/plan_doc.py:163` holds `canonical = json.dumps(fixed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
- `tests/lib/test_plan_models.py:59` holds `assert set(pm.mutable_item()) == {"status", "evidence", "verification_references"}`
- `plugins/harness/lib/harness_lib/plan_doc.py:159` holds `def frozen_digest(plan: pm.ActionPlan) -> str:`
- `plugins/harness/lib/harness_lib/plan_models.py:220-221` holds `the commit and tree the plan was frozen at and a digest of every field`
- `tests/contract/test_plan_schema_generated.py:16-25` holds `"plugins/harness/lib/harness_lib/todo_sync/rules_plans.py", )`

Wave 1, parallel2 implement lane task-2. Copy tests/lib/test_plan_record_models.py and tests/lib/test_plan_record.py from the plan first. plan_enums.py: RecordSource(StrEnum) commit, staged; OutcomeKind(StrEnum) complete, started, blocked, closed; RecordScheme(StrEnum) sealed. plan_models.py, each new class closed (_CLOSED) with a docstring: Provenance(source: RecordSource, tree: 40 hex, commit: Optional 40 hex = None) with a model_validator: the commit is required for source commit and forbidden for source staged. PassedTests(nodes: List[NonEmpty] with min_length 1, command: NonEmpty); no class name starts with Test, since pytest would try to collect it from a test module that imports it. One class per outcome, each with kind: Literal[OutcomeKind.<member>], status: ClassVar[ItemStatus] and evidence(date) -> str: Completed(provenance, tests: Optional[PassedTests] = None) is COMPLETE with evidence 'commit <c7>: <n> test node(s) passed', 'commit <c7>', 'staged tree <t7>: <n> test node(s) passed' or 'staged tree <t7>'; Started is IN_PROGRESS with 'started <date>'; Blocked(reason: NonEmpty) is BLOCKED with the reason; Closed(rationale: NonEmpty) is CLOSED_NO_ACTION with the rationale. Outcome = Annotated[Union[Completed, Started, Blocked, Closed], Field(discriminator='kind')]. The sealed payload is its own closed model, SealedFields(plan_id, id, status, evidence, files, tests: List[PlannedTest], outcome: Outcome, date), with the classmethod of(plan_id, item, outcome, date) and digest() -> str: the sha256 hex of json.dumps(self.model_dump(mode='json', exclude_defaults=True), sort_keys=True, ensure_ascii=False, separators=(',', ':')). exclude_defaults keeps the seal stable when a later release adds a defaulted field to PlannedTest, Provenance, PassedTests or an outcome, and it drops None and absent alike, so a record loaded from disk reseals the same; kind has no default and stays in. ItemRecord(outcome: Outcome, date: _DATE, seal: 64 hex) with the classmethod sealed(plan_id, item, outcome, date) and holds(plan_id, item) -> bool (SealedFields.of(...).digest() equals the seal and item.status equals outcome.status). ActionItem gains record: Annotated[Optional[ItemRecord], Mutable()] = None after verification_references; Frozen gains records: Optional[RecordScheme] = None. The frozen field description names the item record among the digest exclusions and says a set records scheme is folded into the digest; Provenance.tree gets a description (the tree the tests ran on). plan_doc.py: frozen_digest(plan, records: Optional[RecordScheme] = None) adds 'records': records.value to the hashed fields only when records is set, so every existing digest is unchanged and deleting a stored scheme by hand is a plan change (review S1). New module harness_lib/plan_record.py (no git, no argparse): RecordProblemKind(StrEnum) missing, seal; RecordProblem (a frozen pydantic model: plan_id, item, status, kind) whose __str__ is '<ID> is <STATUS> without a sealed record; run plan.py record <plan_id> <ID>' (missing) or '<ID> record does not match its seal (status, evidence, files, tests or the record changed by hand); run plan.py record <plan_id> <ID> again' (seal); legacy_allowed(plan): frozen and frozen.records is None; legacy_shape(item): COMPLETE with refs[0] 40 hex and refs[1] 'tree <40 hex>', any other non-PENDING status with non-empty evidence; record_problems(plan) -> List[RecordProblem] over every item with a record or a non-PENDING status; an item that carries a record is judged by ItemRecord.holds alone, and legacy_shape applies only when record is None (review S4); record_holds(plan, item) -> bool is (record is not None and record.holds(plan_id, item)) or (record is None and legacy_allowed(plan) and legacy_shape(item)), so a legacy COMPLETE upstream unlocks its dependents on a legacy plan such as 0002 (review T2); scheme_for(plan) -> Optional[RecordScheme]: sealed unless a non-PENDING item lacks a record; stamp(plan, item, outcome, date) sets status, evidence, verification_references = [] and record = ItemRecord.sealed(...), in that order. Known limit, accepted like a recomputed hash: copying an item's own earlier record back by hand passes the seal (review C2). tests/lib/test_plan_models.py: the mutable_item set gains 'record'. tests/contract/test_plan_schema_generated.py: PLAN_MODULES gains plugins/harness/lib/harness_lib/plan_record.py (review D8). Regenerate the schema with tools/gen_plan_schema.py.

- [ ] Test `tests/lib/test_plan_record_models.py::test_a_commit_provenance_needs_its_commit` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_a_staged_provenance_carries_no_commit` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_provenance_rejects_a_short_tree` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_each_outcome_names_the_status_it_implies` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_kind_selects_the_outcome_class` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_a_blocked_or_closed_outcome_needs_its_text` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_passed_tests_need_a_node` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_evidence_names_the_commit_or_the_staged_tree` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_a_sealed_record_holds_for_its_item` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_every_outcome_seals` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_seal_breaks_when_a_covered_field_changes` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_seal_binds_the_plan_id` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_seal_ignores_fields_outside_the_record` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_sealed_fields_are_a_model_whose_digest_is_the_seal` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_a_record_reseals_after_a_round_trip_through_the_plan_file` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_a_defaulted_field_added_later_keeps_the_seal` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_record_is_a_mutable_item_field` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_frozen_carries_the_record_scheme` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_record_models_are_closed` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record_models.py::test_the_generated_schema_names_the_record_models` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_stamped_item_has_no_record_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_pending_plan_has_no_record_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_hand_set_status_is_a_missing_record` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_hand_edit_after_the_stamp_is_a_seal_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_record_copied_to_another_item_is_a_seal_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_record_left_on_a_pending_item_is_a_seal_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_legacy_shapes_pass_only_without_a_record_scheme` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_legacy_complete_item_needs_both_references` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_an_unfrozen_plan_accepts_no_legacy_shape` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_the_scheme_is_sealed_once_no_legacy_item_remains` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_stamp_clears_the_legacy_references` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_dependency_counts_only_with_a_valid_record` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_a_legacy_dependency_counts_only_on_a_legacy_plan` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_on_a_legacy_plan_an_item_with_a_record_is_judged_by_its_seal` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_record.py::test_the_freeze_digest_folds_in_only_a_set_record_scheme` fails with ImportError, then passes
- [ ] Run `python tools/gen_plan_schema.py`: the schema file rewritten from the models
- [ ] Run `python -m pytest tests/lib/test_plan_record_models.py tests/lib/test_plan_record.py tests/lib/test_plan_models.py tests/lib/test_plan_models_differential.py tests/lib/test_plan_doc.py tests/lib/test_plan_api.py tests/contract/test_plan_schema_generated.py tests/schemas/test_agent_schemas.py -q`: passed, 0 failed
- [ ] Record the commit: `plan.py record 0009 TASK-2 --sha <sha>`

**Evidence:** not started

### TASK-3: Driver: sealed records, record --staged, verify, refreeze tolerance

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-2
**Files:** `plugins/harness/scripts/plan.py`, `tests/scripts/test_plan_driver.py`, `tests/scripts/test_plan_record_driver.py`

**Anchors:**
- `plugins/harness/scripts/plan.py:183` holds `if frozen is None or frozen.digest == pd.frozen_digest(plan):`
- `plugins/harness/scripts/plan.py:474` holds `require_frozen(repo, plan)`
- `plugins/harness/scripts/plan.py:190-197` holds `def record_shape_problem(repo: Path, item: pm.ActionItem) -> Optional[str]:`
- `plugins/harness/scripts/plan.py:200-208` holds `def completion_problems(repo: Path, plan: pm.ActionPlan) -> List[str]:`
- `plugins/harness/scripts/plan.py:220-225` holds `+ completion_problems(repo, plan))`
- `plugins/harness/scripts/plan.py:324` holds `problems = [p for p in all_problems(repo, plan) if not (refreeze and p.startswith("plan changed after"))]`
- `plugins/harness/scripts/plan.py:342` holds `plan.frozen = pm.Frozen(commit=head, tree=tree, date=today(), digest=pd.frozen_digest(plan))`
- `plugins/harness/scripts/plan.py:353` holds `problems = digest_problems(plan) + completion_problems(repo, plan)`
- `plugins/harness/scripts/plan.py:361-363` holds `status = pd.item_by_id(plan, dep).status if status not in DONE:`
- `plugins/harness/scripts/plan.py:377-378` holds `raise pd.PlanError([f"commit {full[:7]} is not reachable from HEAD"])`
- `plugins/harness/scripts/plan.py:382` holds `def commit_problems(repo: Path, plan: pm.ActionPlan, item: pm.ActionItem, sha: str) -> List[str]:`
- `plugins/harness/scripts/plan.py:400` holds `tree = pr.make_tree(repo, sha, active().resolve_worktree_root())`
- `plugins/harness/scripts/plan.py:431` holds `item.verification_references = [sha, f"tree {tree}", *command]`
- `plugins/harness/scripts/plan.py:458` holds `item.status = apply_record(repo, plan, item, args)`
- `plugins/harness/scripts/plan.py:488` holds `mode = record.add_mutually_exclusive_group(required=True)`
- `plugins/harness/scripts/plan.py:519` holds `"lanes": cmd_lanes, "record": cmd_record,`
- `plugins/harness/scripts/parallel2.py:81` holds `"GIT_AUTHOR_NAME": "parallel2", "GIT_AUTHOR_EMAIL": "parallel2@localhost",`
- `plugins/harness/scripts/parallel2.py:329` holds `done = subprocess.run(["git", "commit-tree", tree, "-p", head, "-m", message], cwd=repo,`
- `tests/scripts/test_plan_driver.py:309` holds `"problem: TASK-1 is COMPLETE without the record of record --sha" in err`
- `tests/scripts/test_plan_driver.py:339` holds `item["verification_references"][0] == sha`
- `tests/scripts/test_plan_driver.py:374` holds `def test_record_refuses_a_commit_unreachable_from_head(run: Run, filled: Fill, project: Path) -> None:`

Wave 2, parallel2 implement lane task-3, after TASK-2 is staged. Copy tests/scripts/test_plan_record_driver.py from the plan first. (a) Delete record_shape_problem and completion_problems; all_problems appends str(p) for each plan_record.record_problems(plan). (b) require_frozen keeps the not-frozen refusal and digest_problems only, for record; digest_problems compares frozen.digest with pd.frozen_digest(plan, plan.frozen.records). A new require_valid adds record_problems for cmd_lanes, which writes nothing and so cannot deadlock (D6). (c) dependency_problems: a dependency counts when its status is DONE and record_holds is True; otherwise '<ID> depends on <DEP>, which is <STATUS>', with ' without a valid record; run plan.py record <plan_id> <DEP>' appended when the status is DONE. (d) resolve_commit drops the ancestry check (D5). (e) commit_problems works on a revision: the base diff runs against the commit or the index tree; the working-tree rule compares the item paths with the commit (--sha, message unchanged) or with the index (--staged: git diff --name-only -- <paths> plus untracked paths, message '<ID> files differ from the index in the working tree: <paths>; stage them and record again'). (f) --staged: the tree is git write-tree; the tests run on a throwaway worktree at a dangling git commit-tree <tree> -p HEAD made with a fixed identity (the parallel2 SNAPSHOT_IDENTITY pattern, own names), and no ref is written; a failure reads '<ID> tests failed at the index (tree <t7>): <tail>'. (g) apply_record returns an Outcome (Completed with Provenance and PassedTests, Started, Blocked, Closed); cmd_record calls plan_record.stamp(plan, item, outcome, today()); the completed logic stays. (h) _record_parser: --staged joins the mutually exclusive group. (i) freeze: on --refreeze, record problems of kind seal are tolerated (missing ones still refuse); cmd_freeze prints 're-record after refreeze: <ID>' per tolerated item after the done line. The scheme never drops: when the loaded frozen.records is SEALED, or frozen.digest equals pd.frozen_digest(plan, SEALED) (the key was deleted by hand), the refreeze judges record problems as sealed and stamps SEALED; otherwise it stamps scheme_for(plan). The new digest is pd.frozen_digest(plan, records), and Frozen gets records only when it is set, so no null key is written. (j) New subcommand verify PLAN [--staged], read-only: one throwaway worktree at HEAD (or at the index snapshot), one pytest run per COMPLETE item with tests, dropped in a finally. It prints '<ID> pass' and '<ID> no tests' lines to stdout for every item, then either 'verify [ok] | plan <id> | <n> item(s) pass at HEAD <h7>' (or 'at the index (tree <t7>)') or raises PlanError lines '<ID> tests fail at <where>: <tail>; fix the code, then run plan.py record <plan_id> <ID> again'. (k) The module docstring describes check, record (--staged), freeze (the record scheme) and verify as built, and digest_problems' message and the freeze paragraph name the item record among the execution fields. Every function stays under 50 lines. (l) tests/scripts/test_plan_driver.py: test_check_flags_a_hand_set_complete_item expects 'problem: TASK-1 is COMPLETE without a sealed record'; test_record_runs_the_tests_and_completes_the_item reads item['record']['outcome']['provenance']['commit'] == sha instead of verification_references; delete test_record_refuses_a_commit_unreachable_from_head (D5; the record driver test covers the new rule). (m) The finished plans keep passing the record rules: the legacy-plans command loads every docs/plans/000[1-8]_*_ActionPlan.json (both 0002 files, by path) and expects record_problems empty for each (check itself can fail on those plans for reasons outside this plan).

- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_sha_writes_a_sealed_record_with_tree_and_commit` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_check_flags_a_hand_set_status` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_check_flags_a_hand_edit_of_the_evidence` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_lanes_refuses_a_hand_set_status` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_an_amend_of_the_recorded_commit_keeps_check_green` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_squash_of_two_recorded_commits_keeps_check_green` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_record_made_in_a_worktree_survives_a_staged_attach` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_sha_accepts_a_commit_unreachable_from_head` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_staged_records_the_index_and_survives_the_commit` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_staged_refuses_unstaged_item_files` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_staged_runs_the_tests_on_the_index` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_refuses_both_a_sha_and_staged` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_complete_item_records_again` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_record_runs_while_another_item_has_a_broken_seal` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_hand_set_complete_dependency_unlocks_nothing` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_legacy_dependency_unlocks_its_dependent_on_a_legacy_plan` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_refreeze_that_changes_an_item_breaks_only_its_seal` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_refreeze_refuses_a_status_without_a_record` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_verify_passes_and_writes_nothing` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_verify_staged_runs_the_tests_on_the_index` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_verify_reports_every_item_and_check_stays_green` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_legacy_plan_passes_check_without_git` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_sealed_plan_refuses_a_pasted_legacy_shape` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_deleting_the_record_scheme_by_hand_is_a_plan_change` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_record_driver.py::test_a_refreeze_seals_the_scheme_once_no_legacy_item_remains` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/scripts/test_plan_record_driver.py tests/scripts/test_plan_driver.py tests/scripts/test_plan_missing_pydantic.py tests/lib/test_plan_record.py -q`: passed, 0 failed
- [ ] Run `PYTHONPATH=plugins/harness/lib python -c "import glob, pathlib; from harness_lib import plan_doc, plan_record; print([str(p) for f in sorted(glob.glob('docs/plans/000[1-8]_*_ActionPlan.json')) for p in plan_record.record_problems(plan_doc.load_plan(pathlib.Path(f)))])"`: []
- [ ] Record the commit: `plan.py record 0009 TASK-3 --sha <sha>`

**Evidence:** not started

### TASK-4: PIP renders the record

**Status:** PENDING | **Model:** sonnet | **Depends on:** TASK-2
**Files:** `plugins/harness/lib/harness_lib/plan_render.py`, `tests/lib/test_plan_render_record.py`, `tests/fixtures/plan_models/0001_Minimal_PIP.md`, `tests/fixtures/plan_models/0002_Full_PIP.md`, `tests/fixtures/plan_models/0003_Inflight_PIP.md`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_render.py:107` holds `record = f"plan.py record {plan.plan_id} {item.id} --sha <sha>"`
- `plugins/harness/lib/harness_lib/plan_render.py:125` holds `refs = item.verification_references`

Wave 2, parallel2 implement lane task-4. Copy tests/lib/test_plan_render_record.py from the plan first. _boxes: the record step reads 'Record it: `plan.py record <plan_id> <ID> --sha <sha>` or `--staged`'; rewrite the six record-box lines of the three golden fixture PIPs to that text (review T1: tests/lib/test_plan_models.py compares render_pip with them byte for byte). _item: with item.record, one line '**Recorded:** <date>, commit `<c7>`, tree `<t7>`' (commit provenance), '**Recorded:** <date>, staged, tree `<t7>`' (staged) or '**Recorded:** <date>, <kind>' (any other outcome), then '- `<command>`' when the outcome carries passed tests; without a record the legacy verification_references render as today. Update the module docstring's box sentence.

- [ ] Test `tests/lib/test_plan_render_record.py::test_a_commit_record_renders_its_commit_tree_and_command` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_record.py::test_a_staged_record_renders_the_index_tree` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_record.py::test_the_record_box_names_both_ways_to_record` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_record.py::test_legacy_references_still_render` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/lib/test_plan_render_record.py tests/lib/test_plan_render.py tests/lib/test_plan_models.py -q`: passed, 0 failed
- [ ] Record the commit: `plan.py record 0009 TASK-4 --sha <sha>`

**Evidence:** not started

### TASK-5: todo_sync P2 reads a sealed COMPLETE record

**Status:** PENDING | **Model:** sonnet | **Depends on:** TASK-2
**Files:** `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py`, `tests/lib/test_todo_sync_rules_plans_record.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:74` holds `def _names_sha(item: Dict[str, Any]) -> bool:`
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:87` holds `if item.get("status") == ItemStatus.COMPLETE and not _names_sha(item):`

Wave 2, parallel2 implement lane task-5. Copy tests/lib/test_todo_sync_rules_plans_record.py from the plan first. rules_plans.py stays free of pydantic (todo_sync imports only the standard library and plan_enums), so it probes the record's JSON shape rather than validating ItemRecord: _complete_record(item) is True when item['record'] is a dict with a 64-hex seal and a date string, whose outcome kind equals OutcomeKind.complete (imported from plan_enums, not spelled again), whose provenance source is a RecordSource value and whose provenance tree is a 40-hex string (review C3). p2_evidence_sha passes an item when _names_sha or _complete_record holds. Update both docstrings and the finding's fix text to name the record. The unlisted nodes test_p2_still_flags_a_record_that_is_not_complete and test_p2_flags_a_complete_record_missing_its_seal pass before and after: they guard that only a whole COMPLETE record counts.

- [ ] Test `tests/lib/test_todo_sync_rules_plans_record.py::test_p2_accepts_a_complete_record_without_a_sha_in_the_evidence` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/lib/test_todo_sync_rules_plans_record.py tests/lib/test_todo_sync_rules_plans.py -q`: passed, 0 failed
- [ ] Record the commit: `plan.py record 0009 TASK-5 --sha <sha>`

**Evidence:** not started

### TASK-6: write-plan SKILL.md and schema docs describe the sealed record

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/skills/write-plan/SKILL.md`, `plugins/harness/schemas/README.md`, `plugins/harness/schemas/PLANS_PIP_Template.md`, `plugins/harness/rules/HARNESS_RULES.md`, `README.md`, `tests/skills/test_write_plan_record_contract.py`

**Anchors:**
- `plugins/harness/skills/write-plan/SKILL.md:18` holds `marked COMPLETE only when they pass on a throwaway worktree at a commit that changed its files`
- `plugins/harness/skills/write-plan/SKILL.md:81` holds `` any COMPLETE item without the commit and tree `record` writes. ``
- `plugins/harness/skills/write-plan/SKILL.md:96-97` holds `` so `record` waits until the developer commits the staged work ``
- `plugins/harness/schemas/README.md:252` holds `` `status: COMPLETE` always carries commit SHA(s) in `evidence` or `verification_references` (todo_sync rule P2) ``
- `plugins/harness/schemas/PLANS_PIP_Template.md:107` holds `` #### Verification references (mirror `items[].verification_references`) ``
- `plugins/harness/schemas/PLANS_PIP_Template.md:199` holds `` `plan.py record {PLAN_ID} <ITEM> --sha <commit>` (COMPLETE) or `--closed "<rationale>"` ``
- `plugins/harness/schemas/README.md:217` holds `plan.py record <id> <ITEM> --sha <commit>`
- `plugins/harness/rules/HARNESS_RULES.md:78` holds `` **Status is never a claim:** `COMPLETE` requires a commit SHA; ``
- `README.md:26` holds `` `record` reruns the item's tests on a throwaway worktree at the commit ``

Wave 1, parallel2 implement lane task-6; the interface is fixed by this plan and the spec. Copy tests/skills/test_write_plan_record_contract.py from the plan first. SKILL.md: restate the opening claim (lines 17-19): an item with tests is marked COMPLETE only when they pass on a throwaway worktree at the recorded commit or index tree, and every status record writes is sealed. Step 8: the Mutable fields add the item record; replace 'any COMPLETE item without the commit and tree `record` writes' with 'any status without a sealed record (a hand-set status, a hand edit, a record copied from another item)'; state that --refreeze tolerates a broken seal on a recorded item and prints 're-record after refreeze: <ITEM>'. After step 8 add the paragraph of the spec section 'write-plan SKILL.md text' as a plain paragraph, without its '>' quote markers (review T4), and end it with: 'Restoring an item's own earlier record by hand is not caught: the seal is a keyless hash, not a signature.' (review C2). Step 9: staged lane work is recorded with `PLAN record <id> <ITEM> --staged` once it is in the index, or with `--sha` after the developer commits it; the --sha requirements drop 'reachable from HEAD' (D5) and the dependency requirement reads 'its dependencies done with valid records'; `PLAN lanes <id>` also refuses a plan with a record problem. schemas/README.md: lines 252-254 say COMPLETE carries a sealed record (or, on a plan frozen before the record scheme, a SHA in evidence or verification_references) and that verification_references is the legacy proof list; the Step 3 block (lines 213-221) lists record --sha, --staged and --closed, verify, and 'COMPLETE <- a sealed record of the tested tree, and the commit when there was one'. PLANS_PIP_Template.md: beside the verification references section, the '**Recorded:**' line the PIP renders from items[].record; line 199 names --staged beside --sha. HARNESS_RULES.md line 78: 'COMPLETE requires a commit SHA or a sealed record of the tested tree'. README.md line 26, write-plan row: record runs the tests at the commit or the index, seals each status, and check refuses a status without a sealed record; verify reruns the COMPLETE items' tests at HEAD (review F5).

- [ ] Test `tests/skills/test_write_plan_record_contract.py::test_the_skill_says_what_a_record_proves` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_record_contract.py::test_the_skill_names_verify_for_the_work_still_being_there` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_record_contract.py::test_the_skill_records_staged_lane_work` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_record_contract.py::test_a_broken_seal_is_repaired_by_record` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_record_contract.py::test_the_commit_ancestry_rule_is_gone` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/skills/test_write_plan_record_contract.py tests/skills/test_write_plan_skill_models.py tests/lib/test_strap_lint.py tests/skills/test_skill_guidance_tail_contract.py tests/schemas/test_agent_schemas.py tests/hooks/test_session_rules.py -q`: passed, 0 failed
- [ ] Record the commit: `plan.py record 0009 TASK-6 --sha <sha>`

**Evidence:** not started

### TASK-7: Version bump, strap freeze, lint and selected tests

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-1, TASK-3, TASK-4, TASK-5, TASK-6
**Files:** `plugins/harness/.claude-plugin/plugin.json`, `docs/plans/strap/write-plan/SkillSpec.json`

**Anchors:**
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.58.0",`

Wave 3, main session, after P2 stage of every lane and P2 cleanup. Bump plugins/harness plugin.json 0.58.0 to 0.59.0. strap check, then strap freeze write-plan (mechanical only: every planned node passes on the staged content). ruff with --no-cache over every changed .py file. select_tests diffs commits only and the work sits in the index (review D2): snapshot it with git commit-tree $(git write-tree) -p HEAD -m snapshot, run python tools/select_tests.py --base main --head <snapshot>, require a non-empty selection and run each selected file by name. Hand off: the changed-file list, the frozen hash and a merge recommendation. Plan 0009 is recorded with this checkout's driver, sh plugins/harness/scripts/hpy plugins/harness/scripts/plan.py, for every item (review C1: a published 0.58.0 driver has no --staged and refuses a plan holding sealed records): record --staged before the developer commits, or --sha of that commit after it.

- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" freeze write-plan`: freeze [done]
- [ ] Run `python -m ruff check --no-cache plugins/harness/scripts/plan.py plugins/harness/lib/harness_lib/plan_models.py plugins/harness/lib/harness_lib/plan_enums.py plugins/harness/lib/harness_lib/plan_record.py plugins/harness/lib/harness_lib/plan_render.py plugins/harness/lib/harness_lib/todo_sync/rules_plans.py tests/lib/test_plan_record_models.py tests/lib/test_plan_record.py tests/lib/test_plan_render_record.py plugins/harness/lib/harness_lib/plan_doc.py tests/lib/test_plan_models.py tests/scripts/test_plan_driver.py tests/contract/test_plan_schema_generated.py tests/lib/test_todo_sync_rules_plans_record.py tests/scripts/test_plan_record_driver.py tests/skills/test_write_plan_record_contract.py`: All checks passed!
- [ ] Run `python tools/select_tests.py --base main --head <snapshot of the index>`: a non-empty selection, each listed file then run by name
- [ ] Record the commit: `plan.py record 0009 TASK-7 --sha <sha>`

**Evidence:** not started
