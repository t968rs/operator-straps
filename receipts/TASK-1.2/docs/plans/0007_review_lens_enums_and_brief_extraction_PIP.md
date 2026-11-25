# Plan 0007: review lens enums and brief extraction

> Rendered by `plan.py render` from `0007_review_lens_enums_and_brief_extraction_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-05
**Spec:** `docs/RESEARCH/pr-review/0203_roast_slot_duration.md`
**Branch:** 1130-roast-efficiency -> main
**Base commit:** `e2b7dd7`
**Frozen:** 2026-11-05 at `45051d7`
**Execution model:** serial

## Decisions

- **D1** How does a slot name roast, given project lenses are free-form names? Chosen: `scope-enum` (ScopeLens(StrEnum) OVERALL/ROAST; roast slot lens is always ROAST; Slot.roast derived). Rejected: `lens-none` (roast slot carries lens=None and keeps a roast field). Developer choice 2026-11-05; None loses the scope and forces a None branch everywhere.
- **D2** Does a skills/<name>/ folder need a SKILL.md at the PR head to trigger per-skill-package? Chosen: `skill-md` (only folders holding SKILL.md at the head count). Rejected: `pure-glob` (any **/skills/<name>/ path counts). Developer choice 2026-11-05; a domain folder named skills/ must not trigger.
- **D3** What happens to the tuples and name constants the enums replace? Chosen: `remove` (delete them and update every in-repo caller). Rejected: `alias` (keep module-level aliases with a DeprecationWarning). Developer choice 2026-11-05; every caller is in this repo.
- **D4** Which brief code moves to harness_lib/review_briefs.py? Chosen: `reviewer-shared` (reviewer brief composition plus the helpers fixer briefs share). Rejected: `all-briefs` (reviewer and fixer brief composition). Developer choice 2026-11-05; fixer briefs can follow in a later change.
- **D5** Which slots drop the default linear docstring-vs-code pass? Chosen: `roast-only` (the roast slot only). Rejected: `overall-and-roast` (both OVERALL-scope slots). Developer choice 2026-11-05 after the issue 203 experiment.
- **D6** How is the roast exception expressed so a project's own default sub-lenses keep reaching roast? Chosen: `catalog-skip` (the catalog row carries skip_lenses; the planner filters each slot's sub-lenses). Rejected: `drop-all` (the roast slot drops every default sub-lens). The exception is a property of the plugin's linear pass, not of every project sub-lens.
- **D7** What role line does the roast slot get once its lens is always ROAST? Chosen: `unified` ('roast reviewer covering the OVERALL scope' on small and large PRs). Rejected: `split` (keep a separate replaces-OVERALL flag to tell the two apart). Both roast slots already carry every reviewable path and the OVERALL scope sentence.

## Formats

- **plan.json slots[] entry**: `{"id": "roast", "lens": "roast", "model": "opus", "paths": ["src/a.py"], "templates": ["overall-system-shape"], "roast": true}`, copied from `plugins/harness/scripts/pr_review.py:578`
- **catalog default_sub_lenses row**: `{"name": "linear docstring-vs-code pass", "summary": "...", "trigger": {...}, "skip_lenses": ["roast"], "scope_template": "..."}`, copied from `plugins/harness/schemas/catalogs/CrossCuttingLensCatalog.json:6`

## Sweeps

- **S1** `\b(PATH_BUCKETS|LENS_NAMES|UNBUCKETED|SKILL_PACKAGE|MULTI_ARTIFACT|SYSTEM_SHAPE|_SLOT_IDS)\b`: `plugins/harness/lib/harness_lib/review_plan.py` (definitions removed; PathBucket / Lens members replace them (TASK-1)), `plugins/harness/scripts/pr_review.py` (rp.SKILL_PACKAGE / MULTI_ARTIFACT / PATH_BUCKETS uses become enum members or Slot predicates (TASK-1, TASK-2)), `tests/lib/test_review_plan.py` (helpers and expectations move to PathBucket / Lens (TASK-1))
- **S2** `(\bskills_touched|\bskill_folder\(|rp\.skills_dir|GREP_ROOTS|grep_roots)`: `plugins/harness/lib/harness_lib/review_plan.py` (skills_dir / skill_folder / skills_touched replaced by the skills/ folder API (TASK-4)), `plugins/harness/scripts/pr_review.py` (GREP_ROOTS / grep_roots become rp.SKILL_GREP_ROOTS / rp.skill_grep_roots (TASK-4)), `tests/lib/test_review_plan.py` (TestSkillsTouched / TestSkillMentioned move to the folder API (TASK-4))
- **S3** `\b(BriefContext|header_lines|record_heredoc|_draft_json|target_label|key_literal|brief_header|scope_section|lens_section|rules_section|record_section|reviewer_brief|TOO_LONG_RULE|TEST_DESIGN_CLAUSE|ROAST_VOICE|OVERALL_SCOPE|BUCKET_SCOPE|SEVERITY_RULES|PROSE_GAP_RULE|REMOVAL_DEFECTS|hpy_command)\b`: `docs/PR_REVIEWS/0158_1105_bug_pr_review.json` (historical record quoting the pre-change code; not updated), `docs/PR_REVIEWS/0174_1110_review_local.json` (historical record quoting the pre-change code; not updated), `docs/PR_REVIEWS/0186_Fixpr-review_grade_a_missing_mention_as_minor_repair_before.json` (historical record quoting the pre-change code; not updated), `docs/TODO/RepoToDo.json` (historical record quoting the pre-change code; not updated), `plugins/harness/lib/harness_lib/commit_txt.py` (unrelated local variable header_lines), `plugins/harness/scripts/bubble_memo.py` (unrelated reviewer_brief of the bubble-memo driver), `plugins/harness/scripts/pr_review.py` (definitions move to review_briefs; fixer brief code imports the shared helpers (TASK-2)), `tests/scripts/test_pr_review_driver.py` (script.<name> references read review_briefs (TASK-2))
- **S4** `lens (==|in) .*\"(overall|roast)\"`: `plugins/harness/scripts/pr_review.py` (_role / _scope_text comparisons become Slot predicates in review_briefs (TASK-2)), `tests/lib/test_review_plan.py` (small-PR roast expectation becomes lens 'roast' (TASK-1))

## Tasks

### TASK-1: Lens enums replace the bucket and lens constants; roast lens is always ROAST

**Status:** COMPLETE | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/review_plan.py`, `plugins/harness/scripts/pr_review.py`, `tests/lib/test_review_plan.py`, `tests/lib/test_review_plan_enums.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/review_plan.py:33` holds `PATH_BUCKETS = ("cicd", "config-or-registry", "tests", "runtime", "docs")`
- `plugins/harness/lib/harness_lib/review_plan.py:40` holds `LENS_NAMES = (SKILL_PACKAGE, MULTI_ARTIFACT, SYSTEM_SHAPE)`
- `plugins/harness/lib/harness_lib/review_plan.py:45` holds `_SLOT_IDS = {"config-or-registry": "config"}`
- `plugins/harness/lib/harness_lib/review_plan.py:47-49` holds `_RESERVED_SLOT_IDS = frozenset( {"cicd", "config", "tests", "runtime", "docs", "overall", "roast", "system_shape", "skill_package", "multi_artifact"})`
- `plugins/harness/lib/harness_lib/review_plan.py:226` holds `if not _LENS_NAME.match(name) or lens_slot_id(name) in _RESERVED_SLOT_IDS:`
- `plugins/harness/lib/harness_lib/review_plan.py:343` holds `roast: bool = False`
- `plugins/harness/lib/harness_lib/review_plan.py:376` holds `return [Slot("roast" if roast else "overall", "overall", "opus", reviewable, folded, roast)]`
- `plugins/harness/lib/harness_lib/review_plan.py:381` holds `slots.append(Slot("roast", "roast", "opus", reviewable, (), True))`
- `plugins/harness/scripts/pr_review.py:443` holds `lenses[rp.SKILL_PACKAGE] = tuple(p for p in reviewable if p.startswith(folders))`
- `plugins/harness/scripts/pr_review.py:446` holds `lenses[rp.MULTI_ARTIFACT] = new`
- `plugins/harness/scripts/pr_review.py:578` holds `"slots": [asdict(s) for s in scope.slots]`
- `tests/lib/test_review_plan.py:66` holds `rp.PATH_BUCKETS + ("unbucketed",)`
- `tests/lib/test_review_plan.py:399` holds `assert roast.roast and roast.lens == "overall" and roast.paths == reviewable`
- `tests/scripts/test_pr_review_driver.py:547` holds `assert "overall" not in slots and slots["roast"]["roast"] is True`

1. Copy the planned test file to tests/lib/test_review_plan_enums.py; watch it fail (ImportError).
2. review_plan.py: add the developer's draft enums, fixed: _MissStrEnum._missing_ compares the lowered input with each member's lowered name and value (the draft compared the member with its own name, so every string resolved to CICD) and returns Optional['_MissStrEnum']; drop the unused Any and ClassVar imports; docstrings on each class; two blank lines between top-level defs.
3. PathBucket (CICD, CFG, TESTS, RUNTIME, DOCS, UNBUCKETED) gains slot_id (CFG -> 'config') and classmethod slotted() (every member but UNBUCKETED, precedence order). Lens gains slot_id (skill_package, multi_artifact, system_shape). New ScopeLens(OVERALL='overall', ROAST='roast') with slot_id = value. SlotLens = Union[PathBucket, Lens, ScopeLens, str] (str: a project lens).
4. Remove PATH_BUCKETS, UNBUCKETED, SKILL_PACKAGE, MULTI_ARTIFACT, SYSTEM_SHAPE, LENS_NAMES, _SLOT_IDS; _RESERVED_SLOT_IDS derives from every member's slot_id; _check_project_lens also rejects a name equal to any member value (message keeps 'reserved'). review_bucket returns members; sort_buckets keys are members; merge_registry_into_tests uses PathBucket keys.
5. Slot: lens typed SlotLens and resolved in __post_init__ (a string naming a member becomes that member; a project lens stays a str); the roast field becomes a property (lens is ScopeLens.ROAST); record() returns asdict plus 'roast'. _overall_slots builds the small-PR roast slot with ScopeLens.ROAST and OVERALL with ScopeLens.OVERALL; _bucket_slots iterates PathBucket.slotted(); _lens_slots and extra_lens_names use Lens.
6. pr_review.py: lens_paths uses rp.Lens members; plan_document writes [s.record() for s in scope.slots]; _role and _scope_text read the new properties (they move in TASK-2).
7. tests/lib/test_review_plan.py: _buckets keys from PathBucket; TestCatalog compares with Lens; TestSlotPlan expects roast.lens == 'roast' on the small PR; rp.MULTI_ARTIFACT becomes rp.Lens.MULTI_ARTIFACT.
8. Run tests/lib/test_review_plan_enums.py, tests/lib/test_review_plan.py and tests/scripts/test_pr_review_driver.py by file.

- [x] Test `tests/lib/test_review_plan_enums.py::TestLookup::test_value_or_name_in_any_case` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestLookup::test_unknown_value_raises` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestLookup::test_members_are_their_strings` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotIds::test_bucket_slot_ids_in_precedence_order` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotIds::test_lens_and_scope_slot_ids` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotIds::test_catalog_lenses_are_the_enum` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotIds::test_project_lens_named_like_a_member_is_rejected` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestConstantsRemoved::test_name_is_gone` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotLens::test_small_pr_roast_slot_is_roast` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotLens::test_large_pr_roast_slot_is_roast` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotLens::test_bucket_lens_and_project_slots` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotLens::test_string_lens_resolves_to_its_member` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotLens::test_record_keeps_the_roast_key` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_plan_enums.py::TestSlotLens::test_sort_buckets_keys_are_members` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0007 TASK-1 --sha <sha>`

**Evidence:** commit 4f340cc: 14 test node(s) passed

- `4f340cc1e8155f35d79f18391be9db79364dded2`
- `tree b55fb70e21d22b6c8516a55055fc7cb246dea7f3`
- `python -m pytest -q tests/lib/test_review_plan_enums.py::TestLookup::test_value_or_name_in_any_case tests/lib/test_review_plan_enums.py::TestLookup::test_unknown_value_raises tests/lib/test_review_plan_enums.py::TestLookup::test_members_are_their_strings tests/lib/test_review_plan_enums.py::TestSlotIds::test_bucket_slot_ids_in_precedence_order tests/lib/test_review_plan_enums.py::TestSlotIds::test_lens_and_scope_slot_ids tests/lib/test_review_plan_enums.py::TestSlotIds::test_catalog_lenses_are_the_enum tests/lib/test_review_plan_enums.py::TestSlotIds::test_project_lens_named_like_a_member_is_rejected tests/lib/test_review_plan_enums.py::TestConstantsRemoved::test_name_is_gone tests/lib/test_review_plan_enums.py::TestSlotLens::test_small_pr_roast_slot_is_roast tests/lib/test_review_plan_enums.py::TestSlotLens::test_large_pr_roast_slot_is_roast tests/lib/test_review_plan_enums.py::TestSlotLens::test_bucket_lens_and_project_slots tests/lib/test_review_plan_enums.py::TestSlotLens::test_string_lens_resolves_to_its_member tests/lib/test_review_plan_enums.py::TestSlotLens::test_record_keeps_the_roast_key tests/lib/test_review_plan_enums.py::TestSlotLens::test_sort_buckets_keys_are_members`

### TASK-2: Reviewer brief composition moves to review_briefs; planning predicates to review_plan

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-1
**Files:** `plugins/harness/lib/harness_lib/review_briefs.py`, `plugins/harness/lib/harness_lib/review_plan.py`, `plugins/harness/scripts/pr_review.py`, `tests/scripts/test_pr_review_driver.py`, `tests/lib/test_review_briefs.py`

**Anchors:**
- `plugins/harness/scripts/pr_review.py:592-593` holds `class BriefContext:`
- `plugins/harness/scripts/pr_review.py:652-660` holds `if slot.roast: return "roast reviewer covering the OVERALL scope" if slot.lens == "overall" else "roast reviewer"`
- `plugins/harness/scripts/pr_review.py:715` holds `return OVERALL_SCOPE if slot.lens in ("overall", "roast") else ""`
- `plugins/harness/scripts/pr_review.py:743` holds `return any(rp.review_bucket(p) == "tests" or tests.is_test_path(p) for p in paths)`
- `plugins/harness/scripts/pr_review.py:823` holds `brief = reviewer_brief(ctx, slot, diff_path, partial_paths(text))`
- `plugins/harness/scripts/pr_review.py:833` holds `label = target_label(plan['pr'])`
- `plugins/harness/scripts/pr_review.py:894` holds `ctx = BriefContext(repo.as_posix(), _LIB.as_posix(), key, run_id, facts, at_head, catalog,`
- `plugins/harness/scripts/pr_review.py:1807` holds `return f"{hpy_command()} -m pytest {paths} -q -p no:cacheprovider"`
- `plugins/harness/scripts/pr_review.py:1853` holds `defects in that code and the removal resolves it: {REMOVAL_DEFECTS}.`
- `plugins/harness/scripts/pr_review.py:1888-1889` holds `lines = [f"# Fixer brief: {agent} - {target_label(ctx.pr)}", ""] lines += [f"- {line}" for line in header_lines(agent, "fixer", ctx.run_id, ctx.pr)]`
- `plugins/harness/scripts/pr_review.py:1901-1902` holds ```` "```bash", record_heredoc(ctx, call), "```", "", TOO_LONG_RULE] ````
- `plugins/harness/scripts/pr_review.py:1912` holds `return BriefContext(repo.as_posix(), _LIB.as_posix(), parse_key(plan["pr"]),`
- `tests/scripts/test_pr_review_driver.py:510` holds `clause = _normalized(script.TEST_DESIGN_CLAUSE)`
- `tests/scripts/test_pr_review_driver.py:1518` holds `assert _normalized(script.TEST_DESIGN_CLAUSE) in _normalized(script.rules_section(slot))`
- `tests/scripts/test_pr_review_driver.py:1555` holds `defects = _normalized(script.REMOVAL_DEFECTS)`

1. Copy the planned test file to tests/lib/test_review_briefs.py; watch it fail (ImportError).
2. review_plan.Slot gains the planning predicates the brief reads: bucket -> Optional[PathBucket], overall_scope (lens is a ScopeLens member), lists_skills (lens is Lens.SKILL_PACKAGE).
3. New harness_lib/review_briefs.py (module docstring, no import of the driver): BriefContext, hpy_command, header_lines, target_label, key_literal, catalog_rows, role (was _role, reads the predicates; roast reads 'roast reviewer covering the OVERALL scope' per D7), brief_header, the read-method and path-line helpers, scope_section, scope_text, lens_section, ownership_clause, tests_in_scope (compares with PathBucket.TESTS), domain_pointers, rules_section, TOO_LONG_RULE, record_heredoc, draft_json, record_section, reviewer_brief, and the texts TEST_DESIGN_CLAUSE, ROAST_VOICE, OVERALL_SCOPE, BUCKET_SCOPE, REMOVAL_DEFECTS, PROSE_GAP_RULE, SEVERITY_RULES. Behavior unchanged apart from D7.
4. pr_review.py: delete the moved definitions; import them from review_briefs (fixer_brief, pytest_command, capture_summary, wave_context, write_briefs and _cmd_capture keep working); no comparison of a slot lens with a string literal remains. Module docstring names review_briefs.
5. tests/scripts/test_pr_review_driver.py: the four direct references (TEST_DESIGN_CLAUSE, rules_section, PROSE_GAP_RULE, REMOVAL_DEFECTS) read review_briefs.
6. Run tests/lib/test_review_briefs.py, tests/scripts/test_pr_review_driver.py and tests/lib/test_review_plan.py by file.

- [x] Test `tests/lib/test_review_briefs.py::TestRole::test_role_line` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestPlannedKind::test_bucket_and_overall_scope` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestPlannedKind::test_skill_list_only_for_the_skill_package_lens` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestBrief::test_sections_in_order` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestBrief::test_scope_sentences` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestBrief::test_roast_voice_only_for_roast` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestBrief::test_test_design_clause_follows_test_paths` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestDriverSplit::test_moved_names_live_in_the_library` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_briefs.py::TestDriverSplit::test_no_comparison_with_a_lens_literal` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0007 TASK-2 --sha <sha>`

**Evidence:** commit 4f340cc: 9 test node(s) passed

- `4f340cc1e8155f35d79f18391be9db79364dded2`
- `tree b55fb70e21d22b6c8516a55055fc7cb246dea7f3`
- `python -m pytest -q tests/lib/test_review_briefs.py::TestRole::test_role_line tests/lib/test_review_briefs.py::TestPlannedKind::test_bucket_and_overall_scope tests/lib/test_review_briefs.py::TestPlannedKind::test_skill_list_only_for_the_skill_package_lens tests/lib/test_review_briefs.py::TestBrief::test_sections_in_order tests/lib/test_review_briefs.py::TestBrief::test_scope_sentences tests/lib/test_review_briefs.py::TestBrief::test_roast_voice_only_for_roast tests/lib/test_review_briefs.py::TestBrief::test_test_design_clause_follows_test_paths tests/lib/test_review_briefs.py::TestDriverSplit::test_moved_names_live_in_the_library tests/lib/test_review_briefs.py::TestDriverSplit::test_no_comparison_with_a_lens_literal`

### TASK-3: The roast slot drops the plugin's linear docstring pass

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-2
**Files:** `plugins/harness/lib/harness_lib/review_plan.py`, `plugins/harness/lib/harness_lib/review_briefs.py`, `plugins/harness/schemas/catalogs/CrossCuttingLensCatalog.json`, `tests/lib/test_review_roast_sub_lens.py`

**Anchors:**
- `plugins/harness/scripts/pr_review.py:727-728` holds `for sub in catalog_rows(ctx.catalog, "default_sub_lenses"): lines += [f"### Default sub-lens: {sub['name']}", "", str(sub["scope_template"]), ""]`
- `plugins/harness/schemas/catalogs/CrossCuttingLensCatalog.json:9` holds `"description": "Always on for every bucket reviewer scope (docs/tests/runtime/config-or-registry/cicd).",`
- `plugins/harness/lib/harness_lib/review_plan.py:217-218` holds `out["default_sub_lenses"] = [*out["default_sub_lenses"],`

1. Copy the planned test file to tests/lib/test_review_roast_sub_lens.py; watch it fail.
2. CrossCuttingLensCatalog.json: the linear docstring-vs-code row gains "skip_lenses": ["roast"] (D5, D6).
3. review_plan.sub_lenses_for(slot, catalog) -> the catalog's default_sub_lenses rows whose skip_lenses (absent = none) does not name the slot's lens; project rows carry none, so they reach every slot.
4. review_briefs.lens_section iterates rp.sub_lenses_for(slot, ctx.catalog) instead of every row.
5. Run tests/lib/test_review_roast_sub_lens.py, tests/lib/test_review_briefs.py and tests/scripts/test_pr_review_driver.py by file.

- [x] Test `tests/lib/test_review_roast_sub_lens.py::test_catalog_row_skips_roast` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_roast_sub_lens.py::test_planner_filters_sub_lenses` fails with ImportError, then passes
- [x] Test `tests/lib/test_review_roast_sub_lens.py::test_roast_brief_drops_only_the_linear_pass` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0007 TASK-3 --sha <sha>`

**Evidence:** commit 4f340cc: 3 test node(s) passed

- `4f340cc1e8155f35d79f18391be9db79364dded2`
- `tree b55fb70e21d22b6c8516a55055fc7cb246dea7f3`
- `python -m pytest -q tests/lib/test_review_roast_sub_lens.py::test_catalog_row_skips_roast tests/lib/test_review_roast_sub_lens.py::test_planner_filters_sub_lenses tests/lib/test_review_roast_sub_lens.py::test_roast_brief_drops_only_the_linear_pass`

### TASK-4: per-skill-package triggers on any skills/<name>/ folder holding SKILL.md

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-2
**Files:** `plugins/harness/lib/harness_lib/review_plan.py`, `plugins/harness/scripts/pr_review.py`, `tests/lib/test_review_plan.py`, `tests/lib/test_review_plan_skill_lens.py`, `tests/scripts/test_pr_review_skill_lens.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/review_plan.py:87-89` holds ``` def skills_dir() -> str: """The project's skills directory as a POSIX prefix ending in ``/``.""" ```
- `plugins/harness/lib/harness_lib/review_plan.py:149-153` holds `def skills_touched(paths: Sequence[str]) -> Tuple[str, ...]:`
- `plugins/harness/lib/harness_lib/review_plan.py:156` holds `def skill_mentioned(name: str, grep_lines: Sequence[str], patterns: Sequence[str]) -> bool:`
- `plugins/harness/scripts/pr_review.py:201` holds `GREP_ROOTS = (".claude", "docs", ".github")`
- `plugins/harness/scripts/pr_review.py:417-420` holds `def grep_roots() -> Tuple[str, ...]:`
- `plugins/harness/scripts/pr_review.py:425` holds `result = git(repo, "grep", "-I", "-n", "-F", name, head, "--", *grep_roots())`
- `plugins/harness/scripts/pr_review.py:438-439` holds `skills = tuple(s for s in rp.skills_touched(reviewable) if rp.skill_mentioned(s, grep_lines(repo, facts.head_sha, s), patterns))`
- `plugins/harness/scripts/pr_review.py:556` holds `lenses, skills = lens_paths(repo, facts, reviewable, patterns, catalog)`
- `tests/lib/test_review_plan.py:264` holds `assert rp.skills_touched(paths) == ("pr-review", "pr-sum")`
- `tests/lib/test_review_plan.py:274` holds `assert rp.skill_mentioned("pr-review", ["docs/a.md:3:run pr-review now"], _PATTERNS)`

1. Copy both planned test files; watch them fail.
2. review_plan.py: remove skills_dir, skill_folder and skills_touched. Add skill_candidates(paths) (sorted unique '<prefix>skills/<name>/' folders, first 'skills' segment followed by a name and at least one more segment), skill_files(candidates) (each + 'SKILL.md'), skill_folders(candidates, present) (candidates whose SKILL.md is in present), skill_name(folder), SKILL_GREP_ROOTS = ('.claude', 'docs', '.github') moved from the driver, skill_grep_roots(folders) (the fixed roots plus each folder's top segment, ordered, unique), and skill_mentioned(folder, grep_lines, patterns) (name from the folder; a hit under that folder or an excluded path never counts).
3. pr_review.py: delete GREP_ROOTS and grep_roots; grep_lines(repo, head, name, roots); a helper asks git ls-tree -r --name-only <head> -- <skill files> for the SKILL.md files present; lens_paths keeps its signature, builds the folders, keeps those mentioned, and returns the per-skill-package paths (reviewable under a kept folder) and the unique skill names in folder order.
4. tests/lib/test_review_plan.py: TestSkillsTouched and TestSkillMentioned move to the new API (folder argument) or are dropped where the planned file covers them.
5. Run both planned files, tests/lib/test_review_plan.py and tests/scripts/test_pr_review_driver.py by file.

- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_candidates_sorted_unique` fails with AttributeError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_skill_files_name_each_candidate_skill_md` fails with AttributeError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_only_folders_holding_skill_md_count` fails with AttributeError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_skill_name_is_the_folder_name` fails with AttributeError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestGrepRoots::test_roots` fails with AttributeError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_hit_outside_folder_fires` fails with AssertionError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_hit_in_another_root_counts` fails with AssertionError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_hit_inside_own_folder_does_not` fails with AssertionError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_longer_name_and_excluded_path_do_not` fails with AssertionError, then passes
- [x] Test `tests/lib/test_review_plan_skill_lens.py::TestOldHelpersRemoved::test_name_is_gone` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_pr_review_skill_lens.py::test_any_skills_folder_with_skill_md_triggers` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0007 TASK-4 --sha <sha>`

**Evidence:** commit 4f340cc: 11 test node(s) passed

- `4f340cc1e8155f35d79f18391be9db79364dded2`
- `tree b55fb70e21d22b6c8516a55055fc7cb246dea7f3`
- `python -m pytest -q tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_candidates_sorted_unique tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_skill_files_name_each_candidate_skill_md tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_only_folders_holding_skill_md_count tests/lib/test_review_plan_skill_lens.py::TestCandidates::test_skill_name_is_the_folder_name tests/lib/test_review_plan_skill_lens.py::TestGrepRoots::test_roots tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_hit_outside_folder_fires tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_hit_in_another_root_counts tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_hit_inside_own_folder_does_not tests/lib/test_review_plan_skill_lens.py::TestMentioned::test_longer_name_and_excluded_path_do_not tests/lib/test_review_plan_skill_lens.py::TestOldHelpersRemoved::test_name_is_gone tests/scripts/test_pr_review_skill_lens.py::test_any_skills_folder_with_skill_md_triggers`

### TASK-5: Docs state the roast sub-lens exception and the any-skills/ trigger; version bump

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-3, TASK-4
**Files:** `plugins/harness/skills/pr-review/SKILL.md`, `plugins/harness/schemas/catalogs/CrossCuttingLensCatalog.json`, `plugins/harness/config/harness.schema.json`, `README.md`, `plugins/harness/.claude-plugin/plugin.json`, `tests/skills/test_pr_review_lens_docs.py`

**Anchors:**
- `plugins/harness/skills/pr-review/SKILL.md:233` holds `Every reviewer, in every slot, runs a linear docstring-vs-code pass`
- `plugins/harness/skills/pr-review/SKILL.md:244` holds `` | per-skill-package | the PR touches `<skills_dir>/<name>/` AND `<name>` appears ``
- `plugins/harness/config/harness.schema.json:20` holds `"description": "Where this project keeps its own skills (review lens detection);`
- `README.md:453` holds `` | `skills_dir` ``
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.56.0",`

1. Copy the planned test file to tests/skills/test_pr_review_lens_docs.py; watch it fail.
2. pr-review SKILL.md, section 'Default sub-lens (mandatory)': 'Every reviewer slot except roast runs a linear docstring-vs-code pass ...', with one sentence on why (the roast slot carries the OVERALL scope and every bucketed path gets the pass from its bucket slot; the catalog row's skip_lenses carries the exception). Lens table row per-skill-package: 'the PR touches any `skills/<name>/` folder holding a `SKILL.md` at the PR head AND `<name>` appears as a whole word ... under `.claude`, `docs`, `.github` or that skill root's top folder, outside the skill's own folder'.
3. CrossCuttingLensCatalog.json: the linear row's summary and trigger.description say every reviewer slot 'except the roast slot'; policy.mechanical_triggers says 'per-skill-package matches any skills/<name>/ folder holding a SKILL.md at the PR head' (pr-team's shell form keeps $SKILLS_DIR).
4. harness.schema.json and the README key row of skills_dir: 'pr-team's per-skill-package shell trigger' replaces '(review lens detection)'.
5. Bump plugins/harness/.claude-plugin/plugin.json from 0.56.0 to 0.57.0.
6. Run tests/skills/test_pr_review_lens_docs.py and tests/skills/test_pr_review_skill_contract.py by file.

- [x] Test `tests/skills/test_pr_review_lens_docs.py::test_skill_states_the_roast_exception` fails with AssertionError, then passes
- [x] Test `tests/skills/test_pr_review_lens_docs.py::test_skill_trigger_row_names_any_skills_folder` fails with AssertionError, then passes
- [x] Test `tests/skills/test_pr_review_lens_docs.py::test_catalog_linear_pass_names_its_skip` fails with AssertionError, then passes
- [x] Test `tests/skills/test_pr_review_lens_docs.py::test_catalog_policy_names_the_pr_review_skill_trigger` fails with AssertionError, then passes
- [x] Test `tests/skills/test_pr_review_lens_docs.py::test_skills_dir_no_longer_claims_pr_review_detection` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0007 TASK-5 --sha <sha>`

**Evidence:** commit 4f340cc: 5 test node(s) passed

- `4f340cc1e8155f35d79f18391be9db79364dded2`
- `tree b55fb70e21d22b6c8516a55055fc7cb246dea7f3`
- `python -m pytest -q tests/skills/test_pr_review_lens_docs.py::test_skill_states_the_roast_exception tests/skills/test_pr_review_lens_docs.py::test_skill_trigger_row_names_any_skills_folder tests/skills/test_pr_review_lens_docs.py::test_catalog_linear_pass_names_its_skip tests/skills/test_pr_review_lens_docs.py::test_catalog_policy_names_the_pr_review_skill_trigger tests/skills/test_pr_review_lens_docs.py::test_skills_dir_no_longer_claims_pr_review_detection`
