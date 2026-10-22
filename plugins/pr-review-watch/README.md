# pr-review-watch

Run tracking for the harness plugin's `pr-review` and `pr-team` skills, written as a CLI plugin of function
hooks. It turns review rules that depended on the model remembering prose, or on a keyword heuristic, into
hooks over the structured state the skills already write.

Every hook fails open: an unreadable file, a malformed return block, a missing project root or a refused
host call degrades to "no run" or "no row". No hook blocks or fails a tool call, a turn or a stop on its own
error. The Stop guard blocks only on the condition below.

## Activation and configuration

The watch is active only in a project that holds `.claude/harness.json`, the harness plugin's per-project
configuration. Candidates follow the harness library's `project_root`: the git top level of the session cwd
(a linked worktree, or a subfolder of one), then `CLAUDE_PROJECT_DIR`, then the cwd itself; the first that
holds the file is the project root. Without the file every hook passes straight through. Configured paths
are joined to that root unless absolute.

An installed mod lives in its own plugin cache folder and cannot read the harness plugin's
`config/defaults.json`, so `hooks/config.ts` carries copies of the values it needs and merges the
project's `harness.json` over them (objects key by key, scalars replace; malformed JSON or a wrong-typed
value keeps the default):

| Key | Default | Used for |
|-----|---------|----------|
| `state_dir` | `.claude/state/harness` | Phase 5 sentinels in `<state_dir>/pr-review/`, pr-team runs in `<state_dir>/pr-team/_runtime/` |
| `matrix_path` | `docs/_harness/pr_review_invocation_test_matrix.jsonl` | the invocation matrix rows are appended to |
| `agent_usage_path` | `docs/_harness/pr_review_agent_usage.jsonl` | the agent usage rows are appended to |
| `artifacts.reviews` | `docs/PR_REVIEWS` | consolidated review JSON |
| `artifacts.scratch` | `docs/_scratch/pr_review` | pr-review run folders |
| `base_branch` | `null` | `dev_commit`'s merge base; null resolves `origin/HEAD`, else `main` |

`tests/mods/test_pr_review_watch_config_mirror.py` fails when `defaults.json` changes one of these values
without `config.ts` following.

## Rules it enforces

| # | Rule | Behavior |
|---|------|----------|
| R1 | Phase 5 must close before the session stops | A band above the prompt shows `PR #N · <phase> · K bubbled` while a run is active or a `<state_dir>/pr-review/.phase5_pending_<PR>` sentinel is hot (younger than 24 h, the harness `check_phase5_sentinel.py` rule). A hot sentinel for the run's PR follows the phase rather than replacing it (`PR #N · fixers 2/5 · Phase 5 pending · K bubbled`). The phase comes from the latest dispatch; for pr-review, the `phase` in the current run's `plan.json` wins when it is a known value. K for pr-review counts the review JSON's `bubbles[]` plus ids bubbled in the run's `fixes/*.json` that no `RESOLVED` / `CLOSED_NO_ACTION` resolution closes. Each prompt also carries `PHASE5_PENDING=<ids>` while sentinels are hot. |
| R2 | Matrix rows carry real `tokens` / `tool_uses` / `duration_s` | One row per reviewer, from engine-measured usage. |
| R3 | Rows validate against `pr_review_invocation_test_matrix.schema.json` before append | Validated in-process; an invalid row is not appended, is kept in `failures` and raised as a toast. |
| R4 | `model_family` is the family token | Token search over the resolved model id; an id with no `haiku` / `sonnet` / `opus` token fails R3. |
| R5 | `dev_commit` starts with the merge base against the base branch | Run by the mod: `git merge-base HEAD <base>`, written as `<sha> -- <branch> (pr-review-watch auto)`. |
| R6 | Bubbled issues are dispositioned in the review JSON before stopping | Two triggers, each blocking once (`stop_hook_active` lets the stop through). **State** (pr-team runs): every tracked bubbled id must appear in the run's review JSON `bubbles[]`, `bubble_up[]` or `post_review_resolutions[]` (the `id_handling.disposition_ids` rule). **Keyword** (any active review): when the last assistant message contains "bubble" (any case or inflection), the active review JSON's `bubbles[]` must be populated unless every issue is already dispositioned. |
| R7 | Every returned dispatch of a defined agent gets a usage row | One row per reviewer, fixer, orchestrator, planner and closer dispatch of a pr-review or pr-team run, and one per dispatch of any other agent the marketplace defines (`skill: standalone`, `role: other`). Written when the agent returns and validated against `pr_review_agent_usage.schema.json` before append; fixer and closer rows add `issues_assigned`, `issues_fixed`, `issues_bubbled` and `files_touched` (null when unknown). A denied dispatch writes none. |

