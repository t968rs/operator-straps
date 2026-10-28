# PR 117 review cycle: wall time, and a comparison with the planner at `f9becaa`

PR #117 (`New Skill: write-plan`), branch `1092-writing-plans`, review run `pr117_20261028T143937Z`.
Branch head at review time `e4ce565` (PR base `main`). Date: 2026-10-28.

## Session

- Work under review: the `harness:write-plan` skill and its driver (`plugins/harness/scripts/plan.py`), v1 in
  `3ac4b7c` and v2 (`red`, `lanes`, freeze runs red) in `e4ce565`. Background: issue #116.
- `harness:pr-review 117`, `--roast roll` (rolled no). Structural guards skipped (no CICD or test-infra paths).
- Review JSON: `docs/PR_REVIEWS/0117_New_Skill_write-plan.json`. Run directory:
  `docs/_scratch/pr_review/0117/pr117_20261028T143937Z/` (`plan.json`, `waves.json`, `findings/`, `fixes/`).
- Findings after `merge`: 1 critical, 9 important, 15 minor (C1, I1-I9, M1-M15); no regrades, no merge
  candidates, 22 strengths. Verdict at build: `NOT READY TO MERGE - critical: C1`.
- Phase 4 first and second runs passed (dirty paths were all excluded artifacts). No bubbles.
- Closeout: first run blocked on M6 (a split part listed a `no_change` file outside its fixer's set; the fix was
  in place in all three files), settled with `closeout --resolved M6=...`. Final verdict
  `READY TO MERGE - 25 of 25 findings resolved, 0 bubbled`.
- Post-fix check: 238 passed over the plan, lanes and contract test files (`test_plan_driver`, `test_plan_red`,
  `test_plan_lanes`, `test_plan_doc`, `test_plan_checks`, `test_plan_checks_cycles`, `test_plan_render`,
  `test_parallel_lanes`, `test_no_repo_literals`, `test_root_separation`). Ruff `--no-cache` clean on the touched
  files after one E501 fix in `tests/scripts/test_plan_driver.py:83` left by a fixer. Full suite not run.

## Measured durations

Engine-reported, per agent.

| Phase | Agent | Model | Seconds | Issues |
|---|---|---|---|---|
| Reviewers (parallel) | config | sonnet | 42 | 2 minor |
| | docs | opus | 253 | 3 I, 5 M |
| | runtime | opus | 376 | 3 I, 5 M |
| | overall | opus | 627 | 1 C, 5 I, 5 M |
| | tests | opus | **1144** | 1 C, 2 I, 5 M |
| Wave 1 (parallel) | w1_fix_5 | haiku | 41 | M6, M7, M12 |
| | w1_fix_1 | haiku | 48 | M7, M8, M11, I6, I8 |
| | w1_fix_4 | haiku | 65 | M6, M10, M11, M14, M15, I8 |
| | w1_fix_3 | opus | 86 | M4, M5, M9, M10, M11 |
| | w1_fix_2 | opus | **213** | M1, M2, M13, I3, C1 |
| Wave 2 | w2_fix_1 | opus | **395** | M3, I1, I2, I4, I5, I9 |
| Wave 3 | w3_fix_1 | opus | **34** | I7 |

Wall: reviewers 1144 s, fixes about 645 s (213 + 395 + 34, plus about 3 s of gaps between waves), capture to
dispatch about 11 s, merge through dispatch about 40 s, closeout about 15 s. Cycle about 1855 s.

## Comparison with `f9becaa`

**Method: replay.** `pr_review.widened_waves` from each tree, run on the review JSON's 25 issues (no held ids, no
registry entries, same `existing` set). The current-tree replay reproduces this run's `waves.json` exactly, so
the `f9becaa` replay is the plan that commit would have made. Script under Reproduce.

**Reviewer slots: unchanged.** Between `f9becaa` and HEAD, `pr_review.py` changed only in `waves`, tracking and
serial-lock code. `review_plan.py` and `pr_capture.py` are unchanged, so the same 5 slots and models apply.

**Wave plan at `f9becaa` (8 fixers; current 7):**

- W1:
  - fix_1, opus: I1, I2, I4, I5, I7, C1 (10 files)
  - fix_2, opus: M1 (plan_checks), M2, M6 (schemas/README), M14, M15, I8 (test_plan_driver)
  - fix_3, haiku: M12
- W2:
  - fix_1, opus: M3, M4, M6 (schema), M10 (schema), M11 (schema), I9
  - fix_2, haiku: M1 (test_plan_red), M5 (SKILL), M9, M10 (SKILL), M11 (SKILL), M13
  - fix_3, haiku: M6 (plan_doc), M7 (plan_doc)
