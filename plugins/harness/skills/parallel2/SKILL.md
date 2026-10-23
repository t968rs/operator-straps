---
name: parallel2
description: Use when about to dispatch two or more subagents in parallel, when splitting a plan into waves of lanes that edit files, or when per-tool permission prompts interrupt subagent runs
argument-hint: "[plan JSON path]"
---

# Parallel Dispatch Setup

Two prongs before any parallel dispatch: **lanes that cannot collide** (one worktree per implement lane, file
sets disjoint within a wave) and **tools that will not prompt** (one probe agent per tool profile). The driver
owns every mechanical step; the session writes the plan, dispatches, and judges. `README.md` explains why.

**REQUIRED:** a parallel-dispatch skill (`superpowers:dispatching-parallel-agents`, when installed) decides
whether the work splits into independent domains. This skill runs after that decision and before the dispatch.

Below, `P2` stands for `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/parallel2.py"
--repo "<target checkout>"`, where the target checkout is the directory with the target branch checked out.

## When to keep work inline instead

- Six or fewer small mechanical edits: inline is faster than worktrees plus agents.
- A lane needs a destructive tool (`rm -rf`, `git reset --hard`) that should not be pre-approved.
- The work is exploratory and its tool needs are unknown.

## Steps

1. **Write the plan** outside the project tree (the session scratchpad), or pipe it on stdin as `-`:

   ```json
   {"target": "feat-x", "lanes": [
     {"id": "parser", "kind": "implement", "model": "haiku", "task": "add the tokenizer",
      "files": ["src/parser.py", "tests/test_parser.py", "src/tokens/"], "tools": ["Read", "Write", "Edit", "Bash(pytest *)", "Bash(git add *)", "Bash(git commit *)"]},
     {"id": "api-drift", "kind": "review", "model": "opus", "files": ["src/"], "tools": ["Read", "Grep"]}]}
   ```

   `kind` is `implement` (edits, gets a worktree), `review` or `research` (read-only). `files` lists every path
   an implement lane may change, tests and deletions included; a trailing `/` is a directory, `*` a glob.
   `tools` lists what the lane runs, and an implement lane commits, so it includes its git tools
   (`Bash(git add *)`, `Bash(git commit *)`, `Bash(git rm *)` when it deletes). `target` defaults
   to the checked-out branch. `wave` goes on every lane or on none. Omitted everywhere, `plan` packs lanes
   first-fit from wave 1 by file overlap only, never by dependency, so give explicit waves whenever one lane
   reads the output of another or shares an invariant with it.
2. **`P2 plan <plan>`.** A `problem:` line means a defect in the plan: an overlap means split the shared file
   into one lane or put the lanes in different waves. Rerun until clean. Then check what the driver cannot:
   lanes on different files that share an invariant (a signature one changes and another calls) belong in
   different waves.
3. **`P2 setup --wave N`**, then **`P2 probe --wave N`**. Dispatch each printed probe prompt as its own agent
   with the printed model. Any `BLOCKED`: fix the rule with the `update-config` skill (a worktree path outside
   the project glob is the usual gap), re-probe, and dispatch nothing until every probe is clean. `P2 probe`
   covers implement lanes with a live worktree only; a read-only wave prints `nothing to probe`. For a
   read-only wave whose tools the session has not run without a prompt, dispatch one hand-written probe
   agent (model `haiku`) that runs each listed tool once and reports any prompt as `BLOCKED`. Read-only
   waves skip the probe when the session has already run the same tools without a prompt.
4. **Dispatch the wave in one message**: one `Agent` call per dispatch row, with the row's `model` and a
   prompt that opens with `Brief: <path>` from the row. Announce any skipped prong ("Prong 1 skipped:
   review-only wave").
5. **Review each returned implement lane** before staging: a spec-compliance reviewer and a code-quality
   reviewer, in parallel, read-only, over `git -C "<worktree>" diff <target>...HEAD` (`P2 status` shows the
   lane's worktree path; the three-dot range starts at the lane's base commit). Findings go back to the same lane's worktree; the lane re-commits.
6. **`P2 stage <lane>`** as soon as a lane passes, not at the end of the wave. The driver applies the lane's
   diff from its base with a three-way merge into the target's index, deletions and renames included, and
   never commits. A conflict leaves markers in the named files: resolve them, `git add` them, and tell the
   developer which files merged.
7. **Next wave.** Worktrees are cut from the target's HEAD, and staged changes are not in it. When a later
   wave reads files an earlier wave wrote, ask the developer to commit the staged work before `setup`.
8. **`P2 cleanup`** after the last lane stages. No permission question: the run's worktrees and `p2/*`
   branches are session artifacts, and the driver removes only the ones it recorded. A leftover probe file
   is deleted with the worktree. `--all` and `--lane` also remove lanes not yet staged, and their unstaged
   commits on `p2/<id>` go with the branch: stage or discard each such lane knowingly first.

## Rules

- Never commit, merge or switch branches in the target checkout. The developer reviews `git diff --cached`
  and commits.
- Never stage a lane by hand with `git checkout <lane> -- <files>`: it reverts any commit the target gained
  since setup, and drops the lane's deletions and renames.
- Every dispatch passes an explicit `model`; the plan names one per lane.

## When the driver refuses

| Message | Fix |
|---|---|
| `overlap: wave N lanes a, b share <path>` | Merge the shared path into one lane, or move one lane to a later wave. |
| `pending changes in the checkout overlap lane <id>` | The checkout has uncommitted edits to lane files; ask the developer to commit or stash them. |
| `pending changes in the checkout would be overwritten` | Same, found at `stage`. |
| `branch p2/<id> already exists` | A previous run was not cleaned up: `P2 status`, then `P2 cleanup --all`. When `P2 status` does not list the lane, the branch belongs to another target's run (pass `--target <branch>` to clean it there) or to no recorded run: after the developer confirms, `git worktree remove <path>` and `git branch -D p2/<id>`. |
| `lane <id> changed paths outside its files` | Review those paths; rerun with `--include-undeclared` only when they belong to the lane. |
| `lane <id> worktree has uncommitted changes` | Have the lane commit in its worktree. |
| `three-way merge left conflicts in <paths>` | The lane is recorded staged. Resolve the markers, `git add` the files, tell the developer. |
| `a run for this target has unfinished lanes` | `P2 status`; finish or `P2 cleanup --all`, or pass `--replace` to discard the record of lanes without a worktree. |
| `a run for this target still has worktrees for lanes` | `--replace` keeps no record of live worktrees: run `P2 cleanup --all` first, then `--replace`. |
