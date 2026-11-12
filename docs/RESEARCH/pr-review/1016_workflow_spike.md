# Plan 1016 SPK-1: workflow spike results

Run: workflow `wf_46bfd4df-48d`, task `wbbmy9jvt`, launched 2026-11-12T19:03:52Z (UTC, noted before launch).
`docs/_harness/agent_usage.jsonl` held 1020 lines before launch.

Inputs: `plugins/harness/workflows/spike-probe.js` (two probes `a`, `b` through `pipeline`; stage 2 returns
`null` for `b`) and `plugins/harness/agents/spike-probe.md` (one Bash echo, one Write). Launched with
scriptPath `<checkout>/plugins/harness/workflows/spike-probe.js` and
args `{"draftDir": ".../.claude/state/harness/spike1016"}`.

The prompt numbers assumptions 1-8 only through its parentheticals. The mapping below is inferred from them:
1 and 3 are the two roots (text and Bash), 2 is strict validation, 4 permission prompts, 5 the null stage,
6 the return timing, 7 the usage rows, 8 `workflowProgress`.

## Summary

| # | Assumption | Result |
|---|------------|--------|
| 1 | Text `${CLAUDE_PLUGIN_ROOT}` in an agent body resolves to the checkout | Confirmed: both probes echoed the checkout |
| 2 | `claude plugin validate --strict` accepts `workflows/` | Confirmed (given in the prompt, not re-run) |
| 3 | `$CLAUDE_PLUGIN_ROOT` in a subagent Bash call | Not set: `bash_root=` was empty for both probes |
| 4 | No permission prompt during the run | None observed |
| 5 | A `null` from a middle stage skips later stages and comes back `null` | Confirmed |
| 6 | Workflow tool returns at once with a task id | Confirmed |
| 7 | turn.complete writes a usage row per workflow agent | Refuted: zero rows appended |
| 8 | `workflowProgress` carries per-agent metrics | Confirmed (reference only) |

## 1. Text root (checkout or cache)

Both draft files carry the same line:

```
text_root=<checkout>/plugins/harness
```

The checkout, not `~/.claude/plugins/cache/...`. The scriptPath was the explicit checkout path, so the script
root is the checkout by construction; whether a bare `name` would resolve from the cache was not tested.
Whether the session was started with `--plugin-dir plugins/harness` was not verified from inside the session;
the checkout value is consistent with it.

## 2. Strict validation with `workflows/` present

Given in the session prompt: `claude plugin validate --strict plugins/harness` passed with `workflows/`
present. Not re-run here.

## 3. Bash environment root

`a.txt` and `b.txt` both end with:

```
bash_root=
```

`$CLAUDE_PLUGIN_ROOT` is empty in the Bash tool of a workflow subagent. A workflow agent cannot rely on the
variable inside a command; the path must arrive in its prompt (or the text substitution of assumption 1).

## 4. Permission prompts

None observed during the run. The workflow ran from launch to completion (about 7.8 s) without any prompt
reaching the session. The probe agent used Bash and Write only.

## 5. Null stage

Workflow return value:

```
{"results":["stage3 ran for a; prev=done a",null]}
```

Stage 3 ran for `a` and received `prev=done a`. For `b`, stage 2 returned `null`; stage 3 did not run (no
"stage3 ran for b" string exists) and `b` came back `null`. `pipeline` short-circuits a `null`.

## 6. Launch timing

The Workflow call returned at once:

```
Workflow launched in background. Task ID: wbbmy9jvt
```

Completion arrived later as a `task-notification` (status `completed`).

## 7. Usage rows in `docs/_harness/agent_usage.jsonl`

`wc -l` after the run: 1020, the same as before launch. `tail -n +1021` printed nothing. For the two
workflow agents (`af73f1678fe20b100` probe-a, `a944c545beef90f1f` probe-b):

- Row written at all: **no**. No turn.complete row with either agentId reached the log.
- `tokens` above 0: not applicable, no row.
- `tool_uses` of 2 or more: not applicable, no row.
- `duration_s`: not applicable, no row.

The three newest rows in the file predate the run (`logged_at` 18:12 to 18:19 UTC, all `general-purpose`).
Workflow agents are invisible to the agent-watcher usage log; their metrics exist only in assumption 8's
source. The check ran immediately after the completion notice, and a later recheck in the same session still
found no row for either agentId, so a delayed write is ruled out (DesignEvolution EX4).

## 8. Workflow task output (reference only)

The task output file's `workflowProgress` carries, per agent:

| agent | model | tokens | toolCalls | durationMs |
|-------|-------|--------|-----------|------------|
| probe-a (`af73f1678fe20b100`) | claude-haiku-5-5 | 15930 | 3 | 6891 |
| probe-b (`a944c545beef90f1f`) | claude-haiku-5-5 | 16014 | 3 | 6503 |

Also present: `label`, `agentType: "harness:spike-probe"`, `state`, `phaseTitle`, `startedAt`,
`lastToolName: "SubagentHandback"`. Totals: `totalTokens` 31944, `totalToolCalls` 6. The `toolCalls` of 3
counts Bash, Write and SubagentHandback. The journal (`journal.jsonl`) lists `toolsUsed`
`["Bash","Write","SubagentHandback"]` per agent.

The `model` value shows the agent frontmatter `model: haiku` was honored.