- W3:
  - fix_1, haiku: M7, M8, M11, I3, I6, I8 (plan.py, plan_red.py)
  - fix_2, haiku: M5 (plan_render)

M6 and M11 each span all 3 waves there, which raises the closeout split-part risk seen with M6 in this run.

| Phase | Current (measured) | At `f9becaa` (estimated) | Driver |
|---|---|---|---|
| Capture to dispatch | 11 s | 11 s | same code |
| Reviewers | 1144 s | 1144 s | slot planning unchanged |
| Merge, build, Phase 4, waves | 40 s | 40 s | planner runtime negligible |
| W1 | 213 s (w1_fix_2) | ~470 s (430-500), fix_1 | old widest-first order and largest-fixer-with-room packing put C1 with the hub |
| W2 | 395 s (w2_fix_1) | ~175 s (150-220) | current `_cut` defers the most connected unit, the hub, past W1 |
| W3 | 34 s (I7 alone) | ~65 s (50-75) | current: a 7-unit group over the 6-unit cap leaves I7; old: plan.py minor parts tail |
| Gaps | ~3 s | ~3 s | measured |
| Closeout | ~15 s | ~15-30 s | more split parts across waves at `f9becaa` |
| **Fixes** | **~645 s** | **~715 s (640-800)** | |
| **Total** | **~1855 s** | **~1925 s** | |

**Result:** current is about 70 s faster (about 10% of the fix phase, 4% end to end). The difference sits inside
the error band: the direction is likely, the size is not.

**Structure.**

- I1, I2, I4, I5, I7, I9 and M3 share `plan.py`, `SKILL.md` or `README.md`. About 400 s of that judgment work is
  serial under any file-disjoint plan.
- `f9becaa` runs that hub first and stacks C1 (about 120 s) on it.
- The current planner runs C1 in parallel (`_components`, `_cut`; `_place_free` spreads mechanical units over 4+
  fixers), but queues the hub behind W1's 213 s critical fixer. The hub is 61% of fix wall.

