---
name: pr-sum-viz
description: Use when asked for a visual, diagram, flowchart or "more visual" PR summary, one "akin to" an
  earlier visual summary, or a PR summary of a PR that changes runtime behavior, relocates code, migrates call
  sites to a new API, sweeps a rename, or adds a small utility with a clear decision rule
model: haiku
effort: medium
context: fork
agent: harness:messenger
---

# PR Summary (Visual)

Same job and script as `harness:pr-sum` (`${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py`): the script owns facts,
tables and layout; the agent writes the prose plus the visual sections: behavior flowcharts, at most one shape
diagram, and a Changed Symbols table. No code review.

## Running the script

Every command runs through the Bash tool (never the PowerShell tool) with the plugin's Python launcher:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" <command> ...
```

The script works on the project that holds the working directory (its git top level; in a worktree, that
worktree). Run from the project root, or add `--repo <dir>` to any command to name the project. Output goes to
the project's configured summaries directory: `artifacts.summaries` in `.claude/harness.json` (plugin default
`docs/PR_SUMMARIES`), written below as `<summaries>`.

## Step 1 — Capture

The PR number comes from the invocation arguments. No number given: report that and stop; never guess one from
the branch or `gh pr list`.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" capture --pr NNN
```

The capture runs at any point of the PR's life. The PR anchors the number, title and base; the content is
local branch state. While the PR branch is checked out, it covers the branch's local commits plus staged,
unstaged and untracked changes, so unpushed work and pending review fixes appear; elsewhere it reads the
committed PR head `gh` reports. `--remote-head` forces that remote head; `--committed-only` keeps the local
head without uncommitted changes. Pass either only when asked. A local capture adds a `**Source:**` header
line.

Exit 1 prints `problem:` lines (malformed JSON or config, missing file, `gh` missing): report them and stop.
Exit 0 writes `<summaries>/<NNNN>_pr.json` and prints `wrote <path>`; use that path as `SKELETON` below. The
skeleton holds `facts` (script-owned — **never edit**) and `draft` (yours: `title`, `summary`, `descriptions`,
`sections`). Rerunning `capture` refreshes `facts` and keeps the draft (title, summary, sections, and
descriptions for paths still in the PR). Header totals are local `git diff --numstat` sums and can differ
slightly from GitHub's.

## Step 2 — Read what changed

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" diff SKELETON
```

`diff` skips machine-generated artifact files unless named with `--path`, prints source sections first, then
tests (the project's configured test layout), then docs, and stops at a line budget and a 60k-character output
cap. A section that reads `[omitted: block output budget spent]` or prints as `summary` was cut: rerun `diff`
with `--path <p>` (repeatable) for those paths. `--path` also accepts a renamed file's old path.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" diff SKELETON --path src/pkg/module.py
```

Removed lines give the old behavior, added lines the new; the patch is the only source for the diagrams, and it
is not reviewed.

## Step 3 — Write the draft

Edit only `draft`. `summary` and each section `body` may be a list of lines (no `\n` escapes needed).

- **`title`** — `harness:pr-sum`'s Step 3 rule: Conventional prefix + the one backticked entity + a minimal artifact
  noun; no imperative verbs, issue numbers or `and X`. `Feature(cursor): add drop_sentinel_values utility and
  enhance field validation` → ``Feature(cursor): `drop_sentinel_values` utility``.
- **`summary`** — a first paragraph of 2-3 sentences on what changed and why; then a second paragraph on the
  shape of the change. Paragraphs cap at three sentences. Asides that qualify a number go on their own line as
  `***Note:*** ...` with a blank line above and below. The artifact-noise Note is added by the script.
- **`descriptions`** — one line per file, from the diff; backtick identifiers.
- **`sections`** — `[{"heading": ..., "body": [...]}]`, in the order below; `build` rejects other headings,
  extra sections and a different order.

### 1. Behavior flows (when behavior changed or was added)

One section per behavior, at most three. A flow shows what a caller or user observes: the trigger, the
conditions, and the outcomes (files written, values returned, errors raised, messages shown). It is not a call
graph; a function name goes in parentheses only when it helps the reader find the code.

| Behavior            | Heading                      | Body                                            |
|---------------------|------------------------------|-------------------------------------------------|
| Changed behavior    | `Behavior: <trigger>`        | `BEFORE` and `AFTER` flows                      |
| New behavior        | `New Behavior: <trigger>`    | one flow, no label                              |

