# Plan 1013: plan receipts

> Rendered by `plan.py render` from `1013_plan_receipts_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-10
**Spec:** `docs/superpowers/specs/2026-11-10-plan-receipts-design.md`
**Branch:** 2150-plan-refreeze -> main
**Base commit:** `5a8ef39`
**Frozen:** no
**Execution model:** parallel

## Decisions

- **D1** How does `record` pair a deviation (`--also`, `--substitute`) with its `--cite`? Chosen: `order` (each --cite binds every uncited --also/--substitute given before it). Rejected: `single` (one --cite for the whole record), `inline` (PATH=ID inside the flag value). Keeps the spec's `--also PATH --cite ID` syntax and lets one record cite two entries; a deviation with no --cite after it is refused, naming the path or node.
- **D2** Which status does the status view take from a receipt whose seal is broken? Chosen: `receipt` (the receipt's status; check, verify and the gates still refuse the seal). Rejected: `pending` (PENDING, as if the receipt were absent). verify and the dependency gate then name the broken record and its repair instead of silently treating the item as open, the behavior a sealed plan has today.
- **D3** How do the sealed and legacy schemes stay proven once a first freeze stores receipts? Chosen: `fixture` (existing driver suites run with plan_record.FIRST_SCHEME patched to sealed). Rejected: `legacy-file` (a new tests/scripts/test_plan_receipts_legacy.py (the spec's name)). The spec's legacy file would pass before the work, so it cannot be planned red; the existing suites (test_plan_driver.py, test_plan_record_driver.py, test_plan_api.py) already pin every sealed and legacy behavior and stay green, assertions unchanged, under an autouse fixture.
- **D4** Does the todo-watch mod change? Chosen: `mod-unchanged` (no change). Rejected: `watch-receipts` (watch receipts and DesignEvolution). isWatchedPath already matches every path under the plans folder (plugins/todo-watch/hooks/checks.ts:188-198), and no P rule reads receipts or the DesignEvolution, so a write of either has nothing to recheck. Spec deviation.
- **D5** Does todo_sync rule P2 change? Chosen: `p2-unchanged` (no change). Rejected: `accept-receipt` (P2 accepts a sealed COMPLETE receipt). A receipts plan's JSON statuses stay PENDING for good, so P2 never meets a COMPLETE item there; a hand-set COMPLETE is a digest problem for check. Spec deviation.
- **D6** Which PIP does a plan that was never frozen render? Chosen: `receipts-bound` (HTML only when its first freeze stores receipts (scheme_for); a first receipts freeze moves a `_PIP.md` documentation to the page). Rejected: `html` (the HTML page; markdown only for plans frozen sealed or legacy), `at-new` (decided at `new`: a plan whose documentation names `_PIP.md` stays sealed), `markdown` (markdown until the first freeze). Developer's choice after review. Nine never-frozen plans (0001-0008) carry COMPLETE items and can never be first-frozen, so they keep markdown; plan 1012 (unfrozen, all PENDING, documentation `_PIP.md`) gets the page at its first freeze, which repoints documentation before the digest and deletes the superseded `_PIP.md`. Keying the format on `plan_record.scheme_for` keeps the D3 fixture's legacy suites on markdown end to end.
- **D7** Where do the DesignEvolution enums live? Chosen: `evolution_enums` (a new standard-library module, like plan_enums). Rejected: `plan_enums` (beside the plan enums). Keeps plan_enums to plan vocabularies; StrEnum members with snake-case names (IssueCategory.spec_coverage), values unchanged from the old schema.
- **D8** Does a receipt bind the text of each DesignChange it cites? Chosen: `bind` (Deviations.change_digests holds the sha256 of each cited change; the seal covers it and check compares it with the catalog). Rejected: `loose` (existence and names-the-item checks only). Developer's choice after review: editing a cited change after its receipt asks for a new record, so the trail from receipt to change cannot drift silently.
- **D9** How is `live.js` kept out of git? Chosen: `folder-ignore` (write_live keeps `<plans>/<id>/.gitignore` listing live.js). Rejected: `readme` (the README tells each project to add an ignore line). Project rule: a setting a driver can act on belongs in the driver, not in prose a project must follow. One tracked line beside the receipts; no root `.gitignore` entry. Spec deviation.
- **D10** How do plan.py commands read the record rules of two schemes? Chosen: `record-book` (plan_receipts.book_for(plans_dir, plan) returns one RecordBook (holds, status, nodes, problems, view) per command). Rejected: `branches` (the status view plus a scheme branch at each record-rule call site). One branch point in plan.py instead of six; a missed call site cannot report a receipts item as 'COMPLETE without a sealed record'. The view stays for plan_lanes and plan_red, which take a plan.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| live.js reload interval | 3000 ms (plan_render_html.RELOAD_MS) | spec 'PIP HTML': every few seconds; builder's call | - |
| harness version | 0.65.4 -> 0.66.0 | plugins/harness/.claude-plugin/plugin.json:3; minor bump per spec 'Other consumers' | - |
| suggested release | v0.8.0 | gh release list: latest v0.7.0; a plugin minor bump since; v0.7.1.md is still proposed, so DOC-1 measures from the latest tag when it runs | - |
| change id pattern | ^(S\|PR\|P\|EX\|CX)[0-9]+$ | spec 'Models': the 1-2 digit cap of the old schema is lifted | - |

## Sweeps

- **S1** `DesignEvolution`: `plugins/harness/config/defaults.json` (commit grouping: the file name stays Planning; unchanged), `plugins/harness/rules/HARNESS_RULES.md` (DOC-1 replaces the catalog line), `plugins/harness/schemas/catalogs/DesignEvolutionCatalog.schema.json` (SCH-1 regenerates it from the models), `plugins/harness/skills/branch-commit-msg/SKILL.md` (commit grouping by file name; unchanged), `plugins/harness/skills/branch-commit-msg/txt_format.md` (commit grouping by file name; unchanged), `tests/fixtures/pr1558_issues.json` (historic review fixture; unchanged), `tests/lib/_commit_helpers.py` (commit grouping fixture; unchanged), `tests/lib/test_branch_commits.py` (commit grouping test; unchanged), `tests/lib/test_commit_grouping.py` (commit grouping test; unchanged)
- **S2** `PIP_SUFFIX|pip_path\(`: `plugins/harness/lib/harness_lib/plan_api.py` (DRV-1 routes write through plan_render_html.write_pip), `plugins/harness/lib/harness_lib/plan_doc.py` (HTML-1 adds PIP_HTML_SUFFIX and pip_html_path beside them), `plugins/harness/lib/harness_lib/todo_sync/sources.py` (TDS-1 pairs _PIP.html prefixes too), `plugins/harness/scripts/plan.py` (DRV-1 routes write_pip and new through plan_render_html), `tests/lib/test_plan_doc.py` (markdown path test; unchanged)
- **S3** `record_holds|recorded_nodes|scheme_for|open_items\(`: `docs/PR_REVIEWS/0229_Refactorplan_record_add_tests_and_update_documentation_for.json` (historic review; unchanged), `plugins/harness/lib/harness_lib/plan_lanes.py` (open_items reads the plan it is given: plan.py passes the view), `plugins/harness/lib/harness_lib/plan_record.py` (DRV-1 scheme_for returns FIRST_SCHEME on a first freeze), `plugins/harness/lib/harness_lib/plan_red.py` (open_items reads the plan it is given: plan.py passes the view), `plugins/harness/scripts/plan.py` (DRV-1/DRV-2 read status through the receipts view on a receipts plan), `tests/lib/test_plan_record.py` (sealed and legacy unit tests; unchanged), `tests/lib/test_plan_record_models.py` (sealed record model tests; unchanged), `tests/lib/test_plan_red.py` (red unit tests; unchanged), `tests/scripts/test_plan_driver.py` (DRV-1 runs it under the sealed first-freeze fixture)

## Tasks

### EVO-1: DesignEvolution models, enums and catalog file IO

**Status:** PENDING | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/evolution_enums.py`, `plugins/harness/lib/harness_lib/evolution_models.py`, `plugins/harness/lib/harness_lib/evolution_doc.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_doc.py:81-89` holds `def schema_lines(exc: ValidationError) -> List[str]:`
- `plugins/harness/lib/harness_lib/plan_models.py:37-38` holds `_CLOSED = ConfigDict(extra="forbid", regex_engine="python-re")`

Add `harness_lib/evolution_enums.py` (StrEnum, standard library only, D7): `ChangePhase` (spec_review, pr_bot_review, plan_review, post_exec_start), `IssueCategory` (the twelve values of the old schema, in its order) and `OutcomeCategory` (the nine). Add `harness_lib/evolution_models.py`, every model a closed pydantic BaseModel (`extra="forbid"`, regex_engine python-re): `ChangeOriginal(doc, location, indicated)`, `ChangeIssue(category, why_categorical, why_free_form)`, `NewOutcome(doc, indicated)`, `WhyNewOutcome(category, free_form)`, `DesignChange(id ^(S|PR|P|EX|CX)[0-9]+$, discovered_by, phase, items=[], original, issue, new_outcome, why_new_outcome, date default today)` with `digest()` (sha256 of its canonical JSON: sort_keys, compact separators; D8), `FindingRef(id, rationale)`, `EvolutionSummary(highest_impact_finding?, most_embarrassing_finding?, lessons=[])`, `IdConventions(comment?, prefixes={})`, `EvolutionCounts(by_phase, by_issue, by_outcome)` and `DesignEvolution(plan_id ^[0-9]{4}$, feature, issue?, pr?, branch_lineage, primary_documents, id_conventions?, changes=[], summary?)` with an after-validator refusing duplicate change ids, a doc key outside primary_documents, a primary_documents without `plan`, and a summary finding id that names no change (each message names the id or key); `counts()` (value strings as keys), `find(id)`, `schema_dict()` and `schema_text()` with `$id` `.../schemas/catalogs/DesignEvolutionCatalog.schema.json`. Add `harness_lib/evolution_doc.py`: `catalog_path(plans_dir, plan_id)` = `<plans>/<id>/DesignEvolution.json`, `load_evolution(path)` (None when absent; a `PlanError` of `schema:` lines, via `plan_doc.schema_lines`, when invalid), `dump_evolution`, `save_evolution` and `plan_problems(evo, plan)` (a plan_id that is not the plan's; each change item that is no plan item, naming the change id and the item).

- [ ] Test `tests/lib/test_evolution_models.py::test_the_enums_carry_the_old_schema_values` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_every_nested_shape_parses_to_its_own_class` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_every_model_is_closed` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_an_unknown_issue_category_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_change_id_takes_a_known_prefix_and_any_number` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_change_id_without_a_known_prefix_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_change_date_defaults_to_today` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_duplicate_change_ids_are_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_doc_key_outside_the_primary_documents_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_the_plan_is_always_a_primary_document` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_summary_finding_must_name_a_change` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_catalog_needs_a_plan_id` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_pr_and_summary_are_optional` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_id_conventions_is_a_class_with_a_prefix_map` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_counts_tally_phase_issue_and_outcome` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_change_is_found_by_id` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_a_change_digest_follows_its_text` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_models.py::test_the_generated_evolution_schema_has_no_category_enums` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_doc.py::test_the_catalog_lives_in_the_plan_folder_and_round_trips` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_doc.py::test_a_catalog_that_does_not_validate_is_a_schema_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_doc.py::test_a_catalog_names_only_items_of_its_plan` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_doc.py::test_a_catalog_of_another_plan_is_a_problem` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1013 EVO-1 --sha <sha>` or `--staged`

**Evidence:** not started

### RCP-1: Receipt models, the receipts record scheme and the regenerated ActionPlan schema

**Status:** PENDING | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/receipt_models.py`, `plugins/harness/lib/harness_lib/plan_enums.py`, `plugins/harness/lib/harness_lib/plan_models.py`, `plugins/harness/schemas/ActionPlan.schema.json`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_enums.py:72-75` holds `sealed = "sealed"`
- `plugins/harness/lib/harness_lib/plan_models.py:174` holds `pip_document: Optional[str] = Field(default=None, pattern=r"^docs/PLANS/.+_PIP\.md$")`
- `plugins/harness/lib/harness_lib/plan_models.py:300` holds `Outcome = Annotated[Union[Completed, Started, Blocked, Closed], Field(discriminator="kind")]`
- `plugins/harness/lib/harness_lib/plan_models.py:323-327` holds `def digest(self) -> str:`
- `tools/gen_plan_schema.py:46` holds `SCHEMA.write_text(pm.schema_text(), encoding="utf-8", newline="\n")`

Add `harness_lib/receipt_models.py`: closed models `ExtraFile(path, change)`, `TestSubstitution(planned, node, change)` (both nodes use the `PlannedTest.node` pattern; `__test__: ClassVar[bool] = False` so pytest never collects it), `Deviations(extra_files=[], substitutions=[], change_digests={})` with a `cited` property (change ids in first-seen order) and a validator that the keys of `change_digests` are exactly the cited ids (D8; the message names a missing or stray id), and `Receipt(plan_id, item, outcome: Outcome, evidence, deviations=Deviations(), ref: Optional[str]=None, date, seal)`. `Receipt.sealed(plan_id, item, *, outcome, date, deviations=None, ref=None)` sets evidence from `outcome.evidence(date)` and the seal: sha256 of canonical JSON (sort_keys, compact separators, exclude_defaults) of the receipt without `seal` plus the item's planned `files` and `tests`. `holds(plan_id, item)` recomputes it; `status` is `outcome.status`; `nodes(item)` is the item's planned nodes with each substitution applied, in plan order. Reuse `Outcome`, `Provenance` and `PassedTests` from plan_models unchanged. `schema_dict()`/`schema_text()` with `$id` `.../schemas/Receipt.schema.json`. In plan_enums add `RecordScheme.receipts = "receipts"`. In plan_models widen `PrAttributes.pip_document` to `^docs/PLANS/.+_PIP\.(md|html)$`. Regenerate `ActionPlan.schema.json` with today's generator in the same change, so the schema contract test holds on every commit.

- [ ] Test `tests/lib/test_receipt_models.py::test_the_record_scheme_has_receipts` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_a_pip_document_may_be_html` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_a_sealed_receipt_holds_for_its_item` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_every_outcome_seals` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_seal_breaks_when_a_receipt_field_changes` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_seal_breaks_when_the_items_planned_files_change` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_seal_breaks_when_the_items_planned_tests_change` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_seal_binds_the_plan_and_the_item` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_seal_ignores_item_fields_outside_files_and_tests` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_deviations_and_ref_are_sealed_and_kept` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_nodes_of_a_receipt_apply_its_substitutions` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_a_receipt_round_trips_through_json` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_the_receipt_models_are_closed` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_a_substitution_names_a_pytest_node` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_pytest_does_not_collect_the_substitution_model` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_deviations_bind_the_digest_of_each_cited_change` fails with ImportError, then passes
- [ ] Test `tests/lib/test_receipt_models.py::test_deviations_refuse_a_citation_without_its_digest` fails with ImportError, then passes
- [ ] Run `python tools/gen_plan_schema.py`: wrote plugins/harness/schemas/ActionPlan.schema.json
- [ ] Run `python -m pytest tests/contract/test_plan_schema_generated.py -q`: all pass
- [ ] Record it: `plan.py record 1013 RCP-1 --sha <sha>` or `--staged`

**Evidence:** not started

### SCH-1: Generate the three plan schemas

**Status:** PENDING | **Model:** haiku | **Depends on:** EVO-1, RCP-1
**Files:** `tools/gen_plan_schema.py`, `plugins/harness/schemas/catalogs/DesignEvolutionCatalog.schema.json`, `plugins/harness/schemas/Receipt.schema.json`

**Anchors:**
- `tools/gen_plan_schema.py:21-23` holds `SCHEMA = ROOT / "plugins" / "harness" / "schemas" / "ActionPlan.schema.json"`

Extend `tools/gen_plan_schema.py` to a table of (path, schema_dict) for `ActionPlan.schema.json` (plan_models), `catalogs/DesignEvolutionCatalog.schema.json` (evolution_models) and `Receipt.schema.json` (receipt_models); without an option it writes all three, with `--check` it prints `ok: <name> matches the models` per file and exits 1 on any drift. Run it to regenerate the two new files (ActionPlan.schema.json is already current from RCP-1).

- [ ] Test `tests/contract/test_evolution_receipt_schema_generated.py::test_the_committed_evolution_schema_equals_the_generated_one` fails with ImportError, then passes
- [ ] Test `tests/contract/test_evolution_receipt_schema_generated.py::test_the_committed_receipt_schema_equals_the_generated_one` fails with ImportError, then passes
- [ ] Test `tests/contract/test_evolution_receipt_schema_generated.py::test_the_generator_checks_all_three_schemas` fails with ImportError, then passes
- [ ] Run `python tools/gen_plan_schema.py`: wrote each of the three schema files
- [ ] Run `python -m pytest tests/contract/test_plan_schema_generated.py -q`: all pass
- [ ] Record it: `plan.py record 1013 SCH-1 --sha <sha>` or `--staged`

**Evidence:** not started

### RCP-2: Receipt files, the record book, the status view and live.js

**Status:** PENDING | **Model:** opus | **Depends on:** EVO-1, RCP-1
**Files:** `plugins/harness/lib/harness_lib/plan_receipts.py`, `plugins/harness/lib/harness_lib/plan_live.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_record.py:33-41` holds `def record_command(plan_id: str, item_id: str, status: Optional[ItemStatus] = None,`
- `plugins/harness/lib/harness_lib/plan_record.py:90-99` holds `def record_holds(plan: ActionPlan, item: ActionItem) -> bool:`
- `plugins/harness/lib/harness_lib/plan_record.py:117-119` holds `def recorded_nodes(item: ActionItem) -> List[str]:`

Add `harness_lib/plan_receipts.py` (no git): `receipts_dir(plans_dir, plan_id)` = `<plans>/<id>/receipts`, `receipt_path`, `write_receipt(plans_dir, receipt) -> Path`, a closed pydantic `ReceiptSet(receipts: Dict[str, Receipt], problems: List[str])` and `load_receipts(plans_dir, plan_id)` keyed by file stem (a file that does not parse or validate, or whose `item` differs from its stem, is a problem naming the file); `uses_receipts(plan)` (frozen with records == receipts); `status_view(plan, receipts)`: a deep copy whose items take status and evidence from their receipt (D2: also from a receipt whose seal is broken) and are PENDING without one, the plan itself untouched; `receipt_holds(plan, receipts, item_id)`; `citation_problems(evolution, item_id, deviations)` (a cited id missing from the catalog, a catalog entry whose `items` lacks the item, or a stored change digest that differs from the entry's `digest()` (D8: `<ITEM> cites <ID>, which changed after its receipt; run plan.py record ... again`), each line naming the id and the item; any citation without a catalog); `receipt_problems(plan, receipts, evolution)`: the load problems, a receipt for no plan item, a broken seal (`<ITEM> receipt does not match its seal ...; run plan.py record <id> <ITEM> again (...)`, reusing `plan_record.record_command`) and the citation problems; `split_substitution(value)`: PLANNED and NODE split at the first `=` whose remainder matches `^[^:=\[\]]+\.py::`, None when there is none. Record book (D10): `book_for(plans_dir, plan)` returns a `ReceiptBook` on a receipts plan (receipts and catalog loaded once) or a `SealedBook` over plan_record's rules otherwise; both give `holds(item_id)`, `status(item_id)`, `nodes(item_id)` (receipt nodes, or `plan_record.recorded_nodes`), `problems()` (receipt_problems, or record_lines) and `view()` (the status view, or the plan itself). Add `harness_lib/plan_live.py`: a closed `PlanLive(receipts: List[Receipt], evolution: Optional[DesignEvolution], built: str)` (receipts sorted by item id; built is the UTC write time), `live_path(plans_dir, plan_id)` = `<plans>/<id>/live.js`, and `write_live(plans_dir, plan_id) -> Path` writing `window.PLAN_LIVE = <PlanLive JSON>;` plus a newline and keeping `<plans>/<id>/.gitignore` listing `live.js` once, other lines kept (D9).

- [ ] Test `tests/lib/test_plan_receipts.py::test_a_receipt_lands_under_the_plan_folder_and_loads_back` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_no_receipts_folder_is_no_receipts` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_receipt_that_does_not_parse_is_a_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_only_a_receipts_plan_uses_receipts` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_the_status_view_reads_receipts_and_leaves_the_plan_alone` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_sound_receipt_has_no_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_hand_edited_receipt_breaks_its_seal` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_receipt_copied_to_another_item_breaks_its_seal` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_receipt_for_no_item_is_a_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_citation_needs_a_catalog_entry` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_citation_needs_an_entry_that_names_the_item` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_citation_without_a_catalog_is_a_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_matching_citation_passes` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_status_set_in_the_plan_without_a_receipt_reads_pending` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_cited_change_edited_after_the_receipt_is_a_problem` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_the_book_of_a_receipts_plan_reads_receipts` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_the_book_of_a_sealed_plan_reads_the_plan_and_ignores_receipts` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_receipts.py::test_a_substitution_splits_where_the_replacement_node_begins` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_live.py::test_live_js_lands_in_the_plan_folder` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_live.py::test_live_js_carries_the_receipts_by_item_id_and_the_evolution` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_live.py::test_live_js_without_receipts_or_catalog_is_empty` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_live.py::test_the_live_payload_is_a_closed_model` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_live.py::test_the_plan_folder_ignores_live_js` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1013 RCP-2 --sha <sha>` or `--staged`

**Evidence:** not started

### HTML-1: The HTML PIP page

**Status:** PENDING | **Model:** opus | **Depends on:** RCP-1
**Files:** `plugins/harness/lib/harness_lib/plan_render_html.py`, `plugins/harness/lib/harness_lib/plan_doc.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_doc.py:23-24` holds `PIP_SUFFIX = "_PIP.md"`
- `plugins/harness/lib/harness_lib/plan_doc.py:58-62` holds `def pip_path(plan_file: Path) -> Path:`
- `plugins/harness/lib/harness_lib/plan_record.py:102-105` holds `def scheme_for(plan: ActionPlan) -> Optional[RecordScheme]:`
- `plugins/harness/lib/harness_lib/plan_render.py:101-103` holds `return run.replace("{base}", plan.base_commit) if plan.base_commit else run`
- `plugins/harness/lib/harness_lib/plan_render.py:148-154` holds `def render_pip(plan: ActionPlan, plan_name: str) -> str:`

Add `harness_lib/plan_render_html.py`: `RELOAD_MS = 3000`; `uses_html(plan)`: frozen plans by `records == receipts`, a never-frozen plan when `plan_record.scheme_for(plan)` (read through the module, so a test may swap it) is `RecordScheme.receipts` (D6); `render_pip_html(plan, plan_name)`: one self-contained page (inline CSS and JS, no network address), every plan text HTML-escaped, the header, decisions, values, formats, sweeps and each item (action, files, anchors, tests, commands with `{base}` expanded as in plan_render), plus a script that adds `<script src="<id>/live.js?t=<ms>">` and re-adds it every RELOAD_MS with a fresh `t`, redrawing only each item's status, receipt (provenance, nodes, extra files and substitutions with citations), the DesignEvolution entries linked from the items they name, and `PLAN_LIVE.built` beside the line 'after a pull, run plan.py render <id>'; with no PLAN_LIVE the page shows every item PENDING and names `plan.py render <id>`. In plan_doc add `PIP_HTML_SUFFIX = "_PIP.html"` and `pip_html_path(plan_file)`. Manual check after DRV-2: open a receipts PIP in the developer's browser from disk, run `record`, see the status change.

- [ ] Test `tests/lib/test_plan_render_html.py::test_the_page_is_self_contained` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_the_page_loads_its_sidecar_and_reloads_it` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_the_page_renders_every_item_and_decision` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_plan_text_is_escaped` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_a_command_shows_the_full_base_commit` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_without_the_sidecar_the_page_names_the_render_command` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_the_page_says_how_to_refresh_a_stale_sidecar` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_the_format_follows_the_record_scheme` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_a_never_frozen_plan_renders_html_only_when_bound_for_receipts` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_a_never_frozen_plan_with_a_status_stays_markdown` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1013 HTML-1 --sha <sha>` or `--staged`

**Evidence:** not started

### EVO-2: evolution_api: the agent's write path into DesignEvolution

**Status:** PENDING | **Model:** sonnet | **Depends on:** EVO-1, RCP-2
**Files:** `plugins/harness/lib/harness_lib/evolution_api.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/plan_api.py:43-56` holds `def _plan_file(ref: PlanRef) -> Path:`

Add `harness_lib/evolution_api.py` in the style of plan_api (missing-pydantic guard; each entry point activates the project named by `repo`): `load(plan, repo=None)` returns the plan's catalog, or a fresh one built from the plan without writing it (plan_id; feature from the plan file's title part with underscores as spaces; primary_documents `plan` = the repo-relative plan file and `spec` = source_document when set; branch_lineage `<base_branch>-->` + branch, `none` for a missing side); `next_id(plan, prefix="EX", repo=None)`: the prefix plus one more than the highest number in use, writing nothing; `add(plan, change, repo=None)` refuses a duplicate id, and through `evolution_doc.plan_problems` an unknown item, writing nothing; `write(evolution, repo=None)` validates the whole catalog (model rules plus plan_problems) and saves it. Every write rebuilds `live.js` (`plan_live.write_live`); neither touches the plan JSON or its PIP. Refusals are `PlanError` lists.

- [ ] Test `tests/lib/test_evolution_api.py::test_the_first_add_creates_the_catalog_from_the_plan` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_add_appends_and_load_reads_back` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_load_without_a_catalog_returns_a_fresh_one_and_writes_nothing` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_add_refuses_a_duplicate_id` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_add_refuses_an_unknown_item_and_writes_nothing` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_add_rebuilds_live_js` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_add_leaves_the_plan_file_alone` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_write_validates_the_whole_catalog` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_an_unknown_plan_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_evolution_api.py::test_next_id_returns_the_next_free_number_and_writes_nothing` fails with ImportError, then passes
- [ ] Record it: `plan.py record 1013 EVO-2 --sha <sha>` or `--staged`

**Evidence:** not started

### DRV-1: plan.py: receipts scheme at freeze, strict digest, HTML PIP, check, red and freeze by book

**Status:** PENDING | **Model:** opus | **Depends on:** HTML-1, RCP-2
**Files:** `plugins/harness/scripts/plan.py`, `plugins/harness/lib/harness_lib/plan_record.py`, `plugins/harness/lib/harness_lib/plan_doc.py`, `plugins/harness/lib/harness_lib/plan_api.py`, `plugins/harness/lib/harness_lib/plan_render_html.py`, `tests/scripts/_plan_driver_helpers.py`, `tests/scripts/test_plan_driver.py`, `tests/scripts/test_plan_record_driver.py`, `tests/lib/test_plan_api.py`

**Anchors:**
- `plugins/harness/scripts/plan.py:152-155` holds `target = pd.pip_path(plan_file)`
- `plugins/harness/scripts/plan.py:188` holds `raw = skeleton(plan_id, spec, base, base_commit, current_branch(repo), rel(repo, pd.pip_path(plan_file)))`
- `plugins/harness/scripts/plan.py:204-211` holds `if frozen is None or frozen.digest == pd.frozen_digest(plan, frozen.records):`
- `plugins/harness/scripts/plan.py:220` holds `return (plan.base_commit or None) if any(i.status in DONE for i in plan.items) else None`
- `plugins/harness/scripts/plan.py:230-232` holds `return claim_problems(repo, plan) + digest_problems(plan) + prc.record_lines(plan)`
- `plugins/harness/scripts/plan.py:281-283` holds `results, problems = red_problems(repo, plan)`
- `plugins/harness/scripts/plan.py:324-328` holds `found = [(p, refreeze and p.kind == RecordProblemKind.seal) for p in prc.record_problems(plan)]`
- `plugins/harness/scripts/plan.py:366-374` holds `def stays_sealed(`
- `plugins/harness/scripts/plan.py:389` holds `plan.frozen = new_frozen(repo, plan, prc.scheme_for(plan))`
- `plugins/harness/lib/harness_lib/plan_record.py:102-105` holds `return None if legacy else RecordScheme.sealed`
- `plugins/harness/lib/harness_lib/plan_record.py:108-114` holds `def keeps_sealed(plan: ActionPlan) -> bool:`
- `plugins/harness/lib/harness_lib/plan_doc.py:168-171` holds `hashed = fixed if records is None else {"plan": fixed, "records": records.value}`
- `plugins/harness/lib/harness_lib/plan_api.py:147-149` holds `pip_text = render_pip(checked, path.name)`
- `tests/scripts/_plan_driver_helpers.py:43-49` holds `def project(make_project, tmp_path: Path) -> Path:`
- `tests/lib/test_plan_api.py:42-43` holds `def _bytes(path: Path) -> Dict[str, bytes]:`

plan_record: `FIRST_SCHEME = RecordScheme.receipts`; `scheme_for` returns FIRST_SCHEME for a plan never frozen with every item PENDING and no record; receipts when the plan stores them, when `frozen.digest == frozen_digest(plan, receipts)` (a hand deleted the scheme) or when the plan's copy at HEAD stores them, checked before the sealed rule; else today's rule. plan_doc `frozen_digest`: under receipts hash every field but `frozen` (no execution field). In plan_render_html add `write_pip(plan_file, plan) -> Path`: the HTML page when `uses_html`, plus `plan_live.write_live` only when `plan_receipts.uses_receipts(plan)`, else the markdown of `plan_render.render_pip`. plan.py: `new` names `pip_html_path` as `documentation` when `uses_html`; `render` on a frozen receipts plan rebuilds live.js and writes the page only when it is missing (freeze and --refreeze stay the writers of an existing page), and prints the path; a first freeze that stores receipts sets a `documentation` naming this plan's `_PIP.md` to the `_PIP.html` path before the digest and deletes that `_PIP.md`; `freeze` writes the page and live.js. On a receipts plan `check`, `red` and `freeze` read status through `plan_receipts.book_for` (D10): `check` adds the catalog's schema lines and `plan_problems` and the book's problems in place of `record_lines`, and claims_rev, unproven_items, started_items and red run on `book.view()`; the refreeze prints `re-record after refreeze: <ITEM>` for each receipt whose seal it broke, refuses other receipt problems, and saves the raw plan, never the view. plan_api.write renders through `write_pip`. Keep every function under 50 lines; put new logic in the library modules. Until DRV-2 lands, `record` on a receipts plan still stamps the JSON: no plan is frozen on this branch in that window (plan 1013 itself is sealed). Existing suites (D3): add a `sealed_first_freeze` fixture to `tests/scripts/_plan_driver_helpers.py` (monkeypatch `harness_lib.plan_record.FIRST_SCHEME` to sealed), autouse in `test_plan_driver.py` and `test_plan_record_driver.py`, and the same autouse fixture in `tests/lib/test_plan_api.py`; their assertions do not change, since a sealed first freeze keeps the markdown PIP (D6).

- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_new_writes_an_html_pip_and_names_it_as_documentation` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_a_first_freeze_stores_the_receipts_scheme_and_writes_live_js` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_check_passes_a_frozen_receipts_plan` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_check_flags_a_formerly_mutable_field_edited_after_freeze` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_check_flags_a_hand_set_status_as_a_plan_change` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_check_reports_a_receipt_that_does_not_parse` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_check_reports_a_design_evolution_that_does_not_validate` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_render_writes_the_html_pip_of_a_receipts_plan` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_render_leaves_a_frozen_page_alone_and_rebuilds_live_js` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_a_sealed_plan_still_renders_markdown` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_plan_api_write_renders_the_html_pip_of_an_unfrozen_plan` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_a_first_freeze_moves_a_markdown_pip_to_html` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_a_refreeze_of_a_receipts_plan_keeps_the_scheme` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_freeze.py::test_a_refreeze_keeps_receipts_when_the_scheme_is_deleted_by_hand` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_write_pip_writes_html_and_the_sidecar_for_a_receipts_plan` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_write_pip_writes_no_sidecar_for_a_plan_not_yet_frozen` fails with ImportError, then passes
- [ ] Test `tests/lib/test_plan_render_html.py::test_write_pip_keeps_markdown_for_a_sealed_plan` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/scripts/test_plan_driver.py tests/scripts/test_plan_record_driver.py tests/lib/test_plan_api.py tests/lib/test_plan_record.py -q`: all pass: the sealed and legacy schemes behave as before
- [ ] Record it: `plan.py record 1013 DRV-1 --sha <sha>` or `--staged`

**Evidence:** not started

### DRV-2: plan.py record writes receipts; deviations, citations and status reads

**Status:** PENDING | **Model:** opus | **Depends on:** DRV-1, EVO-2
**Files:** `plugins/harness/scripts/plan.py`, `plugins/harness/lib/harness_lib/plan_record.py`

**Anchors:**
- `plugins/harness/scripts/plan.py:415-426` holds `if done and prc.record_holds(plan, upstream):`
- `plugins/harness/scripts/plan.py:429-431` holds `return list(dict.fromkeys([*item.files, *nodes]))`
- `plugins/harness/scripts/plan.py:434-439` holds `done = git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")`
- `plugins/harness/scripts/plan.py:508-517` holds `nodes = [t.node for t in item.tests]`
- `plugins/harness/scripts/plan.py:537-548` holds `def apply_record(`
- `plugins/harness/scripts/plan.py:551-565` holds `prc.stamp(plan, item, apply_record(repo, plan, item, args), today())`
- `plugins/harness/scripts/plan.py:570-577` holds `print(json.dumps(plx.lanes_plan(plan, target), indent=2))`
- `plugins/harness/scripts/plan.py:594-601` holds `if not prc.record_holds(plan, item):`
- `plugins/harness/scripts/plan.py:604-606` holds `done = pr.run_pytest(pytest_argv(prc.recorded_nodes(item)), tree)`
- `plugins/harness/scripts/plan.py:614-616` holds `items = [i for i in plan.items if i.status == ItemStatus.COMPLETE]`
- `plugins/harness/scripts/plan.py:643-653` holds `mode = record.add_mutually_exclusive_group(required=True)`
- `plugins/harness/lib/harness_lib/plan_lanes.py:32-34` holds `return [item for item in plan.items if item.status in LANE_OPEN]`

On a receipts plan `record` builds the outcome by today's rules, then writes `<plans>/<id>/receipts/<ITEM>.json` (`Receipt.sealed`) and live.js and never saves the plan or its PIP; the `[done]` line lists open items from the book. New flags (repeatable, D1): `--also PATH`, `--substitute PLANNED=NODE` (split by `plan_receipts.split_substitution`), `--cite ID`, parsed in order into one list; each --cite binds every uncited deviation before it; a deviation left uncited is refused naming its path or node, `--cite` and the `evolution_api.add` call that records a change; PLANNED must be one of the item's planned nodes; every cited id goes through `citation_problems` against the plan's catalog, and the receipt stores each cited change's `digest()` (D8). The new flags need `--sha` or `--staged` and a receipts plan; otherwise they are refused with a `problem:` line naming the flag. Extra files and substituted node files join the item paths for the base-diff and clean-path rules; the test run uses the substituted nodes. `--sha` takes any revision: `resolve_commit` keeps the full SHA, and a revision that is not that SHA's prefix is stored as `ref`. The dependency gate, `lanes` (`plan_lanes.lanes_plan` on `book.view()`; `require_valid` on the book's problems), and `verify` (COMPLETE items of the view, nodes from `book.nodes`, a receipt whose seal is broken reported as unrecorded with its record command) read the book (D10).

- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_record_writes_the_receipt_and_live_js_and_nothing_of_the_plan` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_check_reads_the_claims_at_the_base_once_a_receipt_completes_an_item` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_check_flags_a_hand_edited_receipt` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_record_start_and_closed_write_receipts` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_record_also_with_a_valid_citation_passes` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_each_cite_binds_the_deviations_before_it` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_editing_a_cited_change_asks_for_a_new_record` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_the_deviation_flags_are_refused_on_a_sealed_plan` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_the_deviation_flags_need_sha_or_staged` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_an_extra_file_joins_the_clean_path_rule` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_deviation_without_a_cite_is_refused` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_citation_missing_from_the_catalog_is_refused` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_citation_that_does_not_list_the_item_is_refused` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_substituted_node_is_the_node_run_and_verified` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_dirty_substituted_test_file_refuses_the_record` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_substitute_must_replace_a_planned_node` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_record_sha_accepts_a_tag_and_keeps_it` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_the_dependency_gate_reads_receipts` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_lanes_lists_only_items_without_a_done_receipt` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_red_runs_only_the_items_without_a_done_receipt` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_verify_names_a_receipt_whose_seal_is_broken` fails with ImportError, then passes
- [ ] Test `tests/scripts/test_plan_receipts_record.py::test_a_refreeze_keeps_receipts_and_names_each_broken_seal` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/scripts/test_plan_driver.py tests/scripts/test_plan_record_driver.py -q`: all pass: sealed and legacy plans record into the plan JSON as before
- [ ] Record it: `plan.py record 1013 DRV-2 --sha <sha>` or `--staged`

**Evidence:** not started

### TDS-1: todo_sync plan rules on a receipts plan

**Status:** PENDING | **Model:** sonnet | **Depends on:** RCP-1
**Files:** `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py`, `plugins/harness/lib/harness_lib/todo_sync/sources.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:58-63` holds `def _p1_pair(src: Sources, pair: PlanPair, out: List[Finding], rule: str = "P1") -> List[Finding]:`
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:139-149` holds `def p4_sync_claim(src: Sources) -> List[Finding]:`
- `plugins/harness/lib/harness_lib/todo_sync/sources.py:21` holds `PIP_SUFFIX = "_PIP.md"`
- `plugins/harness/lib/harness_lib/todo_sync/sources.py:232` holds `prefixes = sorted({n[:-len(s)] for n in names for s in (PLAN_SUFFIX, PIP_SUFFIX) if n.endswith(s)})`
- `plugins/harness/lib/harness_lib/todo_sync/sources.py:235-239` holds `return PlanPair(prefix, plan, None, None)`

In `todo_sync/rules_plans.py` P1 (`_p1_pair`) and P4 skip a plan whose raw JSON has `frozen.records == RecordScheme.receipts` (probe the dict; the module stays free of pydantic). In `todo_sync/sources.py` add `PIP_HTML_SUFFIX = "_PIP.html"` to the prefix scan, and in `_pair`, when `prefix + _PIP.md` is absent and `prefix + _PIP.html` is present, return `PlanPair(prefix, plan, rel(html), None)`: pip_rel names the page, the parsed doc stays None (P1 reads only markdown and already returns on `pair.pip is None`), so P3 warns a lone page by its path. P2 is unchanged (D5).

- [ ] Test `tests/lib/test_todo_sync_rules_plans_receipts.py::test_p1_skips_a_receipts_plan` fails with AssertionError, then passes
- [ ] Test `tests/lib/test_todo_sync_rules_plans_receipts.py::test_p4_skips_a_receipts_plan` fails with AssertionError, then passes
- [ ] Test `tests/lib/test_todo_sync_rules_plans_receipts.py::test_p3_warns_a_lone_html_pip` fails with AssertionError, then passes
- [ ] Record it: `plan.py record 1013 TDS-1 --sha <sha>` or `--staged`

**Evidence:** not started

### DOC-1: Rules, README, schema docs, version and release notes

**Status:** PENDING | **Model:** sonnet | **Depends on:** DRV-2, SCH-1
**Files:** `plugins/harness/rules/HARNESS_RULES.md`, `README.md`, `plugins/harness/schemas/README.md`, `plugins/harness/schemas/PLANS_PIP_Template.md`, `plugins/harness/.claude-plugin/plugin.json`, `docs/RELEASES/v0.8.0.md`

**Anchors:**
- `plugins/harness/rules/HARNESS_RULES.md:117-119` holds `` Spec or plan changes that alter the design are catalogued in a `DesignEvolution.json` beside the plan's research notes ``
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.65.4",`
- `docs/RELEASES/v0.7.1.md:1` holds `# v0.7.1 (proposed)`

HARNESS_RULES.md 'Plans and specs': replace the DesignEvolution line: changes that alter a plan's design go to `<artifacts.plans>/NNNN/DesignEvolution.json` through `evolution_api`, and a receipt that differs from its item cites one; lint, guard, helper-extraction and rename changes stay out. README.md: the write-plan row says `record` writes a sealed receipt beside the frozen plan and the PIP is an HTML page with a derived `live.js` sidecar, kept out of git by the `.gitignore` the driver writes in each plan folder (D9). schemas/README.md: `Receipt.schema.json` and the regenerated `DesignEvolutionCatalog.schema.json` (generated, never edited; plan-bound; `category_enums` gone) plus a Migration entry. `PLANS_PIP_Template.md`: say that plans frozen from this version render HTML. Bump `plugins/harness/.claude-plugin/plugin.json` to 0.66.0. Release notes, measured from the latest tag when this item runs (`gh release list --limit 1`): if it is still v0.7.0, write `docs/RELEASES/v0.8.0.md` from v0.7.0 (harness 0.65.1 -> 0.66.0, arc-straps 0.3.0 -> 0.3.1) carrying v0.7.1.md's change lines, and tell the developer v0.7.1.md is superseded; if v0.7.1 was cut, the table runs harness 0.65.4 -> 0.66.0. One line for issue 258; flag that the DesignEvolution schema change may count as breaking, and that plan 1012 also bumps harness.

- [ ] Test `tests/contract/test_plan_receipts_docs.py::test_the_harness_rules_bind_design_evolution_to_the_plan` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_plan_receipts_docs.py::test_the_repo_readme_names_the_live_js_sidecar` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_plan_receipts_docs.py::test_the_schema_readme_names_the_receipt_schema` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/schemas/test_agent_schemas.py -q`: all pass after the PIP template edit
- [ ] Record it: `plan.py record 1013 DOC-1 --sha <sha>` or `--staged`

**Evidence:** not started

### SKL-1: write-plan SKILL.md through a strap refreeze

**Status:** PENDING | **Model:** opus | **Depends on:** DRV-2, EVO-2
**Files:** `plugins/harness/skills/write-plan/SKILL.md`, `docs/plans/strap/write-plan/SkillSpec.json`

**Anchors:**
- `plugins/harness/skills/write-plan/SKILL.md:20-21` holds `The PIP markdown is rendered from the JSON and never edited by hand.`
- `plugins/harness/skills/write-plan/SKILL.md:120-122` holds `item's PIP section`
- `plugins/harness/lib/harness_lib/strap_api.py:110-111` holds `raise StrapError(f"{name} is frozen")`
- `plugins/harness/lib/harness_lib/strap_api.py:248` holds `def add_part(name: str, kind: Union[PartKind, str], path: str) -> SkillSpec:`

Through `harness:strap-skills` on the frozen `write-plan` spec (`docs/plans/strap/write-plan/SkillSpec.json`), using only the frozen-spec path (a frozen spec refuses `add_behavior`): `strap_api.add_part("write-plan", "contract_test", "tests/skills/test_write_plan_receipts_contract.py")` and `add_part` as `reference` for plan_receipts.py, receipt_models.py, plan_render_html.py and evolution_api.py; the new contract test is a part, not a behavior. Edit SKILL.md, every receipts sentence scoped to receipts plans and the sealed text kept as 'plans frozen before receipts': the intro's PIP sentence becomes the `_PIP.html` page with its `live.js` sidecar, opened from disk; step 8 says nothing writes a receipts plan after its freeze, `record` writes receipts, and the seal is on the receipt; a new step between 8 and 9: a change found during execution goes to the plan's `DesignEvolution.json` through `evolution_api.add`, shown as a worked heredoc (imports from `harness_lib.evolution_models` and `evolution_enums`, `evolution_api.next_id`, a `DesignChange(...)` with `ChangeIssue(...)` and the other nested classes) followed by the matching `record --also PATH --cite EX1` line, and 'A refreeze is for a design change the developer asks for'; 'What a record proves' and 'Common mistakes' scoped by scheme, receipts first; step 9: on a receipts plan each lane prompt takes the item's action, anchors, tests and commands from `plan_api.load(<id>).items` (the page is HTML), and a lane that needs a deviation stops and reports it, then the main session adds the change, stages with `parallel2.py stage <lane> --include-undeclared` and records with the citation. Keep the B8 contract phrases true for sealed plans or update B8's test with the spec. Then `strap.py freeze write-plan --refreeze` (the B1-B8 nodes stay green under the D3 fixture).

- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_the_skill_says_nothing_writes_a_frozen_receipts_plan` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_the_skill_routes_a_mid_build_change_to_design_evolution` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_the_skill_shows_a_design_change_built_through_the_models` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_a_lane_takes_its_item_text_from_the_plan_json` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_the_skill_keeps_refreeze_for_a_design_change_the_developer_asks_for` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_a_lane_that_needs_a_deviation_stops_and_reports_it` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_write_plan_receipts_contract.py::test_the_pip_is_an_html_page` fails with AssertionError, then passes
- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" freeze write-plan --refreeze`: freeze [done]
- [ ] Run `python -m pytest tests/skills/test_write_plan_record_contract.py -q`: all pass
- [ ] Record it: `plan.py record 1013 SKL-1 --sha <sha>` or `--staged`

**Evidence:** not started