**Estimate model** (calibrated on this run's fixers):

- Haiku fixer: about 25 s + 7 s per unit. Predicts 53, 60, 67 s; measured 41, 48, 65 s.
- Opus fixer: about 20 s + 65 s per important or critical judgment issue + 30 s per minor judgment issue + 10 s
  per mechanical part.
  - w2_fix_1: predicted 375 s, measured 395 s.
  - w1_fix_3: predicted 100 s, measured 86 s.
  - C1 alone is taken as about 120 s (from w1_fix_2's 213 s).
- Old W1 fix_1 = measured w2_fix_1 (395) - M3 (30) - I9 (65) + I7 (40) + C1 (120), giving about 460-485 s.
- Model choice per fixer follows the same rule in both trees (haiku only for all-mechanical fixers).
- Per-wave main-session overhead is the same in both trees.

## Planner tweaks (proposed)

All in `plugins/harness/lib/harness_lib/review_merge.py`. What shipped differs from these proposals: see
Follow-up below.

1. **Cost-aware cut** (saves about 125 s; fixes 645 s to about 520 s).
   - In `_cut` (deferral key near line 671), defer mechanical units and minor issues before important or critical
     judgment issues. After cutting, re-admit deferred units that link to only one group with room.
   - On PR 117:
     - W1 runs three file-disjoint fixers in parallel: the hub {I1, I2, I4, I5, I9, I7} (about 420 s), the C1
       fixer (213 s), and a haiku fixer {M12, M6 README part}.
     - W2: M3 with the plan.py mechanical parts (about 100 s), plus small haiku or plan_render groups.
     - No W3.
2. **Keep the kin rule off judgment fixers** (saves about 40 s on the current planner).
   - The rule that joins a group to the fixer holding another part of its issue (near lines 716-718) added
     {M1 (plan_checks), M2} to C1's fixer, which made it 213 s instead of about 170 s.
   - Skip that preference when the target fixer holds an important or critical judgment issue.
   - Smaller variant: let a judgment-only group exceed the cap by one unit instead of leaving a 1-unit wave
     (I7). Saves about 15-20 s.

**Bigger lever: the reviewer phase** (62% of the cycle).

- The tests slot (7 files, opus, 1144 s) ran 517 s past the next-slowest reviewer.
- Splitting that bucket at capture would save more than either wave tweak. No change between `f9becaa` and HEAD
  touches it.
- Corrected in Follow-up: the slot was slow for another reason, and a split would not have helped.

## Follow-up (branch `1093-pr-review-reviewers`)

### The tests reviewer did not run long from its scope

The transcript of the tests reviewer (`agent-a9ba3958c4fecf67c`) shows the time:

- 344 s of normal work: 42 tool calls, all files read in the first minute.
- **One turn of about 800 s** (14:45:05 to 14:58:25 UTC) that emitted 128,000 output tokens, the output cap, with
  163 thinking tokens recorded. The session then injected "Output token limit hit. Resume directly", and the
  reviewer recorded its findings in the next 20 s.

Largest single-turn output per agent in the run: tests 128,000 tokens; every other reviewer and fixer under
9,000 (overall 8,886, runtime 8,983). The tests slot was a runaway generation, not a scope too large to read.
Splitting the bucket was dropped: it would not have prevented a runaway turn. Without that turn the reviewer
phase is bounded by the overall slot (627 s), and the cycle would have run about 1340 s.

The plugin cannot cap a subagent's output per turn. A session can lower the cap with the
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` environment variable, which bounds the cost of such a turn. Each output token
also costs time, so the cap trades a runaway's duration against long legitimate turns (record calls run to
about 9,000 tokens here).

### Planner: tweak 1 as proposed regressed other reviews

Replay over all 29 saved reviews in `docs/PR_REVIEWS/` with the estimate model above (sum over waves of the
slowest fixer):

| Variant | Total, 29 reviews | PR 117 | Reviews worse than current |
|---|---|---|---|
| Current (most-connected cut) | 7732 s | 615 s | - |
| Tweak 2: kin rule off heavy fixers | 7657 s | 615 s | 0 |
| Tweak 1: light-first cut | 8352 s | 510 s | 14 |
| Tweak 1 and 2 | 8312 s | 510 s | 14 |
| **Cheaper of both cuts, plus tweak 2 (shipped)** | **7517 s** | **510 s** | **0** |

Light-first keeps every linked heavy issue together, which makes one large fixer when the heavy issues share
files (0015: a 410 s fixer against the current 190 s + 280 s). PR 117 gains because its heavy hub queued behind a
heavy W1 fixer under the most-connected cut.

Shipped in plugin 0.39.0 (`review_merge.py`):

- `plan_waves` plans the layout under both cuts (`_cut(..., light_first)`) and keeps the one with the lower
  `_wall_seconds`; a tie keeps the most-connected cut. The estimate constants are `HAIKU_SECONDS` and
  `OPUS_SECONDS`, the model above.
- `_place_free` skips the kin rule for a fixer holding a heavy unit (critical or important judgment), and the
  smallest-fixer fallback prefers a fixer without one.
- Not implemented or replayed: re-admitting deferred units into groups with room, and letting a judgment group
  exceed the cap by one. With both cuts planned, PR 117 has no third wave to remove.

PR 117 under the shipped planner: W1 runs the hub {I1, I2, I4, I5, I7, I9} beside C1's fixer {M1, M13, I3, C1},
a {M1, M2} fixer and a haiku {M6, M12} fixer; W2 runs four fixers of minors and mechanical parts. Estimated fix
wall 510 s against 615 s for the previous planner (measured 645 s). The model prices C1 at 65 s, against the
roughly 120 s observed, so these estimates are a comparison between planners, not a forecast.

## Reproduce

Cut a detached worktree at `f9becaa` with `harness:d-w`, then run the script below once per tree. The arguments
are the tree's `plugins/harness/scripts`, the repo root and the review JSON. Diff the two outputs.

```python
"""Replay pr_review's wave planner (from a given plugin tree) over a saved review JSON; print waves as JSON."""
import importlib.util
import json
import sys
from pathlib import Path

scripts, repo, review = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("pr_review_replay", scripts / "pr_review.py")
pr = importlib.util.module_from_spec(spec)
sys.modules["pr_review_replay"] = pr
spec.loader.exec_module(pr)
pr.activate(pr.load_config(repo))
doc = json.loads(review.read_text(encoding="utf-8"))
issues = pr.all_issues(doc)
held = [str(b) for b in doc.get("bubbles") or []]
entries = pr.registry_entries(repo)
args = (repo, issues, held, [], entries, 1)
if hasattr(pr, "serial_locks"):
    waves = pr.widened_waves(*args, pr.serial_locks(repo, {}))
else:
    waves = pr.widened_waves(*args)
print(json.dumps({"held": held, "registry": len(entries), "waves": waves}, indent=1))
```

Line numbers in this note refer to `review_merge.py` at the time of writing. Old line numbers are in the
`f9becaa` blob.
