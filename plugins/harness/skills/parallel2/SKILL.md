---
name: parallel2
description: Use when about to dispatch parallel subagents for mechanical tasks and want to prevent per-tool permission prompts from interrupting subagent execution
---

# Parallel Dispatch: Two Non-Negotiable Prongs

Before dispatching any parallel subagents, complete **both prongs**. They are independent and can be run simultaneously.

```
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│  PRONG 1: WORKTREE PROTOCOL     │   │  PRONG 2: PROBE + PERMISSIONS   │
│                                 │   │                                 │
│  Structure the work correctly   │   │  Verify tools won't prompt      │
│  so agents don't collide        │   │  before scaling to the batch    │
│                                 │   │                                 │
│  → one worktree per task        │   │  → run one probe agent first    │
│  → stage, don't commit main     │   │  → fix gaps, then dispatch all  │
└─────────────────────────────────┘   └─────────────────────────────────┘
               ↓                                     ↓
        both complete in parallel → dispatch the full batch
```

**REQUIRED:** Use a parallel-dispatch skill (for example `superpowers:dispatching-parallel-agents`, when installed) for WHEN and HOW to split tasks into independent domains. This skill handles the structural and permission setup that must happen before that dispatch.

---

## Prong 1 — Worktree Protocol

### Why worktrees

Parallel subagents writing to the same working tree cause merge conflicts, lost writes, and test interference. Each task gets its own isolated branch so agents can work simultaneously without colliding.

### Setup (run before dispatch)

```bash
# Create one worktree per task group
git -C "<MAIN_CHECKOUT>" worktree add "<WORKTREE_PATH>/<TASK_NAME>" -b <TASK_BRANCH>

# Example
git -C "<REPO_ROOT>" \
    worktree add "<WORKTREES_ROOT>/<REPO_NAME>/task3" \
    -b <ISSUE>-task3-impl
```

`<WORKTREES_ROOT>/<REPO_NAME>` is the project's `worktree_root` from `.claude/harness.json` (default
`~/.config/superpowers/worktrees/<repo>`, the folder `harness:d-w` uses). Keep it outside the project directory: an IDE indexing the workspace holds
file locks on Windows.

### Per-task flow (run in parallel across tasks)

1. **Implementer subagent** — writes tests + code, commits in the worktree branch.
2. **Spec-compliance reviewer subagent** — reads spec + diff in the worktree, reports verdict. No edits.
3. **Code-quality reviewer subagent** — reads diff, reports verdict. No edits.
4. **Fix loop if needed** — implementer addresses findings, re-commits in worktree.
5. **Stage to target branch** — once both reviewers pass, stage that task's files to the main checkout immediately. Do NOT batch across tasks.
6. Move to next task.

Steps 2 and 3 (the two reviewer subagents) run **in parallel** with each other.

### Staging mechanic

```bash
# Verify the target branch is checked out first
git -C "<MAIN_CHECKOUT>" rev-parse --abbrev-ref HEAD

# Stage files from worktree branch onto the target branch (no commit)
git -C "<MAIN_CHECKOUT>" checkout <WORKTREE_BRANCH> -- <file1> <file2> ...

# Example
git -C "<REPO_ROOT>" \
    checkout <ISSUE>-task3-impl -- src/pkg/bar.py tests/test_bar.py
```

Files land staged in the index on the target branch. The developer runs `git diff --cached` and commits. Claude never commits on the target branch.

Stage at task granularity — or the smallest feature-coherent slice the developer would inspect as one unit. Never accumulate all tasks and stage at the end.

### Cleanup (after the last task is staged)

```bash
git -C "<MAIN_CHECKOUT>" worktree remove "<WORKTREE_PATH>/<TASK_NAME>"
git -C "<MAIN_CHECKOUT>" branch -D <WORKTREE_BRANCH>
```

Do not ask permission. Worktrees and worktree branches are session artifacts.
(`-D` is required — changes were staged via path checkout, not merged, so `-d` would refuse to delete.)
Remove only worktrees this session created; leave other branches' worktrees and `.claude/worktrees/` entries alone.

