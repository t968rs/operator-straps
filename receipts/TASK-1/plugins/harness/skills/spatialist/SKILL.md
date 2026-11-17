---
name: spatialist
description: Use when decomposing a spatial processing monolith into modular packages, when tests fail after a major API change, when removing a shared pytest fixture, or when categorizing test failures after unblocking collection errors.
---

# spatial-toolbox-refactoring

## Overview

Refactoring a spatial toolbox monolith (one class → many modules) always breaks tests. The discipline is: categorize before you touch anything, map dependencies before you remove anything, and treat pre-existing failures as documentation — not noise to ignore.

---

## Step 1: Categorize Every Failure Before Fixing Anything

After a major refactor unblocks test collection, you'll see a mix of failure types. Categorize each one before writing a single line of fix code.

| Category | Definition | Action |
|---|---|---|
| **Regression** | Was passing before my changes, fails after | Fix it. Your responsibility. |
| **Pre-existing** | Was already failing before my changes | Document it. Stop. Not your regression. |
| **Deprecated** | Tests code that no longer exists (deleted class, removed method) | Delete the test. |
| **Rewrite** | Right behavior, wrong API (tests old method that was replaced) | Rewrite to call the new API. |

**How to tell pre-existing from regression:**

```bash
# Stash your changes and run the test against the base branch
git stash
<project test command> tests/pipeline/test_pipeline_io.py::test_xyz -v
# FAILED → pre-existing
# PASSED → your regression
git stash pop
```

If collection errors were blocking the test before your changes (as with circular imports), the failure is pre-existing by definition — it was hidden, not caused by you.

---

## Step 2: Map Fixture Dependencies Before Removing a Shared Fixture

Removing a shared fixture cascades into every consumer. Do this before touching `conftest.py`:

```bash
# Find all files that use the fixture
grep -r "pipeline_behavior_module" <test roots> --include="*.py" -l

# For each file, identify how the fixture is used
grep -n "pipeline_behavior_module" tests/pipeline/test_pipeline_orchestration.py
```

The test roots are the project's configured `tests.roots` (`.claude/harness.json`).

For each consumer, categorize it immediately:

```
test_pipeline_orchestration.py
  - test_defined_streams_flow → uses fixture.run_all() → behavior moved to run_processing() → REWRITE
  - test_tolerance_early_exit → uses fixture.run_all() → behavior no longer exists → DELETE

test_pipeline_monolith_behavior.py
  - all 19 tests → test the deprecated monolith directly → DELETE FILE
```

Only start editing files after the full map is complete. Editing while mapping causes drift — you'll miss a consumer or forget a decision.

---

## Step 3: Rewrite vs Delete Decision

When a test used the old API, ask: **does the behavior still exist in the new code?**

```
Old: PipelineProcessor.output_results(stats, ref_paths)
New: write_outputs(config, outputs, ref_paths, registry, stats, io_context)

→ Behavior exists, API changed → REWRITE the test to call write_outputs()

Old: PipelineProcessor.run_all() → early exit when tolerance=0
New: run_processing() does not have this early exit (behavior was removed in refactor)

→ Behavior gone → DELETE the test (or open a ticket if the behavior should be restored)
```

**Never rewrite a test to a no-op** (e.g., replacing a behavioral test with `assert True`). If the behavior can't be tested with the new API, either delete the test or add a source-inspection test asserting the behavior exists in the codebase.

---

## Step 4: Document Pre-existing Failures as a Handoff Artifact

Pre-existing failures are not done until they are written down. Create a structured record before closing the session:

```json
{
  "id": "F2",
  "file": "test_pipeline_io.py",
  "test": "test_build_output_paths_returns_none_for_missing_output_folder",
  "error": "ValueError raised instead of returning None",
  "root_cause": "build_output_paths() raises ValueError for None input; test expects None return",
  "fix_options": [
    "Option A (runtime): check for None before calling build(), return None",
    "Option B (test): change assertion to pytest.raises(ValueError)"
  ],
  "recommended_fix": "Option A — None-in/None-out is the cleaner contract"
}
```

Without this, the next session starts from scratch. With it, any failure can be fixed in under 10 minutes.

---

## Module Dependency Mapping

Before touching import structure, sketch the real dependency graph. For each module in the package, list what it imports from other modules in the same package:

```
config.py   → refs.py, result_types.py
io.py       → config.py *, statistics.py *, refs.py, result_types.py
processing.py → config.py, refs.py, result_types.py, points.py
statistics.py → config.py *
run_tool.py → config.py, processing.py, io.py, refs.py

* = potential cycle source
```

Any module that imports from a module that imports back forms a cycle. Find these before editing — fixing one cycle often reveals another.

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Fixing failures before categorizing them | Categorize all failures first; then fix in priority order |
| Removing a shared fixture before mapping consumers | `grep -r "fixture_name" tests/ -l` first |
| Rewriting a deprecated-code test to test new code | Check if the behavior still exists; if not, delete |
| Treating pre-existing failures as regressions | Verify on base branch with git stash |
| Not documenting pre-existing failures before stopping | Write a structured JSON handoff — future sessions need it |
| Fixing cycle 1 and stopping | Always re-run collection after each fix; secondary cycles hide behind the first |
