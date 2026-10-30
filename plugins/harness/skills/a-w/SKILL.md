---
name: a-w
description: Use when work done in a detached-HEAD worktree (see d-w) is finished and must move onto a target branch, either as the worktree's own commits or as staged, uncommitted changes. Triggers on "attach the worktree", "move the worktree changes to <branch>", "a-w".
argument-hint: "<target-branch|HEAD> [--committed] [--worktree PATH] [-- <guidance>]"
---

# a-w: move a worktree's work onto a branch and drop the worktree

The developer names the target branch, or `HEAD` for the branch checked out in the main checkout; the command
does the rest. On a successful move the developer never
edits, inspects or removes the worktree; only a three-way conflict (below) hands a step back.

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. The
part before it is `<attach arguments>` below (the target, `--committed`, `--worktree`), passed through
unchanged. The part after it is the guidance, for example a worktree path to attach or a note on what to report;
it never reaches the command, and it never turns on `--committed`.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/attach_worktree.py" <attach arguments> --worktree "<worktree path>"
```

Run it with the Bash tool from the main checkout, naming the worktree the session created with `d-w`. A
`--target_branch <name>` flag is accepted in place of the positional branch. `HEAD` resolves to the main
checkout's branch wherever the command runs; a detached main checkout is a problem to report, so name the
branch then.

| Mode | What lands on the target |
|---|---|
| default | The worktree's commits, edits and new files, **staged and uncommitted**. Only what the worktree changed since it was cut is measured (from its cut commit, not from the merge base with the target) and applied three-way, so commits the target gained since the cut are merged, never reverted, and history the cut commit carried that the target lacks stays behind. Conflicts arise only on paths both sides changed. |
| `--committed` | The worktree's own commits, fast-forwarded onto the target with their messages and grouping kept. Refuses uncommitted worktree changes (untracked files included), a worktree with no commits beyond the target, and a target that moved since the cut; none of these changes anything. |

- Default to staged mode. `--committed` puts agent-made commits on the target branch, so it runs only when the
  developer's current message asks for exactly that.

- The target branch must be checked out in some worktree (normally the main checkout) with no tracked changes.
  A branch checked out nowhere is a problem to report; the command never switches branches.
- On success the command removes the worktree without asking. It sets no timer: the move is the trigger.
  Files the worktree's `.gitignore` rules ignore (local env files, caches, build outputs) never move and are
  deleted with the worktree; copy any worth keeping before the attach.
- Staging builds the patch in a throwaway copy of the worktree's index, so the worktree's own staged and
  unstaged split is never changed.
- Exit 1 prints `attach_worktree: <reason>` and keeps the worktree, files and index as they were. A refusal
  changes nothing else. A three-way conflict names the conflicted paths and leaves the markers, plus the rest of
  the patch staged, in the target checkout. A rerun is then refused (the target is no longer clean), so the
  error names both ways out:
  - finish: resolve the markers in the target, then `git worktree remove --force "<worktree path>"`;
  - undo: `git -C "<target checkout>" reset --hard` (the target had no tracked changes before the move), which
    keeps the worktree for a later attempt.
- Report the stdout lines. After a staged move the developer reviews `git diff --cached` and commits; the agent
  does not commit on the target.