### Branch-safety checks

- **Declare the target branch** at session start; every artifact ends committed, staged, or untracked on it. Stage
  doc artifacts (PR summaries, reviews, plan files) there too. Report anything left on a sibling.
- **Never switch the main checkout's branch.** If a worktree for the checked-out branch is needed, treat the main
  checkout as that lane (work inline or point a subagent at the main path); "branch already checked out" means
  exactly that.
- **Record the target HEAD before dispatch** (`git -C <repo> rev-parse <target>`) and re-check it before staging. If
  it moved, re-scope against the new HEAD. A subagent reporting "the change was already half-applied" means the
  developer committed in parallel: stop and re-verify.
- **Diff from the merge base, never `<base>..<lane>`** (`<base>` is the project's configured base branch). If
  `<base>` advanced after the worktree was cut, `<base>..<lane>` carries the newly merged work as deletions and
  un-merges it. Use `git diff $(git merge-base <base> <lane>)..<lane>`. Unexpected deletions in `git status` after
  an apply mean the wrong base; revert.
- **A named wave starts as a whole.** "Begin Wave 1A" for a roadmap wave declared parallel-safe means create every
  lane's worktree and dispatch all of them in the first response.
- **Scale check:** six or fewer small mechanical edits usually run faster inline than dispatched.

### Anti-patterns

| Anti-pattern | Why it's wrong |
|---|---|
| Subagent commits on the user's main-checkout target branch | Forbidden — commits only happen in worktree branches |
| Main session runs `git merge <worktree-branch>` into target | Produces a commit on the target — developer's job |
| Batching all task diffs into one final stage | Defeats incremental review |
| Skipping `git worktree remove` / `git branch -D` | Clutters the worktrees directory and leaks branches |

---

## Prong 2 — Probe + Permissions

### Why a probe instead of settings.json auditing

Static config auditing — reading the user and project `settings.json` files and checking entries — does not confirm that tools won't prompt. It misses glob patterns that look right but don't match the actual path, worktree paths outside the project-dir glob, and settings drift since the session started.

**Run one probe agent first.** The probe exercises the exact tools the real agents will use. If it completes without prompting, the setup is verified. Then dispatch the batch.

### Step 1 — Identify the tool profiles

Group tasks by the tools they need. Each distinct profile needs its own probe.

Common tools to account for:
- `Read(**)` — reading source/test files
- `Edit(**)` — modifying source files
- `Write(**)` — creating new files
- `Bash(pytest *)`, `Bash(python *)` — running tests
- `Bash(git *)` — git operations
- `WebFetch(domain:...)` — any external fetch

**Worktree path check:** When tasks run in a git worktree, the filesystem path differs from `$CLAUDE_PROJECT_DIR`. Globs like `Edit($CLAUDE_PROJECT_DIR/**)` resolve to the main repo path and will NOT match worktree paths. For `Read`, `Write`, and `Edit`, verify the permission covers the worktree path — if not, that's a gap the probe will surface.

### Step 2 — Dispatch a probe agent

Craft a minimal agent that touches one representative call per tool in the profile:

```markdown
## Probe Task
You are a permission probe. Execute exactly these actions and report whether each succeeded or was blocked:
1. Read: read the first 5 lines of `<A_RELEVANT_SOURCE_FILE>`
2. Bash(git): run `git -C "<REPO_PATH>" status --short`
3. Bash(tests): run the project's test command against `<A_TEST_FILE>` in collect-only mode (report exit code and first error if any — the probe checks for permission blocks, not test pass/fail)
4. Edit: append a single blank line to `<A_SCRATCH_FILE>`, then remove it

For each action, report: SUCCESS or BLOCKED (describe what appeared).
Do not do anything else. Do not fix anything. Only probe and report.
```

Adjust the list to exactly the tools the real tasks need — no more, no less.

### Step 3 — Interpret and act

| Probe outcome | Action |
|---|---|
| All actions SUCCESS | Dispatch the full parallel batch. |
| One or more BLOCKED | Stop. Fix the gap (see below), re-probe, then dispatch. |

**If a tool is blocked:** Use the `update-config` skill to add or correct the permission entry in the user or project `settings.json`. Common fixes:
- Missing tool entry entirely → add it
- Glob covers project-dir path but not worktree path → add explicit worktree glob (e.g., `Write(<WORKTREES_ROOT>/**)`)
- Pattern too narrow for the argument shape being used → widen it

Re-probe after every fix. Don't dispatch the batch until the probe is clean.

### Step 4 — Include the permission block in every agent prompt

Once the probe passes, add this at the TOP of every agent prompt you dispatch:

```markdown
## Pre-Authorized Tools
The following tools are approved and will not prompt for this task.
Use them freely:
- Read(**)
- Edit(**)
- Bash(git *)
- Bash(pytest *)
[list only what this specific task actually needs]

If you need a tool NOT listed here: stop and report it back to the caller instead of prompting.
```

Only list tools the specific task needs. Declaring `WebFetch` for a pure test-fix task invites scope drift.

---

## Running Both Prongs Together

Prong 1 (worktree setup) and Prong 2 (probe dispatch) are independent. Run them in parallel:

```
Parent session:
  ├── git worktree add ... (Prong 1 setup — fast, local)
  └── dispatch probe agent (Prong 2 — runs while worktrees are created)

Both resolve → dispatch real agents into worktrees with verified permissions
```

---

## Read-Only Reviews — Skip Prong 1

Parallel **review** agents (e.g., scoped reviewers dispatched by `harness:pr-review`) read source +
docs and emit a JSON verdict. They do NOT write to the working tree. Per-task worktrees serve no purpose:
there is no diff to isolate, nothing to stage, and Prong 1's "stage to target branch" mechanic is moot.

**Decision rule for parallel dispatch:**

| Agent type | Prong 1 (worktrees) | Prong 2 (probe) |
|---|---|---|
| Implementer (writes code, commits) | REQUIRED — one worktree per task | REQUIRED |
| Reviewer (reads, emits verdict JSON) | SKIP — read-only, no isolation needed | OPTIONAL — only if reviewers need a tool the session hasn't already exercised |
| Probe / investigator (read-only research) | SKIP | OPTIONAL — same logic |
| Mixed batch (some review, some implement) | REQUIRED for the implementer subset only | REQUIRED |

**Why Prong 2 is optional for read-only agents:** review agents typically use `Read`, `Grep`, `Bash(git ...)`,
and `Bash(gh ...)` — tools the parent session has already exercised in this turn. If those calls have run
without prompts, the same calls in subagents will too. Run a probe only when a reviewer needs an unusual tool
(e.g., `WebFetch` for a doc cross-reference, or `Bash(pytest ...)` to actually execute structural guards).

When you skip a prong, **say so explicitly** in the dispatch announcement (e.g., "Skipping Prong 1 — review-only
dispatch, no worktrees needed"). Silent skips invite drift.

---

## When to Keep Tasks Inline Instead

- Task requires a destructive tool (`rm`, `git reset --hard`) that shouldn't be globally pre-approved
- Task is fast enough that subagent + worktree overhead isn't worth the setup
- Task is exploratory — tool needs are unknown until it runs

---

## Integration with dispatching-parallel-agents

This skill is **Step 0** before the existing dispatch pattern:

```
[Step 0] harness:parallel2 (this skill)
  → Prong 1: create worktrees, verify staging path
  → Prong 2: probe tools, fix gaps, prepare permission blocks

[Step 1] Identify independent domains       ← dispatching-parallel-agents
[Step 2] Create focused agent tasks         ←
[Step 3] Dispatch in parallel               ← inject permission block + worktree path per agent
[Step 4] Review, stage, and integrate       ←
```
