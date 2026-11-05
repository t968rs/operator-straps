# Issue 203: roast reviewer slot duration

Source data: `docs/_harness/agent_usage.jsonl` (197 pr-review reviewer rows, 2026-10-20 to 2026-11-05),
`docs/_harness/pr_review_invocation_test_matrix.jsonl` (findings per slot), and each run's `plan.json`
under `docs/_scratch/pr_review/` (slot paths, diff size). Analysis scripts are not committed; the numbers
below reproduce from those three files.

## Answer in one line

The roast voice is not the cause. The slot that carries OVERALL's scope is the long pole of the review,
whether it runs as `roast` or as `overall`. Roast is the long pole in 13 of 17 roast runs only because
roast replaces OVERALL on small PRs.

## Measured breakdown

Roast against the longest other slot, 17 runs with a roast (duration_s from the usage log):

| Metric | Value |
|---|---|
| Runs where roast is the longest slot | 13 of 17 |
| Median roast / longest-other ratio | 1.25 |
| Roast median duration | 195 s |
| OVERALL median duration (32 runs) | 223 s |
| Bucket slots median duration (tests / docs / runtime) | 111 s / 121 s / 105 s |

Scope-matched comparison, runs with no `system_shape` slot (small-PR cut applies):

| Scope slot | n | Median duration | Median files | Median diff lines | Median s per file | Median tool uses |
|---|---|---|---|---|---|---|
| roast | 11 | 160 s | 8 | 362 | 18.6 | 24 |
| overall | 23 | 196 s | 10 | 489 | 20.5 | 27 |

Roast is not slower than OVERALL per file or per tool use. The OVERALL-scope slot out-lasts the longest
bucket slot in 37 of 41 runs with two or more bucket slots. Median excess over the longest bucket slot:
50 s for roast (n=15), 58 s for overall (n=22); mean 122 s and 113 s (outliers: pr89 1747 s, pr72 1121 s).

Yield (matrix rows, mean Critical + Important per slot): roast 1.77 (n=22), overall 1.66 (n=35),
tests 1.14, docs 0.92, runtime 0.82. The OVERALL-scope slot is also the most productive slot.

## Answers to the issue's questions

- **Scope or voice?** Scope. Roast and overall match per file (18.6 s against 20.5 s) and per tool use.
- **Linear docstring pass over every file?** Yes, by design (before plan 0007): every slot ran the pass
  over its in-scope files, and OVERALL's scope is every reviewable file. The extra tool uses (19 against 7 to 13 in PR 202)
  are that scope, not re-reading by the roast voice. No log shows per-file re-read counts, so re-reads of
  files the bucket slots cover are untested.
- **Is the `opus` floor needed on a small PR?** Not answerable from this data. No run has a `sonnet`
  slot at OVERALL scope (`review_plan.py` sets sonnet only for one-file bucket slots), so model and
  scope are not separable. Needs an experiment.
- **Dispatch first or time budget?** Dispatch order does not help: all slots go out in one message and
  run in parallel, so wall time is the max slot duration whatever the order. A budget is the only lever
  that shortens the wall time, and it trades against the highest-yield slot.

## Data caveats

- The `tokens` column of the usage log does not match the engine figures in the issue (PR 202 roast:
  769,744 logged, 65,960 reported). Duration and tool uses are comparable; token totals are not.
- PR 89 (1747 s) and PR 122 (roast 364 s against runtime 1131 s) are outliers; medians are used.

## Recommendation

1. Do not change the roast slot on its own. A roast-only cut moves the long pole to OVERALL-scope slots
   on the other 50 percent of runs.
2. Expected saving if the OVERALL-scope slot is capped at the longest bucket slot: median about 55 s of
   a median about 200 s review (roughly 25 percent), mean about 115 s. That is the ceiling; a cap also
   cuts the slot with the best Critical + Important yield.
3. Candidate experiments, in order of cost: (a) a `sonnet` OVERALL-scope slot on PRs under 10 files,
   compared on yield; (b) split the small-PR OVERALL scope into the system-shape template and the
   linear read as two parallel slots (halves the long pole, adds one launch); (c) a tool-use budget in
   the brief. Each needs a run set before adoption.

## Experiment (2026-11-05): model and linear pass on the OVERALL-scope slot

Replay of five merged small PRs (4 to 9 reviewable files) with `capture --pr N --allow-closed --roast no`,
one fresh run per arm, only the `overall` slot dispatched. The voice is held out (`--roast no`); the
measured part of this note found it does not change duration.

