# PR 164 reviewer fan-out: why every reviewer ran on opus

Run `pr0164_20261031T043414Z`, `harness:pr-team`, PR #164 (`1107-merge-msg-drop-md` into `main`, head `8802b6c`, one commit).

## Section 1 - Who chose the model

The shim did not choose. The orchestrator (MODE=PLAN, sonnet) wrote `dispatch_plan_review.json` with five
`harness:pr-reviewer` agents, each carrying `"model": "opus"`. The shim then followed the pr-team SKILL.md rule
that Step 2 passes `model=<agents[i].model>` unchanged, because inheriting would silently take the main
session's model (sonnet here). So the choice is the planner's, applied under the skill's written default.

## Section 2 - The rule the planner applied

`plugins/harness/skills/pr-team/SKILL.md`, "Model floor (reviewer fan-out)":

- Reviewers SHOULD run on `opus` by default for multi-file analysis and complex reasoning.
- `sonnet` is allowed when the grouping is a single file, needs no comparison across files, or has one narrow
  concern.
- `haiku` is an anti-default for reviewers: it under-calls Critical findings.

The plan's slots against that rule:

| Slot             | Scope                                           | Rule trigger for opus              |
|------------------|-------------------------------------------------|------------------------------------|
| r1_tests         | 4 test files (210 added, 129 removed lines)     | multi-file                         |
| r2_runtime       | `merge_commit_msg.py`, hook, `plugin.json`      | multi-file, cross-file contract    |
| r3_docs          | README, two SKILL.md, `message_format.md`, spec | multi-file, prose vs code drift    |
| r4_overall       | whole diff, 12 files                            | cross-bucket by definition         |
| r5_system_shape  | lens `overall-system-shape`                     | cross-bucket by definition         |

Every slot spans at least two files, so none met the single-file exemption. The floor leaves no sonnet
branch for any of them.

## Section 3 - The case for opus on this PR

The diff is small, but its risk is in agreement between files, not inside any one file:

- The stdin contract lives in three places that must match: `merge_commit_msg.py` (reads stdin, re-fetches the
  title through `gh`), `SKILL.md` (heredoc instructions) and `guard_commit_txt.py` (deny message routing to
  `build`). A reviewer has to hold all three at once.
- The change removes a working file. The question "does anything still depend on `PR<N>_merge.md`" needs a
  tree-wide search plus judgment about what each hit means, which is the work the `overall-system-shape` lens
  exists for.
- Behavior moved from offline (MD on disk) to online (`gh pr view` inside `build`). Seeing that as a
  regression needs reasoning about what the old flow allowed, not just what the new code does.
- The tests fake `gh` and swap stdin for `io.StringIO`. Spotting what such fakes never exercise (encoding,
  tty, closed stdin) is an absence-of-coverage judgment.
- The review JSON is the gate for the merge. A missed Critical costs more than the token difference.

## Section 4 - What the evidence says so far

R2 (the only reviewer returned at the time of writing) found 4 minor issues, all of the kind Section 3
predicts: an encoding and tty edge on stdin that the tests cannot reach, a docstring that no longer states
that `build` now needs `gh` and the network, and a hook docstring that reads as a complete list. Two of the
four needed a view of the test harness or the previous behavior, not just the changed lines.

One data point is not a model comparison. It shows the opus run produced useful findings; it does not show
that a cheaper model would have missed them. Section 5 takes up that question.

Update, all five slots returned (reviewer-reported counts, before consolidation de-duplicates them):

| Slot            | Critical | Important | Minor |
|-----------------|----------|-----------|-------|
| r1_tests        | 0        | 0         | 5     |
| r2_runtime      | 0        | 0         | 4     |
| r3_docs         | 0        | 0         | 3     |
| r4_overall      | 0        | 1         | 5     |
| r5_system_shape | 0        | 1         | 5     |

What the overlap shows:

- Three slots (r3, r4, r5) reported the same defect: `SKILL.md` Step 2 tells the agent to retry every exit 1
  although `build` now also fails on `gh`, PR state or config; r2 reported the driver-docstring half of it.
  r4 graded it Important; r3 and r5 graded it Minor. The same finding under two severities is a
  consolidation call, not a model-tier signal.
- Pairs of slots reported the README `.bak` omission (r3, r4), the missing TTY or BOM handling (r2, r4) and
  the unpinned "Steps 1-2" reference (r4, r5). The fan-out paid more than once for the same findings.
- Only r5 reported what looks like a unique Important finding: `capture` prints no diff while `SKILL.md`
  now bans reading one. It came from the lens slot, the one Section 5 marked uncertain for sonnet.

## Section 5 - Could sonnet or haiku have done these checks

Written after Sections 1 to 4, from the plan and the one returned report. No slot was run on a cheaper model,
so every verdict below is a judgment, not a measurement.

### Sonnet

| Slot             | Sonnet fit  | Reasoning                                                                                   |
|------------------|-------------|---------------------------------------------------------------------------------------------|
| r1_tests         | likely good | Checks are bounded: does each planned behavior have a node, do the fakes match the driver's call shape, are the assertions tight. The brief can hand over the driver path. Weak spot: finding what the tests never reach. |
| r2_runtime       | uncertain   | The R2 findings were edge-case reasoning (BOM, a shell that pipes ASCII, a closed or tty stdin). Sonnet would probably reach the tty and `None` stdin cases; the Windows PowerShell 5.1 encoding point is the one most likely to be missed. |
| r3_docs          | likely good | Mostly consistency work: stale `_merge.md` references, step counts, wording that no longer matches the code. `SKILL.md` and `message_format.md` are short. |
| r4_overall       | likely good | Reads the same files the bucket reviewers read; the value is cross-bucket agreement, which sonnet handles on a 12-file diff. |
| r5_system_shape  | uncertain   | A lens that asks whether the change leaves the system coherent is open-ended; this is where depth shows. |

The SKILL.md floor still points to opus for all five, since each slot compares more than one file. The rule
as written has no way to say "multi-file but shallow", which is what r1 and r3 look like on this PR.

### Haiku

Haiku is a poor reviewer for any slot, and the skill already says so: it under-calls Critical findings. This PR
had no Critical finding to under-call, so it cannot confirm that. Haiku does fit a pre-pass that is not a
review:

- a sweep for leftover references to a removed file name (`_merge.md`, `md_path`, `extract_message`);
- the version bump present in `plugin.json`;
- the step count in `SKILL.md`.

Every one of those is a grep, and this PR's own `test_merge_commit_msg_skill_contract.py` already asserts
two of them. The mechanical checks belong in a test or a script; spending a model on them, even haiku, is the
wrong tool.

### Where the larger saving sits

Model tier is the smaller lever on this PR:

- `SkillSpec.json` (220 of the PR's 516 added lines, 43 percent, and its largest single addition) is a
  generated, frozen artifact that no reviewer should read line by line. Excluding it from the docs bucket
  cuts r3's input more than a tier change would.
- r4 (whole diff) and r5 (system shape) overlap with r1 to r3 and with each other. The `overall-system-shape`
  lens fires on a count rule (three non-empty buckets), so it fires on nearly every multi-bucket PR whatever the
  change's reach.
- Five opus slots on a 12-file PR where over half the added lines are spec and tests is a high fixed cost for
  4 minor findings so far.

### Recommendation

1. Keep opus for r2 and r5, where depth produced or would produce the findings.
2. Try sonnet for r1 and r3 on the next small PR, and compare each against an opus run of the same slot.
3. Record the model per row in the JSONL test matrix (`model_family` already exists) so the comparison is
   data, not opinion.
4. Treat the haiku sweep as a script, not an agent.
5. Revisit this report after consolidation, once the findings of all five slots can be set against their cost.

Open question for the developer: the floor in SKILL.md is the planner's only instruction, and it routes every
multi-file bucket to opus. Whether to add a "shallow multi-file" exemption is a change to that rule, and it
is not made here.
