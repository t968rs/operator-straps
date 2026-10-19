# Kickoff: build the `todo-watch` mod and the harness `todo_sync` engine

Repo: `E:/automation/operator-straps` (marketplace: the `harness` plugin plus TypeScript mods).
Consumer used to prove it: `E:/automation/toolboxes/floodplain_development` (read-only for this work).

## Goal

Ship the MVP (Phases 0-2) of the design in `docs/plans/2026-10-17-todo-sync-mod.md`:

- A Python engine in the harness library (`harness_lib/todo_sync/` behind `plugins/harness/scripts/todo_sync.py`)
  that checks a project's TODO / research / plan JSON and their Markdown pairs for drift.
- A thin mod (`plugins/todo-watch/`) that shows a TODO summary toast, a drift line, and a `/todo` command, and
  runs the engine only after writes to watched files.

Phases 3-4 (GitHub issue reconcile, consumer Action) are out of scope for this pass. Stop after Phase 2 and report.

## Read first, in this order

1. `CLAUDE.md` and `README.md` (repo rules: config-key four-places rule, mod test runner, CI jobs, no repo
   literals in plugin code).
2. `docs/plans/2026-10-17-todo-sync-mod.md`: the design. Sections "Architecture" (files to add, config keys,
   mod state, schema v0), "Testing", "Phased rollout" and "Open decisions" are the build spec. It is untracked in
   the main checkout; carry it onto the work branch.
3. The mod precedents it cites: `plugins/git-status/` (smallest mod) and `plugins/pr-review-watch/` (config
   mirror, toast, `$.process.run`, per-module tests), plus `tests/mods/test_pr_review_watch_config_mirror.py`.
4. Harness config plumbing: `plugins/harness/config/defaults.json`, `config/harness.schema.json`,
   `lib/harness_lib/config.py`, `plugins/harness/hooks/hooks.json`, `plugins/harness/schemas/README.md`.

## Decisions: take the recommended defaults

All 14 open decisions (D1-D14) in the design doc take their recommended default. Do not reopen them; record any
place where the code forces a different choice, with the reason, in the design doc's decision table.

One decision the design doc does not cover, settle it this way:

- **The ranked TODO JSON is the source of truth once it exists.** The consumer's `RepoToDo.json` was bootstrapped
  by a one-off generator (see Port material). Do not port the generator's per-item override tables as code. The
  deterministic part, recomputing `priority.score` and `rank` from item fields per `ranking_method`, belongs in
  the engine. Either add a `todo_sync.py rank` subcommand or include it in a T-rule that reports rank drift; pick
  the smaller change and note it in the doc. Discovering items (reading issues, stubs, folders against code)
  remains agent work and is not part of the engine.

## Port material (consumer checkout, git-ignored)

`E:/automation/toolboxes/floodplain_development/scripts/_untracked/repo_todo/`:

| File | Use |
|---|---|
| `build_repo_todo.py` | Ranking formula (`ranking_method`), tie-breakers, cross-record checks. Port the scoring and validation; leave the per-item override tables behind |
| `validate_repo_todo.py` | Schema validation plus cross-record checks (unique ids, tracker membership, gh numbers): starting point for T1 and T6-T9 |
| `todo_table.py` | Top-N Markdown table: starting point for `render` |
| `refresh_catalog.py` | Catalog + stub merge logic, reference only (first-pass; re-running it undoes later fixes) |
| `wf1_results.json` | Real reader output; good fixture source for rule tests (trim it, never commit the whole file) |
| `workflows/*.js` | The agent workflows that produced the data (understand, write-review, adversarial review, fix-until-ready), for a later skill |

Live consumer artifacts to test against (read-only):

- `docs/RESEARCH/RepoToDo.json` + `RepoToDo.schema.json` (draft-07, closed, 89 items)
- `docs/RESEARCH/ResearchImplementationCatalog.json` + `.schema.json`, `docs/RESEARCH/**/_IMPL_TODO.md` (19 stubs)
- `docs/RESEARCH/TODO/TODO_Snapshot_2026_1017.md`
- `docs/PLANS/*_ActionPlan.json` + `*_PIP.md` pairs
- `scripts/__tests__/discipline/test_research_impl_catalog.py`: the consumer's existing S1-S3 gate (D14: mirror
  it, do not replace it)

## How to work

- Branch from `main` and follow this repo's CLAUDE.md for worktrees, commits and staging. The developer pushes.
  No history rewrites.
- Test-driven: each rule id gets a red then green test on a `make_project` tree before its implementation.
- Run tests by file, never by directory: the Python test files listed in the design doc's Testing table, ruff on
  changed files, the mod test runner on `plugins/todo-watch`, and strict manifest validation. Name each command
  and what it proves in the final report.
- Every new `todo.*` config key lands in all four places the repo's config rule names, plus the mod's mirrored
  defaults and the mirror test.
- Plugin code holds no consumer literals (`tests/contract/test_no_repo_literals.py` must stay green); consumer
  paths live only in test fixtures and in the example config block.
- Functions under 50 lines; `Optional` / `Union`, never `X | Y`; no first/second person in comments or
  docstrings; no AI vendor names in commits, PR text or shipped docs.
- Multi-phase work runs continuously: no pause for approval between Phases 0, 1 and 2.

## Acceptance (outcome behavior)

In the consumer checkout, after you add a `todo` block to a scratch copy of its `.claude/harness.json` (do not
edit the real one):

1. `todo_sync.py check --format markdown` runs in under ~2 s and reports 0 findings on the current tree.
2. Seeded drift is caught, one rule at a time:
   - a stub `status:` line changed (S rule)
   - an ActionPlan item set COMPLETE without a SHA (P rule)
   - a `RepoToDo.json` item edited so its score no longer matches `ranking_method` (T rule)
   - the snapshot's top-10 table out of order (T2)
3. `check --fail-on error` exits 1 on that seeded drift and 0 when it is clean.
4. At session start the mod shows one toast with counts and top-N and no drift section. After a watched write it
   updates. It toasts again only when drift rises or reaches zero. With `todo.catalog` null it does nothing.
5. A Write outside watched paths spawns no process (pinned by a mod test).
6. CI-equivalent runs are green: the named Python test files, the mod tests, strict validation, ruff.

## Report when done

- Status line, then the files added and edited, grouped by phase.
- Each test command with its pass count.
- Every place the code departs from the design doc, with the doc already updated to match.
- The example `todo` config block for the consumer, ready to paste.
- What Phase 3 needs first.
