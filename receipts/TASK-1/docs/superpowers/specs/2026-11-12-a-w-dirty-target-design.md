# a-w: attach onto a dirty target, trial merge, auto-resolves and agent resolution

Issue #161 (todo-c69j). Branch `1157-a-w-committed`, cut from `main` at `6a9347a` (after PR 281 merged).

## Intent

`harness:a-w` refuses to move a worktree onto a branch whose checkout has any tracked change
(`plugins/harness/skills/a-w/commands/attach_worktree.py:254-256`). In #161 the refusal stopped an attach onto
`0101-pac-docs` of a consuming project whose main checkout held in-progress edits, most likely unrelated to the
worktree; the developer had to clean up by hand before the move could run.

The developer wants a-w to:

1. **Land beside in-progress work.** Edits in the target checkout that the worktree does not touch stay where
   they are, untouched.
2. **Never hand a conflict to the target checkout.** The merge is tried first where nothing real can break; the
   target changes only once the result is known to be clean.
3. **Settle routine conflicts by rule** (generated reports such as `*offlineTestReport.json`), and leave the
   rest to the session agent, which already holds the context of both sides. Anything ambiguous refuses.

## Goals

- A dirty target is accepted when no path the move writes is dirty there (staged or unstaged).
- A **trial merge** in memory (`git merge-tree --write-tree`) runs before the target changes.
- **Auto-resolve rules** settle conflicts whole-file in favor of one side, from project config plus
  per-run flags.
- Conflicts left after the rules are resolved **inside the worktree** by the session agent, through
  `--continue` / `--abort` on the same script. The target checkout never receives conflict markers.
- The move **lands atomically** (`git apply --index` of an exact diff, or `merge --ff-only`) after a race
  check, and prints a path-scoped undo.
- A narrow **rules exception** lets `attach_worktree.py` rewrite history inside a `d-w` worktree during an
  attach.

## Non-goals

- Hunk-level auto-resolution. A rule picks one side's whole file.
- Automatic resolution of anything not matched by a rule. The script never guesses.
- Changing what lands: staged mode still lands only the worktree's own changes, uncommitted; `--committed`
  still lands the worktree's commits by fast-forward and still runs only on the developer's explicit ask.
- Untracked files in the target, beyond refusing when one sits on a path the move adds (today's `git apply`
  failure, now reported by name before anything moves).

## Anti-goals

- Conflict markers or a half-applied patch in the target checkout. Today's conflict path
  (`conflict_message`, `attach_worktree.py:160-166`) and its blanket `reset --hard` undo go away.
- Touching the developer's dirty edits: no `stash` (push), no `reset`, no checkout of a dirty path. The one
  exception is a `worktree`-favoring rule on a dirty path (see Decided, item 6), which is backed up first and
  named in the report.
- Silently dropping one side's work. A rule names its side; two rules that disagree on a path refuse.
- The agent typing `rebase`, `merge` or `cherry-pick` itself. The script runs every history operation.

## Constraints

- Python 3.11, `Optional` / `Union`, functions under 50 lines, no first or second person in comments.
- Git 2.40 or later for `merge-tree --write-tree --merge-base` (the developer's machine has 2.45.1). The
  script checks the version once and refuses below it, naming the requirement.
- Plugins stay generic: the plugin default rule list is empty. `*offlineTestReport.json` belongs in the
  consuming project's `.claude/harness.json`.
- A new config key touches the four places in the project CLAUDE.md checklist: `config/defaults.json`,
  `config/harness.schema.json`, the dataclass and builder in `lib/harness_lib/config.py`, the README key table.
- `HARNESS_RULES.md:25` bans `rebase` and `cherry-pick` everywhere today; this design needs the exception
  below, added in the same change.

## Approaches

The developer's starting sketch: a scratch tree from the target branch, `merge --ff-only`, else a merge in the
scratch tree with conflicts resolved there, a stash of any drift in the target, a backup, then
`git branch -f <target>` to the scratch result. Checked against git in a temporary repository:

| Approach | Trade-off | Outcome |
|---|---|---|
| A. Scratch merge, then `git branch -f` | `branch -f` refuses a checked-out branch (`fatal: cannot force update the branch 'main' used by worktree`); `update-ref` would leave the checkout showing the merge reversed. The scratch merge makes a commit, so staged mode would land an agent commit. `git stash` moves the developer's edits. | Rejected; its "try somewhere disposable, then land" core is kept. |
| B. Keep the refusal, name the dirty paths | No new behavior; #161 still stops on unrelated edits. | Rejected. |
| C. In-memory trial merge, resolution inside the worktree, atomic land | `merge-tree` needs no scratch checkout; the worktree is already disposable and commits there are allowed; the target changes once, atomically. Needs the rules exception for the replay. | **Chosen.** |

Within C, the replay for `--committed`: `rebase --onto` and a cherry-pick range give the same commits. The
developer leaned to cherry-pick; `rebase --onto <target_head> <base>` was chosen because `cut_point()`
already yields `<base>`, `--abort` returns to the worktree's original HEAD, and it skips commits the target
already holds. The developer chose the rules exception over keeping `--committed` refusing on conflict.

## Decided

### The flow

1. **Preconditions** (unchanged): the worktree is a linked worktree, the target branch is checked out in a
   checkout other than the worktree, a detached main checkout needs a named branch.
2. **Snapshot the target.** Record `target_head` and the dirty path set: every path in
   `git status --porcelain --untracked-files=no`, both sides of a rename, staged and unstaged alike.
3. **Overlap check.** The worktree's own changed paths (its diff from `patch_base()`, uncommitted changes
   included) against the dirty set, after removing paths a `branch`-favoring rule covers (item 6). Any path
   left in both refuses, naming the paths. An untracked target file on a path the worktree adds refuses the
   same way.