The keyword trigger checks the **active** review: the tracked run's PR (its review JSON no older than the
run), or, with no tracked run, the PR of the first hot Phase 5 sentinel that blocks the stopping session.
Line 3 of a sentinel names the session that armed it; another session's sentinel is skipped, and an
unowned one (no line 3) counts for every session, the `check_phase5_sentinel.py` `blocks_session` rule. A
Stop input with no session id (or a blank one) fails closed: any hot sentinel counts. With neither, the
keyword checks nothing. The band still lists every hot sentinel. The text comes from the Stop input's
`last_assistant_message`, so no transcript is parsed.

## How a run is recognized

| Dispatch | Prompt header | Tracked as |
|----------|---------------|------------|
| pr-team orchestrator / fixer modes | `MODE=PLAN\|CONSOLIDATE\|CLOSEOUT`, `PR_NUMBER=`, `RUN_ID=`, `RUNTIME_DIR=` | `orchestrator_plan`, `orchestrator_consolidate`, `fixer_plan`, `closer` |
| pr-team reviewers and fixers | `AGENT_ID:`, `AGENT_ROLE:`, `RUN_ID:` (`canonical_prompt_template.md`) | the plan's agent id |
| pr-review reviewers and fixers | the same three lines plus `PR:` (rows printed by `pr_review.py capture` / `waves`) | the `AGENT_ID` |
| any other defined agent | none | a run of its own, `standalone_<UTC stamp>_<seq>`, agent id the type's name without its plugin prefix (`harness:messenger` is `messenger`) |

