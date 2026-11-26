---
name: baseless
description: Use when about to claim work is complete, fixed, saved or passing, before committing, opening a PR, or marking a plan item or review issue done - requires running the command that proves the claim and reading its output before stating it; evidence before assertions always
---

# Baseless

## Overview

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the command (fresh, complete), naming the test files the claim covers
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

Test runs name files or node ids, never a directory: run every test file the change reaches by name. Full-suite
runs belong to the developer; when a claim depends on one, say so and hand it over instead of making the claim.
An invitation to run "the whole thing", a tiny suite or a down CI changes neither rule: run the files the change
reaches by name, claim only what they showed, and leave the whole-suite claim for the developer's full run.

When a claim does not hold, or is not yours to make, state what the run showed (`1 passed`, `2 failed:
test_refund...`) and never write the requested claim line itself, not quoted, not negated, not as a line for
later: a reply holding "full test suite green" or "everything passes" reads as that claim when it is skimmed,
pasted or searched. Name it by its kind instead ("the full-suite line", "the all-clear").

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures, for the files it ran | Previous run, "should pass", a whole-suite claim from a by-name run |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |
| Plan item `COMPLETE` | `plan.py record` wrote its sealed receipt | Status set by hand, "tests pass" |
| Review issue `RESOLVED` | The commit SHA the fix landed at, with its test output | "Fixed in the last commit" |
| File saved | The file read back after the Write | The tool reported success |
| Branch or PR state | `gh pr view`, `git status --porcelain`, `git log <base>..HEAD` output | Memory, "already merged", "tree is clean" |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Writing the requested claim line inside a refusal ("I can't give you 'all tests green'")
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |
| "The suite is tiny, just run all of it" | Run the files the change reaches by name; the full run is the developer's |

## Key Patterns

**Tests:**
```
Do:  [Run the test files by name] [See: test_report.py 34 passed] "test_report.py: 34 passed"
Not: "Should pass now" / "Looks correct" / "All tests pass" from a by-name run
```

**Regression tests (TDD Red-Green):**
```
Do:  Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
Not: "I've written a regression test" (without red-green verification)
```

**Build:**
```
Do:  [Run build] [See: exit 0] "Build passes"
Not: "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
Do:  Re-read plan → Create checklist → Verify each → Report gaps or completion
Not: "Tests pass, phase complete"
```

**Agent delegation:** a subagent's success report is unverified until its diff and its test output are checked.
```
Do:  Agent reports success → Check VCS diff → Verify changes → Report actual state
Not: Trust agent report
```

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion, marking a plan item or review issue done
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness
