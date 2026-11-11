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

**Applies to:** `<reviews dir>/{NNNN}_{Title}.json` (4-digit zero-padded PR number) and `<reviews dir>/LOCAL_<label>_<slug>.json` (a review-local run keyed `local-<label>`); `<reviews dir>` is the project's `artifacts.reviews`.

Structure of an agent code-review verdict:

- PR metadata (number, title, branch, base/head SHAs, review_date, reviewers)
- Root metadata (REQUIRED): `schema_ref` (repo-relative path to canonical schema) + `version` (semver, currently "2.2.0")

**Version bump protocol:** any change to the schema that breaks existing PR_REVIEWS JSONs (new required field, type change, removed property) requires a major version bump. `2.0.0` reflects the `fix: string → array[string]` migration completed in PR #1216; `2.1.0` adds the optional issue field `fix_kind` (non-breaking, so no sweep); `2.2.0` adds the optional `stats.source` sub-object (non-breaking, so no sweep). When bumping a major version, sweep all existing PR_REVIEWS JSONs in the same PR.

- Aggregated stats (additions, deletions, files_changed), plus the optional `source` sub-object: the same three counts without the machine-generated paths (the project's exclusions file plus the harness output patterns, both off when `exclusions` is null, and the Artifact commit bucket)
- `verdict` — must match `^(READY TO MERGE|NOT READY TO MERGE)(.*)$`. The string `NEEDS FIXES` is NOT permitted; that wording exists only in skill prose.
- `strengths` — bullet observations (specific, not vague praise)
- `issues` — categorized object (`{critical, important, minor}`), each issue with `id`, `name`, `summary`, `file` and/or `files` (at least one), `fix[]` (array of one-or-more remediation options; each entry is a self-contained alternative; was string pre-PR-1216), and optional `lines`, `step`, `reviewer`, `both_reviewers`, `fix_kind` (`mechanical` | `judgment`; routes the Phase 5 fixer model)
- `bubble_up` — flat array of issues that exit Phase 5 unresolved, each item `{id, classification, reason}` where `classification` ∈ `{architectural_ambiguity, out_of_scope, needs_follow_up, fixer_failed}`. Mirrors the items[] shape of the pr-team skill's `bubble_ups.schema.json` sidecar. Empty array means Phase 5 closed cleanly. *(Naming note: singular `bubble_up` in PR_REVIEW because the field is the array itself; plural `bubble_ups` in pr-team because the file is the sidecar container holding `items[]`.)*
- `post_review_resolutions` — when issues are addressed in-session, append entries with `status` ∈ `{RESOLVED, DOWNGRADED_TO_*, CLOSED_NO_ACTION}` and recompute `verdict` in the same write

### 2. `ActionPlan.schema.json`

**Applies to:** `docs/PLANS/{NNNN}_ActionPlan.json` and `docs/PLANS/{NNNN}_*_ActionPlan.json`.

**Generated, never edited.** The pydantic models in `plugins/harness/lib/harness_lib/plan_models.py` are the one definition of a plan; `tools/gen_plan_schema.py` writes this file from them (draft 2020-12) and `tests/contract/test_plan_schema_generated.py` fails when the committed file drifts. `plan.py` validates through the models; the `validate_pr_json_schema.py` hook validates plan writes against this file, or a project's pinned copy.

Execution tracking:

- `plan_id` (4-digit zero-padded), `plan_created`, `execution_model` (`sequential` / `parallel_worktrees`)
- `pr_attributes[]` — zero or more PR references (the `PrAttributes` model per element). Project-scoped plans (research, refactor, incident) may omit this entirely.
- `items[]` — one entry per action item, with `id`, `priority`, `title`, `action` (exact remediation steps), `files[]`, `status`, `evidence`; optional add-ons are `record` (the sealed record `plan.py record` writes), `verification_references[]` (legacy) + `markdown_section`
- Optional markdown sync metadata: `markdown_sync_status` + `markdown_last_updated`
- Plan-level fields written by `plan.py`: `base_commit` (merge base, `{base}` stands in for it in commands), `frozen` (tree, date, digest and the `records` scheme set by `plan.py freeze`; a first freeze stores `"receipts"`, and `"sealed"` or unset appears only on plans frozen before receipts; a plan with a ledger does not store it in the JSON, `plan.py` fills it from the last ledger `freeze` entry, and only a plan frozen before the ledger keeps the in-file stamp, with its commit), `ledger` (the stem `plan/<id>-<slug>` of the freeze ledger, set by the first ledger freeze), `completed`
- Design fields: `decisions[]` (open until `chosen` is set, which blocks freeze), `values[]` (thresholds with the options they assume), `formats[]` (literal layouts copied from a producer or parser), `sweeps[]` (searches `plan.py check` runs)
- Per-item fields: `model` (agent model for dispatch), `anchors[]` (line ranges checked against code), `commands[]` (commands with the output that means pass), `tests[]` (pytest node ids with the failure that precedes the fix)

The write-plan skill (`plugins/harness/skills/write-plan/SKILL.md`) and `plugins/harness/scripts/plan.py` own the authoring and checks for these fields. Agents author a plan through `harness_lib.plan_api` (`load`, change a copy with `model_copy(update=..., deep=True)`, `write`), which validates before it writes; plan JSON is not edited by hand.

**Status rules:**
- `COMPLETE` requires a sealed proof of the tested tree — never a claim. On a receipts plan the proof is the item's receipt (`<artifacts.plans>/NNNN/receipts/<ITEM>.json`) and the item stays `PENDING` in the JSON; on a plan frozen before receipts it is the item's `record` (legacy, on plans frozen before the record scheme: the `[<40-hex commit>, "tree <40-hex>"]` shape in `verification_references`)
- `CLOSED_NO_ACTION` requires written rationale
- `IN_PROGRESS` / `PENDING` are transient; every item must terminate in COMPLETE or CLOSED_NO_ACTION (in its receipt on a receipts plan, in the JSON on a plan frozen before receipts)
- Two record rules sit in the models only, since the generated schema cannot express them: a `commit` provenance names its commit and a `staged` one names none (checked when `plan.py` loads the plan), and an item's `status` agrees with its record's outcome (checked by `plan.py check`). The schema hook validates with `jsonschema` alone, so it passes a plan that breaks either rule

### 3. PR attributes (a model, no schema file)

**Applies to:** Each element of `ActionPlan.pr_attributes[]`.

Per-PR metadata: `pr` (number or string), `branch`, `base_branch`. Required when an ActionPlan is tied to one or more PRs. The `PrAttributes` model in `plan_models.py` defines it, and the generated plan schema carries it as a definition; there is no standalone schema file.

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

### 8. `SkillSpec.schema.json`

**Applies to:** The strap-skills design spec (`SkillSpec`): the model in `plugins/harness/lib/harness_lib/strap_models.py` that the skill-authoring driver reads and writes.

**Generated, never hand-edited.** The file is `strap_models.schema_text()` written by `tools/gen_skillspec_schema.py` (repo-only; `--check` exits 1 on drift). Regenerate after any model change; `tests/schemas/test_skillspec_schema_drift.py` pins the committed file to the generator byte for byte (CRLF folded to LF), so `pydantic` is pinned in `requirements-dev.txt`. Draft 2020-12, with `$schema` and `$id` first.

**Driver-owned markers:** top-level properties the driver writes (`strap_models.DRIVER_OWNED_TOP`) carry `driver_owned: true`; an author never sets them.

### 9. `agent_usage.schema.json`

**Applies to:** each line of the project's `agent_usage_path` (default `docs/_harness/agent_usage.jsonl`), JSONL: one row per returned Agent dispatch of any agent type (completed or errored; a denied dispatch writes none). Draft-07.

**Writer:** the `agent-watcher` mod, when the agent returns. A pr-review or pr-team dispatch belongs to its run; any other dispatch is a generic row whose `skill`, `role`, `run_id`, `agent_id` and `pr` come from the prompt's leading header block, with the remaining header keys in `fields`.

**Key fields:** `logged_at`, `run_id`, `pr`, `skill`, `role`, `agent_id`, `subagent_type`, `model`, `model_family`, `effort`, `tool_uses`, `duration_s`, `signal`, `notes`; cost columns `tokens` (input + output + cache read + cache creation, summed over every model request: what the run billed), `context_tokens` (the same four counts for the last request that reported usage; null when unknown) and `requests` (model requests the agent's loop made; null when none was heard). Fixer and closer rows also carry `issues_assigned`, `issues_fixed`, `issues_bubbled`, `files_touched`; other roles carry none of them.

**History:** rows written before agent-watcher 0.7.0 lack `context_tokens` and `requests`, and their `tokens` holds, for a foreground dispatch, the last request's count (what `context_tokens` now holds).

### 10. `pr_review_invocation_test_matrix.schema.json`

**Applies to:** each line of the project's `matrix_path` (default `docs/_harness/pr_review_invocation_test_matrix.jsonl`), JSONL: one row per reviewer subagent invocation or per end-to-end pr-review skill test cell. Draft-07.

**Writers:** the `agent-watcher` mod (`notes` starting `agent-watcher auto row`) and the pr-team orchestrator without the mod (its Step 5).

**Key fields:** `cell`, `pr`, `model_family` (`haiku` / `sonnet` / `opus`), `effort`, `dev_commit` (40-char merge-base SHA, optionally ` -- <suffix>`; freetext only on `legacy: true` rows), `dispatch_shape` (`parallel` / `inline`), `tokens`, `tool_uses`, `duration_s`, `findings_count`, `C_count` / `I_count` / `M_count` / `other_count`, `verdict_prefix`, `notes`.

**`tokens`:** input + output + cache read + cache creation. Watcher rows sum them over every model request of the invocation; watcher rows from before agent-watcher 0.7.0 hold, for a foreground dispatch, the last request's count, and nothing in the row dates them. Orchestrator rows carry the reviewer's self-reported figure, or 0.

### 11. `Receipt.schema.json`

**Applies to:** `<artifacts.plans>/NNNN/receipts/<ITEM>.json`, the sealed outcome `plan.py record` writes beside a plan frozen with the receipt scheme.

**Generated, never edited.** The pydantic models in `plugins/harness/lib/harness_lib/receipt_models.py` are the one definition of a receipt; `tools/gen_plan_schema.py` writes this file (draft 2020-12) and `tests/contract/test_evolution_receipt_schema_generated.py` fails when the committed file drifts.

**Key fields:** `plan_id`, `item`, `outcome` (discriminated on `kind`: `complete` with its `provenance` and optional passed `tests`, `started`, `blocked` with a `reason`, `closed` with a `rationale`), `evidence`, `date`, `seal`, and the optional `ref` and `deviations`. `deviations` lists the `extra_files` and test `substitutions` that differ from the item, each naming the `DesignChange` that allows it, plus `change_digests` (change id -> digest of that change). The seal is the SHA-256 of the receipt without the seal and the item's planned files and tests.

### 12. `FreezeLedgerEntry.schema.json`

**Applies to:** each file under `<artifacts.plans>/freezes/plan/<id>-<slug>/` and `<artifacts.plans>/freezes/skill/<name>/`, named `r<N>.<k>-<kind>.json`: the freeze ledger that `plan.py` and `strap.py` append to. A driver writes one file per `freeze`, `lock`, `unlock`, `arm`, `reopen` or `relink` and never rewrites it, so a folder is an append-only history; `N` is the round (a plan has only round 1) and `k` a sequence that counts across kinds.

**Generated, never edited.** The file is `LedgerEntry.model_json_schema()` from `plugins/harness/lib/harness_lib/freeze_ledger.py` (`schema_text()`, draft 2020-12, `$schema` and `$id` first), and `tests/lib/test_freeze_ledger.py` pins the committed file to the model. Closed (`additionalProperties: false`).

**Key fields:** `kind`, `round`, `seq` and `at` (ISO date-time) are required. `tree` (40-hex) is the git tree of the entry's scoped, not-gitignored file set (null on `unlock`, `arm`, `reopen`, `relink` and on history entries); `files` maps each tree member's repo path to its blob SHA, and `ignored` maps each gitignored file of the set to its sha256 (so the lock gate and `drift:` need no tree object); `base` is the round's base commit; `history` is true on an entry copied from a pre-ledger stamp (never tagged). Plan entries add `digest` and `records` (the freeze digest and record scheme); strap entries add `skill_hash` and `grader`, copied from the stamp in `SkillSpec.json`; `arm` adds `reason`; `relink` adds `old_base`, `new_base` and `match` (`patch-id` or `ref`).

**State:** a plan's state is the kind of its highest entry (`freeze` Frozen, `lock` Locked, `arm` Locked and armed, `unlock` editable again; `reopen` and `relink` leave the state as it was). A strap spec keeps its stamp in `SkillSpec.json` and reads only Locked from the ledger (the highest entry of its current round is a `lock`).

**Tags:** the same commands create annotated, local tags named for the entry: `base/<stem>/r<N>`, `freeze/<stem>/r<N>.<k>-tree`, `lock/<stem>/r<N>.<k>-tree` and the `-commit` tag of the commit that added the entry file (`.2`, `.3` after a rewrite), with `<stem>` as `plan/<id>-<slug>` or `skill/<name>`; `plan.py record` adds `receipt/<stem>/<ITEM>-commit|-tree`. Each command prints `tag:` lines and one `push: git push origin <names>` line, which never names a `receipt/` tag. Read a release version with `git describe --match 'v*'`, since driver tags sit on main-line commits.

**Lock guard:** the harness hook `guard_locked.py` denies Write, Edit and the Bash and PowerShell write shapes onto every file under `freezes/` and onto the files a Locked or armed subject's last `lock` entry lists under the plans folder. It is not registered on its own: the dispatchers `write_pretool.py` (Write|Edit, then `guard_commit_txt`), `bash_pretool.py` (Bash) and `powershell_pretool.py` (PowerShell, then `powershell_allow_shapes`) run it first, so a deny outranks any allow. A plan frozen with the `sealed` scheme or none keeps its plan JSON writable, since `record` still writes it. A developer's own edit is not blocked; `check` reports it as `drift:`.

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

Top-level fields (required): `generated`, `generated_from` (`description`, `head_sha`, optional `branch`), `ranking_method` (formula text, `impact_weights`, `loe_points`, `blast_factors`, `unblock_bonus`, `tie_breakers`, `impact_definitions`, `severity_scale`), `counts`, `items[]`, `trackers[]`, `close_candidates[]`; optional `$schema`, `retired_ids[]` (ids of retired or split items, never drawn again; `init` writes an empty list), `legacy_ids` (`migrated` date and `map` of rank-tied `TODO-NNN` id -> stable id, written by `todo_sync.py migrate-ids`; a rerun adds new legacy ids to the map and keeps the first migrated date) and `split_ids` (retired id -> its parts' ids, in spec order).

Per-item fields: `id` (`todo-k7qf`: `todo-` plus 4 random characters of `23456789abcdefghjkmnpqrstuvwxyz` holding a digit and a letter; stable, never renamed by a re-rank, retire or split, never reused once retired), `rank` (1-based position; changes on every re-rank), `title`, `kind`, `status` (`OPEN` / `PARTIAL` / `NEEDS_DECISION` / `BLOCKED`; no terminal status: finished work leaves the file), `needs_decision` + `decision_question`, `tracker`, `sources[]` (`gh_issue` / `impl_stub` / `research_folder` / `note`, the last a local-only item with no issue, `ref` the date added), `gh_issues[]`, `related_gh_issues[]`, `catalog_entry_ids[]`, `summary`, `proposed_change`, optional `code_snippet`, `files[]`, `blast_radius`, `loe`, `impact`, `severity`, `priority` (`score`, `components`), `depends_on[]`, `unblocks[]`, `why_ranked`.

Cross-record rules the schema cannot express that `todo_sync` rules T6-T10 check: unique ids absent from `retired_ids`, every `split_ids` key in `retired_ids` with each part an item or retired, ranks 1..n, `priority.score` and order recomputed with the fixed formula from the numeric `ranking_method` tables, mutual `depends_on` / `unblocks`, tracker membership, and `counts` tallies other than `sources_absorbed` and `merged_items`. Unchecked: `counts.sources_absorbed`, `counts.merged_items`, `close_candidates[].related_todo_ids` membership, and the sort order of `unblocks` and `related_todo_ids`. The `ranking_method` formula strings (`value`, `cost`, `score`, `tie_breakers`) are human-readable records; `todo_sync` never parses them. A catalog whose items still carry rank-tied `TODO-NNN` ids gets one T6 finding naming `todo_sync.py migrate-ids` (plus any duplicate ids); T1 drops the pattern errors those ids raise.

### `catalogs/DesignEvolutionCatalog.schema.json`

**Applies to:** `<artifacts.plans>/NNNN/DesignEvolution.json`, the design changes of one plan, written through `harness_lib.evolution_api`.

**Generated, never edited.** The models in `plugins/harness/lib/harness_lib/evolution_models.py` define it and `tools/gen_plan_schema.py` writes the file; `tests/contract/test_evolution_receipt_schema_generated.py` fails on drift.

**Base relationship:** Standalone, closed (`additionalProperties: false`). Plan-bound: `plan_id` (4 digits) is required, and `primary_documents` always holds the `plan`. A change requires `id` (`S`, `PR`, `P`, `EX` or `CX` plus a number), `discovered_by`, `phase`, `original`, `issue`, `new_outcome` and `why_new_outcome`, and carries `items[]` (the plan items it touches, default empty) and `date` (`YYYY-MM-DD`, default today). The `category_enums` block is gone: the issue categories are an enum in the models.

**Cross-record rules the schema cannot express:** unique change ids, each change's `original.doc` and `new_outcome.doc` naming a key of `primary_documents`, and summary finding ids that name a change are checked by the model validator (`evolution_models.DesignEvolution`), not by the generated schema. A tool that validates with the JSON schema alone accepts a catalog the models refuse; write through `evolution_api`.

---

## Workflow

### Step 1 — Review → PR_REVIEW.schema.json

Agent invokes `pr-review`. The skill orchestrates the review pipeline across five phases (Phase 1 dispatch prep, Phase 2 delegate, Phase 3 consolidate, Phase 4 branch safety, Phase 5 fix-application). The canonical phase-by-phase narrative lives in the pr-review skill's `SKILL.md` — this README is the JSON-shape contract, not a second copy of the flow.

The Phase 3 JSON must validate against `PR_REVIEW.schema.json`. Verdict re-evaluation is mechanical, not judgment — see the schema's `verdict` field rule and the skill's "Verdict re-evaluation rule" section. Phase 4 updates the `verification_log.pre_fix_time` block in the same file before any fix lands.

### Step 2 — Plan → ActionPlan + PIP (paired)

Agent invokes the `write-plan` skill (`plugins/harness/skills/write-plan/SKILL.md`):

```
Read docs/PR_REVIEWS/{NNNN}_*.json
  → plan.py new "<title>" --spec <path>       (creates the ActionPlan JSON and records the base commit)
  → plan_api.load("<id>")                     (author items, execution_model, pr_attributes[] as models)
  → plan_api.write(plan.model_copy(update=..., deep=True))   (validates, then writes)
  → plan.py check / red / freeze <id>         (freeze writes a ledger entry and tags its tree; see section 12)
  → plan.py lock <id>                         (only on the developer's explicit ask, after the developer commits the freeze)
  → plan.py render <id>                       (a frozen receipts plan: rebuilds live.js, and the HTML page only when missing; a plan frozen before receipts: rewrites the markdown PIP)
```

The ActionPlan JSON is never edited by hand: every change goes through `plan_api.write`, which validates the whole plan before it touches the file. The PIP is rendered from the JSON and never edited by hand: on a plan bound for receipts it is the `_PIP.html` page that `plan.py new`, `plan_api.write` and `plan.py freeze` write, with a derived `live.js` sidecar; on a plan frozen before receipts it is the markdown PIP.

### Step 3 — Execute → Status + Evidence (through `record`)

Agent executes the items (inline, or as `harness:parallel2` lanes from `plan.py lanes <id>`):

```
For each item:
  Execute steps → run tests → stage, or developer commits
  plan.py record <id> <ITEM> --sha <commit>   (COMPLETE: tests run at the commit; the record keeps commit and tree)
  plan.py record <id> <ITEM> --staged         (COMPLETE: tests run at a snapshot of the index; the record keeps the tree)
  plan.py record <id> <ITEM> --closed "<rationale>"   (CLOSED_NO_ACTION)
  plan.py render <id>                          (rebuilds live.js; a sealed plan's markdown PIP is rewritten; no checkbox is ticked by hand)
Before the merge:
  plan.py verify <id>                          (reruns the COMPLETE items' tests at HEAD; writes nothing)
```

On a receipts plan, `record` writes `<artifacts.plans>/<id>/receipts/<ITEM>.json` and rebuilds `live.js`, so the HTML PIP shows the new status without a render; the plan JSON and its page stay as frozen. A receipt that differs from its item (extra files, replaced test nodes) needs `--also` / `--substitute` plus a `--cite` of a change added to `<artifacts.plans>/<id>/DesignEvolution.json` through `evolution_api.add`.

`record` is the only way an item's status or evidence changes (in its receipt on a receipts plan, in the plan JSON on a plan frozen before receipts), and it seals every status it writes; it refuses a COMPLETE whose commit or index tree did not change the item's files or whose test nodes fail there. `COMPLETE` ← a sealed record of the tested tree, and the commit when there was one. `CLOSED_NO_ACTION` ← rationale, sealed. On a plan frozen with the record scheme, `check` refuses any status without a sealed record; a plan frozen before it still accepts the old `record --sha` shapes. `check` never compares a record with HEAD; `verify` answers whether the work is still in the code. Status is never a claim.

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
- Exactly one `docs/PR_REVIEWS/{NNNN}_*.json` file per PR (4-digit padded). **Known 5-digit-prefix exceptions:** `01039_*`, `01044_*`, `01047_*` are preserved as-is to keep historical cross-references (commits, issues, sibling docs) resolvable. The canonical predicate `is_review_artifact_name` (regex `^(\d{4}|LOCAL_<label>)_`, `<label>` being lower-case letters, digits and single hyphens) intentionally rejects 5-digit prefixes — these files are skipped by the validation hook by design. A review-local run (no PR) writes `LOCAL_<label>_<slug>.json` at the top of the folder, keyed `local-<label>`, and is validated the same way. New PR review files MUST use 4-digit padding; if a future PR number exceeds 9999, widen the digit branch of the predicate to `\d{4,5}` and document the migration here.

### ActionPlan JSON

- Linked to valid plan-level source docs (`source_document` and `documentation`) and PR linkage docs (`pr_attributes[].review_doc` / `pr_attributes[].pip_document`)
- Every issue from the review has a corresponding item
- On a receipts plan (`frozen.records` is `"receipts"`), the JSON stays as frozen: an item's status comes from its sealed receipt in `<artifacts.plans>/NNNN/receipts/`, and a deviation found during execution goes to `DesignEvolution.json` through `evolution_api.add` and is cited from the receipt, never written into the plan JSON
- On a plan frozen before receipts, the JSON is the source of truth for TODO and progress state; if execution deviates, JSON must be updated before completion claims
- On a plan frozen before receipts, `status: COMPLETE` always carries a sealed `record` (`items[].record`: the tested tree, the commit when there was one, the test run when the item has tests, and the seal). On a plan frozen before the record scheme (`frozen.records` unset), `plan.py check` instead accepts `verification_references` of the shape `[<40-hex commit>, "tree <40-hex>", ...]`; todo_sync rule P2, on any plan, accepts a commit SHA in `evidence` or `verification_references`, or a record shaped as a COMPLETE record (64-hex seal, provenance tree); it does not recompute the seal or read `frozen.records`, which `plan.py check` does
- `status: CLOSED_NO_ACTION` always carries rationale, sealed in its `record` on a plan whose `frozen.records` is `"sealed"`
- `verification_references[]` is the legacy proof list: `record` no longer writes it, and `plan.py check` reads it only on plans frozen before the record scheme (todo_sync rule P2 still reads it on any plan)
- On a plan with a Markdown PIP (frozen before receipts), `markdown_section` should point to the Markdown section that expands the JSON item's evidence/details
- `files[]` matches the actual changes in the recorded tree
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
- **Schema dialect:** `https://json-schema.org/draft/2020-12/schema` for new schemas. PR_REVIEW.schema.json is on draft-2020-12 as of PR #1216. ActionPlan.schema.json is generated on draft-2020-12 from the plan models.
- **Update protocol:** When changing any schema file under this directory, update this README in the SAME PR. Mismatched README + schema is a discipline failure.

## Updates & Extensibility

To change a schema (new field, enum value, required-set change):

1. Edit the `.schema.json` file. Exception: `ActionPlan.schema.json` is generated, never edited. Change `harness_lib/plan_models.py` (and `plan_enums.py` for an enum), then run `python tools/gen_plan_schema.py`; `tests/contract/test_plan_schema_generated.py` fails on drift.
2. Update this README's relevant section
3. Update the harness rules if the change affects an agent-facing rule
4. Update the relevant skill's SKILL.md if it pins the schema
5. Run validation against existing artifacts in the project's review and plan directories to catch breakage

Existing artifacts validate as-is unless their schema's required-set is widened. Backwards-incompatible changes require a coordinated sweep of historical artifacts or a schema-version bump.

---

## Migration

- **ActionPlan, model first (harness 0.43.0).** `prAttributes.schema.json` is retired and `ActionPlan.schema.json` is generated from the plan models. A project that pinned the old draft-07 `ActionPlan.schema.json` must drop the pin or replace it with a copy of the plugin's generated `ActionPlan.schema.json` (a consuming project never runs the generator). With only the old `ActionPlan.schema.json` pinned, the schema hook reports an unresolvable `$ref` and exits 1 (it used to exit 0 as a setup error). With the old `prAttributes.schema.json` pinned too, the pinned directory still registers it, so the `$ref` resolves and the hook keeps validating plan writes against the old draft-07 shape while `plan.py` validates through the models; drop both pins. `plan.py` ignores a pinned plan schema and validates through the models, so a project that pinned a looser `prAttributes` loses that override.
- **Receipts and a plan-bound DesignEvolution (harness 0.67.0).** `Receipt.schema.json` is new, and `catalogs/DesignEvolutionCatalog.schema.json` is regenerated from the models: `plan_id` is required, `primary_documents` always holds the `plan`, each change lists the plan `items` it touches, and `category_enums` is removed. A `DesignEvolution.json` kept beside the research notes no longer validates; move it to `<artifacts.plans>/NNNN/DesignEvolution.json`, add the `plan_id`, and drop `category_enums`. Every level is now closed, so also drop the top-level `$schema` and `_comment`; keep only `highest_impact_finding`, `most_embarrassing_finding` and `lessons` under `summary` (drop `total_changes_cataloged`, `by_phase`, `by_issue_category` and `by_why_new_outcome_category`, which `DesignEvolution.counts` computes); and move each prefix key of `id_conventions` under `id_conventions.prefixes`, renaming `id_conventions._comment` to `id_conventions.comment`. A project that pinned the old catalog schema must drop the pin or copy the plugin's. Plans frozen from this version render the PIP as HTML with a derived `live.js` sidecar; plans frozen earlier keep their markdown PIP.
- **Freeze ledger (harness 0.69.0).** `FreezeLedgerEntry.schema.json` is new, and a plan's freeze stamp moves from the plan JSON into the ledger. Nothing migrates at once: a plan frozen earlier keeps its in-file `frozen` stamp, `plan.py check` prints `legacy: plan <id> keeps an in-file stamp; migrates at its next refreeze`, and `plan.py lock` refuses it until the next `freeze --refreeze`, which writes a history entry for the old stamp, drops `frozen` from the JSON and sets `ledger`. A strap spec frozen earlier gets history entries for its stamps at its first ledger write. A project that pinned `ActionPlan.schema.json` must drop the pin or copy the plugin's, which now allows the `ledger` field. Plan numbers are drawn above every number on any local or remote-tracking branch and in any `*/plan/<no>-*` tag.
- **Every `plan.py` command validates.** `render`, `red`, `lanes` and `record` refuse a plan that does not validate, with the same `schema:` lines `check` prints; only `check` and `freeze` did before. A plan that fails to load is the one case for a hand edit: repair the JSON, then run `plan.py check`.
