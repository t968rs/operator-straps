# Plan 0003: Inflight

> Rendered by `plan.py render` from `0003_Inflight_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-10-29
**Spec:** `docs/specs/inflight.md`
**Branch:** work -> main
**Base commit:** `0123456`
**Frozen:** 2026-10-29 at `0123456`
**Execution model:** serial

## Decisions

- **D1** Keep it? Chosen: `keep` (keep). Rejected: `drop` (drop).

## Sweeps

- **S1** `OLD`: `src/old.py` (frozen)

## Tasks

### IN-1: Done

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `src/old.py`

Finished work.

- [x] Run `git diff 0123456789abcdef0123456789abcdef01234567 --stat`: one file
- [x] Record the commit: `plan.py record 0003 IN-1 --sha <sha>`

**Evidence:** commit 0123456

- `0123456789abcdef0123456789abcdef01234567`
- `tree fedcba9876543210fedcba9876543210fedcba98`

### IN-2: Waiting

**Status:** BLOCKED | **Model:** sonnet | **Depends on:** IN-1
**Files:** none

Blocked work.

- [ ] Test `tests/test_b.py::test_b` fails with AssertionError, then passes
- [ ] Record the commit: `plan.py record 0003 IN-2 --sha <sha>`

**Evidence:** needs the developer

### IN-3: Closed

**Status:** CLOSED_NO_ACTION | **Model:** sonnet | **Depends on:** none
**Files:** none

Dropped work.

- [x] Record the commit: `plan.py record 0003 IN-3 --sha <sha>`

**Evidence:** superseded
