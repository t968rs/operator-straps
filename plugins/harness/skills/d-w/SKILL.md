---
name: d-w
description: Use when asked to start, move, or do the work in a detached-HEAD worktree, a throwaway worktree, or an isolated checkout cut from HEAD, the base branch, or another ref.
argument-hint: "[HEAD|<integration-branch>|<ref>] [--name NAME] [--no-fetch] [--no-setup] [-- <guidance>]"
---

# d-w: work in a detached-HEAD worktree

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. The
part before it is `<worktree arguments>` below (a bare ref, `--name`, `--no-fetch`, `--no-setup`), passed through
unchanged.
The part after it is the guidance: the task or paths for the work done inside the worktree. It never reaches
the command.

Create the worktree with the bundled command (Bash tool), then do every later step of the task inside it.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/new_worktree.py" <worktree arguments>
```

When `.claude/harness.json` sets `worktree_setup` or `worktree_baseline` and `--no-setup` is not passed, run
the command with `run_in_background` and wait for its exit notification, or pass the Bash tool
`timeout: 600000`. Each step may run up to 600 s before it is killed, so several steps can outlast any
foreground timeout. The path is printed before the first step, so a run cut short still names the worktree;
its missing step lines then mean the setup and baseline state is unknown, not passed.

- Base defaults to the current **HEAD**. The project's integration branches (`integration_branches` in
  `.claude/harness.json`; when empty, the configured `base_branch` or the `origin/HEAD` branch, plus `main`)
  fetch `origin` and cut from `origin/<base>`. Without a remote, or with `--no-fetch`, they cut from the local
  branch (else the existing `origin/<base>`). Any other ref is cut as given.
- **stdout is the absolute worktree path, nothing else**; stderr names the sha and ref. Exit 1 = bad ref, a
  failed fetch (offline: rerun with `--no-fetch`) or an unreadable `harness.json`, nothing created. `--help`
  lists the rest.
- The path lands under the project's `worktree_root` (default `~/.config/harness/worktrees/<repo>/`; `--root`
  overrides); collisions get `-2`, `-3`.
- **Run from a linked worktree**, the command warns on stderr (`... is itself a linked worktree`) and still cuts
  the new worktree as a sibling under `worktree_root`. Say so in the report and confirm a second worktree is
  wanted before building on it; a worktree that already holds the task needs no second one.
- **Setup and baseline.** After the cut, the project's `worktree_setup` commands run in the new worktree (a
  dependency install into a worktree-local environment; an editable install into a shared interpreter repoints
  its package at the worktree), then its `worktree_baseline` commands (test files that name what they prove). Both are
  argv lists in `.claude/harness.json`; with neither set, nothing runs. stderr reports each as
  `setup [ok|fail]` or `baseline [ok|fail|skipped]`, with the output tail of a failure. In each list the first
  failure stops the list: a failed setup skips the baseline, and a failed baseline command marks each later one
  `baseline [skipped] <command>`. A step runs without a shell and with stdin closed, so a prompting command
  fails instead of waiting; a bare program is looked up on PATH (`.cmd` shims included on Windows) and a
  relative program path resolves against the new worktree. A failed step never fails the command: the
  worktree exists and the exit code stays 0. `--no-setup` skips both.
- **Why `EnterWorktree` is not used.** The host tool creates its worktree inside the project
  (`.claude/worktrees/`), on a new branch. That puts it inside the project directory; worktrees stay outside
  it because an IDE indexing the workspace holds file locks on Windows. This command keeps worktrees under
  `worktree_root`, detached, and `harness:a-w` owns the branch. Do not substitute `EnterWorktree` for this
  command.

## Afterward

- Report the path and the base sha in one line, then each `setup` and `baseline` line from stderr. A failed
  baseline means those failures exist before any change: record them and do not fix them as part of the task.
  A `baseline [skipped]` command was never run, so its state is unknown: record it as unrun, not as passing.
- Every Read / Edit / Write uses absolute paths under that worktree; every git call is `git -C "<path>" ...`.
  Do not `cd`. Do not touch the main checkout.
- Commits in the worktree are allowed. They sit on a detached HEAD until the work moves.
- Finishing: `harness:a-w` moves the work onto the branch the developer names (staged, or the commits with
  `--committed`) and removes the worktree. Use it rather than a hand-run `git worktree remove` for work that
  moves. Two cases take the hand-run `git worktree remove --force "<path>"`: a worktree whose work is
  discarded or that holds nothing to move (a-w refuses both), and a worktree whose a-w move stopped on a
  three-way conflict, once the markers in the target are resolved (`harness:a-w` names the command).
