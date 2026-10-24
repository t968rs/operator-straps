---
name: a-w
description: Use when work done in a detached-HEAD worktree (see d-w) is finished and must move onto a target branch, either as the worktree's own commits or as staged, uncommitted changes. Triggers on "attach the worktree", "move the worktree changes to <branch>", "a-w".
argument-hint: "<target-branch> [--committed] [--worktree PATH]"
---

# a-w: move a worktree's work onto a branch and drop the worktree

The developer names the target branch; the command does the rest. The developer never edits, inspects or removes
the worktree.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/attach_worktree.py" $ARGUMENTS --worktree "<worktree path>"
```

Run it with the Bash tool from the main checkout, naming the worktree the session created with `d-w`. A
`--target_branch <name>` flag is accepted in place of the positional branch.

| Mode | What lands on the target |
|---|---|
| default | The worktree's commits, edits and new files, **staged and uncommitted**. The combined diff from the merge base is applied three-way, so commits the target gained since the cut are merged, never reverted. |
| `--committed` | The worktree's own commits, fast-forwarded onto the target with their messages and grouping kept. Refuses uncommitted worktree changes and a target that moved since the cut; neither case changes anything. |

- The target branch must be checked out in some worktree (normally the main checkout) with no tracked changes.
  A branch checked out nowhere is a problem to report; the command never switches branches.
- On success the command removes the worktree without asking. It sets no timer: the move is the trigger.
- Exit 1 prints `attach_worktree: <reason>` and leaves the worktree. A three-way conflict names the conflicted
  paths; the markers sit in the target checkout and the worktree stays until the developer resolves them.
- Report the stdout lines. After a staged move the developer reviews `git diff --cached` and commits; the agent
  does not commit on the target.
