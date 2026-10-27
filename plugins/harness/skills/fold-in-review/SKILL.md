---
name: fold-in-review
description: Use when a developer hands feedback to an active or nascent harness:pr-review run - free-text notes, pasted failing test or CI output, a GitHub review URL, or another tool's report - and it should become issues in the review. Triggers on "fold in", "add this to the review", "fold-in-review". Verifies each claim against the tree, records findings through the driver and continues the pr-review sequence.
argument-hint: "<notes> | <pasted test output> | <GitHub review URL> [-- <guidance>]"
---

# fold-in-review: turn outside feedback into review issues

The input becomes verified findings, the driver's `fold` records them as a findings source of the run, and the
`harness:pr-review` sequence continues. The driver validates and writes; never map input to issues by hand or
edit `draft.json` or the review JSON. Run every command with the Bash tool from the project checkout. A
`--repo <abs project root>` flag, only needed from outside the checkout, goes before the subcommand
(`pr_review.py --repo DIR fold ...`); after the subcommand the parser rejects it. `pr_review.py` below stands for
`sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py"`.

Arguments: `$ARGUMENTS`

An empty argument list prints the `argument-hint` line and stops.

The input is everything before a standalone `--` token; what follows is the guidance (which findings to stress,
a file to check first, a severity ceiling), per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Look for
the token only on the last line of the arguments: pasted output holds `--` lines of its own (pytest's
`-- Docs:` line). Guidance with no input before it prints the `argument-hint` line and stops. The guidance
steers verification and classification; it never lowers what the tree proves, and a finding is recorded only
as the tree supports it.

## 1. Locate the run

- **PR number `<N>`:** the PR of the `harness:pr-review` run in this conversation. Otherwise the PR of the current
  branch (`gh pr view --json number`), confirmed by a `<NNNN>/current` file under the scratch root
  (`pr_review.py config --get artifacts.scratch`). When both fail, ask which PR: scratch keeps the folders of
  every past PR, so the folder list alone never names it.
- **No `current` file** (the driver prints `no current pr-review run for PR <N>`): there is nothing to fold into.
  Say so and point to `harness:pr-review`; do not capture from here.
- **Phase:** read `plan.json` in the run directory (`<scratch>/<NNNN>/<run id in current>/`).

| `plan.json` | State | What a fold does |
|---|---|---|
| no `review_path` | before `build` | the source is `merge` input; regrade with `amend` afterwards |
| `review_path` set | after `build` | issues append with fresh ids; `amend` does not run, so the severity written is final |

Before `build`, wait until every dispatched reviewer has returned.

## 2. Classify the input

| Input | `--kind` | `--source` (snake_case) |
|---|---|---|
| GitHub review URL, `https://github.com/<owner>/<repo>/pull/<N>#pullrequestreview-<id>` | `external` | `<login>_review` |
| pasted test, CI or lint output | `tests` | `failing_tests_1` |
| the developer's own notes or thoughts | `developer` | `developer_notes_1` |
| another tool's report, a teammate's message | `adhoc` | `adhoc_1` |

Input of mixed kinds becomes one fold per kind. A source id never equals a reviewer slot id. Every new batch,
before and after `build`, takes the next free number in its series (`developer_notes_2`): read the `folded` ids
in `plan.json`. Before `build`, a fold under an id already used replaces that fold, so reuse an id only to
correct that exact fold. After `build`, a source is never re-folded.

## 3a. A GitHub review URL

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" fold --pr <N> \
  --source <login>_review --kind external --from-gh-review "<URL>" --severity <level>