4. **Backup.** `git stash create` in the target returns a commit of the dirty state, or nothing when the target
   is clean. Nothing in the checkout or the stash list changes. The sha is printed in every report.
5. **Trial merge.** Build a commit of the worktree's current state without touching its index or refs (the
   existing scratch index, `write-tree`, `commit-tree` on HEAD). Run
   `git merge-tree --write-tree --merge-base=<patch_base> <target_head> <that commit>`.
   - Clean: the result tree is the final tree. Go to item 8.
   - Conflicted: apply the rules to the conflicted paths (item 6) by taking the chosen side's blob into the
     result. When every conflict is ruled, go to item 8. Otherwise item 7.

   That routing is staged mode's. `--committed` goes to item 7 whenever `target_head` is not the worktree's
   merge base with the target (the target moved, or the cut is not in the target), clean trial or not: a
   fast-forward needs the worktree's commits replayed onto `target_head`, and only the replay can carry ruled
   blobs. The rebase applies the rules at each stop. Today's two `--committed` refusals (target moved,
   `attach_worktree.py:123-125`; cut not in the target, `:115-118`) go away: the rebase onto `target_head`
   from the cut carries only the worktree's own commits. `test_committed_refuses_when_the_target_moved` flips
   to a success test, and "cut not contained in the target" succeeds in both modes. The trial still runs first
   in `--committed`, so a conflict no rule covers is known before the worktree is touched.
6. **Auto-resolve rules.** `AutoResolve(pattern: str, in_favor_of: Literal["worktree", "branch"])`, frozen
   dataclass. `pattern` is an `fnmatch` pattern over the repository-relative POSIX path (the rule the
   exclusions file uses). The side's whole file wins, a deletion included. Sources: the project config key
   (below), then repeatable `--auto-resolve PATTERN=SIDE` flags from the agent. A path matched by rules
   that name different sides refuses (ambiguity), whatever their source. In staged mode a rule also governs
   a dirty overlap (item 3): `branch` keeps the checkout's copy and the move skips that path; `worktree`
   overwrites it, after the backup, and the report names it (item 8 gives the order). In `--committed` mode a
   dirty overlap always refuses, rule or none: a fast-forward cannot skip a path, and overwriting the dirty
   copy before it would break "a refusal changes nothing".
7. **Resolution in the worktree.** Requires a clean worktree: with uncommitted changes the script refuses and
   says to commit them in the worktree first (commits there are allowed). Then, under the rules exception:
   - staged mode squashes the worktree's own commits since `<patch_base>` into one commit, then runs
     `git rebase --onto <target_head> <patch_base>`, so conflicts come up once;
   - `--committed` runs the same rebase without the squash, so each commit keeps its message and grouping.

   At each stop the script applies the rules to the conflicted paths, `git add`s them and continues on its
   own while nothing else is conflicted. Otherwise it writes the state file, prints the remaining paths with
   the worktree path and exits 2. The agent edits those files in the worktree, `git add`s them and reruns the
   script with `--continue`. When either side's intent is unclear, the agent runs `--abort` and reports;
   `--abort` stops the rebase and returns the worktree to its original HEAD (`reset --hard` to the recorded
   sha, exact since the worktree was clean). After the last stop the final tree is the worktree's HEAD tree.
