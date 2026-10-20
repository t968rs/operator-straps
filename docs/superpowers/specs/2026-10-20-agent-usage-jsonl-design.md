# Agent usage JSONL for review runs

Date: 2026-10-20. Branch: `0016-agent-jsonl` (from `main` at `d9707cd`). Implements issue #10, narrowed by
the developer to usage telemetry plus fixer outcome counts.

**Status: frozen 2026-10-20 after the review patch.** This file is a snapshot of the design. The plan,
`docs/superpowers/plans/2026-10-20-agent-usage-jsonl.md`, is the source of truth from here on.

## Intent

After a pr-review or pr-team run, the developer wants to answer three questions from one file
(developer, 2026-10-20):

1. Which agent types and models ran.
2. How long each ran.
3. How many tokens each used.

Fixer outcomes ride along as counts only (developer: "add those fields as *counts* only").

Today `pr-review-watch` already tracks every agent of a run in its state (reviewers, pr-review fixers,
pr-team orchestrator plan / consolidate, planner, fixers, closer), with model, effort, tokens, tool count
and duration. It writes rows only for reviewers, only once the verdict lands
(`plugins/pr-review-watch/hooks/tracker.ts` `flushNow`), into the reviewer invocation matrix. Everything else
is dropped when the session ends.

## Decisions

### File and config key (author's call, not objected to)

- A **separate** JSONL: the agent usage log. The reviewer invocation matrix (`matrix_path`, its schema
  `pr_review_invocation_test_matrix.schema.json`, `matrixRow.ts` and its flush) stays exactly as it is: no
  existing row and no existing writer changes.
- New harness config key **`agent_usage_path`**, default `docs/_harness/pr_review_agent_usage.jsonl`, beside
  `matrix_path`. Per the repo rule it touches `plugins/harness/config/defaults.json`,
  `config/harness.schema.json`, the dataclass and builder in `lib/harness_lib/config.py`, the root README key
  table, the mirror in `plugins/pr-review-watch/hooks/config.ts` (`DEFAULT_AGENT_USAGE_PATH`, field
  `agentUsagePath`), and `tests/mods/test_pr_review_watch_config_mirror.py`. The pr-review-watch README
  key table gains the row too.
- The default `commit_buckets` `Artifact` rule in `defaults.json` gains the suffix `agent_usage.jsonl` beside
  `matrix.jsonl`, so `branch-commit-msg` buckets the log as an artifact, not as docs (author's call, after
  review); a case in `tests/lib/test_branch_commits.py` pins it.
- Write rules copied from the matrix writer (`writeRows` / `readMatrix` / `appendRows`): append-only, one
  compact JSON object per line, a missing file is created, a file that exists but cannot be read is never
  overwritten, rows that fail validation are not written and go to the `failures` atom with a toast.

### Which agents get a row

- **Every tracked agent, every role**: `reviewer`, `fixer`, `orchestrator`, `planner`, `closer`, for both
  `pr-review` and `pr-team`. Reviewers appear here and in the matrix; that duplication is the accepted cost of
  answering the three questions from one file.
- A roast is a reviewer slot; it is told apart by `subagent_type` (`harness:roast-my-code` in pr-team) or
  `agent_id` (the pr-review roast slot).
- **One row per completed dispatch.** A row is written when the agent's result is folded
  (`applyCompletion`: the synchronous Agent result, or the background loop's `turn.complete`). It does not
  wait for the verdict, the reviewers' settling or the closeout. A re-dispatch of the same agent id (a
  retry) is a second cost and gets a second row.
