# parallel2

Set up a parallel subagent dispatch so lanes do not collide and tools do not prompt. The agent writes a plan of
lanes; the driver (`scripts/parallel2.py`) checks it, cuts the worktrees, writes each lane's brief, stages
finished lanes onto the target branch and removes what the run created. `SKILL.md` is the procedure the agent
follows; this file explains the shape of it.

## The two prongs

```
PRONG 1: WORKTREE PROTOCOL            PRONG 2: PROBE + PERMISSIONS
structure the work so lanes           verify tools will not prompt
do not collide                        before scaling to the batch

- one worktree per implement lane     - one probe agent per tool profile
- lanes within a wave own disjoint    - fix gaps, re-probe, then
  file sets                             dispatch the batch
- stage onto the target; never
  commit there

           both done -> dispatch the wave
```

The prongs are separate checks: `setup` cuts the worktrees first, then `probe` exercises the tools inside those
worktrees before any lane of the wave is dispatched.

**Why worktrees.** Subagents sharing one working tree overwrite each other's edits and break each other's test
runs. Each implement lane gets its own branch and directory, cut from the target branch's HEAD.

**Why a probe instead of reading `settings.json`.** Reading the allow lists does not prove a tool will not
prompt: a glob that looks right may not match the argument shape used, worktree paths fall outside globs
anchored at the project directory, and settings can drift during a session. One cheap agent exercising each
tool once is proof; a prompt in the middle of a batch of five agents is not cheap.

**Why the driver stages instead of `git checkout <branch> -- <files>` by hand.** A whole-file checkout replaces
the target's copy. If the developer committed to one of those files after the worktree was cut, the hand
checkout silently reverts that commit, and files the lane deleted or renamed are never staged at all. `stage`
applies the lane's own diff (from the commit the worktree was cut at) three-way onto the target's index:
target commits made since setup are merged, deletions and renames land, and a real conflict leaves markers
and is named. It refuses when a lane path has uncommitted edits in the target checkout.

## Lifecycle

| Step | Command | Result |
|---|---|---|
| Plan | `parallel2.py plan plan.json` (`-` for stdin) | Overlap check, waves, prongs, probe profiles; run state written |
| Set up a wave | `parallel2.py setup --wave N` | One worktree and branch `p2/<lane>` per implement lane; one brief per lane; dispatch rows |
| Probe | `parallel2.py probe --wave N` | One probe prompt per tool profile |
| Stage a lane | `parallel2.py stage <lane>` | Lane's diff merged three-way into the target checkout's index, no commit |
| Inspect | `parallel2.py status` | Lanes with wave, status, branch, worktree |
| Clean up | `parallel2.py cleanup` | Staged lanes' worktrees and branches removed; `--all` for every lane |

Run state lives under the project's `state_dir` (`parallel2/<target>.json`, briefs in `parallel2/<target>/`),
one run per target branch. `--target BRANCH` names the run when the checkout is on another branch; `setup` and
`stage` still require the target to be checked out.

## Worked example: a three-wave refactor

A pipeline coordinator plus its sampling, processing and I/O modules, reduced to its parallel geometry:

```
W0  setup (main session, serial)
W1  W1A coordinator + tests      \
    W1B sampling tests RED        > 3 worktrees, parallel
    W1C test-infra audits        /
W2  W2A sampling.py rewrite      \  2 worktrees, parallel
    W2B processing.py audit      /
W3  io.py cleanup (1 worktree)
W4  verification (main session, serial)
```

Maximum concurrency is three (W1). The W1 lanes own disjoint file sets, so `plan` accepts them as one wave; had
W2A and W2B both listed `processing.py`, `plan` would have refused an explicit shared wave. Without waves, `plan`
packs first-fit from wave 1 by file overlap only, so W2A and W2B would land in waves 1 and 2 and dependencies
are ignored: lanes that depend on another lane or share an invariant must carry explicit waves.

Skills that apply per wave (those outside this plugin apply when installed):

| Wave | Concern | Skill |
|---|---|---|
| W0 | Worktree placement outside the project, IDE file locks | `harness:d-w` (conventions only; `parallel2 setup` cuts the lanes and does not run `worktree_setup` or `worktree_baseline`) |
| W1, W2 dispatch | Mechanical overlap and permissions | `harness:parallel2` |
| W1, W2 dispatch | Conceptual overlap: lanes on different files sharing an invariant | `superpowers-lt:dispatching-parallel-agents` |
| W1A, W2A | A failing test before runtime code | `superpowers-lt:test-driven-development` |
| W1A, W1B | One evidence shape per lane for the merge decision | `harness:subagent-reporting` |
| W1C | CI and guard-suite edits | the project's CI-discipline skill, if any |
| W4 | Evidence before claiming done | `superpowers-lt:verification-before-completion` |

Reading the example:

1. **Draw the wave shape first.** Independent lanes share a wave; a dependency separates waves.
2. **Label each wave by the kind of work**, not by its files: setup, dispatch, test discipline, CI hygiene,
   completion.
3. **A lane can sit in several domains.** W1A is test discipline (red to green) and lane evidence (it reports to
   the merge gate).
4. **`parallel2` and the dispatch skill pair on every multi-lane wave.** `parallel2` catches shared files; the
   dispatch skill catches shared invariants across different files.
5. **A wave that reads an earlier wave's output** needs that output committed on the target first: worktrees
   are cut from the target's HEAD, and staged changes are not in it. `setup` prints a note when the checkout
   has pending changes.

## Related

- `SKILL.md`: the procedure.
- `../../scripts/parallel2.py`: the driver; `--help` on each subcommand lists its options.
- `../d-w/SKILL.md`: a single detached worktree for one-off isolated work.
