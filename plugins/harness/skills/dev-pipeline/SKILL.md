---
name: dev-pipeline
description: Use when fixing bugs, implementing features, or making multi-file changes — especially after systematic-debugging identifies root causes, or when you are about to write fix code without having documented findings or discussed solutions first
---

# Development Pipeline

## Overview

Every significant code change follows an 8-step pipeline with mandatory gates. The pipeline prevents the two most common process failures: (1) jumping from diagnosis to implementation without documenting or discussing, and (2) declaring "done" after tests pass without recording evidence in plan documents.

**Core principle:** Gates are not optional. Violating a gate is a process failure.

## The Pipeline

```
FIND ──► DOCUMENT ──►[GATE]──► DISCUSS ──►[GATE]──► PLAN ──► EXECUTE ──►[GATE]──► VERIFY ──►[GATE]──► SAVE
  1          2                     3                    4         5          6          7                  8
```

| Step | Action | Supporting Skill | **REQUIRED** |
|------|--------|-----------------|---|
| 1 | **Find problems** — diagnose root causes | **superpowers:systematic-debugging** | Phase 1–2 |
| 2 | **Document findings** — save to disk | — | Gate 2 |
| 3 | **Discuss and agree** — present solutions, get explicit agreement | — | Gate 3 |
| 4 | **Create plan** — break into tasks with dependencies | **superpowers:writing-plans** | Always |
| 5 | **Execute** — implement tasks (parallel when independent) | **superpowers:executing-plans**, **harness:parallel2** then **superpowers:dispatching-parallel-agents**, the project's CI-discipline skill (if any task touches CI or test infrastructure) | When possible |
| 6 | **Record evidence** — update plan documents after each task | — | Gate 6 |
| 7 | **Test and verify** — full suite, plan docs current, CI green | **superpowers:verification-before-completion** | Always |
| 8 | **Save** — commit plan updates, present summary | — | — |

## Gate Rules

### Gate 2 → 3: Document Before Discussing

After **superpowers:systematic-debugging** Phase 2 (pattern analysis), **STOP**.

Save findings to disk (under the project's configured `artifacts.research` directory, or the plan's research folder) before writing any fix code. Present to user for discussion. The findings document is the input to Step 3 — without it, discussion lacks structure.

### Gate 3 → 4: Agree Before Planning

No execution plan until design questions are resolved with the user. Record each resolution with a date. Unresolved questions block the tasks that depend on them.

### Gate 6: Record After Each Task

After every completed task, update plan documents (status + evidence). Both files atomically. This is part of "task complete" — not a follow-up. Do not proceed to the next task until evidence is recorded.

### Gate 7: Verify Before Claiming Done

"Tests pass" is necessary but not sufficient. Before claiming completion:
- Plan documents are current (all items have evidence)
- The targeted test files and the project's configured guard files pass, run by name; when correctness depends on a
  full-suite run, that run is handed to the developer
- CI status is green (or explicitly noted as pending)

**REQUIRED:** Invoke **superpowers:verification-before-completion**. This is non-negotiable.

## Red Flags — STOP

If you catch yourself thinking any of these, you are about to violate a gate:

| Thought | Gate Being Violated |
|---------|-------------------|
| "Let me just fix this quickly" | Gate 2: document findings first |
| "The fix is obvious, no need to discuss" | Gate 3: agreement required |
| "I'll discuss after I prototype the fix" | Gate 3: agreement before implementation |
| "Tests pass, we're done" | Gate 6+7: record evidence, verify plan docs |
| "I'll update the docs later" | Gate 6: evidence recording is atomic with task completion |
| "Just one more fix, then I'll document" | Gate 2: momentum bias overriding process |

## Skill Transitions

When a supporting skill finishes, check which gate you are at:

- **After superpowers:systematic-debugging Phase 2**: You are at Gate 2. STOP. Document findings, then discuss with user.
  - **CI branch:** if any root cause involves CI workflows, a test registry, shared fixtures or the project's configured guard suite (`review.guard_suite` in `.claude/harness.json`), invoke the project's CI-discipline skill (if any) before drafting fix code, so the surface of the change is known before committing to a fix shape.
- **After superpowers:writing-plans**: You have a plan. Proceed to Step 5 execution (invoke **superpowers:executing-plans**, or **harness:parallel2** then **superpowers:dispatching-parallel-agents**).
  - **CI branch:** any task whose file-touch list includes a CI or test-infrastructure path names the configured guard files in its task prompt. Subagents executing such tasks need that checklist in their pre-flight; small CI changes regress.
- **After each superpowers:executing-plans or superpowers:dispatching-parallel-agents task**: You are at Gate 6. Update `<artifacts.plans>/{PR}_ActionPlan.json` status + evidence AND check off `<artifacts.plans>/{PR}_PIP.md` steps NOW (atomic).
  - **CI branch:** if the task touched CI, running the configured guard files by name is part of "task complete" — not a follow-up. Do not accept a subagent's "all my tests pass" as a guard run; per-file loops do not run guards.
- **After superpowers:verification-before-completion**: You are at Gate 7. Verify all plan docs are current before claiming done.

## When to Use This Skill

- Any multi-file bug fix or feature implementation
- After **superpowers:systematic-debugging** identifies multiple root causes
- When you notice momentum pulling you toward implementation before documentation
- When you are about to claim work is complete
- **TRIGGER:** When you are tempted to skip Steps 2–3 (documentation and discussion) and jump to Step 4–5 (planning and execution)

## When NOT to Use

- Single-line typo fixes
- Documentation-only changes
- Trivial test additions with no source changes

## Why the gates exist

Each supporting skill is self-contained; none enforces the full sequence. Without transition gates the two common
failures are jumping from diagnosis straight into fix code (no findings on disk, no agreed solution) and declaring
done after a green run without recording evidence in the plan documents.