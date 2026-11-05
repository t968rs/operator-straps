# agent-watcher

Renamed from `pr-review-watch` (0.6.0): enable `agent-watcher@operator-straps` and drop the old key. The usage
log default is now `docs/_harness/agent_usage.jsonl` (`git mv` the old log, or set `agent_usage_path`).

A usage row for every `Agent` dispatch and every forked skill (`context: fork`), and run tracking for the
harness plugin's `pr-review` and `pr-team` skills, written as a CLI plugin of function hooks. It turns review
rules that depended on the model remembering prose, or on a keyword heuristic, into hooks over the structured
state the skills already write.

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
`config/defaults.json`, so it carries copies of the values it needs (core keys in `hooks/core/config.ts`,
pr-review keys in `hooks/layers/pr-review/config.ts`) and merges the project's `harness.json` over them
(objects key by key, scalars replace; malformed JSON or a wrong-typed value keeps the default):

| Key | Default | Used for |
|-----|---------|----------|
| `state_dir` | `.claude/state/harness` | Phase 5 sentinels in `<state_dir>/pr-review/`, pr-team runs in `<state_dir>/pr-team/_runtime/` |
| `matrix_path` | `docs/_harness/pr_review_invocation_test_matrix.jsonl` | the invocation matrix rows are appended to |
| `agent_usage_path` | `docs/_harness/agent_usage.jsonl` | the agent usage rows are appended to |
| `artifacts.reviews` | `docs/PR_REVIEWS` | consolidated review JSON |
| `artifacts.scratch` | `docs/_scratch/pr_review` | pr-review run folders |
| `base_branch` | `null` | `dev_commit`'s merge base; null resolves `origin/HEAD`, else `main` |

`tests/mods/test_agent_watcher_config_mirror.py` fails when `defaults.json` changes one of these values
without the matching `config.ts` following.

## Layout

The mod is a generic **core** and one **layer** per skill it knows. Core tracks dispatches and logs usage;
a layer claims its skill's dispatches and adds what only it knows.

| Path | Holds |
|------|-------|
| `hooks/register.ts` | The composition root, the one file that imports both sides: `registerCore(on, LAYERS)`, then `registerPrReviewLayer(on)`. |
| `hooks/core/` | `layer.ts` (the `Layer` and `Io` contract), `tracker.ts` (`Agent` dispatches, loop ids, usage folding, the usage append, the per-run calls to the claiming layer, the refresh / Stop fan-out), `runs.ts` (pure dispatch and completion transitions), `contract.ts` (header, leading header block and return-block parsing, `DEFINED_AGENTS`, generated run ids, model family), `usageRow.ts` (rows, their validator, the unclaimed identity and the `fields` rule), `jsonl.ts` (validated appends, failures), `watch.ts` (project resolution and `ioOf`), `root.ts`, `config.ts`. |
| `hooks/layers/index.ts` | `LAYERS`, in claim order. |
| `hooks/layers/pr-review/` | `layer.ts` (`prReviewLayer`, `registerPrReviewLayer`), `identify.ts`, `runKey.ts`, `runs.ts`, `bubbles.ts`, `sentinels.ts`, `phase5Scan.ts`, `matrixRow.ts`, `band.tsx`, `config.ts`. |

No file under `hooks/core/` imports from `hooks/layers/` (`tests/mods/test_agent_watcher_layers.py`).

**The contract** (`hooks/core/layer.ts`). A `Layer` has a `name` and a pure `identify(subagentType, header,
watch)`, called once per `Agent` call in a harness project, in `LAYERS` order, with every header line of the
prompt and the resolved project. The first layer that returns a claim (run id, skill, agent id, role, run
key, phase) owns the run, recorded as its `claimedBy`. A dispatch no layer claims is an unclaimed run with
no claimer, which core logs from the header convention below; core tells the two apart by `claimedBy`
alone, never by the skill name.

