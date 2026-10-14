---
name: consumer-contract-audit
description: Use when modifying a shared mutable container that two or more public APIs read or walk — especially when changing WHEN entries enter or leave it. Triggers on words like pop, purge, drain, mark, fail, remove, skip, evict applied to a structure with multiple consumers (task trackers, path or history ledgers, registry/schema dyads, summary accounting dicts, schema catalogs, status-tracker maps). Also use when a code review on such a structure flags "the caller no longer sees X" or when a fix to one consumer changes timing visible to another consumer.
---

# Consumer Contract Audit

## Overview

A shared mutable container (queue, tracker, ledger, registry) is rarely doing one job. It's usually serving 2+ consumers with different needs from the same data. Changing **when** entries enter or leave the container changes what each consumer observes — and the consumer that wasn't on the author's mind silently breaks.

**Core principle:** Before changing how a shared container is mutated, enumerate every consumer and write down each one's observable contract. Walk the change against each contract. If a contract survives only by coincidence, the change is wrong or the container is doing two jobs.

## When to Use

**Triggers (any one is enough):**

- Adding `pop` / `remove` / `purge` / `evict` to a container that is also walked by an accounting or summary function
- Changing **when** a state transition happens (not just whether)
- A fix described as "close the leak from X" — ask: what *besides* the leak depends on X being there?
- Reviewer asks "what does the caller see?" and the answer requires a code re-read
- A spec touches a shared-state class (task tracker, history ledger, task manager, schema catalog) without listing consumers
- The changed container already appears in the project's fixture catalog (see below)

**Don't use for:**

- Pure-function refactors with no observable mutation (no consumer contracts to break)
- New containers with a single consumer (no second master to break)
- Read-only structures (frozen dataclasses, tuples)

## Core Pattern

The audit is four mechanical questions, asked in order. Skipping any one is how the bug gets through.

### 1. Enumerate consumers

For the container being changed, list every public-API code path that **reads** or **walks** it. Group:

| Role | Examples |
|---|---|
| **Producer** | mutates the container — adds, marks, transitions |
| **Gatekeeper** | filters or skips entries based on container state (drain loops, validators) |
| **Accountant** | reads container contents to produce a summary or report (end-of-run summaries, status logs) |

Use grep, not memory. Even a "known" consumer list gets grepped — silent consumers (debug log lines, telemetry, error-summary builders) are exactly what the audit catches.

### 2. Write each consumer's observable contract

One line per consumer. Format: *"<consumer> depends on <container> having <X> when <Y> happens."*

Examples for a task tracker's `pending` queue:

- `run_all` depends on `pending` containing every task that still needs work, in FIFO order, when `run_all` enters its loop.
- `drain_queued` depends on `pending` retaining terminal-status entries long enough for drain to purge them on the next pass (self-heal).
- `summary` depends on **either** `pending` retaining ERROR-status entries until `summary` walks them, **or** the task registry covering them.

Write the contract in observable terms — "what the consumer sees" — not implementation terms.

### 3. Walk the change against each contract

For each (change, consumer) pair, answer one question: **does this consumer's contract still hold after the change?**

| Answer | Meaning |
|---|---|
| Yes, by construction | Safe — the change preserves the contract |
| Yes, by coincidence | Flag — a future refactor will break it silently |
| Only if the consumer is also changed | The PR scope is wrong — list the consumer change |
| No | Stop — either revert the change or split the container |

"Coincidence" includes cases like *"the consumer reads the container 100ms after the producer mutates it, so usually it sees the post-change state."* That's a race, not a contract.

### 4. If two consumers need contradictory things → split the container

If consumer A needs the container to hold X until A walks it, AND consumer B needs the container to drop X immediately, the container is serving two jobs. Either:

- **Split** into two structures (work queue + accounting ledger)
- **Document the tension explicitly** in the spec, with a named priority (e.g., "`pending` serves the queue role first; accounting falls back to a registry walk")

The wrong answer is "tighten the coupling" — that is how one fix's regression becomes the next fix's regression.

## Worked Example: a task tracker's `pending` queue

**The fixture:** `OrderedDict[int, None]` at `TaskTracker.pending` — tracks tasks that still need work.

**The change:** a fix added `tracker.fail()` + `tracker.pop_failed()` at every launch-stage failure path, to stop tasks stuck in RUNNING from lingering in `pending`.

**The consumers nobody audited:**

| Consumer | Role | Contract |
|---|---|---|
| `run_all` (via `drain_queued`) | Gatekeeper | depends on `pending` retaining tasks until drain purges terminal-status ones |
| `summary` | Accountant | **depends on every failed task being yielded by `run_all` so it lands in the "Failed Tasks" report** ← THIS ONE BROKE |

