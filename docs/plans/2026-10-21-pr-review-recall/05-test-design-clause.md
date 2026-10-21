# 05 - Widen the reviewer test-design clause

Repository: `E:/automation/operator-straps`. Read `CLAUDE.md` there first. Index: `00-INDEX.md` beside this file.

## Goal

Every reviewer brief whose scope holds a test file carries a test-design clause. Today it asks one question (is
the test a mock-chain wiring test?). Widen it so reviewers also check, for each test the PR adds or changes:

1. **Can it fail?** The reviewer names the production change that would make the test fail. When no plausible
   change would, the test is a finding.
2. **Is it a duplicate?** A new test that asserts the same thing on the same fixture as an existing test is a
   finding (recommend deleting one).
3. **Do its docstrings and the module docstring match the tests?** A class or module docstring that states an
   invariant the tests contradict, or names a mechanism the file no longer uses, is a finding.

## Evidence

The second run (PR #1627) found these on code the first run (PR #1625) had already reviewed:

- **M7**: `test_decimal_degrees_native_returns_self` passed whether or not the `is_two_flavor` gate existed: no
  production change could fail it.
- **M11**: `test_us_survey_sr_square_feet_is_exact_shape_area_copy` duplicated
  `TestCalculateAreaTiers.test_tier_a_gdb_projected_units_match`.
- **M10**: the `TestOutputUnitContract` docstring claimed the output unit is invariant to the source SR; the tests
  pinned the opposite for the foot flavor.

Review JSONs: `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1627_Feature_UnitOfMeasureDraft.in_flavor_of_foot-flavor_matching.json`
(issues M7, M10, M11).

## Current code

- `plugins/harness/scripts/pr_review.py:187` `TEST_DESIGN_CLAUSE`, added by `rules_section` (`:688`) when
  `_tests_in_scope` (`:677`) is true.
- `plugins/harness/scripts/pr_review.py:208` `SEVERITY_RULES` already says a test that cannot fail is `critical`.
  The new clause must agree with that grading or the severity rule must change. Decide and state it: a test that
  cannot fail stays `critical` when it is the only test of a behavior the PR claims to pin, `important`
  otherwise; a duplicate is `minor`; a docstring mismatch is `minor`. Update `SEVERITY_RULES` to match.
- `plugins/harness/skills/pr-review/SKILL.md`, section "Prompt and brief contract": quotes the clause verbatim
  ("Test-design clause (every brief whose scope includes test files, verbatim)").
- `plugins/harness/agents/pr-team-orchestrator.md`: carries its own copy of the clause for `pr-team` briefs.
- `tests/scripts/test_pr_review_driver.py`: pins brief text (grep `Test-design principle`).

## Requirements

1. `TEST_DESIGN_CLAUSE` keeps the mock-chain sentence unchanged and gains the three checks above, as short
   sentences, each saying what to flag and at what severity.
2. The "can it fail" check asks the reviewer to write the named production change into the finding's `summary`
   when it flags the test, so the fixer knows what the replacement test must catch.
3. `SEVERITY_RULES` and the clause agree on grading.
4. The SKILL.md quote, the `pr-team-orchestrator.md` copy and the brief text are byte-identical. If a test
   already enforces the SKILL.md / code identity, extend it to the agent file; if none does, add one in
   `tests/scripts/test_pr_review_driver.py` (read the clause from `pr_review.TEST_DESIGN_CLAUSE`, assert it
   appears verbatim in both markdown files).
5. No other brief text changes.

## Tests

- Red first: a driver test asserting the brief for a slot with a test path contains each new sentence, and the
  identity test of requirement 4.
- `python -m pytest tests/scripts/test_pr_review_driver.py -q`
- `python -m pytest tests/skills/test_pr_review_skill_contract.py -q`
- `python -m ruff check plugins/harness/scripts/pr_review.py tests/scripts/test_pr_review_driver.py`

## Out of scope

The fixer brief, wave planning, new subcommands.

## Done

Changed files listed, the three commands above green with counts, and the SKILL.md / agent text quoted in the
report.
