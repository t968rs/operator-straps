---
name: pr-sum
description: Use when asked to summarize a PR, describe PR changes, or write a PR summary document
model: haiku
effort: low
context: fork
agent: harness:messenger
---

# PR Summary

The plugin script `${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py` does the mechanics: one `gh pr view` metadata read,
local git for commits, files and line counts, layout, save. The agent writes the prose: title, Summary, one
description per file. No code review. No status or merge claims.

For a diagram-rich summary, use `harness:pr-sum-viz`.

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

Exit 1 prints `problem:` lines (malformed JSON or config, missing file, `gh` missing): report them and stop.
Exit 0 writes `<summaries>/<NNNN>_pr.json` and prints `wrote <path>`; use that path as `SKELETON` below.

- `facts` — script-owned: refs, commit lines, files with status and `+/-` counts. **Never edit.**
- `draft` — yours: `title`, `summary`, `descriptions` (one key per file that needs one), `sections` (leave `[]`).

Artifact files (paths the project's commit buckets classify as Artifact) and pure moves have no description
key; the script tags and places them, and adds the artifact `***Note:***` itself (do not write one). Header
totals are local `git diff --numstat` sums and can differ slightly from GitHub's. Rerunning `capture` refreshes
`facts` and keeps the draft (title, summary, sections, and descriptions for paths still in the PR).

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

Read `facts.commits` alongside the diff.

## Step 3 — Write the draft

Edit only `draft` in the JSON.

**`title`** — not a copy of `facts.pr_title` or a commit subject:

1. **Prefix:** the Conventional Commit prefix (`Type(scope):` or `Type:`) of `facts.pr_title`, else of the first
   commit subject.
2. **Primary subject:** the single most important entity changed (parameter, function, class, module, file), in
   backticks.
3. **Artifact noun:** the minimal noun phrase for what was produced (`insertion catalog`, `refactor`, `test`,
   `migration`).
4. **Drop:** imperative verbs (`add`, `fix`, `introduce`, `update`, `remove`, `move`), issue/PR numbers, and
   secondary topics joined by `and` / `plus`.

| Raw PR title / commit message                                                  | Title                                       |
|--------------------------------------------------------------------------------|---------------------------------------------|
| Docs(cache): add Issue #291 eviction catalog and blast radius analysis         | Docs(cache): `evict_stale` eviction catalog |
| Feat(parser): introduce max_depth parameter into tokenizer pipeline            | Feat(parser): `max_depth` parameter         |
| Refactor(io): remove duplicate normalize_headers and fix merge signature       | Refactor(io): `normalize_headers` deduplication |

No single subject (a broad multi-file change): scope plus artifact noun only.

**`summary`** — what changed and why. 2-3 sentences up to 1000 changed lines; 1-2 more per additional 1000.
Paragraphs cap at three sentences; separate paragraphs with a blank line (`\n\n`). `summary` may also be a list
of lines (no `\n` escapes); an empty `""` entry is the blank line between paragraphs.

**`descriptions`** — one line per file: what changed in it, from the diff. Backtick identifiers.

## Step 4 — Build

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" build SKELETON
```

`build` checks: `title` and `summary` non-empty, `title` on one line, a description for every listed
non-artifact path and none for paths outside the PR, and no AI vendor names. The header's Files Changed count
notes relocated files.

Exit 1: each `problem:` line names a draft defect; fix the draft and rerun. Exit 0 writes
`<summaries>/<NNNN>_<Title>.md` and prints the receipt. Output the receipt verbatim — nothing else.

## Common Mistakes

| Mistake                                                   | Fix                                                             |
|-----------------------------------------------------------|-----------------------------------------------------------------|
| Editing `facts` (counts, commits, file rows)              | Rerun `capture`; it refreshes `facts` and keeps the draft       |
| Writing or patching the summary markdown by hand          | Edit `draft`; rerun `build`. The markdown is script output.     |
| Writing the artifact `***Note:***` into `summary`         | Delete it; the script adds it                                   |
| An AI vendor or product name anywhere in `draft`          | Remove it; `build` rejects it                                   |
| Running `gh pr diff` / `gh api` for files or commits      | `capture` and `diff` already have them                          |
| Descriptions guessed from filenames                       | Read the diff; state the change                                 |
| Review language (verdicts, strengths, issues, next steps) | This is a summary, not a review — delete it                     |
| Mining a PR review JSON for findings                      | It is an artifact row; never a content source                   |
| Running the script from another project's directory       | Run from the project root, or pass `--repo <dir>`               |
