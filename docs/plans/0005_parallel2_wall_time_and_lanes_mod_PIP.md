# Plan 0005: parallel2 wall time and lanes mod

> Rendered by `plan.py render` from `0005_parallel2_wall_time_and_lanes_mod_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-03
**Spec:** `https://github.com/t968rs/operator-straps/issues/181#issuecomment-6618854195`
**Branch:** none -> main
**Base commit:** `10d0ad2`
**Frozen:** 2026-11-03 at `10d0ad2`
**Execution model:** serial

## Decisions

- **D1** Base of a wave set up while earlier-wave work is staged Chosen: `snapshot` (commit-tree of the index with HEAD as parent; no ref moves). Rejected: `require-commit` (keep asking the developer to commit first). Developer approved W1 as the wanted skill behavior.
- **D2** How the driver learns a probe came back clean Chosen: `probe-passed` (`probe --passed <names>` records the lanes probed). Rejected: `no-skip` (probe every wave). Developer choice.
- **D3** Runner for `setup --with-setup` Chosen: `reuse-dw` (load d-w new_worktree.py by path and call prepare()). Rejected: `move-lib` (move the step runner into harness_lib). Developer choice; no code moves, d-w tests untouched.
- **D4** Model when the Agent call differs from the plan's lane model Chosen: `plan-wins` (rewrite to the lane model and toast the override). Rejected: `call-wins` (fill only a missing model). Developer choice.
- **D5** Name of the new mod Chosen: `parallel2-lanes` (plugins/parallel2-lanes). Rejected: `lane-watch` (plugins/lane-watch). Developer choice.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| snapshot commit identity | parallel2 <parallel2@localhost> | D1 | snapshot |

## Formats

- **dispatch row Brief line**: `Brief: C:/repo/.claude/state/harness/parallel2/feat-x/task1.md`, copied from `plugins/harness/lib/harness_lib/parallel_lanes.py:434-437`
- **run state JSON**: `{"target": "feat-x", "lanes": [{"id": "task1", "status": "dispatched"}]}`, copied from `plugins/harness/lib/harness_lib/parallel_lanes.py:340-342`

## Sweeps

- **S1** `seven TypeScript mods`: `CLAUDE.md` (changed to eight by TASK-9), `docs/PR_REVIEWS/0122_1095_bubble_memos.json` (historical review record, unchanged), `tests/contract/test_bubble_stamp_registration.py` (changed to eight by TASK-9)
- **S2** `pending paths in the checkout|commit them first if a lane`: `plugins/harness/scripts/parallel2.py` (note reworded by TASK-1), `tests/scripts/test_parallel2.py` (note test updated by TASK-1)
- **S3** `commit the staged work`: `plugins/harness/skills/parallel2/SKILL.md` (step 7 rewritten by TASK-6)

## Tasks

### TASK-1: W1: cut a wave from an index snapshot when changes are staged

**Status:** COMPLETE | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/scripts/parallel2.py`, `plugins/harness/lib/harness_lib/parallel_lanes.py`, `tests/scripts/test_parallel2.py`

**Anchors:**
- `plugins/harness/scripts/parallel2.py:278-283` holds `pending = pending_paths(repo)`
- `plugins/harness/scripts/parallel2.py:282` holds `base_sha = git_out(repo, "rev-parse", "HEAD").strip()`
- `plugins/harness/scripts/parallel2.py:348-353` holds `if head == item.base_sha:`
- `plugins/harness/scripts/parallel2.py:373` holds `pending = pl.pending_overlap(changed, pending_paths(repo))`
- `plugins/harness/scripts/parallel2.py:292-295` holds `pending paths in the checkout are not in the lanes' base`
- `plugins/harness/lib/harness_lib/parallel_lanes.py:64` holds `base_sha: Optional[str] = None`

In setup, when the index differs from HEAD, write the index as a tree and cut the lanes from `git commit-tree <tree> -p HEAD` (fixed parallel2 identity), so staged earlier-wave work is in the lanes' base without a commit on the target. Record `head_sha` (HEAD at setup) beside `base_sha`; `moved_note` compares HEAD with `head_sha` (falling back to `base_sha` for older state). Setup refuses only unstaged or untracked paths inside lane files; staged paths go into the snapshot, and the note counts unstaged or untracked paths and says to stage them. Print `note: lanes cut from an index snapshot <base7> of HEAD <head7> (<n> staged paths)`. At stage, a changed path is refused when it is unstaged or untracked in the checkout, or staged with index content that differs from the lane base.

