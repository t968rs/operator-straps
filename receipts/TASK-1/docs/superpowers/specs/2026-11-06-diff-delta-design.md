# DiffDelta: source-only line counts for pr-sum and pr-review (issues 233, 232, 234)

## Intent

Machine-generated files (a regenerated test report, review JSONs, usage rows) inflate the line counts that
pr-sum prints and that pr-review records in `stats`, which makes those counts useless as a size signal
(issue 232: +10671/-6782 headline against a +2714/-610 source delta). One module computes the delta with the
machine-generated files filtered out, keeps the unfiltered delta beside it, and both skills read it.

## Goals

- `harness_lib/diff_delta.py` with a frozen `DiffDelta` (issue 233) and one exclusion rule shared by every
  caller.
- pr-review: `stats` keeps the full totals; a new `stats.source` sub-object carries the filtered counts
  (issue 232, the developer's choice).
- pr-sum: the artifact Note becomes a delta table (issue 234, the developer's choice).
- A CLI, `scripts/diff_delta.py <ref-a> <ref-b>`, for any two git refs.

## Non-goals

- merge-commit-msg's size line (`+a -d across N files`, from `gh`): it stays on GitHub's counts. A later
  change may move it to `DiffDelta.between`.
- branch-commit-msg's read budgets (`commit_diff.py`): unrelated to the headline.
- Issues 231 and 230 (pr-sum alignment pass, side-by-side flow format): a separate design.

## Anti-goals

- Two definitions of "machine-generated" again. Today pr-sum uses only the commit-bucket `Artifact` rule
  (`pr_summary.py:61`) while pr-review uses `review_plan.is_excluded` (exclusions file, the harness's own output
  patterns, plus `Artifact`). In this repository no `Artifact` bucket is configured, so pr-sum tags nothing
  while pr-review excludes `docs/PR_REVIEWS/*`.
- Changing what `stats.additions` / `deletions` / `files_changed` mean: old and new review JSONs must agree.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| **A (picked)** | `DiffDelta.from_stats(stats, patterns)` over the per-file counts each skill already captured; `DiffDelta.between(repo, a, b)` runs one `git diff --numstat -M -z` and calls `from_stats` | No extra git read in either skill; working-tree captures (untracked files) keep their counts; one filter for all callers. "Any two refs" applies to the CLI and library callers, not to the skills' captures |
| B | Every caller goes through `between(a, b)` | One entry point, but pr-sum's local captures hold files no ref holds, and each capture pays a second numstat read |
| C | A or B, plus the delta persisted in the skeleton / `plan.json` | Nothing recomputed at render, but one more field that can go stale against `files` |

Picked A: the counts are already in hand, so recomputing is cheap and cannot drift.

## Decided

- **Model.**

  ```python
  @dataclass(frozen=True)
  class DiffDelta:
      adds: int
      subs: int
      files: int
      excluded: Tuple[str, ...]          # excluded repo-relative paths, sorted
      full: Optional["DiffDelta"] = None  # the unfiltered delta; None on the unfiltered one itself

      @cached_property
      def net(self) -> int: ...
  ```

  Names follow the issue (`adds`, `subs`, `net`). `excluded` holds excluded file *paths* (the issue's
  `_exclusion_paths` read that way), never exclusion-file names. `full.excluded` is empty.
- **Exclusion rule.** `review_plan.is_excluded(path, patterns)`: fnmatch over the configured `exclusions`
  file plus the harness output patterns (`exclusion_patterns(repo)`), or the `Artifact` commit bucket. A
  project with `exclusions: null` still filters `Artifact`-bucketed paths. The issue's request to audit other
  exclusion files resolves to the one `exclusions` key: the FP `machine_generated_exclusions.json` is that key's
  value there, and this repository has no other exclusions file on disk.
- **pr-review.** `review_meta` writes
  `stats = {additions, deletions, files_changed, source: {additions, deletions, files_changed}}`.
  `PR_REVIEW.schema.json` gains an optional `stats.source` object (the three integer keys required inside
  it); older review JSONs without it stay valid. `review_edit.set_stats` keeps an existing `source` rather
  than dropping it.
- **pr-sum.** "Machine-generated" in pr-sum means `is_excluded`, everywhere: the `(machine-generated
  artifact)` tag, the no-description rule, `diff` skipping, and the delta. `render_summary` takes the
  patterns; `pr_sum.py` passes `exclusion_patterns(repo)`. The header line keeps the full totals. When at least
  one listed file is excluded, the `***Note:***` line is replaced by this table, after the Summary:

  ```
  | Delta             | Files |     + |     - |   Net |
  |-------------------|------:|------:|------:|------:|
  | Source            |    17 |  2714 |   610 | +2104 |
  | Machine-generated |     1 |  7957 |  6172 | +1785 |
  | Total             |    18 | 10671 |  6782 | +3889 |
  ```

  The "more than half" trigger goes away; any excluded file shows the table.
- **CLI.** `scripts/diff_delta.py <ref-a> <ref-b> [--repo DIR] [--json]`: activates the project config,
  prints one line (`source +2714/-610 (net +2104) in 17 files; total +10671/-6782 in 18 files; 1 excluded`),
  or with `--json` the model as JSON. Exit 1 with `problem:` lines on a bad ref or config.
- **Skill text.** pr-sum SKILL.md (the Note paragraph and the Common Mistakes row) and the pr-review
  operating rules where they describe `stats`.

## Left to the builder

- Where `split_reviewable` and `DiffDelta` share code in `pr_review.py`.
- The test file layout (`tests/lib/test_diff_delta.py` plus updates to the pr-summary and pr-review tests).
- Plugin version bump in `plugins/harness/.claude-plugin/plugin.json`.