An `Agent` call without `RUN_ID` is ignored unless its `subagent_type` is a defined agent (`DEFINED_AGENTS` in
`hooks/contract.ts`: every file under a plugin's `agents/` folder, spelled `<plugin>:<name>`); a header that
fails to identify a defined agent (an unknown role or `MODE`) also falls back to a standalone run. Built-in
types (`Explore`, `general-purpose`, `Plan`) and other plugins' agents are never tracked. A standalone run
feeds only the usage log: it has no PR, no phase, no band entry, no matrix row and no Stop check, and its
state entry is dropped as soon as its usage row is attempted. A pr-team slot without `OUTPUT_FILE` is placed in
`<state_dir>/pr-team/_runtime/<RUN_ID>`. Return blocks are parsed per the pr-team skill's
`return_contract.md`: the last column-1 `---` fenced block that has a `SIGNAL:` line.

Usage comes from the `Agent` result when it ran in the foreground (`totalTokens`, `totalToolUseCount`,
`totalDurationMs`, `resolvedModel`). For a background launch, the mod counts the subagent loop's tool calls
and takes tokens (input + output + cache read + cache write), duration and the report from that loop's
`turn.complete`.

## Hooks

| Hook | Does |
|------|------|
| `tool.call` on `Agent` | Records the dispatch, folds the result, refreshes, and for pr-review reviewers appends the ownership note to the result's context once the run is recorded with a PR. |
| `tool.call` (any) | Counts tool calls per subagent loop id. |
| `tool.call` on `Bash` / `PowerShell` | After a command that names `pr_review.py`, refreshes, so the band follows the script's phases within a turn. |
| `turn.complete` | Completes a background subagent; on every turn end, refreshes and appends rows that became due. |
| `session.start` | Recovers pr-team runs a previous session claimed but never logged, then refreshes. |
| `prompt.submit` | Scans the sentinels and attaches `PHASE5_PENDING=<ids>` when the hot set changed since the line last attached. |
| `session.end`, `session.compact` | After `/clear`, a resume or a main compaction, the next prompt gets the `PHASE5_PENDING=` line again. |
| `classic.Stop` | Keeps a settings hook's block as is; otherwise blocks on R6. |
| `ui.render` `AbovePrompt` | Draws the band above whatever the hooks beneath drew (band-line's banner stays on screen); yields to a survey and passes when there is nothing to show. |

A refresh reads the hot sentinels, the active run's review JSON (the newest
`<artifacts.reviews>/<NNNN>_*.json` for its PR, and no older than the run), and `bubble_ups.json` in the
run's runtime dir. For a pr-review run it also reads `<artifacts.scratch>/<NNNN>/current`; only when that
names the run's `RUN_ID` does it read `<RUN_ID>/plan.json` (`phase`: a missing or unknown value is ignored)
and every `<RUN_ID>/fixes/*.json` (`bubbled[].id`). The latest `post_review_resolutions[]` status per id
decides whether it is closed.

A sentinel is hot by its line-2 unix stamp, else the listed file mtime, else the `stat` mtime.

| Phase | Band text |
|-------|-----------|
| `review` / `fix` | `reviewers k/n` / `fixers k/n` (tracked agents that returned, of those dispatched) |
| `plan`, `consolidate`, `fix-plan`, `closeout` | `planning`, `consolidating`, `fix planning`, `closeout` |
| `done` | the run is hidden; only a hot sentinel shows, as `PR #N · Phase 5 pending` |

## Matrix-row ownership

Rows go to `<matrix_path>` once the review JSON has a `READY TO MERGE` / `NOT READY TO MERGE` verdict and
every tracked reviewer has returned. `cell` is `pr<N>_<agentId>`, `dispatch_shape` is `parallel`,
`other_count` is 0 and `phase4_script` is null. Each reviewer is attempted once. A matrix file that exists
but cannot be read (a lock, an OS refusal, over the 4 MiB read limit) is never rewritten: its rows go to
`failures` as `matrix unreadable; not overwritten` and are toasted.

- **pr-team.** When the orchestrator PLAN returns DONE, the mod writes `<runtime_dir>/.matrix_owner` with
  `pending`. It rewrites the marker to `logged <iso time>` after the append. The `pr-team-orchestrator`
  agent's Step 5 skips when the marker exists. If a session ends between the reviewer returns and the
  consolidation, the next `session.start` rebuilds the run from `dispatch_plan_review.json` and
  `terminals.jsonl` under `<state_dir>/pr-team/_runtime/`. It writes those rows with usage 0 and says so in
  `notes`. The rebuilt run starts at the `RUN_ID`'s UTC stamp, so a review JSON older than the run (an
  earlier review of the same PR) is never taken for its verdict; a `RUN_ID` without a valid stamp is not
  recovered.
- **pr-review.** Each tracked reviewer's `Agent` result (`AGENT_ROLE: reviewer`) carries
  `[pr-review-watch] Matrix rows for this run are recorded by the pr-review-watch mod; ...`, and pr-review
  Phase 3 Step 4 skips when that note was seen. The note is added only when the run was recorded in
  state with a PR; otherwise the skill's own append runs. Fixer results (`AGENT_ROLE: fixer`) never carry
  the note, even though their dispatch rows include the `PR:` header.

## Agent usage rows

