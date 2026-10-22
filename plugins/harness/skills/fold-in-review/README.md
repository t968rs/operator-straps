# fold-in-review

Turn feedback into issues of a `harness:pr-review` run. Paste notes, failing test output or a GitHub review link;
the skill checks each claim against the working tree, records the survivors as findings, and hands the run back
to the pr-review sequence. Nothing is hand-edited: the driver (`scripts/pr_review.py fold`) validates and writes.

## Usage

Type the command with whatever is on hand. `/fold-in-review` works when the name is unambiguous;
`/harness:fold-in-review` always does.

Free-text notes:

```
/fold-in-review "add_note silently overwrites a notes file it cannot parse, and the README never shows --list"
```

Pasted failing tests (triple quotes keep a multi-line paste in one argument):

```
/fold-in-review """
FAILED tests/skills/test_add_note_script.py::test_cap_boundary - AssertionError: assert 21 == 20
FAILED tests/skills/test_add_note_script.py::test_cap_message - AssertionError: 'too many' not in 'ok'
2 failed, 41 passed in 3.10s
"""
```

A GitHub review:

```
/fold-in-review https://github.com/<owner>/<repo>/pull/56#pullrequestreview-1234567
```

No arguments prints the argument hint and stops.

## Before you start

A review run must exist for the PR: `harness:pr-review` has run `capture` (the driver otherwise answers
`no current pr-review run for PR <N>`). The skill finds the PR from the conversation, or else from the current branch (`gh pr view --json number`),
confirmed by a `<NNNN>/current` file under the scratch root. It asks only when both fail: the scratch
directory keeps the folders of every past PR, so the folder list alone never names the run.

## What the skill does

1. **Locates the run and its phase.** Before `build` the findings become `merge` input. After `build` they are
   appended to the built review with fresh ids; `amend` no longer runs, so the severity written is final.
2. **Classifies the input** and picks the driver's `--kind` and a snake_case `--source` id:

   | Input | Kind | Source id |
   |---|---|---|
   | GitHub review URL | `external` | `<login>_review` |
   | pasted test, CI or lint output | `tests` | `failing_tests_1` |
   | your own notes | `developer` | `developer_notes_1` |
   | anything else | `adhoc` | `adhoc_1` |

3. **Splits** the input into one defect per finding. Failures sharing a root cause become one finding that lists
   every node id. A question, a preference or a wish with no checkable defect is handed back to you.
4. **Verifies** each claim: reads the named code and, for test failures, reruns only the named node ids (never a
   directory). A claim that does not hold, or a failure that no longer reproduces, is dropped and reported.
5. **Deduplicates.** Before `build`, `merge` flags candidates and `amend --merge` joins them. After `build`
   nothing merges, so a claim an existing issue already states is skipped and its id named.
6. **Folds** the findings through `fold --findings -` (stdin, so no file lands in the project).
7. **Continues the pr-review sequence:** `merge`, `amend --regrade`, `build` before the build; the printed
   `next:` line (Phase 4 second run, `waves` for the new ids, `closeout`) after it.
8. **Reports** what was folded, what was dropped and why.

## Example

Input, folded after `build` of PR 56:

```
/fold-in-review "add_note overwrites a notes file it cannot parse. Also the README has no --list example."
```

Result:

```
fold [done] | developer_notes_1 (developer) | 2 folded, 0 dropped | ids: I6, M9

| id | severity  | file                                                      |
|----|-----------|-----------------------------------------------------------|
| I6 | important | plugins/harness/skills/add-bookmark/commands/add_note.py  |
| M9 | minor     | README.md                                                 |
```

Each folded finding carries a severity, a one-line name, a summary with the evidence and how it was checked, one
or more fix options, a repo-relative `file` (optionally `lines` and `also`), and a `fix_kind` of `mechanical` or
`judgment`. The full field table is in `SKILL.md`.

## Rules worth knowing

- **Severity after `build` is final.** The skill grades by blast radius before folding. Say so when a note is
  more serious than it sounds.
- **A finding needs a file.** A claim with no file to anchor it is anchored to the file that owns the behavior,
  or the skill asks which file it concerns.
- **One source id per fold.** Every new batch, before and after `build`, takes the next free number in its
  series (`developer_notes_2`, then `developer_notes_3`), read from the `folded` ids in `plan.json`. Before
  `build`, a fold under an id already used replaces that fold, so reuse an id only to correct that exact fold.
  After `build` a source is never re-folded.
- **A GitHub review body folds under its own id.** A body with no file anchor that names a defect folds as
  free text under `<login>_review_body`; reusing `<login>_review` would replace the inline-comment fold before
  `build` and is refused after it.
- **Mixed input is several folds**, one per kind: notes plus a pasted traceback fold as `developer` and `tests`.

## When the driver refuses

| Message | Meaning and fix |
|---|---|
| `no current pr-review run for PR <N>` | No `capture` yet; run `harness:pr-review` first. |
| `--source <id> is a reviewer slot of this run` | Pick another source id. |
| `--source <id> is already in the built review` | Use a new source id for new findings. |
| `Phase 4 first run has not succeeded (pre_fix_time pending)` | Settle the first run, rerun `build --replace`, fold again. |
| `draft.json predates this fold` (note) | Rerun `merge`, or `merge --force` when the draft was amended. |
| `DISMISSED` / `blank body and no inline comments` | The GitHub review has nothing to fold. |
| `--from-gh-review names PR <X>, not PR <N>` | The URL belongs to another PR. |
| `--from-gh-review names <owner>/<repo>, not the PR's repository` | The URL is from another repository, or `plan.json` has no GitHub PR url. Use the run's repository's review URL. |
| `--from-gh-review <url> must look like https://github.com/...` | The URL is malformed. Use `https://github.com/<owner>/<repo>/pull/<N>#pullrequestreview-<id>`. |
| `unrecognized arguments: --repo` | `--repo` goes before the subcommand: `pr_review.py --repo DIR fold ...`. |

## Related

- `SKILL.md`: the procedure the skill follows.
- `../pr-review/SKILL.md` (step 0 of the Phase 3 order) and `../pr-review/operating_rules.md` (Folding outside
  reviews): where the fold sits in the review run.
- `../../scripts/pr_review.py`: the driver; `fold --help` lists its options.