The fix called `pop_failed()` during `launch()`, before `run_all` ran. Drain never saw the terminal entries; `summary` never reported them. File-scoped review, a spec, a plan and TDD all missed it. A reviewer reading from the caller's perspective caught it cold: *"the caller still gets a task ID back from launch(), but the later summary logic never sees it."*

**The structural truth:** `pending` was serving two masters — work queue for `run_all`, accounting ledger for `summary`. The fix optimized for the first master and silently broke the second.

**The corrected fix:** drop `pop_failed()` at launch sites (let `tracker.fail()` flip status, let drain self-purge) and widen `summary()` to sweep the task registry for ERROR-status tasks it has not processed. Two consumers, two compatible contracts.

**The lesson the audit captures in writing:** when a fix is framed as "close the leak from X," ask "what besides the leak depends on X being there?" before writing code.

## Quick Reference — Audit Checklist

```
[ ] Grep all reads/walks of the container — DO NOT trust memory
[ ] Classify each: Producer / Gatekeeper / Accountant
[ ] One-line observable contract per consumer
[ ] Walk change against each contract:
    [ ] Survives by construction?
    [ ] Survives by coincidence? → flag
    [ ] Requires consumer change? → expand PR scope
    [ ] Breaks? → revert or split container
[ ] If two consumers contradict → split or document tension
```

## Project Fixture Catalog

Each project keeps its own catalog of known shared mutable fixtures and their consumer maps at
**`.claude/harness/consumer-fixtures.json`** (project-relative; the file is optional). When the audit triggers and the
changed container appears in the catalog, **read the catalog entry first** — it pre-fills steps 1 and 2 for fixtures
that have already been audited.

The catalog validates against `${CLAUDE_SKILL_DIR}/repo-fixtures.schema.json`: a top-level object with
`catalog_version` and a `fixtures` array (one entry per fixture: `name`, `location`, `kind`, `consumers`, optional
`summary` and `history`). Create the file on first use and add
entries when a fixture meets the criteria (2+ consumers, mutable, externally observable). The catalog is a working
document — entries grow with the codebase. Record past regressions in an entry's `history` so the next audit starts
with the prior that this fixture has bitten before.

## Anti-patterns

| Anti-pattern | Why it hides the failure |
|---|---|
| "I only changed *when* pop happens, not *what* pop does" | The contract is *when*, not *what* — every consumer that walks the container at a different time is exposed |
| "Three reviewers walked the diff" | File-scoped review ≠ contract-scoped review. None of them walked from caller's perspective |
| "TDD covered the unit" | Unit tests pin internal invariants. Consumer contracts are caller-observable — different test surface |
| "The fix is mechanically correct" | Mechanical correctness ≠ consumer-observable correctness. Both can be true; both can be false; verifying one doesn't verify the other |
| "Spec listed the public API" | Public API ≠ consumer contract. Two consumers can use the same API and have different contracts |

## Red Flags — STOP and run the audit

- "Just need to add `pop`/`remove`/`purge` to close this leak" — what *besides* the leak depends on the entry being there?
- "Let me tighten the coupling between status and queue membership" — coupling-tightening is consumer-merging
- "The fix is one line" — one-line fixes to shared state are exactly when this audit pays off
- "Reviewers will catch it" — file-scoped reviewers routinely miss this class. Don't outsource the audit
- "TDD will catch it if I write good tests" — TDD on the unit is necessary, not sufficient. Need caller-perspective contract test
- "I'm changing the spec, not the code" — specs that touch shared-state classes need a `Consumers` section before they're done

## Cross-references

Skills outside this plugin apply when installed.

- **Plan writing** (e.g. `superpowers:writing-plans`) — when a spec touches a shared mutable fixture, the spec is incomplete without a `Consumers` section enumerating each consumer's contract. This skill is the audit; the spec section is the deliverable.
- **Test-driven development** (e.g. `superpowers:test-driven-development`) — pair unit tests (invariant pinning) with caller-perspective contract tests (e.g., "register → fail-at-launch → summary sees it"). Two test surfaces, both required for shared state.
- **`harness:pr-review` / `harness:pr-team`** — when a PR touches a fixture in the project catalog, scope at least one reviewer by **caller perspective** (trace from public API entry points to observable side effects), not by file or domain.
- **Receiving code review** (e.g. `superpowers:receiving-code-review`) — when a reviewer comment phrases the issue at the API boundary (*"the caller no longer sees X"*), the underlying problem is a consumer-contract break. Run this audit before fixing — the surface fix will likely break a third consumer.

## The Bottom Line

Reviewers, a spec, a plan, and TDD can all miss a one-line consumer-contract bug that a caller-perspective read finds in seconds.

State-machine correctness ≠ caller-observable correctness. Run the audit before the change. The audit is four questions; the bug it catches otherwise takes several reviewers and a follow-up PR to surface.