```

The URL must name the run's repository (the PR url in `plan.json`) and the run's PR; the driver refuses a
malformed URL (`must look like https://github.com/...`), another repository (`names <owner>/<repo>, not the PR's
repository`, also when `plan.json` has no GitHub PR url) and another PR (`names PR <X>, not PR <N>`).

Each inline comment becomes one `judgment` finding at `--severity` (default `minor`). Exit 1 with `DISMISSED` or
`blank body and no inline comments` means nothing to fold: report it.

**Verify first.** Fetch the comments (`gh api repos/<owner>/<repo>/pulls/<N>/reviews/<id>/comments`) and read
the code each one names. When every comment holds and all share one severity, fold the URL with that
`--severity <level>`. Otherwise convert the comments to findings (section 3b: verify, a per-finding `severity`)
and fold the survivors through `--findings -` under the same `--source <login>_review --kind external` instead
of the URL. A comment that reports a critical or important defect never lands at the default `minor`; after
`build` the severity is final.

A `review body not folded` note means the body has no file anchor; when it names a defect, fold it as free text
(section 3b) under its own id, `--source <login>_review_body --kind external --findings -`. Reusing
`<login>_review` would replace the inline-comment fold before `build` and is refused after it.

## 3b. Notes, pasted tests, anything else

**Split.** One defect per finding.
- *Notes:* each statement that names something checkable. A question, a preference or a wish with no checkable
  defect is not a finding: hand it back to the developer in one line.
- *Test output:* the failing node ids with their assertion or exception lines. Failures with one root cause (the
  same exception at the same source line, one changed contract) are one finding; list every node id in its
  summary. Passes, skips and warnings are not findings.

**Verify.** A note or a pasted log is a claim, not a fact. Read the named code and confirm the defect exists in
the working tree. For test failures, rerun only the named node ids
(`sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" -m pytest <test file>::<test> -q -p no:cacheprovider`, never a
directory) or the project's equivalent. An import or collection error means a wrong environment, not a verdict:
fix the interpreter or ask before folding or dropping.
A claim that does not hold, or a failure that no longer reproduces, is dropped and reported. A test that cannot
run here keeps the pasted output as its evidence; the summary says so.

**Deduplicate.** Before `build`, `merge` prints merge candidates; fold anyway and join duplicates with
`amend --merge`. After `build` nothing merges: skip any claim an existing issue (the review JSON at `plan.json`
`review_path`) already states and name that id to the developer.

**Write each finding** with these fields; every field but `lines` and `also` is required, and a missing
`severity` falls back to `--severity` (`minor`):

| Field | Content |
|---|---|
| `severity` | `critical` blocks the merge (wrong behavior, data loss, broken contract, a test that cannot fail); `important` should be fixed before merging; `minor` is polish. Grade by blast radius: count the callers a contract change reaches. |
| `name` | one line, at most 120 characters |
| `summary` | what is wrong, the evidence (the developer's words, the node ids and assertion line) and how it was verified |
| `fix` | one or more options, any of which resolves it |
| `file` | repo-relative posix path of the file to change: the source file when the test is right, the test file when the test is wrong. No `..`, no drive letter |
| `lines` | optional: `12`, `12-18`, `12-18,40` |
| `also` | optional: other files the fix touches, never repeating `file` |
| `fix_kind` | `mechanical` when the fix is an exact edit a small model can apply; `judgment` otherwise |

A claim with no file it could be anchored to cannot be folded: pick the file that owns the behavior, or ask the
developer which file it concerns.

**Fold** through stdin so no file lands in the project (a JSON list of findings, or
`{"findings": [...], "strengths": [...]}`; `--findings <FILE>` also works):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" fold --pr <N> \
  --source developer_notes_1 --kind developer --findings - <<'EOF'
[
  {"severity": "important", "name": "load_notes drops entries after a blank line",
   "summary": "Developer note: notes after a blank entry vanish. Confirmed: load_notes breaks out of the loop at the first blank text (notes.py:41).",
   "fix": ["skip blank entries instead of breaking"], "file": "src/pkg/notes.py", "lines": "38-44",
   "also": ["tests/test_notes.py"], "fix_kind": "mechanical"}
]
EOF
```

## 4. Continue

- **Before `build`:** the fold prints `draft.json predates this fold` when a draft exists. Continue the
  `harness:pr-review` Phase 3 sequence: `merge` (`merge --force` when the draft was amended), `amend --regrade
  <ID>=<severity>` for each folded issue by blast radius, `build`. The issue is credited as `<source> (<kind>)`.
- **After `build`:** the fold prints the added ids, the new verdict and a `next:` line. Follow it: the Phase 4
  second run, `waves` for the new ids, `closeout`; inside an open Phase 5 pass, `waves` for the new ids, then
  `closeout`.
- A fold refused for `Phase 4 first run has not succeeded` waits for `build --replace`.

## 5. Report

Open with a status line: `fold [done] | <source> (<kind>) | <n> folded, <m> dropped | ids: <list>`. Then one row per
folded issue (id, severity, file) and one line per dropped item with its reason: not confirmed, no longer
reproduces, duplicate of `<id>`, opinion without a checkable defect.