Per-run members go only to the claiming layer, after core's own step: `foldRun(run, agentId, completion)`
(pure) inside the same state update that folds the completion into the agent, whether or not a project
resolves; `onComplete(io, run, agentId, completion)` for side effects once that fold is stored;
`rowFields(io, run, agent, completion)` for a usage row's outcome counts; `resultContext(io, run, claim,
result)` for lines appended to a successful `Agent` result's `context`. Every-layer members go to each layer
in order: `onSettle(io, run)` with the active run on core's refreshes (after a claimed dispatch, on every turn
end, before the Stop check) and `stopReason(io, stop)` after that refresh at Stop (the first reason blocks).
A layer's own hooks may settle it alone: pr-review's shell and session-start refreshes call only its own
`onSettle`. A member that throws counts as no answer; the next layer and core's own step still run.

**`Io`, not the engine.** The engine refuses `$` handed to a method of an imported object, so layer members
never receive it (a layer's own hooks get it from the engine and reach `Io` through `ioOf`). Core builds an
`Io` in the function declaration `ioOf($, watch)` (`hooks/core/watch.ts`):
closures for file reads, listings, writes, git, toasts, the clock, and one reader or writer per state key
(the engine reads only atoms it can see in place, so state is named, not generic). Any function that takes
`$` is a function declaration: the engine follows `$` past an import only into one.

**Adding a layer.** Create `hooks/layers/<name>/layer.ts` exporting a `Layer` and, when it raises hooks of
its own (a band, a prompt line, a shell refresh), a `register<Name>Layer(on)`; append the layer to `LAYERS`
and call its register function in `hooks/register.ts`. The engine also refuses `on` passed through an object,
so a registry loop over `LAYERS` cannot register hooks. Keys it reads from `harness.json` go in its own
`config.ts`, read from the parsed file `Watch.harness`, with a mirror test.

A run's `skill` and a row's `role` are open names (the usage schema's `SKILL_PATTERN` and `ROLE_PATTERN`), so
a new layer needs no vocabulary change for them. A second layer today still touches:

- the `Dispatch` fields `pr`, `runtimeDir` and `phase` (`hooks/core/contract.ts`), which every claim fills in
  and the `Run` keeps, whether or not the layer has a use for them;
- per-layer state: a key in `types/index.d.ts` and new members on `Io` built in `ioOf`, since the engine
  refused a generic atom read through `Io` ("the state library's read takes a source the scan can read: a
  reference whose plugin and key are string literals, or what atom, memberOf or derive ... made of one").

## Rules it enforces

| # | Rule | Behavior |
|---|------|----------|
| R1 | Phase 5 must close before the session stops | A band above the prompt shows `PR #N · <phase> · K bubbled` while a run is active or a `<state_dir>/pr-review/.phase5_pending_<PR>` sentinel is hot (younger than 24 h, the harness `check_phase5_sentinel.py` rule). A hot sentinel for the run's PR follows the phase rather than replacing it (`PR #N · fixers 2/5 · Phase 5 pending · K bubbled`). The phase comes from the latest dispatch; for pr-review, the `phase` in the current run's `plan.json` wins when it is a known value. K for pr-review counts the review JSON's `bubbles[]` plus ids bubbled in the run's `fixes/*.json` that no `RESOLVED` / `CLOSED_NO_ACTION` resolution closes. Each prompt also carries `PHASE5_PENDING=<ids>` while sentinels are hot. |
| R2 | Matrix rows carry real `tokens` / `tool_uses` / `duration_s` | One row per reviewer, from engine-measured usage; `tokens` is the summed figure of [Usage figures](#usage-figures) (before 0.7.0 a foreground reviewer's was its last request's count). |
| R3 | Rows validate against `pr_review_invocation_test_matrix.schema.json` before append | Validated in-process; an invalid row is not appended, is kept in `failures` and raised as a toast. |
| R4 | `model_family` is the family token | Token search over the resolved model id; an id with no `haiku` / `sonnet` / `opus` token fails R3. |
| R5 | `dev_commit` starts with the merge base against the base branch | Run by the mod: `git merge-base HEAD <base>`, written as `<sha> -- <branch> (agent-watcher auto)`. |
| R6 | Bubbled issues are dispositioned in the review JSON before stopping | Two triggers, each blocking once (`stop_hook_active` lets the stop through). **State** (pr-team runs): every tracked bubbled id must appear in the run's review JSON `bubbles[]`, `bubble_up[]` or `post_review_resolutions[]` (the `id_handling.disposition_ids` rule). **Keyword** (any active review): when the last assistant message contains "bubble" (any case or inflection), the active review JSON's `bubbles[]` must be populated unless every issue is already dispositioned. |
| R7 | Every returned `Agent` dispatch gets a usage row | One row per reviewer, fixer, orchestrator, planner and closer dispatch of a pr-review or pr-team run, and one per any other dispatch, of any agent type: this marketplace's agents, built-ins (`Explore`, `general-purpose`, `Plan`) and other plugins' agents, its values read from the header convention below, and one per forked skill run ([Forked skills](#forked-skills)). Written when the agent returns and validated against `agent_usage.schema.json` before append; fixer and closer rows add `issues_assigned`, `issues_fixed`, `issues_bubbled` and `files_touched` (null when unknown). A denied dispatch writes none. |

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
| pr-review reviewers and fixers | the same three lines plus `PR:` (rows printed by `pr_review.py capture` / `waves`); `PR:` holds the run key, a PR number or `local-<label>` | the `AGENT_ID` |
| any other dispatch, of any agent type | the header convention below, or none | an unclaimed run of its own |
| a forked skill (`context: fork`), by the Skill tool or a typed `/<skill>` | none: no `Agent` call is made | an unclaimed run under its skill ([Forked skills](#forked-skills)) |

The pr-review layer refuses a header whose `SKILL:` line is present and names neither `pr-review` nor
`pr-team`: another skill may print `RUN_ID`, `AGENT_ID` and `AGENT_ROLE: reviewer` without its dispatch
becoming a pr-team run. A header that fails to identify a layer's run (an unknown role or `MODE`) is an
unclaimed run too. A pr-team slot without `OUTPUT_FILE` is placed in `<state_dir>/pr-team/_runtime/<RUN_ID>`.
Return blocks are parsed per the pr-team skill's `return_contract.md`: the last column-1 `---` fenced block
that has a `SIGNAL:` line.

### The header convention

Every `Agent` call is tracked: this marketplace's agents (`DEFINED_AGENTS` in `hooks/core/contract.ts`, kept
as data), built-ins (`Explore`, `general-purpose`, `Plan`) and other plugins' agents. A dispatch no layer
claims reads the prompt's **leading header block**: the run of uppercase `KEY: value` (or `KEY=value`) lines
at its top, ending at the first line that is not one, so a `SIGNAL:`-style line in the prompt's body never
counts. Core reads five keys from it; each value that fails its rule falls back instead of failing the row:

| Key | Row column | Kept when | Else |
|-----|------------|-----------|------|
| `SKILL` | `skill` | after a leading `<plugin>:` is stripped (`harness:strap-skills` logs `strap-skills`), it matches `^[a-z][a-z0-9-]*$` | `standalone` |
| `AGENT_ROLE` | `role` | it matches `^[a-z][a-z0-9_-]*$` and is not `fixer` or `closer` (their counts need a layer) | `other` |
| `RUN_ID` | `run_id` | it holds no `/` or `\` | the generated `standalone_<UTC stamp>_<seq>` |
| `AGENT_ID` | `agent_id` | it holds no `/` or `\` | the type's name without its plugin prefix (`harness:messenger` is `messenger`; `general-purpose` when the call names none) |
| `PR` | `pr` | it is a positive integer | null |

Every other key of the block, and each of the five whose value fell back, lands in the row's **`fields`**
object, value as written (trimmed). No local or absolute path enters the log: a value holding `/` or `\` is
dropped with its key, and any other value is cut to 200 characters (197 and `...`). `fields` is absent when
empty, and a layer's rows never carry it, so pr-review and pr-team rows are unchanged. The same rule holds
for the columns: a return block's SIGNAL holding a separator logs as `UNRECOGNIZED` (and so does `notes`,
built from it), any other SIGNAL is cut to 200 characters, and the validator and the schema refuse a row
whose `run_id`, `agent_id`, `signal` or `notes` holds a separator.

An unclaimed run's state entry is keyed by its generated id whatever its header `RUN_ID`, so parallel
dispatches under one `RUN_ID` keep separate entries and each logs its own row. It feeds only the usage log:
no band entry, no active-run change, no layer refresh, no matrix row and no Stop check, and its state entry
is dropped as soon as its usage row is attempted.

### Forked skills

A skill whose frontmatter sets `context: fork` runs in a subagent loop of its own (the type its `agent:` key
names, such as `harness:messenger` for `c-msg`, `branch-commit-msg`, `merge-commit-msg` and `pr-sum`). The
engine launches that loop without an `Agent` call, raises no `agent.spawn` for it, and a typed `/<skill>`
raises no Skill tool call either; only the loop's own `turn.step`, `tool.call` and `turn.complete` reach the
mod. On a loop's first model request the mod looks the loop up once in `$.agent.list()` (a lookup the list
refuses is retried on the next request, at most 3 lookups per loop): an entry described as `/<skill>`, one
token, is a forked skill unless an `Agent` call with that same `description` is still in flight or its
result not yet recorded, which makes it that call's loop. The loop
becomes an unclaimed run with `skill` read as a `SKILL:` header line would be (`/harness:c-msg` logs `c-msg`;
a name off the pattern logs `standalone` and lands in `fields`), `agent_id` and `subagent_type` from the
entry's agent type, and it is registered as a background launch is, so its `turn.complete` writes the row
with the background figures below. Whether the fork ran in the background or not makes no difference. A
fork resumed after its loop ended is looked up again and logs a second row. The project is resolved only for
a loop the list names as a fork, so outside a harness project a fork is looked up but never logged.

### Review-local runs

A run of the harness `review-local` skill is keyed by `local-<label>` instead of a PR number (label:
lower-case letters, digits and single hyphens, at most 48 characters; `hooks/layers/pr-review/runKey.ts` mirrors
`harness_lib.review_local_models`, pinned by `tests/mods/test_local_run_key_mirror.py`). Its `RUN_ID` is
`local-<label>_<UTC stamp>`, its run folder `<artifacts.scratch>/local-<label>/`, its review JSON
`<artifacts.reviews>/LOCAL_<label>_*.json` and its sentinel `.phase5_pending_local-<label>`. The band and the
Stop text name it `local review local-<label>` where a PR run reads `PR #N` (`local review local-x · reviewers
1/3`, `local review local-x · Phase 5 pending`). Phase, bubbled set, Phase 5 state, usage rows and the Stop
guard work as for a PR run; a usage row logs `pr: null` (its `run_id` carries the key). **No matrix rows** are
written and reviewer results carry no ownership note: the matrix schema keys rows by PR number.

## Hooks

| Hook | Does |
|------|------|
| `tool.call` on `Agent` | Records the dispatch, folds the result, refreshes, and for pr-review reviewers appends the ownership note to the result's context once the run is recorded with a PR. |
| `tool.call` (any) | Counts tool calls per subagent loop id. |
| `turn.step` | Once a subagent's model request has streamed through untouched, counts it in that loop's tally and adds its usage (summed, and the last request). On a loop's first request (the next request when the list refuses), registers a forked skill's loop. The main loop's requests are skipped. |
| `tool.call` on `Bash` / `PowerShell` | After a command that names `pr_review.py`, refreshes, so the band follows the script's phases within a turn. |
| `turn.complete` | Completes a background subagent or a forked skill; on every turn end, refreshes and appends rows that became due. |
| `session.start` | Recovers pr-team runs a previous session claimed but never logged, then refreshes. |
| `prompt.submit` | Scans the sentinels and attaches `PHASE5_PENDING=<ids>` when the hot set changed since the line last attached. |
| `session.end`, `session.compact` | After `/clear`, a resume or a main compaction, the next prompt gets the `PHASE5_PENDING=` line again. |
| `classic.Stop` | Keeps a settings hook's block as is; otherwise blocks on R6. |
| `ui.render` `AbovePrompt` | Draws the band above whatever the hooks beneath drew (band-line's banner stays on screen); yields to a survey and passes when there is nothing to show. |

A refresh reads the hot sentinels, the active run's review JSON (the newest
`<artifacts.reviews>/<NNNN>_*.json` for its PR, `LOCAL_<label>_*.json` for a local key, and no older than
the run), and `bubble_ups.json` in the run's runtime dir. For a pr-review run it also reads
`<artifacts.scratch>/<NNNN>/current` (`local-<label>/current` for a local key); only when that
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
  `[agent-watcher] Matrix rows for this run are recorded by the agent-watcher mod; ...`, and pr-review
  Phase 3 Step 4 skips when that note was seen. The note is added only when the run was recorded in
  state with a PR; otherwise the skill's own append runs. Fixer results (`AGENT_ROLE: fixer`) never carry
  the note, even though their dispatch rows include the `PR:` header.

## Agent usage rows

Each tracked dispatch that returns appends one row to `<agent_usage_path>`: who ran (`role`, `agent_id`,
`subagent_type`, full `model` and its `model_family`, `unknown` when the id holds no family token), what it
cost (`tokens`, `context_tokens`, `requests`, `tool_uses`, `duration_s`, defined under
[Usage figures](#usage-figures)) and its `signal`. An unclaimed dispatch writes the same fields,
with `skill`, `role`, `run_id`, `agent_id` and `pr` from its header (with no header: `skill: standalone`,
`role: other`, `pr: null`), no count fields, its header `fields`, and `signal: NO_BLOCK` for an agent that
ends without a return block. A synchronous result is logged when it returns, a background agent when its loop
turn ends, and a forked skill when its loop turn ends; nothing waits for the verdict. A retried dispatch is a
second row. An errored result logs `signal: ERROR` with zero usage and `context_tokens` and `requests` null;
a foreground result with no request heard, or a background turn with no usage, logs `tokens: 0` (the tool
calls and duration still land) with `usage not measured` in `notes`; a denied dispatch never ran and logs
nothing. A background loop that is interrupted or dies on an API error is not told apart from a normal
return: it logs the signal of its return block, `NO_BLOCK` when it left none, never `ERROR`.

Fixer and closer rows carry outcome counts. A pr-review fixer reads `issue_ids` in the run's `waves.json`
and `fixed` / `bubbled` / the distinct edited `files` in `fixes/<agent_id>.json`, falling back to its return
block's `FIXED` / `BUBBLED` / `EDITED`; pr-team fixers and the closer count from the block, and their
`issues_assigned` is null. Reviewers a restarted session rebuilds from disk write no usage row. The file
follows the matrix's write rules: append-only, and a file that exists but cannot be read is never
rewritten (its rows go to `failures` as `usage log unreadable; not overwritten` and are toasted). The log
takes one row (about 450 bytes, more with `fields`) per `Agent` dispatch or forked skill run, so it reaches
the 4 MiB read limit well before the matrix does; past it every row fails as unreadable. Move or archive the
file when it nears 4 MiB; the next row recreates it.

### Usage figures

Two token figures, each input + output + cache read + cache write. **`tokens`** is summed over every model
request the agent made, what the run billed; **`context_tokens`** is the last request alone, the agent's
context size at the end and the figure its completion notification shows. A long agent's `tokens` runs
several times its `context_tokens`, since every request re-reads the cached context.

- **Foreground:** `tokens` sums the requests the mod heard on `turn.step` for the result's loop id;
  `context_tokens`, tool calls, duration and model come from the `Agent` result (`totalTokens`,
  `totalToolUseCount`, `totalDurationMs`, `resolvedModel`). With no request heard, `tokens` is 0 and the row
  says `usage not measured`.
- **Background** (a background `Agent` launch or a forked skill): the mod counts the loop's tool calls, and
  takes `tokens` (the turn's requests summed), duration and the report from its `turn.complete`;
  `context_tokens` is the last request heard on `turn.step` that reported usage, null when none did. When
  `turn.complete` carries no usage, `tokens` falls back to the requests heard on `turn.step` summed, and the
  row says `usage not measured` only when none of them reported usage either.
- **Loop tallies:** the per-loop request tally is dropped once the loop's result or registered loop end is
  folded. A loop never folded (an errored dispatch whose result names no loop, an unregistered background
  launch) stays in memory until evicted: the mod holds at most 256 loop tallies, dropping the least recently
  stepped first.

**`requests`** counts the model requests the loop made (every `turn.step` heard for it, with or without
usage); null when none was heard. A request is one call to the model: the conversation so far goes out, one
reply comes back. Tools run between requests, and one reply may ask for several, so `requests` is not
`tool_uses`. `tokens` divided by `requests` is the mean request size when every request reported usage.

Before 0.7.0 a foreground row's `tokens` held the result's `totalTokens` (the last request's count, now
`context_tokens`), and a background row's the summed figure. Rows written before 0.7.0 keep that mixed
meaning and carry neither `context_tokens` nor `requests`. Matrix rows follow the same change: a foreground
reviewer's matrix `tokens` before 0.7.0 is its last request's count.

## State

`$.state['agent-watcher']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `runs` | Tracked runs by `RUN_ID`, or by the generated id of an unclaimed run (held only while its agent is in flight, with its logged `logRunId` and `fields`): skill, PR, phase (dispatch-derived; for pr-review refined by the current run's `plan.json`), agents (subagent type, background launch model, usage, signal, counts, matrix and usage row attempt times), bubbled set and its source (`closer`, `bubble_ups`, or `review_json`: for pr-review the review JSON plus open fixer bubbles), verdict, and the claiming layer's name (`claimedBy`; unset for an unclaimed run). |
| `active` | The pr-review or pr-team run dispatched most recently; an unclaimed dispatch never becomes active. |
| `loops` | Background subagent or forked skill loop id to `[runId, agentId]`. |
| `failures` | The last 20 rows that failed validation or could not be written. |
| `phase5` | Run keys (PR numbers or `local-<label>`) of hot Phase 5 sentinels. |
| `missing` | Tracked bubbled ids the active run's review JSON does not disposition. |

## Known limitations

- A pr-review run, or a pr-team run whose consolidation already logged, loses its tracker state when the
  process restarts. The band then shows only hot sentinels until the next dispatch.
- A background subagent's tool calls made before its launch result registered are not counted.
- A dispatch whose prompt opens with no `SKILL:` line logs `skill: standalone`; only `subagent_type`, the
  time and its other header `fields` identify it.
- Every `Agent` call resolves the project before passing on, since every call is tracked: a cached git top
  level, and in a harness project one more, uncached `git rev-parse --git-common-dir` (the Phase 5 sentinel
  root). Every subagent loop not already registered as a background launch costs one `$.agent.list()`
  lookup per run of turns (repeated while the list rejects, at most 3 lookups per loop); only a forked
  skill's loop resolves the project there too.
- Forked skills are told apart by how the engine describes their loop in `$.agent.list()` (`/<skill>`, as
  observed on Claude Code 2.1.318). An `Agent` call whose own `description` is a single `/token` is not taken
  for a fork while it is in flight or until its result is recorded (a background launch's loop is registered
  by then, and is skipped after that); a forked skill that starts while an `Agent` call with its exact
  `/<skill>` description runs logs no row. An engine that describes forks otherwise logs none. Before 0.8.0 forked skills logged no
  row at all.
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

`tests/mods/test_agent_watcher_matrix_contract.py` pins `MATRIX_REQUIRED`, `MATRIX_OPTIONAL`,
`DISPATCH_SHAPES`, `DEV_COMMIT_PATTERN` and `MODEL_FAMILIES` to the harness plugin's
`schemas/pr_review_invocation_test_matrix.schema.json`; `tests/mods/test_agent_watcher_usage_contract.py`
pins `USAGE_REQUIRED`, `USAGE_COUNT_FIELDS`, `USAGE_OPTIONAL`, `USAGE_COUNTED_ROLES`, `SKILL_PATTERN`,
`ROLE_PATTERN`, `FIELD_KEY_PATTERN`, `FIELD_VALUE_PATTERN`, `FIELD_VALUE_MAX`, `USAGE_MODEL_FAMILIES` and
`LOGGED_AT_PATTERN` to `schemas/agent_usage.schema.json`, and
`DEFINED_AGENTS` to the agent files under `plugins/*/agents/` (a new agent file fails the test until the list
follows);
`tests/mods/test_agent_watcher_config_mirror.py` pins the mirrored defaults. The plugin test sandbox
cannot read repository files.

## Loading

Install from the `operator-straps` marketplace:

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install agent-watcher@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env`
block (or `claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces
the marketplace copy of the same-named mod, so it never runs twice. The variable is one string,
`;`-separated on Windows: append to its existing value rather than replacing it. The engine reads it only
from the process environment or the user settings `env` block, never from a project's settings.

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "C:\\path\\to\\operator-straps\\plugins\\agent-watcher;C:\\path\\to\\operator-straps\\plugins\\git-status;C:\\path\\to\\operator-straps\\plugins\\session-bookmark"
  }
}
```

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
