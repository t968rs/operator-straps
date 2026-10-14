# PipelineCoordinator — Waves and Skills (worked example)

A multi-wave refactoring plan (a pipeline coordinator plus its sampling, processing and I/O modules), reduced to
its parallelization geometry and per-wave skill mapping as a worked example for `harness:parallel2`.

## Plan — parallel-friendly waves

```
W0  setup (main, serial)
W1  ┬─ W1A coordinator+tests   ┐
    ├─ W1B sampling tests RED   ├─ 3 worktrees, parallel
    └─ W1C test-infra audits    ┘
W2  ┬─ W2A sampling.py rewrite  ┐
    └─ W2B processing.py audit  ┴─ 2 worktrees, parallel
W3  io.py cleanup (1 worktree)
W4  verification (main, serial)
```

Max concurrency: 3 subagents (W1). The lanes have non-overlapping file scopes, so `harness:parallel2` accepts the
dispatch plan without flagging.

## Per-wave skill mapping

Skills outside this plugin apply when installed.

| Wave              | Domain                | Justification                                                                                                                                                                                                                                         | Skill                                        | Why                                                                |
|-------------------|-----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|--------------------------------------------------------------------|
| W0                | Workspace setup       | Pre-execution environment prep whenever the plan needs more than one worktree or a non-default checkout topology. Owns path conventions, IDE-lock avoidance (Windows file locks, workspace indexing) and post-merge worktree cleanup.                 | `superpowers:using-git-worktrees`            | Three new worktrees                                                |
| W1 dispatch       | Dispatch choreography | Any wave running two or more subagents concurrently. `harness:parallel2` is the structural validator (non-overlapping file sets, one-shot vetting of the dispatch plan); a parallel-dispatch skill is the strategy layer (whether parallel fits).    | `harness:parallel2`                          | 3-way subagent dispatch with non-overlapping file sets             |
| W1 dispatch       | Dispatch choreography | Pair with `harness:parallel2` for every multi-lane wave: parallel2 catches mechanical overlap; the dispatch skill catches conceptual overlap (two lanes on different files that share an invariant only one lane respects).                          | `superpowers:dispatching-parallel-agents`    | Three independent tasks, no shared state                           |
| W1A, W2A subagent | Test discipline       | Every line of runtime code is preceded by a failing test in the worktree history. Applies whenever a wave drives new behavior into existence or failing tests to green; skip only for documentation or verification waves.                          | `superpowers:test-driven-development`        | No production code without a failing test first                    |
| W1A, W1B subagent | Lane evidence         | The main session needs one evidence shape across lanes to make the merge decision: completion, non-overlapping file scopes, tests passing in isolation.                                                                                             | `harness:subagent-reporting`                 | Each lane reports completion + non-overlap evidence                |
| W1C subagent      | CI/test-infra hygiene | Any edit to CI workflows, test registries, shared fixtures or the project's configured guard suite (`review.guard_suite` in `.claude/harness.json`). Silent CI skips and registry drift are invisible until the guard files run by name.            | the project's CI-discipline skill, if any    | Run the configured guard files before handing off                  |
| W2 dispatch       | Dispatch choreography | Reapply on every wave with two or more lanes. A 2-way dispatch costs nothing to vet and catches overlapping edits (two lanes both touching `processing.py`, last write wins) before they become merge conflicts.                                     | `harness:parallel2`                          | 2-way dispatch                                                     |
| W4                | Completion gating     | Owns "evidence before assertions" before commit, PR creation or merge. Catches the common terminal failure: lanes report green per file, but the guard suite or the full lane was never run end to end.                                              | `superpowers:verification-before-completion` | Pre-merge gate; never claim done without evidence                  |

## How to read this example

1. **Identify the wave shape first.** ASCII tree of waves → lanes within each wave. Independent lanes go in the same
   wave; sequential dependencies separate waves.
2. **For each wave, label its domain** before picking skills. Domain comes from the *kind of work* (workspace setup vs.
   dispatch vs. test discipline vs. CI hygiene vs. completion), not the file targets.
3. **A lane can belong to multiple domains.** W1A is both Test discipline (its job is RED→GREEN) and Lane evidence (it
   reports back to the merge gate). Skills compose; one skill per domain per lane.
4. **`harness:parallel2` and the dispatch skill always pair for multi-lane waves.** Treat them as a single
   dispatch-choreography invocation, not two separate skills.
5. **Single-lane waves still have domains.** W3 here is single-lane io.py cleanup — its domain is "Test discipline" in
   the loose sense (don't break the green tests) plus "Workspace setup" (one new worktree). Even one-lane waves benefit
   from explicit domain labeling because it forces articulation of what the wave is *for*.
