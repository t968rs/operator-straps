---
name: subagent-reporting
description: Use when a long-running subagent may be silently blocked before it times out, or when you want an independent reasoning pass over its log + worktree while it keeps running
---

# Subagent Reporting

An **observer subagent** is a read-only agent dispatched mid-flight to inspect a running implementer and return a structured snapshot. Not a reflex "check the log" — reserved for the cases below.

## When to Dispatch

- Implementer is **blocked on a permission prompt** and has not yet timed out — it will never self-report until the timeout clock fires
- Implementer has been silent >2 minutes and you need a direction check before letting it run another 5+
- You want independent LLM reasoning over log + worktree while the implementer keeps working

## When NOT to Dispatch

- You want to read one log file → inline `Read` is cheaper and faster
- The implementer self-reported recently and you can wait for the next one
- You have no independent work to parallelize — just await the final report
- As a routine "check on progress" action — inline reads are correct for routine

## The Core Rationalization to Defeat

Baseline instinct: *"observers tell me nothing the implementer's final report won't."*

**Wrong in exactly one case.** The implementer's self-report arrives only on task completion. A permission-blocked implementer has not completed — there is no self-report, and the timeout clock is burning. The observer catches the block before you lose minutes of wall clock. **This is the canonical win case and the reason this skill exists.**

**Right in every other case.** For routine progress, inline `Read`/`Grep` is cheaper. Do not dispatch observers as a reflex.

What the observer actually adds: not raw bytes (you can grep the log yourself) but **independent reasoning** over log + worktree. Observers cannot see another subagent's live tool calls — subagents are isolated processes — but they can read the harness log file and the worktree, and form a fresh judgment.

## Safety Invariant: Empty Write Set

**Observers MUST be dispatched with zero write tools.** No `Edit`, no `Write`, no mutating `Bash`.

Two live agents with overlapping write scopes is a race condition with no coordination primitive. The temptation — *"the monitor found one stuck file, just give it Edit to fix that one thing while the implementer keeps running"* — feels efficient and is never safe. A tool grant is a role change: `Monitor + Edit` is not "a monitor that can edit"; it is a second Implementer with no migration context and a misleading name. If the fix is real, dispatch a second Implementer after the first has returned.

Allowed observer tools: `Read`, `Grep`, `Glob`, read-only `Bash` (`git status`, `git log`, `ls`). Nothing else.

## Snapshot Semantics

An observer's report is a **historical record of a past moment**, not live state. By the time you read it, the implementer has moved on.

Before aborting an implementer on an observer's word:

1. Confirm the snapshot is recent (last ~60 seconds)
2. Re-check the log or worktree yourself for activity since
3. Remember the observer is itself an LLM with failure modes — "0% complete at the 5-minute mark of a 30-minute job" is not grounds for abort

## Red Flags — STOP

| Thought | Reality |
|---|---|
| "I'll give the observer Edit just this once" | Never. Dispatch a second Implementer after the first returns. |
| "Observer said stuck, abort the implementer" | Snapshot is historical. Verify first. |
| "I'll dispatch an observer every N minutes as routine" | No. Inline reads are correct for routine checks. |
| "The implementer self-reports eventually" | Only on completion. Blocked implementers never get there. |
