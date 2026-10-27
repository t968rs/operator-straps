---
name: d-w
description: Use when asked to start, move, or do the work in a detached-HEAD worktree, a throwaway worktree, or an isolated checkout cut from HEAD, the base branch, or another ref.
argument-hint: "[HEAD|<integration-branch>|<ref>] [--name NAME] [--no-fetch] [-- <guidance>]"
---

# d-w: work in a detached-HEAD worktree

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. The
part before it is `<worktree arguments>` below (a bare ref, `--name`, `--no-fetch`), passed through unchanged.
The part after it is the guidance: the task or paths for the work done inside the worktree. It never reaches
the command.

Create the worktree with the bundled command (Bash tool), then do every later step of the task inside it.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/new_worktree.py" <worktree arguments>
```

- Base defaults to the current **HEAD**. The project's integration branches (`integration_branches` in
  `.claude/harness.json`; when empty, the configured `base_branch` or the `origin/HEAD` branch, plus `main`)
  fetch `origin` and cut from `origin/<base>`. Without a remote, or with `--no-fetch`, they cut from the local
  branch (else the existing `origin/<base>`). Any other ref is cut as given.
- **stdout is the absolute worktree path, nothing else**; stderr names the sha and ref. Exit 1 = bad ref, a
  failed fetch (offline: rerun with `--no-fetch`) or an unreadable `harness.json`, nothing created. `--help`
  lists the rest.
- The path lands under the project's `worktree_root` (default `~/.config/harness/worktrees/<repo>/`; `--root`
  overrides); collisions get `-2`, `-3`.

## Afterward

- Report the path and the base sha in one line.
- Every Read / Edit / Write uses absolute paths under that worktree; every git call is `git -C "<path>" ...`.
  Do not `cd`. Do not touch the main checkout.
- Commits in the worktree are allowed. They sit on a detached HEAD until the work moves.
- Finishing: `harness:a-w` moves the work onto the branch the developer names (staged, or the commits with
  `--committed`) and removes the worktree. Use it rather than a hand-run `git worktree remove` for work that
  moves. Two cases take the hand-run `git worktree remove --force "<path>"`: a worktree whose work is
  discarded or that holds nothing to move (a-w refuses both), and a worktree whose a-w move stopped on a
  three-way conflict, once the markers in the target are resolved (`harness:a-w` names the command).
