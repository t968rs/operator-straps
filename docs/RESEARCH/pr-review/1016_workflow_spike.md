# Plan 1016 SPK-1: workflow spike results

Run: workflow `wf_46bfd4df-48d`, task `wbbmy9jvt`, launched 2026-11-12T19:03:52Z (UTC, noted before launch).
`docs/_harness/agent_usage.jsonl` held 1020 lines before launch.

Inputs: `plugins/harness/workflows/spike-probe.js` (two probes `a`, `b` through `pipeline`; stage 2 returns
`null` for `b`) and `plugins/harness/agents/spike-probe.md` (one Bash echo, one Write). Launched with
scriptPath `E:/automation/operator-straps/plugins/harness/workflows/spike-probe.js` and
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
text_root=E:/automation/operator-straps/plugins/harness
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
source. The check ran once, immediately after the completion notice; a delayed write was not ruled out.

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

## "Outgoing" Message to Session:
SPK-1 [done] | report at E:/automation/operator-straps/docs/RESEARCH/pr-review/1016_workflow_spike.md (4879 bytes, on disk)

The most important result: workflow agents write no rows to agent_usage.jsonl (assumption 7). The file held 1020 lines before and after the run.

┌─────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  #  │                                                   Result                                                   │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1   │ Text ${CLAUDE_PLUGIN_ROOT} resolved to the checkout, E:/automation/operator-straps/plugins/harness, in     │
│     │ both probes.                                                                                               │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2   │ Strict validation with workflows/ present passed, per your prompt. I did not re-run it.                    │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3   │ $CLAUDE_PLUGIN_ROOT in the Bash call was empty (bash_root=) in both probes. A workflow agent needs the     │
│     │ path in its prompt.                                                                                        │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 4   │ No permission prompt appeared.                                                                             │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 5   │ Stage 2 returned null for b, so stage 3 never ran for it and b came back null. The result was              │
│     │ {"results":["stage3 ran for a; prev=done a",null]}.                                                        │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 6   │ The Workflow call returned at once with task id wbbmy9jvt.                                                 │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 7   │ No row for either agent. The check ran once, right after the completion notice, so a delayed write is not  │
│     │ ruled out.                                                                                                 │
├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 8   │ workflowProgress carries the per-agent figures. Each probe used about 16k tokens and 3 tool calls (Bash,   │
│     │ Write, SubagentHandback) in about 6.5 to 6.9 s. Both ran on haiku.                                         │
└─────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

- Numbering: your prompt names assumptions 1-8 only through its parentheticals. I inferred the numbering, and the report says so.
- Untested: the scriptPath was an explicit checkout path, so I could not tell whether a bare workflow name would resolve from the cache. I also could not verify from inside the session that it ran with --plugin-dir; the checkout root is consistent with that.

Per step 6 I deleted nothing. The throwaway files are still in place: plugins/harness/agents/spike-probe.md, plugins/harness/workflows/spike-probe.js and the two drafts under .claude/state/harness/spike1016/.
