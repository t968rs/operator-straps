# PR #240: Feature(harness): pr-sum `align_draft` pass

**Branch:** 1141-pr-sum-levels-update
**Base:** main
**Date:** 2026-11-09
**Source:** local branch at `d0618f0`
**Files Changed:** 11 (+782 / -38 lines)

## Summary

`pr_sum.py build` now aligns section bodies at levels 2 and 3 before it validates them, and saves what it changed back to the skeleton. Side-by-side `Behavior:` fences become a comparison format with BEFORE, AFTER and `[CHANGE]` columns, checked by a new `pr_compare` module.