8. **Race check and land.** Re-read the target's HEAD and dirty set. A HEAD other than `target_head`, or a
   dirty path the move writes, refuses; on the resolution path the worktree keeps its resolved commits and the
   message says to rerun. Otherwise:
   - staged: `git apply --index` of `git diff --binary --full-index <target_head> <final tree>`, minus the
     dirty paths any rule governs. The remaining paths are clean in the target, so the apply is exact or
     fails whole. Only after it succeeds does each `worktree`-ruled dirty path get the final tree's blob,
     written to the working file and staged; an apply failure therefore leaves the dirty copies untouched;
   - `--committed`: `git merge --ff-only <worktree HEAD>` in the target. Git refuses it atomically if a dirty
     path would be overwritten.
9. **Report and cleanup.** Report lines name the staged file count or commit count, the backup sha, any
   overwritten dirty path, and the undo:
   - staged: `git -C <target> restore --source=HEAD --staged --worktree -- <paths>` for the clean paths;
     for each overwritten dirty path, `restore --source=<backup> --worktree` and
     `restore --source=<backup>^2 --staged` (the stash commit's tree holds the working copy, its second
     parent the index);
   - `--committed`: `git -C <target> reset --keep <target_head>`.

   The worktree is then removed, as today. Every refusal changes nothing in the target; refusals after
   item 7 started leave the worktree's resolved commits for a rerun.

### Interface

```
attach_worktree.py [TARGET] [--target-branch BRANCH] [--worktree PATH] [--committed]
                   [--auto-resolve PATTERN=SIDE ...] [--continue | --abort]
```

Exit codes: 0 moved, 1 refused (`attach_worktree: <reason>`), 2 stopped for agent resolution. `--continue`
and `--abort` read the state file and take no target or mode arguments; passing them with a different target
or mode refuses.

State file: `<worktree git dir>/harness-attach.json` (from `git rev-parse --git-path harness-attach.json`),
holding the target branch and checkout, mode, `target_head`, the worktree's original HEAD, `patch_base` and
the rules. It lives in the worktree's git dir, so it goes when the worktree goes. A plain rerun while it
exists refuses and names `--continue` / `--abort`. The file lasts until the land succeeds or `--abort` runs:
after a race refusal at item 8 the rerun is `--continue`, which, with no rebase in progress, redoes the
snapshot, overlap check and race check against the resolved worktree HEAD and lands; `--abort` still
returns the worktree to its original HEAD.

### Config key

`attach.auto_resolve`: a list of `{"pattern": str, "in_favor_of": "worktree" | "branch"}`, default `[]`.
Four places per the checklist. The script reads it through `harness_lib.config` after `activate(...)`, per
"drivers activate, library code reads".

### Rules exception (`plugins/harness/rules/HARNESS_RULES.md:25`)

Append to the history-rewrite rule: the one exception is `attach_worktree.py` (`harness:a-w`), which rebases
and squashes the worktree's own unpushed commits inside a `d-w` worktree during an attach. The agent resolves
conflicts and reruns the script with `--continue` or `--abort`; it never runs those operations itself. The
a-w and d-w SKILL.md texts say the same where they describe the move.

### Skill text (`plugins/harness/skills/a-w/SKILL.md`)

- The clean-target bullet becomes the overlap rule, with the backup and the path-scoped undo.
- The conflict bullet becomes the resolution loop: exit 2, edit and `git add` in the worktree, `--continue`;
  `--abort` on any ambiguity, then report.
- `--auto-resolve` and the config key, with the ambiguity refusal.
- `--committed` still runs only when the developer's current message asks for it.

## Left to the builder

- Function split inside `attach_worktree.py` (the developer's sketch names a `try_attach()` with private
  helpers per step); the module may grow past its current 290 lines and may split by concern.
- Exact wording of every refusal and report line, within the content listed above.
- How the squash commit and the state file are built, within the constraints above.
- Tests in `tests/skills/test_attach_worktree_script.py` (and a new file where a concern warrants it), each
  building repositories under `tmp_path`: clean target unchanged; disjoint dirty target; overlapping dirty
  target refused with names; untracked collision refused; trial conflict fully ruled; ambiguous rules
  refused; resolution stop, `--continue`, `--abort`; race refusal; `--committed` rebase and ff onto a moved
  target; cut not contained in the target; git version refusal. Mark `cross_os` where worktree paths matter.
- Release bookkeeping: harness minor bump and the release notes file, per the project CLAUDE.md.
