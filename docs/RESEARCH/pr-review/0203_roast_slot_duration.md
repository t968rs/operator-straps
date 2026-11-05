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
- **Linear docstring pass over every file?** Yes, by design: every slot runs the pass over its in-scope
  files, and OVERALL's scope is every reviewable file. The extra tool uses (19 against 7 to 13 in PR 202)
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
