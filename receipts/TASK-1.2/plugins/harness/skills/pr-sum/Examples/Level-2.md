# PR #240: Feature(harness): pr-sum `align_draft` pass

**Branch:** 1141-pr-sum-levels-update
**Base:** main
**Date:** 2026-11-09
**Source:** local branch at `d0618f0`
**Files Changed:** 11 (+782 / -38 lines)

## Summary

`pr_sum.py build` now runs a vertical alignment pass over section bodies at levels 2 and 3 before validating, and saves any body it changed back to the skeleton. Side-by-side `Behavior:` fences are now a comparison format with BEFORE, AFTER and `[CHANGE]` columns, checked by a new `pr_compare` module.

The change adds two library modules, wires them into `build` and the existing label check, and updates the plugin version and the pr-sum skill text. Tests cover both modules, the label check and the build path.

| Delta             | Files |   + |  - |  Net |
|-------------------|------:|----:|---:|-----:|
| Source            |    10 | 781 | 38 | +743 |
| Machine-generated |     1 |   1 |  0 |   +1 |
| Total             |    11 | 782 | 38 | +744 |

## Behavior: pr_sum.py build at level 2 or 3

```
BEFORE
build SKELETON
     │
     ▼
validate draft as written
     │
     ▼
problems? ──yes──► report, skeleton untouched
     │no
     ▼
write summary markdown
```

```
AFTER
build SKELETON
     │
     ▼
align section bodies, spaces only                [new]
     │
     ▼
skeleton saved if a body changed                 [new]
     │
     ▼
validate the aligned draft                       [changed]
     │
     ▼
problems? ──yes──► report, bodies stay aligned   [changed]
     │no
     ▼
write summary markdown
```

## Changed Symbols

```
A = plugins/harness/lib/harness_lib/pr_align.py
C = plugins/harness/lib/harness_lib/pr_compare.py
S = plugins/harness/lib/harness_lib/pr_summary.py
P = plugins/harness/scripts/pr_sum.py
```

| Symbol                   | File | Status  | Note                         |
| ------------------------ | ---- | ------- | ---------------------------- |
| `align_draft`            | A    | NEW     | entry point of the pass      |
| `align_table`            | A    | NEW     | pads table cells             |
| `snap_connectors`        | A    | NEW     | slides hanging connectors    |
| `align_markers`          | A    | NEW     | gutter marker column         |
| `align_tags`             | A    | NEW     | change tag column            |
| `comparison_problems`    | C    | NEW     | comparison fence checks      |
| `is_comparison`          | C    | NEW     | header test                  |
| `markers`                | C    | NEW     | finds gutter markers         |
| `_label_problems`        | S    | CHANGED | applies comparison rules     |
| `_side_by_side_problems` | S    | NEW     | per-fence comparison check   |
| `run_build`              | P    | CHANGED | aligns draft first           |
| `aligned_payload`        | P    | NEW     | aligned bodies, changed flag |
| `_write_skeleton`        | P    | NEW     | shared skeleton writer       |
| `_cmd_build`             | P    | CHANGED | saves aligned bodies         |
| `_cmd_capture`           | P    | CHANGED | uses `_write_skeleton`       |

<details><summary>Files Changed (11)</summary>
<p>

| File                                            | Change | Description                                                                                                                                                                                                                                                      |
|-------------------------------------------------|--------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `docs/_harness/agent_usage.jsonl`               | M      | (machine-generated artifact)                                                                                                                                                                                                                                     |
| `plugins/harness/.claude-plugin/plugin.json`    | M      | Plugin version `0.62.0` to `0.63.0`.                                                                                                                                                                                                                             |
| `plugins/harness/lib/harness_lib/pr_align.py`   | A      | New module: `align_draft` pads markdown table cells, slides hanging `│` / `▼` connectors in flow fences, and aligns gutter markers and change tags in comparison fences, changing spaces only.                                                                   |
| `plugins/harness/lib/harness_lib/pr_compare.py` | A      | New module: rules for a side-by-side fence with BEFORE, AFTER and `[CHANGE]` header, `<>` / `>>` / `<<` gutter markers paired with `[changed]` / `[new]` / `[removed]` tags, and `[[ ]]` emphasis; exposes `comparison_problems`, `is_comparison` and `markers`. |
| `plugins/harness/lib/harness_lib/pr_summary.py` | M      | `_label_problems` no longer skips tags in a side-by-side fence; new `_side_by_side_problems` applies `comparison_problems` and refuses a BEFORE/AFTER fence lacking `[CHANGE]`.                                                                                  |
| `plugins/harness/scripts/pr_sum.py`             | M      | `run_build` aligns the draft before validation; new `aligned_payload` and `_write_skeleton`; `_cmd_build` saves changed section bodies to the skeleton; `_cmd_capture` writes through `_write_skeleton`.                                                         |
| `plugins/harness/skills/pr-sum/SKILL.md`        | M      | Documents the comparison flow format and the alignment pass.                                                                                                                                                                                                     |
| `tests/lib/test_pr_align.py`                    | A      | New tests for table padding, connector snapping, marker and tag alignment, and that the SKILL.md comparison example is unchanged by the pass.                                                                                                                    |
| `tests/lib/test_pr_compare.py`                  | A      | New tests for the comparison header, gutter markers, tag pairing, columns and emphasis rules.                                                                                                                                                                    |
| `tests/lib/test_pr_summary.py`                  | M      | Updated label-check tests for the side-by-side comparison rules.                                                                                                                                                                                                 |
| `tests/scripts/test_pr_sum.py`                  | M      | New tests that `build` saves aligned section bodies to the skeleton and keeps list-form bodies as lists.                                                                                                                                                         |

Change codes: A = added, M = modified, D = deleted, R = renamed

</p>
</details>