- **Which results count as a run agent** (author's call, after review). A row needs an agent that actually
  started:
  - synchronous Agent result with `status: completed`: a row, measured usage;
  - background loop `turn.complete`: a row; when the event has no `usage`, zero usage and the
    `usage not measured` note;
  - synchronous result that is an error (`isError`) or has a status other than `completed` /
    `async_launched`: a row with zero usage, `signal: ERROR` and the `usage not measured; agent errored`
    note (the agent may have run and cost something the engine did not report);
  - permission deny (`deny` set): **no row**; no agent started.
  `Completion` (or the call into the writer) therefore carries why it is unmeasured; the builder picks the
  shape.
- An agent whose completion the mod never sees (the session ended mid-run) gets no row.
- **Recovered pr-team runs** (author's call, after review): only the reviewers rebuilt from disk by
  `recoverRun` get no row (they never complete in the new session, so nothing extra is needed). Agents the new
  session dispatches into a recovered run (consolidate, planner, fixers, closer) are seen and measured live
  and get rows like any other. No `recovered` flag on `Run`.

### Row fields

Required on every row:

| Field | Type | Value |
|---|---|---|
| `logged_at` | string | ISO-8601 UTC time the row was built |
| `run_id` | string | the dispatch's `RUN_ID` |
| `pr` | integer >= 1, or null | the run's PR; null when unknown |
| `skill` | `pr-review` / `pr-team` | the run's skill |
| `role` | `reviewer` / `fixer` / `orchestrator` / `planner` / `closer` | the tracked role |
| `agent_id` | string | slot id, or `orchestrator_plan` / `orchestrator_consolidate` / `fixer_plan` / `closer` |
| `subagent_type` | string or null | the `Agent` call's `subagent_type`; null when absent |
| `model` | string or null | the resolved model id (engine), else the requested model, else null |
| `model_family` | `haiku` / `sonnet` / `opus` / `unknown` | the family token in `model`; `unknown` when none |
| `effort` | string | the requested effort, else `default` |
| `tokens` | integer >= 0 | input + output + cache read + cache creation, as the mod sums today |
| `tool_uses` | integer >= 0 | tool calls |
| `duration_s` | number >= 0 | wall clock, milliseconds / 1000 |
| `signal` | string | the return block's SIGNAL, `NO_BLOCK` when the agent returned without one, `ERROR` for an errored result |
| `notes` | string | `pr-review-watch auto row; <role> <signal>`, plus `; usage not measured` when the engine reported no usage, or `; usage not measured; agent errored` for an errored result. The matrix's `(session restarted mid-run)` clause is not used here: it is not the cause in this log |

Fixer and closer rows only (absent on other roles), each an integer >= 0 or null:

| Field | pr-review fixer | pr-team fixer | closer (pr-team) |
|---|---|---|---|
| `issues_assigned` | length of that fixer's `issue_ids` in the run's `waves.json` | null (the fix plan lists no ids per fixer) | null |
| `issues_fixed` | length of `fixed` in `fixes/<agent_id>.json` | count of `FIXED:` ids in the return block | count of `FIXED:` ids |
| `issues_bubbled` | length of `bubbled` in `fixes/<agent_id>.json` | count of `BUBBLED:` ids | count of `BUBBLED:` ids |
| `files_touched` | distinct `files` across the report's `fixed` entries | the block's `EDITED:` value | the block's `EDITED:` value |

- **Null means unknown, never zero** (author's call): a missing report, a block without the line, an
  unreadable `waves.json` all give null.
- **For pr-review fixers the report file wins over the return block** (author's call): a FAIL block carries
  no `FIXED` / `BUBBLED` lines but `fixes/<agent_id>.json` still records bubbles. When the report is
  missing or unparseable, fall back to the block's counts, then null.
- The pr-review files live in the run directory the mod already resolves (`prReviewRunDir`: the PR folder's
  `current` names the run); when `current` names a different run, the file counts are null and the block
  fallback applies.
- **`tests_run` is out this round** (developer, 2026-10-20: "drop it this round. maybe we follow-up"):
  nothing records the tests a fixer ran.

### Schema

- New `plugins/harness/schemas/pr_review_agent_usage.schema.json` (draft-07, `additionalProperties: false`):
  the required fields above on every row; the four count fields allowed only when `role` is `fixer` or
  `closer` (an `if` / `then` / `else` on `role`, or `oneOf` branches; builder's choice).
- The mod validates rows in TypeScript before writing, as `matrixRow.ts` does, in a new pure module beside
  it. Its required / optional field lists, role enum, skill enum and model family list are pinned to the
  schema by a new `tests/mods/test_pr_review_watch_usage_contract.py`, in the same style as
  `test_pr_review_watch_matrix_contract.py`.
- A schema test with valid and invalid example rows (each role, null pr, null counts, a count field on a
  reviewer row rejected), in the style of `tests/schemas/test_pr_review_invocation_test_matrix_schema.py`.

## Goals

- One JSONL answers: agent types and models, runtime, tokens, per agent, per run.
- Fixer and closer rows carry outcome counts.
- A pr-review run that dispatches reviewers, then fixers, yields one usage row per dispatched agent; a pr-team
  run and a roast run yield rows that validate against the new schema.

## Non-goals

- `tests_run` (follow-up).
- Ids lists of fixed or bubbled issues (counts only).
- Rows for review skills other than pr-review and pr-team.
- Rows for the main session's own usage.
- Backfilling rows for past runs, or for runs recovered after a restart.

## Anti-goals

- Any change to an existing matrix row, the matrix schema, the matrix writer or when it flushes.
- A usage row written twice for the same completion (parallel completions and overlapping refreshes must not
  double-append; the matrix's claim-then-write pattern and serialized flush tail apply).
- Overwriting a usage file that exists but cannot be read.
- Project paths or names inside the plugins (`tests/contract/test_no_repo_literals.py`).

## Constraints

- Repo rules in `CLAUDE.md`: the four-place config key rule plus the mod mirror; plugins stay generic; data
  goes to the project (`under(w.root, ...)`). Functions under 50 lines.
- Mod tests: `claude plugin test plugins/pr-review-watch`; manifests: `claude plugin validate --strict`.
  Python tests by file.
- Version bumps: `harness` minor (new key, new schema); `pr-review-watch` minor (new output file).

## Left to the builder

- Where the "logged" flag for usage rows lives on `AgentRec` (a second field beside `loggedAt`, or a
  per-completion counter); the anti-goal on double rows is what matters.
- How `subagent_type` reaches `AgentRec` (stored at dispatch, from the `tool.call` event).
- `if` / `then` vs `oneOf` in the schema.
- Reading `waves.json` and `fixes/<agent_id>.json` at completion time vs at flush time, as long as the counts
  reflect the files as they stand when the fixer returns.