| Arm | Model | Brief |
|---|---|---|
| H | opus | the historical run of the PR (roast for 159, 202, 218; overall for 186, 219) |
| A | opus | unedited capture brief |
| B | sonnet | capture brief with the role line and the `plan.json` slot model set to `sonnet` |
| C | opus | capture brief with the linear pass limited to unbucketed paths (only `plugin.json` / `marketplace.json` manifests in all five) |

Run ids (A / B / C): 159 `T162315Z` / `T162332Z` / `T162557Z`; 186 `T162337Z` / `T162342Z` / `T162601Z`;
202 `T162347Z` / `T162352Z` / `T162605Z`; 218 `T162356Z` / `T162402Z` / `T162609Z`; 219 `T162407Z` /
`T162412Z` / `T162615Z` (all `pr<N>_20261105...`). The agent-watcher mod logged them to `agent_usage.jsonl`.

### Duration and tool uses

| PR | A opus | B sonnet | C opus, no OVERALL pass |
|---|---|---|---|
| 159 | 130 s / 23 | 47 s / 15 | 71 s / 17 |
| 186 | 103 s / 20 | 58 s / 14 | 79 s / 15 |
| 202 | 114 s / 17 | 48 s / 18 | 88 s / 17 |
| 218 | 137 s / 21 | 86 s / 18 | 125 s / 23 |
| 219 | 155 s / 21 | 80 s / 21 | 99 s / 19 |
| median | 130 s / 21 | 58 s / 18 | 88 s / 17 |

C is 9 to 45 percent faster than A per PR (per-PR median 23 percent; median duration 130 s to 88 s,
32 percent). B is about 55 percent faster.
A and B ran in one ten-agent message; C ran as a five-agent message that overlapped A's tail, so C's
load was lighter and its saving may be overstated by a few seconds.

### Findings, matched by substance

Severity labels drift between runs of the same model (one issue was Important in one run and Minor in
another), so findings are matched by the defect they name, not by label.

- **Run-to-run noise is large.** H and A, both opus on the same scope, share 1 of 4 findings on 159, 1
  of 5 on 186, at most 1 on 202, 3 of 5 on 218 and 2 of 5 on 219. One run is a sample, not a census.
- **C matches A.** 159: both find the basename-collision batch defect (C as Important). 186: both find
  the removal-only bubble rule that blocks the listed defects (Important in both). 202: C finds the
  post-hand-off review against the snapshot rule, the closest match to H's first Important, which A
  missed; both find the scaffold-append and guidance-forwarding gaps. 218: C finds the uncached git
  spawn (A and H too) and the failed-lookup probe loss (B too, A missed). 219: C matches A on three of
  four. No issue found by A is lost in C in a way that is not equally lost between H and A.
- **B is uneven.** 218 and 219: B matches or beats A (on 218 B finds the failed-lookup probe loss as
  Important, which A missed). 159: one finding only, the shared basename defect. 186: misses the
  Important removal-only rule (it reports only a related reviewer-vs-fixer conflict). 202: misses both
  of H's Importants and shares one of A's three findings (the guidance channel).

Counts (findings / Important): H 23 / 7, A 17 / 1, B 16 / 1, C 15 / 3. Four of H's seven Importants
come from roast runs; the roast voice may label severity higher, not find more.

### Conclusion

- **Drop the linear pass from OVERALL-scope slots (overall and roast).** It saves about a quarter to a
  third of the slot's time with no loss of substance measurable against opus run-to-run noise. Every bucketed file
  still gets the pass from its bucket slot; the unbucketed paths in this set are manifests with no
  docstrings. Before plan 0007 the catalog summary scoped the pass to bucket reviewers
  (`CrossCuttingLensCatalog.json`, `default_sub_lenses[0].summary`) while the reviewer briefs and
  `pr-review/SKILL.md` applied it to every slot.
- **Keep the `opus` floor.** Sonnet halves the time but misses Important findings on two of five PRs.
- **Limits.** n = 5, one run per arm, small PRs only. PRs at or above 20 files run OVERALL and roast
  as separate slots and were not tested.

### Outcome

The developer adopted the cut for the roast slot only; OVERALL keeps the pass. Plan 0007
(`docs/plans/0007_review_lens_enums_and_brief_extraction_ActionPlan.json`) carries it as a catalog
`skip_lenses` entry on the linear pass, with the lens enums and the reviewer-brief extraction.
The adopted cut is wider than arm C: the roast slot drops the pass outright instead of limiting it to
unbucketed paths, so on a small PR whose roast roll fires (roast replaces OVERALL) unbucketed paths get
no linear pass. In this set those paths were docstring-free manifests; elsewhere they may hold code
whose suffix no bucket claims (`.go`, `.rs`, `.yaml`).
Recommendation 1's trade-off stands: runs without a roast keep the OVERALL slot as the long pole.