Each tracked dispatch that returns appends one row to `<agent_usage_path>`: who ran (`role`, `agent_id`,
`subagent_type`, full `model` and its `model_family`, `unknown` when the id holds no family token), what it
cost (`tokens`, `tool_uses`, `duration_s`) and its `signal`. A standalone dispatch writes the same fields:
`skill: standalone`, `role: other`, `pr: null`, no count fields, and `signal: NO_BLOCK` for an agent that ends
without a return block, as most do. A synchronous result is logged when it
returns, a background agent when its loop turn ends; nothing waits for the verdict. A retried dispatch is a
second row. An errored result logs `signal: ERROR` with zero usage; a background turn with no usage logs
`tokens: 0` (the tool calls the mod counted and the turn's duration still land) with `usage not measured` in
`notes`; a denied dispatch never ran and logs nothing. A background loop that is interrupted or dies on an
API error is not told apart from a normal return: it logs the signal of its return block, `NO_BLOCK` when
it left none, never `ERROR`.

Fixer and closer rows carry outcome counts. A pr-review fixer reads `issue_ids` in the run's `waves.json`
and `fixed` / `bubbled` / the distinct edited `files` in `fixes/<agent_id>.json`, falling back to its return
block's `FIXED` / `BUBBLED` / `EDITED`; pr-team fixers and the closer count from the block, and their
`issues_assigned` is null. Reviewers a restarted session rebuilds from disk write no usage row. The file
follows the matrix's write rules: append-only, and a file that exists but cannot be read is never
rewritten (its rows go to `failures` as `usage log unreadable; not overwritten` and are toasted). The log
takes one row (about 450 bytes) per defined-agent dispatch, so it reaches the 4 MiB read limit
well before the matrix does; past it every row fails as unreadable. Move or archive the file when it nears
4 MiB; the next row recreates it.

## State

`$.state['pr-review-watch']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `runs` | Tracked runs by `RUN_ID` (a standalone run only while its agent is in flight): skill, PR, phase (dispatch-derived; for pr-review refined by the current run's `plan.json`), agents (subagent type, background launch model, usage, signal, counts, matrix and usage row attempt times), bubbled set and its source (`closer`, `bubble_ups`, or `review_json`: for pr-review the review JSON plus open fixer bubbles), verdict. |
| `active` | The pr-review or pr-team run dispatched most recently; a standalone dispatch never becomes active. |
| `loops` | Background subagent loop id to `[runId, agentId]`. |
| `failures` | The last 20 rows that failed validation or could not be written. |
| `phase5` | PR ids of hot Phase 5 sentinels. |
| `missing` | Tracked bubbled ids the active run's review JSON does not disposition. |

## Known limitations

- A pr-review run, or a pr-team run whose consolidation already logged, loses its tracker state when the
  process restarts. The band then shows only hot sentinels until the next dispatch.
- A background subagent's tool calls made before its launch result registered are not counted.
- A standalone row never says which skill or command dispatched the agent; only `subagent_type` and the
  time identify it.
- Workflow-run reviews are not tracked. Their agents raise `tool.call` and `turn.complete` with loop ids that
  no dispatch header names.
- Appends are a read and a whole-file write, serialized within the session. Two sessions appending to the
  same JSONL (matrix or usage log) at the same moment can lose a row.
- A git top level, once answered, is cached per cwd for the life of the hooks module; a worktree moved or
  removed mid-session keeps its old root until a reload. A cwd git fails on is asked again each time.
- `claude plugin test` covers Windows path spellings through the host's own `C:\...` paths; Linux runs only
  `/repo` paths.

## Checks

```
claude plugin validate <mod folder>
claude plugin test <mod folder>
tsc -p <tsconfig>   # the tsconfig in the header of the engine's claude-code.d.ts, kept outside this folder
```

`tests/mods/test_pr_review_watch_matrix_contract.py` pins `MATRIX_REQUIRED`, `MATRIX_OPTIONAL`,
`DISPATCH_SHAPES`, `DEV_COMMIT_PATTERN` and `MODEL_FAMILIES` to the harness plugin's
`schemas/pr_review_invocation_test_matrix.schema.json`; `tests/mods/test_pr_review_watch_usage_contract.py`
pins `USAGE_REQUIRED`, `USAGE_COUNT_FIELDS`, `USAGE_ROLES`, `USAGE_COUNTED_ROLES`, `USAGE_SKILLS`,
`USAGE_MODEL_FAMILIES` and `LOGGED_AT_PATTERN` to `schemas/pr_review_agent_usage.schema.json`, and
`DEFINED_AGENTS` to the agent files under `plugins/*/agents/` (a new agent file fails the test until the list
follows);
`tests/mods/test_pr_review_watch_config_mirror.py` pins the mirrored defaults. The plugin test sandbox
cannot read repository files.

## Loading

Install from the `operator-straps` marketplace:

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install pr-review-watch@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env`
block (or `claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces
the marketplace copy of the same-named mod, so it never runs twice. The variable is one string,
`;`-separated on Windows: append to its existing value rather than replacing it. The engine reads it only
from the process environment or the user settings `env` block, never from a project's settings.

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "C:\\path\\to\\operator-straps\\plugins\\pr-review-watch;C:\\path\\to\\operator-straps\\plugins\\git-status;C:\\path\\to\\operator-straps\\plugins\\session-bookmark"
  }
}
```

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
