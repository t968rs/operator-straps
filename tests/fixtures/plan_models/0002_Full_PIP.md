# Plan 0002: Full

> Rendered by `plan.py render` from `0002_Full_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-10-29T08:30:00
**Spec:** `docs/specs/full.md`
**Branch:** feature-x -> main
**Base commit:** `0123456`
**Frozen:** 2026-10-29 at `0123456`
**Execution model:** parallel (2 worktrees)

## Decisions

- **D1** Split? Chosen: `split` (two). Rejected: `keep` (one). smaller diffs
- **D2** Rename? **Open.** Options: `yes` (rename), `no` (keep).

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| limit | 50 | spec Section 2 | split |

## Formats

- **row**: `a|b`, copied from `src/a.py:3`

## Sweeps

- **S1** `old_name`: `docs/x.md` (keep), `src/a.py` (rewrite)

## Tasks

### FX-1: First | piped

**Status:** COMPLETE | **Model:** opus | **Depends on:** none
**Files:** `src/a.py`

**Anchors:**
- `src/a.py:1-2` holds `def read`

Do the first thing.

- [x] Test `tests/test_a.py::test_a` fails with ImportError, then passes
- [x] Run `python gen.py --base 0123456789abcdef0123456789abcdef01234567`: wrote
- [x] Record the commit: `plan.py record 0002 FX-1 --sha <sha>`

**Evidence:** commit 0123456: 1 test node(s) passed

- `0123456789abcdef0123456789abcdef01234567`
- `tree fedcba9876543210fedcba9876543210fedcba98`
- `python -m pytest -q tests/test_a.py::test_a`

### FX-2.1: Second

**Status:** IN_PROGRESS | **Model:** sonnet | **Depends on:** FX-1
**Files:** none

Do the second thing.

- [ ] Record the commit: `plan.py record 0002 FX-2.1 --sha <sha>`

**Evidence:** started 2026-10-30