A `Behavior:` section has a fence whose first line starts with `BEFORE` and a fence whose first line starts
with `AFTER`, or one side-by-side fence with both labels on its first line. Both flows start from the same
trigger and reuse the same wording for unchanged steps, so the difference stands out. Tags go in the AFTER flow
only: `[changed]` on a step whose outcome differs from BEFORE, `[new]` on a step BEFORE lacks; a step worded the
same in both is untagged. `build` checks those labels, and checks tags only in a stacked BEFORE fence (none
allowed there). Keep a flow to about ten steps. Use this grammar and no other glyphs:

```
BEFORE                                         AFTER
append review rows                             append review rows
     │                                              │
     ▼                                              ▼
read matrix ──fails──► treated as empty        matrix exists? ──no──► write a new file                 [new]
     │ok                    │                       │yes
     ▼                      ▼                       ▼
append, write file     write new rows only     read succeeds? ──no──► file kept, rows reported failed  [changed]
                                                    │yes
                                                    ▼
                                               append, write file
```

Side by side in one fence when both fit in 120 columns; otherwise a BEFORE fence, then an AFTER fence. A
refactor with no behavior change has no flows; the summary says behavior is unchanged.

### 2. Shape diagram (optional, at most one)

Pick the one that matches the change; required when there is no behavior flow. Pure file moves need none: the
script's Relocated block already lists them.

| Change shape                          | Heading             | Columns                                  |
|---------------------------------------|---------------------|------------------------------------------|
| Moves with edits, or package shape    | Module Relocations  | `BEFORE  ───►  AFTER` tree               |
| Symbols moved across modules          | Symbol Relocations  | `SYMBOL   FROM   ──►   TO`               |
| Call sites swapped to new API/helpers | Call-Site Migration | `BEFORE (old) ┃ AFTER (new)`             |
| New utility with a decision rule      | Rule Illustration   | `input -> output` cases showing the rule |

### 3. Changed Symbols (always)

A simple markdown table: `Symbol | File | Status | Note`. Long text goes outside the table:

- **File paths**: a fenced key block above the table (`T = src/app/hooks/tracker.ts`); the File cell holds
  the key.
- **Explanations**: the Note cell holds a short phrase. Anything longer goes in a `- `symbol`: ...` bullet
  below the table.

`Status` is NEW, FIXED, RENAMED, KEPT or REMOVED. Symbol is byte-exact, in backticks. Rows are the PR's
source symbols; test helpers and stubs stay out.

Every markdown table cell in a visual section holds 40 characters or fewer, and lines inside a fence are 120
characters or fewer (`build` rejects longer ones). In diagrams and key blocks, a long path may drop a leading
directory every changed source file shares; `descriptions` keys stay the full paths from `facts`.

## Step 4 — Build

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" build SKELETON --visual
```

`build` checks: `title` and `summary` non-empty, `title` on one line, a description for every listed
non-artifact path and none for paths outside the PR, no AI vendor names, and the section rules above. The
header's Files Changed count notes relocated files.

Exit 1: each `problem:` line names a draft defect; fix the draft and rerun. Exit 0 writes
`<summaries>/<NNNN>_<Title>.md` and prints the receipt. Output the receipt verbatim — nothing else.

## Common Mistakes

| Mistake                                         | Fix                                                        |
|-------------------------------------------------|------------------------------------------------------------|
| Editing `facts` or hand-writing the markdown    | Edit `draft`; rerun `build`                                |
| `gh pr diff` / `gh api` for the patch           | `diff` already has it, budgeted                            |
| A flowchart of function calls                   | Steps are observable: condition, outcome, error, file      |
| AFTER flow only, for a fix                      | BEFORE and AFTER, same trigger and same wording            |
| Unlabelled `Behavior:` fences, or BEFORE tags   | First line BEFORE / AFTER; tags in AFTER only              |
| A flow per module                               | A flow per behavior, at most three                         |
| Flow steps or diagrams not in the diff          | Each step traces to removed or added lines                 |
| Long paths or sentences in table cells          | Key block above, bullets below                             |
| Idiosyncratic glyphs (◆◈⊙)                      | The flow grammar and the Status values                     |
| Review language, or PR review JSON findings     | Summary, not review                                        |
| Running from another project's directory        | Run from the project root, or pass `--repo <dir>`          |