- [x] Test `tests/scripts/test_parallel2.py::test_setup_notes_pending_paths_outside_the_lanes` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_parallel2.py::test_setup_cuts_lanes_from_an_index_snapshot_when_changes_are_staged` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_parallel2.py::test_setup_accepts_staged_changes_inside_lane_files` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_parallel2.py::test_a_later_wave_builds_on_the_staged_earlier_wave` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_parallel2.py::test_stage_refuses_a_path_restaged_since_the_snapshot` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-1 --sha <sha>`

**Evidence:** commit 2c294d5: 5 test node(s) passed

- `2c294d5c381393d9414adcc33aadd47a313564ea`
- `tree 0ab2690b2d80574e90f653b00a15ea822f2fcbb5`
- `python -m pytest -q tests/scripts/test_parallel2.py::test_setup_notes_pending_paths_outside_the_lanes tests/scripts/test_parallel2.py::test_setup_cuts_lanes_from_an_index_snapshot_when_changes_are_staged tests/scripts/test_parallel2.py::test_setup_accepts_staged_changes_inside_lane_files tests/scripts/test_parallel2.py::test_a_later_wave_builds_on_the_staged_earlier_wave tests/scripts/test_parallel2.py::test_stage_refuses_a_path_restaged_since_the_snapshot`

### TASK-2: W2: record passed probes and skip covered profiles in later waves

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-1
**Files:** `plugins/harness/scripts/parallel2.py`, `plugins/harness/lib/harness_lib/parallel_lanes.py`, `tests/scripts/test_parallel2.py`

**Anchors:**
- `plugins/harness/scripts/parallel2.py:322-334` holds `for profile in pl.probe_profiles(members):`
- `plugins/harness/scripts/parallel2.py:513-514` holds `probe.add_argument("--wave", type=int`
- `plugins/harness/lib/harness_lib/parallel_lanes.py:304-312` holds `def probe_profiles(lanes: Sequence[Lane]) -> List[Profile]:`

Add `Lane.probed: bool = False`. `probe --passed NAME ...` marks every lane of each named profile of the wave probed and prints `recorded <name> clean: <lane ids>`; an unknown name is `no probe profile <name> in wave <n>`. Without `--passed`, a profile whose tools all belong to probed lanes whose worktrees share the profile's worktree parent prints `probe=<name> skipped: its tools were probed clean (<lane ids>)` instead of a prompt.

- [x] Test `tests/scripts/test_parallel2.py::test_probe_passed_records_the_profile_lanes_clean` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_parallel2.py::test_probe_skips_a_later_profile_covered_by_a_passed_probe` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_parallel2.py::test_probe_passed_names_an_unknown_profile` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-2 --sha <sha>`

**Evidence:** commit 9c5a9e1: 3 test node(s) passed

- `9c5a9e1b4647e0ec8490d433c3417cb7b28bd3fb`
- `tree adfe970a4034180e0efc93629bda302c251ce7e5`
- `python -m pytest -q tests/scripts/test_parallel2.py::test_probe_passed_records_the_profile_lanes_clean tests/scripts/test_parallel2.py::test_probe_skips_a_later_profile_covered_by_a_passed_probe tests/scripts/test_parallel2.py::test_probe_passed_names_an_unknown_profile`

### TASK-3: W4: setup --probe prints the probe prompts after the dispatch rows

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-2
**Files:** `plugins/harness/scripts/parallel2.py`, `tests/scripts/test_parallel2.py`

**Anchors:**
- `plugins/harness/scripts/parallel2.py:511-512` holds `setup.add_argument("--wave", type=int`

Add `setup --probe`: after the dispatch rows, print the wave's probe output exactly as `probe --wave <n>` would, saving one driver call per wave.

- [x] Test `tests/scripts/test_parallel2.py::test_setup_probe_prints_the_dispatch_rows_then_the_probe_prompts` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-3 --sha <sha>`

**Evidence:** commit e041411: 1 test node(s) passed

- `e0414116772a60ecf28fd8ec88eb080a6e2c1477`
- `tree 3c0ca944c95ad7e83d841b3ffdbb5a542281445f`
- `python -m pytest -q tests/scripts/test_parallel2.py::test_setup_probe_prints_the_dispatch_rows_then_the_probe_prompts`

### TASK-4: W5: cut the wave's worktrees concurrently

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-3
**Files:** `plugins/harness/scripts/parallel2.py`, `tests/scripts/test_parallel2.py`

**Anchors:**
- `plugins/harness/scripts/parallel2.py:251-258` holds `done = git(repo, "worktree", "add", "-b", item.branch, item.worktree, base_sha)`

In `create_worktrees`, pick each lane's path first, then run the `git worktree add` calls in a thread pool through the module-level `git`; when any fails, remove every worktree this call made and raise the first failure, as the serial loop does.

- [x] Test `tests/scripts/test_parallel2.py::test_setup_cuts_worktrees_concurrently_and_rolls_back_on_a_failure` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-4 --sha <sha>`

**Evidence:** commit 49bfa07: 1 test node(s) passed

- `49bfa077bd51b2f38816091303311ea30eb79830`
- `tree 23f7fd444e6afe2c43cb259a4e11d51e15f686c7`
- `python -m pytest -q tests/scripts/test_parallel2.py::test_setup_cuts_worktrees_concurrently_and_rolls_back_on_a_failure`

### TASK-5: W7: setup --with-setup runs the project's worktree setup in each lane

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-4
**Files:** `plugins/harness/scripts/parallel2.py`, `tests/scripts/test_parallel2.py`

**Anchors:**
- `plugins/harness/skills/d-w/commands/new_worktree.py:202-208` holds `def prepare(cfg: HarnessConfig, path: Path) -> None:`

Add `setup --with-setup`: after the worktrees are cut, load `skills/d-w/commands/new_worktree.py` by path and call its `prepare(cfg, path)` for each implement lane in turn, each preceded by a `lane <id>:` line on stderr. A failed step never fails setup, as in d-w.

- [x] Test `tests/scripts/test_parallel2.py::test_setup_with_setup_runs_the_project_setup_in_each_lane` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-5 --sha <sha>`

**Evidence:** commit 10329ec: 1 test node(s) passed

- `10329ec6d0dc0aa9e08a89acb64e65b8b3867eba`
- `tree ef77d424448fcc6401bf8e2ef13fa80e53ac64d1`
- `python -m pytest -q tests/scripts/test_parallel2.py::test_setup_with_setup_runs_the_project_setup_in_each_lane`

### TASK-6: W3 + docs: skill and README describe the faster wave flow

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-5
**Files:** `plugins/harness/skills/parallel2/SKILL.md`, `plugins/harness/skills/parallel2/README.md`, `plugins/harness/.claude-plugin/plugin.json`

**Anchors:**
- `plugins/harness/skills/parallel2/SKILL.md:54` holds `` **`P2 setup --wave N`**, then **`P2 probe --wave N`** ``
- `plugins/harness/skills/parallel2/SKILL.md:74-75` holds `` ask the developer to commit the staged work before `setup` ``

SKILL.md: step 3 uses `setup --probe`, dispatches every probe prompt in one message, and records clean probes with `probe --passed`; step 7 says a later wave is cut from an index snapshot, so staged earlier-wave work needs no commit; `--with-setup` is named; the `parallel2-lanes` mod is named as the optional brief inliner and lane band. README.md: lifecycle table and worked-example point 5 follow. Bump the harness plugin version.

- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_the_harness_skill_names_the_mod` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-6 --sha <sha>`

**Evidence:** commit c2c5a75: 1 test node(s) passed

- `c2c5a7548d1b2a92f76877b429a0457444364ce6`
- `tree 2f1d432856372cd604d191553db4686da3505c5b`
- `python -m pytest -q tests/contract/test_parallel2_lanes_registration.py::test_the_harness_skill_names_the_mod`

### TASK-7: M3: parallel2-lanes mod rewrites a lane's Agent spawn

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-6
**Files:** `plugins/parallel2-lanes/.claude-plugin/plugin.json`, `plugins/parallel2-lanes/hooks/hooks.json`, `plugins/parallel2-lanes/hooks/register.ts`, `plugins/parallel2-lanes/hooks/lanes.ts`, `plugins/parallel2-lanes/hooks/spawn.ts`, `plugins/parallel2-lanes/hooks/spawn.test.ts`, `plugins/parallel2-lanes/tsconfig.json`, `plugins/parallel2-lanes/.gitignore`, `plugins/parallel2-lanes/types/index.d.ts`, `plugins/parallel2-lanes/README.md`

**Anchors:**
- `plugins/band-line/hooks/band.tsx:21` holds `const below = await next(e).catch(() => undefined)`

New mod `plugins/parallel2-lanes` (manifest, hooks.json, register.ts, tsconfig, .gitignore, types, README). An `agent.spawn` hook (forks, teammates and resumes pass through) reads a prompt whose first line is `Brief: <path>` with the path at `<folder>/parallel2/<slug>/<lane>.md`, reads the brief and the state `<folder>/parallel2/<slug>.json`, and for a recorded lane: puts the brief text first in the prompt (the Brief line kept below it), sets the planned model (toasting an override of a different model) and sets `cwd` to the lane's worktree for an implement lane. It records `agentId -> lane` in `$.state`. Anything unreadable passes the spawn through unchanged.

- [x] Run `claude plugin validate --strict plugins/parallel2-lanes`: no errors
- [x] Run `claude plugin test plugins/parallel2-lanes`: 0 fail
- [x] Record the commit: `plan.py record 0005 TASK-7 --sha <sha>`

**Evidence:** commit a6eb6a5

- `a6eb6a545d1a1cab33a7fc20b7c5dd4ef5300df5`
- `tree 2388ed32b2e9f87eae7f3c1a62d2dcfef595018e`

### TASK-8: M4: lane status band

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-7
**Files:** `plugins/parallel2-lanes/hooks/register.ts`, `plugins/parallel2-lanes/hooks/band.tsx`, `plugins/parallel2-lanes/hooks/band.test.tsx`, `plugins/parallel2-lanes/hooks/lanes.ts`, `plugins/parallel2-lanes/types/index.d.ts`, `plugins/parallel2-lanes/README.md`

A `ui.render` `AbovePrompt` hook draws one line per run seen this session, above the band beneath: `parallel2 <target>: <lane> <status>[ (running|returned)] ...`. The runs come from the spawn records; each is reread after a lane spawn, a lane's `turn.complete` (marked returned) and a Bash or PowerShell call naming `parallel2.py`. A run whose state file is gone is dropped.

- [x] Run `claude plugin validate --strict plugins/parallel2-lanes`: no errors
- [x] Run `claude plugin test plugins/parallel2-lanes`: 0 fail
- [x] Record the commit: `plan.py record 0005 TASK-8 --sha <sha>`

**Evidence:** commit c4c4daf

- `c4c4daf7d5f3dfb7c63cda12d070237da6b61830`
- `tree 9dcb66b6377356953854f6e281329d2860475c60`

### TASK-9: Register the parallel2-lanes mod

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-8
**Files:** `.claude-plugin/marketplace.json`, `.github/workflows/ci.yml`, `CLAUDE.md`, `README.md`, `tests/contract/test_bubble_stamp_registration.py`, `tests/contract/test_parallel2_lanes_registration.py`

**Anchors:**
- `.github/workflows/ci.yml:126` holds `plugins/bubble-stamp; do claude plugin test`
- `CLAUDE.md:3` holds `seven TypeScript mods`

Marketplace entry, CI mod-test loop, CLAUDE.md mod list and count (eight), root README table row and install line; the bubble-stamp contract test counts eight mods.

- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_the_marketplace_lists_the_mod` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_the_mod_manifest_and_hooks` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_ci_runs_the_mod_tests` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_the_readme_documents_and_installs_the_mod` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_claude_md_names_the_mod` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_the_mod_has_a_readme` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_engine_scaffolding[tsconfig]` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_engine_scaffolding[gitignore]` fails with AssertionError, then passes
- [x] Test `tests/contract/test_parallel2_lanes_registration.py::test_engine_scaffolding[types]` fails with AssertionError, then passes
- [x] Test `tests/contract/test_bubble_stamp_registration.py::test_claude_md_counts_eight_mods` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0005 TASK-9 --sha <sha>`

**Evidence:** commit 865248d: 10 test node(s) passed

- `865248db61166092bafab5917b2cf5a0a2cfac7a`
- `tree b9b3813742d311a61ecd1f2fc4bb1b17e62c18ca`
- `python -m pytest -q tests/contract/test_parallel2_lanes_registration.py::test_the_marketplace_lists_the_mod tests/contract/test_parallel2_lanes_registration.py::test_the_mod_manifest_and_hooks tests/contract/test_parallel2_lanes_registration.py::test_ci_runs_the_mod_tests tests/contract/test_parallel2_lanes_registration.py::test_the_readme_documents_and_installs_the_mod tests/contract/test_parallel2_lanes_registration.py::test_claude_md_names_the_mod tests/contract/test_parallel2_lanes_registration.py::test_the_mod_has_a_readme tests/contract/test_parallel2_lanes_registration.py::test_engine_scaffolding[tsconfig] tests/contract/test_parallel2_lanes_registration.py::test_engine_scaffolding[gitignore] tests/contract/test_parallel2_lanes_registration.py::test_engine_scaffolding[types] tests/contract/test_bubble_stamp_registration.py::test_claude_md_counts_eight_mods`
