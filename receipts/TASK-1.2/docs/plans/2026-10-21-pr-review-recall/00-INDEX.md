# pr-review recall: six changes

Two runs of `harness:pr-review` over the same source tree produced two different finding sets. The first run
(PR #1625, floodplain_development) found 17 findings. The second run (PR #1627) reviewed #1625's post-fix tree
and found 15 more. Of those 15:

| Origin | #1627 ids | Caught by |
|---|---|---|
| Already in the tree #1625 reviewed | M3, M4, M5, M7, M9, M10, M11, M12 | 03, 04, 05 |
| Introduced by #1625's own fix waves | I3, M1, M2, M6, M8, M13 (+ parts of M9, M12) | 01, 02 |
| The PR being recreated (lineage literals) | M14 | 06 |

Evidence (consuming project, read-only; the run directories are git-ignored scratch but still on disk):

- `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1625_0019_unit_ft_flavor.json`
- `E:/automation/toolboxes/floodplain_development/docs/PR_REVIEWS/1627_Feature_UnitOfMeasureDraft.in_flavor_of_foot-flavor_matching.json`
- `E:/automation/toolboxes/floodplain_development/docs/_scratch/pr_review/1625/pr1625_20261021T185921Z/`
- `E:/automation/toolboxes/floodplain_development/docs/_scratch/pr_review/1627/pr1627_20261021T202444Z/`
- Tree identity: #1627 head `c9b1fdb76` equals `origin/0019-unit-ft-flavor` except `.github/offline/offlineTestReport.json`;
  #1625 reviewed `1308ba495`, whose source equals `8f4f06cd9`. `git diff 8f4f06cd9 c9b1fdb76` is #1625's fix waves.

## The prompts

Each file is a self-contained prompt for one session in `E:/automation/operator-straps`. Hand a session the file
path and nothing else.

| # | File | Change | Size |
|---|---|---|---|
| 1 | `01-fix-delta-review.md` | Review the fix delta before the Phase 5 done line | L |
| 2 | `02-fixer-registry-ripple.md` | Registry requests from fixers, a final registry wave, a ripple checklist | L |
| 3 | `03-registry-entry-checklist.md` | Never summarize registry hunks for touched tests; per-entry checklist in the tests brief | M |
| 4 | `04-sibling-sweep.md` | Sweep each finding's pattern across the scope before `build` | M |
| 5 | `05-test-design-clause.md` | Widen the test-design clause: a test that cannot fail, duplicates, docstring claims | S |
| 6 | `06-lineage-check.md` | Mechanical lineage check at `capture`: foreign PR numbers, branches, catalog `pr` | M |

## Order

All six touch `plugins/harness/scripts/pr_review.py` and `plugins/harness/skills/pr-review/SKILL.md`, so run them
**one after another, never in parallel**, each on its own branch cut from the previous one's result (or from `main`
after it merges):

```
05 -> 03 -> 06 -> 04 -> 02 -> 01
```

- 05 and 03 change brief text that 01's delta reviewer brief reuses; land them first.
- 02 and 01 both change `closeout`; 02 first, so 01's gate sees registry-wave state.
- Bump `version` in `plugins/harness/.claude-plugin/plugin.json` once, in the last change to merge, unless the
  developer releases between changes.

## Rules every prompt inherits

- Read `E:/automation/operator-straps/CLAUDE.md` first: plugins stay generic (no consuming-project names, paths or
  package names under `plugins/`; `tests/contract/test_no_repo_literals.py`), a new config key touches four places,
  drivers activate and library code reads, functions under 50 lines, `Optional` / `Union`, no first or second
  person in comments or docstrings.
- Test-driven: write or extend the failing test first, watch it fail, then implement.
- Tests are named by file: `python -m pytest tests/<area>/test_<name>.py -q`. Never a directory. Preview CI
  selection with `python tools/select_tests.py --base main`.
- Lint the changed files: `python -m ruff check <files>`.
- The agent saves files; the developer commits. No `git commit`, `push`, `rebase`, `reset`, `cherry-pick`.
- `pr-team` (`plugins/harness/skills/pr-team/`) shares the brief text and fixer rules through
  `pr_review.py` helpers in some places; each prompt says whether `pr-team` changes too.
- Finish with: the changed-file list, every test command run with its pass count, and anything left open.
