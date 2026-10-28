# Agent Schemas

Standard JSON schemas and templates for agent-produced artifacts: code reviews, action plans, implementation plans, per-task validity gates, and structured catalogs.

## Purpose

These schemas enforce consistent, machine-readable structure for the artifacts agents emit during the review → plan → execute → verify pipeline. Their job is to:

- Make agent outputs reproducible across sessions and reviewers
- Allow automated validation (status = evidence, not claims)
- Provide a stable shape for tooling, dashboards, and cross-PR analysis

When an agent emits a file matching one of these artifact types, it MUST validate against the relevant schema.

**Resolution:** a project may pin its own copy of a schema under its configured `schemas_dir`; the pinned
copy wins, else the plugin copy in this directory is used. Artifact directories (`artifacts.reviews`,
`artifacts.plans`, defaults `docs/PR_REVIEWS` and `docs/PLANS`) come from the project's `.claude/harness.json`.
The `validate_pr_json_schema.py` hook validates review and plan writes against these schemas.

---

## Files

### 1. `PR_REVIEW.schema.json`

**Applies to:** `<reviews dir>/{NNNN}_{Title}.json` (4-digit zero-padded PR number; `<reviews dir>` is the project's `artifacts.reviews`).

Structure of an agent code-review verdict:

- PR metadata (number, title, branch, base/head SHAs, review_date, reviewers)
- Root metadata (REQUIRED): `schema_ref` (repo-relative path to canonical schema) + `version` (semver, currently "2.1.0")

**Version bump protocol:** any change to the schema that breaks existing PR_REVIEWS JSONs (new required field, type change, removed property) requires a major version bump. `2.0.0` reflects the `fix: string → array[string]` migration completed in PR #1216; `2.1.0` adds the optional issue field `fix_kind` (non-breaking, so no sweep). When bumping a major version, sweep all existing PR_REVIEWS JSONs in the same PR.

- Aggregated stats (additions, deletions, files_changed)
- `verdict` — must match `^(READY TO MERGE|NOT READY TO MERGE)(.*)$`. The string `NEEDS FIXES` is NOT permitted; that wording exists only in skill prose.
- `strengths` — bullet observations (specific, not vague praise)
- `issues` — categorized object (`{critical, important, minor}`), each issue with `id`, `name`, `summary`, `file` and/or `files` (at least one), `fix[]` (array of one-or-more remediation options; each entry is a self-contained alternative; was string pre-PR-1216), and optional `lines`, `step`, `reviewer`, `both_reviewers`, `fix_kind` (`mechanical` | `judgment`; routes the Phase 5 fixer model)
- `bubble_up` — flat array of issues that exit Phase 5 unresolved, each item `{id, classification, reason}` where `classification` ∈ `{architectural_ambiguity, out_of_scope, needs_follow_up, fixer_failed}`. Mirrors the items[] shape of the pr-team skill's `bubble_ups.schema.json` sidecar. Empty array means Phase 5 closed cleanly. *(Naming note: singular `bubble_up` in PR_REVIEW because the field is the array itself; plural `bubble_ups` in pr-team because the file is the sidecar container holding `items[]`.)*
- `post_review_resolutions` — when issues are addressed in-session, append entries with `status` ∈ `{RESOLVED, DOWNGRADED_TO_*, CLOSED_NO_ACTION}` and recompute `verdict` in the same write

### 2. `ActionPlan.schema.json`

**Applies to:** `docs/PLANS/{NNNN}_ActionPlan.json` and `docs/PLANS/{NNNN}_*_ActionPlan.json`.

Execution tracking:

- `plan_id` (4-digit zero-padded), `plan_created`, `execution_model` (`sequential` / `parallel_worktrees`)
- `pr_attributes[]` — zero or more PR references (uses `prAttributes.schema.json` per element). Project-scoped plans (research, refactor, incident) may omit this entirely.
- `items[]` — one entry per action item, with `id`, `priority`, `title`, `action` (exact remediation steps), `files[]`, `status`, `evidence`; optional add-ons are `verification_references[]` + `markdown_section`
- Optional markdown sync metadata: `markdown_sync_status` + `markdown_last_updated`
- Plan-level fields written by `plan.py`: `base_commit` (merge base, `{base}` stands in for it in commands), `frozen` (commit, tree, date and digest set by `plan.py freeze`), `completed`
- Design fields: `decisions[]` (open until `chosen` is set, which blocks freeze), `values[]` (thresholds with the options they assume), `formats[]` (literal layouts copied from a producer or parser), `sweeps[]` (searches `plan.py check` runs)
- Per-item fields: `model` (agent model for dispatch), `anchors[]` (line ranges checked against code), `commands[]` (commands with the output that means pass), `tests[]` (pytest node ids with the failure that precedes the fix)

The write-plan skill (`plugins/harness/skills/write-plan/SKILL.md`) and `plugins/harness/scripts/plan.py` own the authoring and checks for these fields.

**Status rules:**
- `COMPLETE` requires commit SHA(s) in evidence — never a claim
- `CLOSED_NO_ACTION` requires written rationale
- `IN_PROGRESS` / `PENDING` are transient; every item must terminate in COMPLETE or CLOSED_NO_ACTION

### 3. `prAttributes.schema.json`

**Applies to:** Each element of `ActionPlan.pr_attributes[]`.

Per-PR metadata: `pr` (number or string), `branch`, `base_branch`. Required when an ActionPlan is tied to one or more PRs.

### 4. `PLANS_PIP_Template.md`

**Applies to:** `docs/PLANS/{NNNN}_*_PIP.md` and `docs/PLANS/{NNNN}_*_PIP.md`.

Implementation Plan template — agent-executable task breakdown with exact commands and verification per task.

Required structure:

- Header (PR/Plan ID, plan date, execution model, branch lineage)
- Goal (one sentence)
- One Task section per issue with: issue ID, files to create/modify, numbered steps with exact commands and expected output, verification command, atomic commit step

**Execution models:** `Serial Execution` (sequential atomic commits) or `Parallel Worktrees` (organize tasks into A/B/C lanes to avoid merge conflicts).

### 5. `_subagent_expectations.example.json`

**Applies to:** Per-task validity gates for subagent-dispatched tasks. Each task entry declares `expected_files_*`, `expected_symbols_defined`, `expected_tests_passing`, `expected_commit_message_contains`, and `accept_if` / `fixup_if` / `reject_if` conditions.

Used by the dispatch wrapper to mechanically validate subagent returns: `accept_if` all-true → accept; `fixup_if` true → accept with inline follow-up; `reject_if` true → re-dispatch.

This is a worked specimen (originally produced for Issue #747's CICD-Decompose-checks subagent dispatch). Treat it as an example of the shape — the structure is general, but the task list is issue-specific. A formal `SubagentExpectations.schema.json` may be promoted later if multiple issues need the same shape.

### 6. `docs/PR_REVIEWS/Catalog.json`

**Purpose:** Migration audit snapshot from Issue #1210 (PR_REVIEW schema migration to fix: string → array[string]). Not maintained; for historical reference only.

### 7. `TodoSyncReport.schema.json`

**Purpose:** Result of one `todo_sync.py check` run, written atomically to `<state_dir>/todo-sync/report.json` and read by the `todo-watch` mod. Derived data, never committed.

**Key fields:** `schema_version` (const 1), `generated_at`, `rules_run[]`, `rules_skipped[]` (`rule`, `reason`), `drift` (counted findings: every error, plus warns when `todo.rules.warn_counts` is true), `by_rule` (counted findings per rule id), `counts` (`error`, `warn` over all findings), `gh_fetched_at` (issue cache time or null), `findings[]`.

**Finding:** `rule` (`S*` research, `P*` plans, `T*` TODO catalog, `G*` GitHub), `severity` (`error` / `warn`), `counted`, `file` (repo-relative POSIX or null), optional `line`, `subject`, `fix`, and a one-line `message`. `tests/mods/test_todo_watch_report_contract.py` pins every key the mod reads to this schema and checks that the mod's finding parser reads those keys and the severity enum through the pinned constants. A `--rules` run marks each left-out rule `not selected` in `rules_skipped`; the mod ignores such a subset report.

---

## Catalog Schemas (`catalogs/`)

Structured catalogs for symbol-level analysis. Most catalog variants — `Decompose`, `ConsumerAudit`, and any future symbol-flavored variant — extend the common `SymbolCatalog.base` via `allOf` + `$ref`, so they share scaffolding (categories, summary, per-entry shape) while carrying purpose-specific fields. A small number of catalogs (`CICDActionAudit` and `TodoCatalog`) describe non-symbol artifacts and are intentionally standalone — they do not inherit `SymbolCatalog.base`. `CICDActionAudit` keeps the `catalog_date` / `summary` shape; `TodoCatalog` uses its own `generated` / `counts` shape and has neither field. Both keep sibling-path refs. Each variant's section below states whether it extends the base. Sibling-schema references use bare relative paths — no leading `./`, no `$id`-by-bare-token.

### `catalogs/SymbolCatalog.base.schema.json`

Universal scaffolding for any symbol catalog. Defines:

- Top-level: `catalog_date`, `categories`, `summary` (required); `module_path`, `file_path`, `total_lines`, `notes` (optional, mandated by some variants)
- `$defs/category` — id (snake_case), label, optional line_range, entry_count
- `$defs/cataloged_entry` — `name`, `kind`, `category_id`, line spans, file_path, docstring_summary, notes

Variant schemas extend `$defs/cataloged_entry` to add purpose-specific per-entry fields. Each variant also adds its own primary array (`symbols`, `consumers`, …) so existing terminology survives the migration.

### `catalogs/Decompose.catalog.schema.json`

**Applies to:** Decomposition-planning catalogs produced by the `decompose-module` skill. Typical path: `docs/RESEARCH/<module>_catalog.json`.

Per-symbol fields beyond the base: `external_usage_count`, `external_usage_files[]`, `evidence`, `disposition` (`keep_and_relocate` / `delete` / `keep_internal` / `needs_review`), `confidence` (when relocating), `relocation_candidates[]`. Top-level adds `dependency_chains[]` (must-move-together groups).

### `catalogs/ConsumerAudit.catalog.schema.json`

**Applies to:** Consumer-contract audits produced by the `consumer-contract-audit` skill (or any plan/spec phase that needs to enumerate readers/writers/walkers/mutators of a target structure before a contract change).

Top-level adds `target_symbol` (the structure being audited), `audit_reason`, optional `proposed_change`, optional `contract_invariants[]`. Per-consumer fields: `role` (`read` / `write` / `walk` / `mutate`), `contract_relied_on`, `risk_if_changed` (`high` / `medium` / `low`), `evidence`, optional `breaks_if`, `mitigations[]`.

### `catalogs/CICDActionAudit.catalog.schema.json`

**Applies to:** CI/CD action audit catalogs produced during GitHub Actions runtime-migration analysis (e.g., Node.js version deprecations). Typical path: `docs/RESEARCH/CICD/<IssueTitle>_Catalog.json`.

**Base relationship:** Standalone — does **not** extend `SymbolCatalog.base`. The audit shape is `workflows[] -> actions[]`, not a flat per-symbol entry list, so the symbol-catalog scaffolding does not apply. The schema is self-contained while still following the README's documentation conventions (`catalog_date`, `summary`, sibling-path refs).

Top-level fields: `catalog_date`, `issue_number`, `issue_title`, `deprecation_notice` (optional), `summary` (aggregate counts), `workflows[]` (per-workflow action inventories), `resolution_summary` (bucketed outcomes), `recommendations`, `notes[]`.

Per-workflow entry: `file` (repo-relative path), `has_force_node24` (boolean), `actions[]`.

Per-action entry: `name` (uses: reference), `line` (1-indexed), `nodejs_version_target`, `current_status` (`compatible_with_force` / `will_auto_migrate` / `outdated` / `up_to_date`), `resolution` (enum), `rationale`, optional `recommended_change`.

### `catalogs/TodoCatalog.schema.json`

**Applies to:** The ranked repository TODO catalog (`<todo.folder>/RepoToDo.json` unless `todo.catalog` names another file under the folder), checked by `todo_sync.py` and summarized by the `todo-watch` mod. Rule T1 validates against it when the project keeps no schema beside the data (`<todo.folder>/RepoToDo.schema.json`, or the file `todo.catalog_schema` names), or when `todo.catalog_schema` is null.

**Base relationship:** Standalone, closed (`additionalProperties: false`) at every level. Draft 2020-12.

Top-level fields (required): `generated`, `generated_from` (`description`, `head_sha`, optional `branch`), `ranking_method` (formula text, `impact_weights`, `loe_points`, `blast_factors`, `unblock_bonus`, `tie_breakers`, `impact_definitions`, `severity_scale`), `counts`, `items[]`, `trackers[]`, `close_candidates[]`; optional `$schema`.

Per-item fields: `id` (`TODO-NNN`, equal to `rank`; both are display labels that change on every re-rank), `title`, `kind`, `status` (`OPEN` / `PARTIAL` / `NEEDS_DECISION` / `BLOCKED`; no terminal status: finished work leaves the file), `needs_decision` + `decision_question`, `tracker`, `sources[]` (`gh_issue` / `impl_stub` / `research_folder`), `gh_issues[]`, `related_gh_issues[]`, `catalog_entry_ids[]`, `summary`, `proposed_change`, optional `code_snippet`, `files[]`, `blast_radius`, `loe`, `impact`, `severity`, `priority` (`score`, `components`), `depends_on[]`, `unblocks[]`, `why_ranked`.

Cross-record rules the schema cannot express that `todo_sync` rules T6-T10 check: unique ids equal to `TODO-<rank>`, ranks 1..n, `priority.score` and order recomputed with the fixed formula from the numeric `ranking_method` tables, mutual `depends_on` / `unblocks`, tracker membership, and `counts` tallies other than `sources_absorbed` and `merged_items`. Unchecked: `counts.sources_absorbed`, `counts.merged_items`, `close_candidates[].related_todo_ids` membership, and the sort order of `unblocks` and `related_todo_ids`. The `ranking_method` formula strings (`value`, `cost`, `score`, `tie_breakers`) are human-readable records; `todo_sync` never parses them.

---

## Workflow

### Step 1 — Review → PR_REVIEW.schema.json

Agent invokes `pr-review`. The skill orchestrates the review pipeline across five phases (Phase 1 dispatch prep, Phase 2 delegate, Phase 3 consolidate, Phase 4 branch safety, Phase 5 fix-application). The canonical phase-by-phase narrative lives in the pr-review skill's `SKILL.md` — this README is the JSON-shape contract, not a second copy of the flow.

The Phase 3 JSON must validate against `PR_REVIEW.schema.json`. Verdict re-evaluation is mechanical, not judgment — see the schema's `verdict` field rule and the skill's "Verdict re-evaluation rule" section. Phase 4 updates the `verification_log.pre_fix_time` block in the same file before any fix lands.

### Step 2 — Plan → ActionPlan + PIP (paired)

Agent invokes `superpowers:writing-plans`:

```
Read docs/PR_REVIEWS/{NNNN}_*.json
  → Write docs/PLANS/{NNNN}_ActionPlan.json (status=PENDING)
  → Write docs/PLANS/{NNNN}_PIP_{Title}.md (matching PIP template)
  → Choose execution_model (sequential vs parallel_worktrees)
```

Both files must be written before any task executes.

### Step 3 — Execute → Status + Evidence (atomic)

Agent invokes `superpowers:subagent-driven-development` (or executes inline):

```
For each PIP task:
  Execute steps → run tests → commit
  Update ActionPlan: status=COMPLETE, evidence=[<commit SHAs>]
  Check off matching PIP.md step
  (Both files updated in the SAME edit — atomic per-task)
```

`COMPLETE` ← commit SHA(s). `CLOSED_NO_ACTION` ← rationale. Status is never a claim.

### Step 4 — Catalog (when applicable)

When a refactor or audit needs structured per-symbol analysis:

- **Decomposition** (`decompose-module` skill) emits a `Decompose.catalog.schema.json`-conformant JSON to `docs/RESEARCH/<module>_catalog.json`.
- **Consumer-contract audit** (`consumer-contract-audit` skill) emits a `ConsumerAudit.catalog.schema.json`-conformant JSON when enumerating consumers of a structure scheduled for contract change.

Catalogs are spec/plan-time artifacts — they inform the ActionPlan but don't replace it.

---

## Validation Rules

### PR_REVIEW JSON

- Verdict is explicit: `READY TO MERGE` or `NOT READY TO MERGE — <reason>`
- Every issue has `id`, `title`, `description`, `fix`, plus at least one of `file` or `files` (the schema's `anyOf` permits both; a single-file issue listing the path in `files` alongside `file` is acceptable but verbose)
- `strengths` are specific (not vague praise)
- `bubble_up` is a complete record of unresolved-after-Phase-5 issues (resolved issues live in `post_review_resolutions`; nothing else is dropped on the floor)
- `verification_log` paste fields contain raw command stdout, not synthesized summaries
- `verification_log` shape contract (canonical here; the skill cites this README, not the other way around): EITHER a `{"skipped": true, "reason": "..."}` advisory (for catalog-style review JSONs) OR the nested two-block structure with `dispatch_time` (Phase 1 / Phase 3) carrying `pr_metadata_check` + `structural_guards_check`, and `pre_fix_time` (Phase 4) which is the literal string `"pending - to be populated in Phase 4"` (ASCII hyphen; the schema `const` is authoritative) at Phase 3 write time and a sub-object (`current_branch_check`, `branch_match_check`, `clean_tree_check`, `sha_ancestry_check`, `base_branch_recorded`) after Phase 4 runs. The two shapes are mutually exclusive — `oneOf` in the JSON Schema. Drift between this README and SKILL.md is caught by the harness tests `tests/skills/test_pr_review_skill_contract.py` (phase-count, sibling-artifact references) and `tests/schemas/test_pr_review_schema_verification_log.py` (schema-vs-data shape).
- Exactly one `docs/PR_REVIEWS/{NNNN}_*.json` file per PR (4-digit padded). **Known 5-digit-prefix exceptions:** `01039_*`, `01044_*`, `01047_*` are preserved as-is to keep historical cross-references (commits, issues, sibling docs) resolvable. The canonical predicate `is_review_artifact_name` (regex `^\d{4}_`) intentionally rejects 5-digit prefixes — these files are skipped by the validation hook by design. New review files MUST use 4-digit padding; if a future PR number exceeds 9999, update the predicate to `^\d{4,5}_` and document the migration here.

### ActionPlan JSON

- Linked to valid plan-level source docs (`source_document` and `documentation`) and PR linkage docs (`pr_attributes[].review_doc` / `pr_attributes[].pip_document`)
- Every issue from the review has a corresponding item
- JSON is the source of truth for TODO and progress state; if execution deviates, JSON must be updated before completion claims
- `status: COMPLETE` always carries commit SHA(s) in `evidence` or `verification_references` (todo_sync rule P2)
- `status: CLOSED_NO_ACTION` always carries rationale
- `verification_references[]` should carry durable proof pointers (commit SHA, command, CI run, artifact path, or anchor)
- `markdown_section` should point to the Markdown section that expands the JSON item's evidence/details
- `files[]` matches the actual changes recorded in commit SHAs
- Every item terminates in `COMPLETE` or `CLOSED_NO_ACTION` before the plan closes

### PIP Markdown

- Every issue ID (C1 / I1 / M1 / …) has a corresponding Task
- Task sections should explicitly map back to ActionPlan keys (item ID / markdown section key)
- Every step has an exact command (no pseudo-code)
- Every step has expected output shown
- Verification step uses real test/lint commands
- Evidence prose in Markdown expands references declared in JSON (not vice versa)
- Atomic commit step at the end of every task; commit message references the issue ID
- No compound bash commands (no `&&` or `;` in single-shot calls)
- Worktree paths use absolute `git -C <path>` form
- Checkboxes use `- [ ]` markdown

### Catalog JSON (SymbolCatalog variants)

Applies to the symbol-flavored variants only. Standalone catalogs (`CICDActionAudit`, `TodoCatalog`) do not extend the base and are not covered by these rules; `TodoCatalog` is checked by todo_sync rules T6-T10.

- Validates against the relevant variant schema (which `allOf`-includes `SymbolCatalog.base.schema.json`)
- `categories[].id` values are referenced by `category_id` on every entry
- Entry `kind` values come from the variant's enum (variants narrow the base enum to their domain)
- For Decompose: `disposition: keep_and_relocate` requires `confidence` AND at least one entry in `relocation_candidates` (or honest `confidence: needs_review` with empty candidates)
- For ConsumerAudit: every consumer has `role`, `risk_if_changed`, and `evidence` (raw line/grep result, not a summary)

---

## Conventions

- **Naming:** `PascalCase.schema.json` for new schemas. Variant catalogs use a sub-namespace (`<Purpose>.catalog.schema.json`). Naming exception: `TodoCatalog.schema.json` is standalone and has no `.catalog.` sub-namespace, named for the artifact it describes.
- **`$ref` form:** Bare relative paths between sibling schemas (e.g., `"$ref": "SymbolCatalog.base.schema.json"`). No leading `./`. No `$id`-by-bare-token.
- **`$id` form:** when declared, `https://github.com/t968rs/operator-straps/plugins/harness/schemas/<path relative to this directory>`. Never a `file:///` path or a consuming project's URL.
- **Schema dialect:** `https://json-schema.org/draft/2020-12/schema` for new schemas. PR_REVIEW.schema.json is on draft-2020-12 as of PR #1216. ActionPlan.schema.json and prAttributes.schema.json remain on draft-07 pending separate migrations.
- **Update protocol:** When changing any schema file under this directory, update this README in the SAME PR. Mismatched README + schema is a discipline failure.

## Updates & Extensibility

To change a schema (new field, enum value, required-set change):

1. Edit the `.schema.json` file
2. Update this README's relevant section
3. Update the harness rules if the change affects an agent-facing rule
4. Update the relevant skill's SKILL.md if it pins the schema
5. Run validation against existing artifacts in the project's review and plan directories to catch breakage

Existing artifacts validate as-is unless their schema's required-set is widened. Backwards-incompatible changes require a coordinated sweep of historical artifacts or a schema-version bump.
