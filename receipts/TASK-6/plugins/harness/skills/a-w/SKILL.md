---
name: a-w
description: Use when work done in a detached-HEAD worktree (see d-w) is finished and must move onto a target branch, either as the worktree's own commits or as staged, uncommitted changes. Triggers on "attach the worktree", "move the worktree changes to <branch>", "a-w".
argument-hint: "<target-branch|HEAD> [--committed] [--auto-resolve PATTERN=SIDE ...] [--worktree PATH] [-- <guidance>] | --continue [--worktree PATH] | --abort [--worktree PATH]"
---

# a-w: move a worktree's work onto a branch and drop the worktree

The developer names the target branch, or `HEAD` for the branch checked out in the main checkout; the command
does the rest. On a successful move the developer never edits, inspects or removes the worktree. A conflict
that no rule settles stops the command (exit 2) and hands the resolution to the agent, in the worktree and
never in the target (below).

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. The
part before it is `<attach arguments>` below (the target, `--committed`, `--auto-resolve`, `--continue`,
`--abort`, `--worktree`), passed through unchanged. The part after it is the guidance, for example a worktree
path to attach or a note on what to report; it never reaches the command, and it never turns on `--committed`.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/attach_worktree.py" <attach arguments> --worktree "<worktree path>"
```

Run it with the Bash tool from the main checkout, naming the worktree the session created with `d-w`. A
`--target_branch <name>` flag is accepted in place of the positional branch. `HEAD` resolves to the main
checkout's branch wherever the command runs; a detached main checkout is a problem to report, so name the
branch then.

| Mode | What lands on the target |
|---|---|
| default | The worktree's commits, edits and new files, **staged and uncommitted**. Only what the worktree changed since it was cut is measured (from its cut commit, the creation entry of its HEAD reflog; the merge base with the target instead when that merge base already contains the cut, or when reflog expiry dropped the creation entry or HEAD left the cut's history). A trial merge puts that change onto the target's HEAD, so commits the target gained since the cut are merged, never reverted, and history the cut commit carried that the target lacks stays behind. Conflicts arise only on paths both sides changed. |
| `--committed` | The worktree's own commits, fast-forwarded onto the target with their messages and grouping kept. Whenever the target's HEAD is not the worktree's base (the target moved since the cut, or lacks the cut), the commits are first rebased onto the target's HEAD inside the worktree; a merge commit in the range then refuses, since a rebase would flatten it (stage the work instead), while a plain fast-forward carries merges. Refuses uncommitted worktree changes (untracked files included) and a worktree with no commits beyond the target; none of these changes anything. |

- Default to staged mode. `--committed` puts agent-made commits on the target branch, so it runs only when the
  developer's current message asks for exactly that.
- The target branch must be checked out in some worktree (normally the main checkout). A branch checked out
  nowhere is a problem to report; the command never switches branches. The target may hold uncommitted edits:
  the ones on paths the move does not write stay exactly as they are.
- **Overlap rule.** A move refuses when it would write a path the target holds dirty, or a path where the
  target has something in the way:
  - a dirty tracked path: commit or stash it in the target, or settle it with an `--auto-resolve` rule
    (`--committed` refuses every dirty path its commits write, rules or not);
  - an untracked file in the way, or a file where the move needs a folder: move it aside. A rule never clears
    an untracked file.
- **Backup and undo.** Before the target changes, the command records a backup sha of the target's dirty
  state. The success report prints it with undo commands that match the mode: path-scoped for a staged move,
  and for `--committed` a `reset --keep <old head>` that moves the branch back, which belongs to the
  developer. Run an undo only when the developer asks for it, or after a failure past the backup point (a staged
  move's error then prints the backup and undo lines, since the target may hold part of the move; a failed
  `--committed` fast-forward prints the backup and leaves the target where it was).
- On success the command removes the worktree without asking. It sets no timer: the move is the trigger.
  Files the worktree's `.gitignore` rules ignore (local env files, caches, build outputs) never move and are
  deleted with the worktree; copy any worth keeping before the attach.
- Staging applies the exact result to the target's index and working tree; the worktree's own staged and
  unstaged split is never changed.

## Auto-resolve rules

`--auto-resolve PATTERN=SIDE` (repeatable) settles a conflict, or a dirty-path overlap, on every path matching
the fnmatch glob `PATTERN` by taking one side's whole file: `SIDE` is `worktree` (the worktree's copy, a
deletion included) or `branch` (the target's copy; a dirty copy there is kept). A `worktree` rule overwrites a
dirty target path after the backup. The rules of the `attach.auto_resolve` key of `.claude/harness.json` apply
first, the flags after them. Rules that name different sides for one path are ambiguous, and the command
refuses. Overlap rules apply to staged mode only. Use a rule only for paths the developer named as always
going one way (a lockfile, a generated file); never invent one to get past a conflict.

## Resolution loop

When the trial merge (or, with `--committed`, the rebase) leaves a conflict no rule settles, the command
replays the worktree's work onto the target's HEAD with `git rebase` inside the worktree (staged mode squashes
it into one commit first), settles ruled paths at each step, and exits 2 naming the paths left. The target
checkout receives no conflict. It needs a worktree with no uncommitted or untracked changes; with any, it
refuses and changes nothing, so commit them in the worktree first (commits there are allowed).

At exit 2:

1. Edit each named file in the worktree to its resolved content, then `git -C "<worktree path>" add -- <paths>`.
2. Rerun the command with `--continue --worktree "<worktree path>"`. It may stop again on the next commit of
   the rebase, with the same steps.
3. If the right resolution is not clear from the two sides, or a rerun refuses in a way not covered below, run
   `--abort --worktree "<worktree path>"` and **report to the developer** which paths conflict and why.
   Guessing at a conflict puts a wrong merge on the developer's branch.

During a stop the agent runs no `rebase`, `merge`, `cherry-pick` or `reset` of its own in the worktree: the
attach cannot tell what such a step brought in, and the land would carry it.

`--continue` and `--abort` take no target, mode or new rules (`--abort` ignores `--auto-resolve`). `--abort`
returns the worktree to the HEAD it had before the attach and leaves the target untouched. Follow a refusal
that names `--continue` or `--abort`; a refusal that names a `git rebase` or `reset` command goes to the
developer, who runs it. While a stop is pending, a plain run refuses.

## Exit codes and reports

- **0**: moved (the worktree is removed), or aborted.
- **1**: refused or failed; `attach_worktree: <reason>` on stderr. A refusal never changes the target. Outside
  the resolution loop it leaves the worktree's files and index as they were. Inside the loop some refusals
  leave the worktree rebased:
  - the error says the attach state is kept: the way out is `--continue` or `--abort`, as it names;
  - the error says the attach is dropped and the worktree kept (a resolution or a `--committed` rebase that
    leaves nothing to move, say): the worktree HEAD may sit at the rebased commit and `--abort` no longer
    applies, so report it to the developer and stop.

  A usage error also exits 1. If the move succeeded but the worktree removal failed, the report prints and the
  error names the removal command.
- **2**: stopped for resolution only; the stdout lines name the paths and the commands for the loop above.

Report the stdout lines and, on exit 1, the `attach_worktree: <reason>` line. After a staged move the developer
reviews `git diff --cached` and commits; the agent does not commit on the target.
