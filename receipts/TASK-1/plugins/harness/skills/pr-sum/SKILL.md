---
name: pr-sum
description: 'Use when asked to summarize a PR, describe PR changes, write a PR summary document, or draw one: a visual, diagram, flowchart or "more visual" summary, one "akin to" an earlier visual summary, or a PR that changes runtime behavior, relocates code, migrates call sites to a new API, sweeps a rename, or adds a small utility with a clear decision rule'
argument-hint: "PR [--level 1|2|3] [--min-viz [N]] [--auto-title] [--no-auto-title] [--local | --remote-head] [--committed-only] [--repo DIR] [-- <guidance>]"
model: sonnet
effort: medium
context: fork
agent: harness:messenger
---

# PR Summary

The plugin script `${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py` does the mechanics: one `gh pr view` metadata read,
local git for commits, files and line counts, layout, save. The agent writes the prose (title, Summary, one
description per file) and, at levels 2 and 3, the visual sections: behavior flowcharts, shape diagrams and a
Changed Symbols table. No code review. No status or merge claims.

## Levels

`--level` picks how much the summary draws. The script stores it in the skeleton at `capture`, and `build`
reads it from there. No `--level` means 2.

| Level | Output                                                                                              |
|-------|-----------------------------------------------------------------------------------------------------|
| 1     | Prose only: Summary, Files Changed, Relocated. No sections.                                         |
| 2     | Default. Behavior flows (at most 3), at most one shape diagram, Changed Symbols.                    |
| 3     | Level 2 plus: up to 5 flows, every shape diagram once (two more: Sequence Diagram, Data Flow).      |

Every level adds the delta table under the Summary when any file is machine-generated.

`--min-viz [N]` applies at level 3 only (ignored at levels 1 and 2). `build` then requires N diagram blocks
(default 3): fenced, over 200 characters between the fences, and holding an arrow (`→ ► ▶ ▼ ▲ ◄ ← ↑ ↓ ➜ ⟶ ->
=>`), counted across the Summary and every section. `capture` arms a Stop-hook sentinel, so the session cannot
end before `build` succeeds.

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

Split the invocation arguments at the first standalone `--` token, per
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. The part after it is guidance for the prose (what to stress,
what to leave out of the Summary): it shapes the agent's writing only, never a command or a flag, and never
breaks a `build` rule. Everything below reads the part before the token.

The PR number comes from the invocation arguments. No number given: report that and stop; never guess one from
the branch or `gh pr list`. The other arguments are the developer's flags: `--level 1|2|3`,
`--min-viz [N]`, `--auto-title` and `--no-auto-title`, plus the source flags `--local`, `--remote-head` and `--committed-only` and `--repo DIR`;
pass them through unchanged. Any other flag, a `--level` or `--min-viz` value holding anything but digits, `--auto-title`
together with `--no-auto-title`, or `--local` together with
`--remote-head` is a problem to report; stop. Never choose a level, a `--min-viz` count, `--auto-title`, a source flag or a
repo yourself. A `--repo DIR` is added to the `diff` and `build` commands below as well.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" capture --pr NNN [--level L] [--min-viz [N]] [--auto-title | --no-auto-title] [--local | --remote-head] [--committed-only] [--repo DIR]
```

`--auto-title` is the developer's consent to rename the PR. `"auto_title": true` in the project's
`.claude/harness.json` is the same consent given once for every run: `capture` then behaves as if the flag
were given, and `--no-auto-title` from the invocation withdraws it for that capture. With neither flag, pass
none and let the key decide. With auto-title on, `capture` stores it in the skeleton and notes on
its line what `build` will do with the PR title. When the PR title is not a one-line ASCII
`Word(scope): summary` subject distinct from the branch name, a title a squash commit cannot use, `build` sets the draft `title` as the PR title (`gh pr edit`). A usable PR
title is kept, and so is a merged PR's title; an unusable title on an open or closed (unmerged) PR is
replaced. Unlike `merge-commit-msg --auto-title`, which refuses a PR that is not open, `build` retitles a
closed PR too, and its receipt says `Retitled` either way.

The capture runs at any point of the PR's life. The PR anchors the number, title and base; the content comes
from local git. While the PR branch is checked out (a branch of the PR head's name whose HEAD contains that
head), it covers the branch's local commits plus staged, unstaged and untracked changes, so unpushed work and
pending review fixes appear; untracked files under the harness output directories (reviews, summaries, commit
messages, scratch) and the skeleton itself are left out. Elsewhere, including a stale or unrelated local branch
of the same name, it reads the committed PR head `gh` reports. `--remote-head` forces that remote head;
`--committed-only` keeps the local head without uncommitted changes. `--local` reads whatever is checked out
when it is not the PR branch (another branch): the script takes that HEAD, diffs from its merge base with the
PR base to the working tree, and so covers the commits since the base plus staged and unstaged changes;
untracked files are left out. On the PR branch itself `--local` changes nothing (untracked files stay). Pass
these only when asked. A local capture adds a `**Source:**` header line: `local branch` on the PR branch,
``local checkout `<branch>` `` for a `--local` capture off it (a stale branch of the PR head's name included),
`local detached checkout` on a detached HEAD. When that HEAD does not contain the PR head, `capture` ends its
line with a `note:`: the summary then covers this checkout only, and descriptions already drafted for PR files
the checkout lacks are dropped by this capture (the note counts them). Report the note. `--local` is meant for ordinary branch
checkouts; on a detached HEAD `diff` verifies only the HEAD SHA, so two worktrees at one commit are not told
apart.

Exit 1 prints `problem:` lines (malformed JSON or config, missing file, `gh` missing): report them and stop.
Exit 0 writes `<summaries>/<NNNN>_pr.json` and prints `wrote <path>`; use that path as `SKELETON` below.

- `facts` — script-owned: refs, commit lines, files with status and `+/-` counts. **Never edit.**
- `draft` — yours: `title`, `summary`, `descriptions` (one key per file that needs one), `sections`.

Machine-generated files (paths matching the project's `exclusions` file plus the harness output patterns,
both off when `exclusions` is null, or classified as Artifact by the commit buckets) and pure moves have no description key; the script tags and
places them. When any file is machine-generated, the script adds a Source / Machine-generated / Total delta
table under the Summary itself (do not write one). The same source-only count between any two refs comes
from `diff_delta.py`, outside the summary flow:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/diff_delta.py" REF_A REF_B [--repo DIR] [--json]
```

It prints `delta [ok] | source +A/-D (net +N), F files | total +A/-D (net +N), F files | excluded X`
(`source` without the machine-generated paths, `total` with every path, `excluded` the count left out), or
with `--json` the same numbers plus the excluded paths; a failure exits 1 with one `problem:` line. Header
totals are local `git diff --numstat` sums and can differ slightly from GitHub's. Rerunning `capture` refreshes
`facts` and keeps the draft (title, summary, sections, and descriptions for paths still in the PR); the level
flags and the auto-title choice are stored fresh on every capture, so repeat them on a rerun.

## Step 2 — Read what changed

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" diff SKELETON [--repo DIR]
```

`diff` skips machine-generated artifact files unless named with `--path`, prints source sections first, then
tests (the project's configured test layout), then docs, and stops at a line budget and a 60k-character output
cap. A section that reads `[omitted: block output budget spent]` or prints as `summary` was cut: rerun `diff`
with `--path <p>` (repeatable) for those paths. `--path` also accepts a renamed file's old path.

A local capture's `diff` reads the working tree as it is when `diff` runs; after edits or a branch switch, rerun
`capture` first. `diff` refuses a working-tree skeleton (`problem: working tree moved since capture`) once the
branch or HEAD has changed: rerun `capture`, then `diff`.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" diff SKELETON --path src/pkg/module.py [--repo DIR]
```

Read `facts.commits` alongside the diff. Removed lines give the old behavior, added lines the new; the patch is
the only source for the diagrams, and it is not reviewed.

## Step 3 — Write the draft

Edit only `draft`. `summary` and each section `body` may be a list of lines (no `\n` escapes needed).

**`title`** — not a copy of `facts.pr_title` or a commit subject:

1. **Prefix:** the Conventional Commit prefix (`Type(scope):` or `Type:`) of `facts.pr_title`, else of the first
   commit subject.
2. **Primary subject:** the single most important entity changed (parameter, function, class, module, file), in
   backticks.
3. **Artifact noun:** the minimal noun phrase for what was produced (`insertion catalog`, `refactor`, `test`,
   `migration`).
4. **Drop:** imperative verbs (`add`, `fix`, `introduce`, `update`, `remove`, `move`), issue/PR numbers, and
   secondary topics joined by `and` / `plus`.

| Raw PR title / commit message                                            | Title                                           |
|--------------------------------------------------------------------------|-------------------------------------------------|
| Docs(cache): add Issue #291 eviction catalog and blast radius analysis   | Docs(cache): `evict_stale` eviction catalog     |
| Feat(parser): introduce max_depth parameter into tokenizer pipeline      | Feat(parser): `max_depth` parameter             |
| Refactor(io): remove duplicate normalize_headers and fix merge signature | Refactor(io): `normalize_headers` deduplication |

No single subject (a broad multi-file change): scope plus artifact noun only.

With `--auto-title` stored, and the PR title refused as above, the title also becomes the PR title. It then
needs the `Type(scope):` prefix even when neither the PR title nor a commit subject has one: take the type the
commit subjects use most, and when none has one, the type that names the change (`Feature`, `Fix`, `Docs`).
It must also be ASCII on one line; `build` refuses anything else.

**`summary`** — what changed and why. Paragraphs cap at three sentences; separate paragraphs with a blank line
(`\n\n`). `summary` may also be a list of lines (no `\n` escapes); an empty `""` entry is the blank line between
paragraphs. Asides that qualify a number go on their own line as `***Note:*** ...` with a blank line above and
below.

- Level 1: 2-3 sentences up to 1000 changed lines; 1-2 more per additional 1000.
- Levels 2 and 3: a first paragraph of 2-3 sentences on what changed and why; then a second paragraph on the
  shape of the change.

**`descriptions`** — one line per file: what changed in it, from the diff. Backtick identifiers.

**`sections`** — level 1: leave `[]` and stop here. Levels 2 and 3: `[{"heading": ..., "body": [...]}]`, in the
order below; `build` rejects other headings, extra sections and a different order.

### 1. Behavior flows (when behavior changed or was added)

One section per behavior, at most three (five at level 3). A flow shows what a caller or user observes: the
trigger, the conditions, and the outcomes (files written, values returned, errors raised, messages shown). It is
not a call graph; a function name goes in parentheses only when it helps the reader find the code.

| Behavior            | Heading                      | Body                                            |
|---------------------|------------------------------|-------------------------------------------------|
| Changed behavior    | `Behavior: <trigger>`        | `BEFORE` and `AFTER` flows                      |
| New behavior        | `New Behavior: <trigger>`    | one flow, no label                              |

A `Behavior:` section draws BEFORE and AFTER from the same trigger and reuses the same wording for unchanged
steps, so the difference stands out. It takes one of two forms:

- **Comparison**, whenever it fits in 120 columns: one fence whose first line names the columns `BEFORE`,
  `AFTER` and `[CHANGE]`, in that order. Steps both flows share before they part are drawn once, at the left.
  Each changed step gets a marker in the gutter between the two flows and one tag in the `[CHANGE]` column,
  on the marker line or on a line continuing that step's text; an unchanged step gets neither. `[[` and `]]`
  mark the words that changed inside an AFTER step.

  | Marker | The row shows                                                   | Tag         |
  |--------|-----------------------------------------------------------------|-------------|
  | `<>`   | the BEFORE step on its left becomes the AFTER step on its right | `[changed]` |
  | `>>`   | an AFTER step BEFORE lacks; the BEFORE `│` runs on past it      | `[new]`     |
  | `<<`   | a BEFORE step AFTER drops                                       | `[removed]` |

- **Stacked**, for a wider flow: a fence whose first line starts with `BEFORE`, then a fence whose first line
  starts with `AFTER`. `[changed]` and `[new]` go in the AFTER fence only: `[changed]` on a step whose
  outcome differs from BEFORE, `[new]` on a step BEFORE lacks. A BEFORE step AFTER drops takes `[removed]`
  in the BEFORE fence.

`build` checks the labels, refuses `[changed]` and `[new]` in a stacked BEFORE fence, and in a comparison fence checks that every
marked step holds the one tag its marker takes, every tag sits on a marked step, the markers share one gutter
column, the tags start at the `[CHANGE]` column and every `[[` closes. A side-by-side fence without
`[CHANGE]` is refused. A `New Behavior:` section is exactly one fence holding at least one non-blank line, with
no `BEFORE` or `AFTER` label on its first line; `build` checks both.

A decision is drawn as a fork with labeled arms (`──no──►` across, `│yes` down), never as a chain of steps.
Every `│` and `▼` sits under the step text or connector on the line above; the single blank between two words
of a step counts as step text. `build` rejects a connector that hangs under a wider blank or under a `──no──►`
arm (its label included), in both flow kinds. Keep a flow to about ten steps. Use this grammar and no other
glyphs:

```
BEFORE                                       AFTER                                     [CHANGE]
append review rows
     │
     │
     │                                   >>  matrix exists? ──no──► write a new file   [new]
     │                                            │yes
     ▼                                            ▼
read matrix ──fails──► treated as empty  <>  read succeeds? ──no──► file kept, [[rows  [changed]
     │ok                    │                     │yes              reported failed]]
     ▼                      ▼                     ▼
append, write file     write new rows only   append, write file
```

A refactor with no behavior change has no flows; the summary says behavior is unchanged.

### 2. Shape diagram (optional; at most one, at level 3 each heading at most once)

Pick the one that matches the change; required when there is no behavior flow. Pure file moves need none: the
script's Relocated block already lists them. At level 3 every row that matches the change gets its own
section, in table order.

| Change shape                           | Heading             | Columns                                  |
|----------------------------------------|---------------------|------------------------------------------|
| Moves with edits, or package shape     | Module Relocations  | `BEFORE  ───►  AFTER` tree               |
| Symbols moved across modules           | Symbol Relocations  | `SYMBOL   FROM   ──►   TO`               |
| Call sites swapped to new API/helpers  | Call-Site Migration | `BEFORE (old) ┃ AFTER (new)`             |
| New utility with a decision rule       | Rule Illustration   | `input -> output` cases showing the rule |
| Level 3: calls between actors in order | Sequence Diagram    | one column per actor, `──►` per message  |
| Level 3: data moving between stages    | Data Flow           | `source ──► stage ──► sink`              |

### 3. Changed Symbols (always, levels 2 and 3)

A simple markdown table: `Symbol | File | Status | Note`. Long text goes outside the table:

- **File paths**: a fenced key block above the table (`T = src/app/hooks/tracker.ts`); the File cell holds
  the key.
- **Explanations**: the Note cell holds a short phrase. Anything longer goes in a `- `symbol`: ...` bullet
  below the table.

`Status` is one of:

| Status  | The symbol                                                            |
|---------|-----------------------------------------------------------------------|
| NEW     | did not exist before the PR                                           |
| CHANGED | existed; its signature, behavior or output changed; no bug is cited   |
| FIXED   | existed; the diff corrects behavior that was wrong                    |
| RENAMED | keeps its role under a new name; the Note gives the old name          |
| MOVED   | keeps its name and role in another file; the Note gives the old file  |
| REMOVED | no longer exists                                                      |

Symbol is byte-exact, in backticks. Rows are the PR's source symbols, each changed by the diff; test helpers,
stubs and untouched callers stay out.

Every markdown table cell in a visual section holds 40 characters or fewer, and lines inside a fence are 120
characters or fewer (`build` rejects longer ones). In diagrams and key blocks, a long path may drop a leading
directory every changed source file shares; `descriptions` keys stay the full paths from `facts`.

## Step 4 — Build

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" build SKELETON [--repo DIR]
```

At levels 2 and 3, `build` first runs a vertical alignment pass over the section bodies and saves what it
changed back to the skeleton, even when a check then fails. It changes only whitespace, separator dash runs
and outer table pipes, never the order of cell or step text: it pads markdown table cells so the pipes line
up (the separator under the header is redrawn at the column width; its colons set right or center padding), slides a hanging `│` or `▼`,
with the connectors below it and a label such as `│yes`, up to 4 columns to the nearest column the line above
feeds down (step text or a connector) where the cells are free, and in a comparison fence moves the markers
into one gutter column where the cells are free and the tags, with the `[CHANGE]` header, into one column two
spaces right of the widest line (of the widest tagged line when that would pass 120 columns; the tags stay put
when neither fits). What the pass cannot move stays as written. So do not hand-pad tables or tag columns; draw
the steps and connectors close, and fix by hand only what the pass leaves as a `problem:` line.

`build` checks: `title` and `summary` non-empty, `title` on one line, a description for every listed
non-artifact path and none for paths outside the PR, no AI vendor names, no emojis and no section sign (write
"Section 2"; backticked text is exempt), no control characters (tab and line breaks excepted) in any drafted
string, the section rules of the skeleton's level (including the
`Behavior:` labels and comparison rules, the one unlabeled fence of a `New Behavior:` section, and connector
alignment in every flow), and with `--min-viz` the diagram-block count. A shortfall prints one `problem:` line
with the count found; add diagrams to the draft and rerun. The header's Files Changed count notes relocated
files.

With `--auto-title` stored, `build` reads the PR again with `gh pr view` and checks the draft `title` as a PR
title before it writes. When it retitles the PR, it does so before writing the summary. A failed `gh pr view`
or `gh pr edit` is a `problem:` line naming `gh`, and nothing is written: report it and stop. The receipt gains a second line: `Retitled PR #N: '<old>' ->
'<new>'`, or `PR #N title kept: ...`.

Exit 1: every other `problem:` line names a draft defect; re-read the skeleton (the alignment pass may have saved
to it), fix the draft and rerun. Exit 0 writes
`<summaries>/<NNNN>_<Title>.md` and prints the receipt. Output the receipt verbatim — nothing else.

## Common Mistakes

| Mistake                                                   | Fix                                                             |
|-----------------------------------------------------------|-----------------------------------------------------------------|
| Editing `facts` (counts, commits, file rows)              | Rerun `capture`; it refreshes `facts` and keeps the draft       |
| Writing or patching the summary markdown by hand          | Edit `draft`; rerun `build`. The markdown is script output.     |
| Writing the delta table or source counts into `summary`   | Delete it; the script adds the table                            |
| An AI vendor or product name anywhere in `draft`          | Remove it; `build` rejects it                                   |
| An emoji or a section sign in `draft`                     | Remove it, or write "Section 2"; `build` rejects both           |
| Running `gh pr diff` / `gh api` for files or commits      | `capture` and `diff` already have them                          |
| Descriptions guessed from filenames                       | Read the diff; state the change                                 |
| Review language (verdicts, strengths, issues, next steps) | This is a summary, not a review — delete it                     |
| Mining a PR review JSON for findings                      | It is an artifact row; never a content source                   |
| Running the script from another project's directory       | Run from the project root, or pass `--repo <dir>`               |
| A flowchart of function calls                             | Steps are observable: condition, outcome, error, file           |
| AFTER flow only, for a fix                                | BEFORE and AFTER, same trigger and same wording                 |
| Unlabelled `Behavior:` fences, or BEFORE tags             | First line BEFORE / AFTER; stacked: [changed]/[new] in AFTER    |
| Side-by-side flows without `[CHANGE]`, markers or tags    | Comparison fence: header, one marker and one tag per change     |
| Padding table pipes or tag columns by hand                | `build` aligns them; fix only what it reports                   |
| A flow per module                                         | A flow per behavior, at most three (five at level 3)            |
| Flow steps or diagrams not in the diff                    | Each step traces to removed or added lines                      |
| Long paths or sentences in table cells                    | Key block above, bullets below                                  |
| Idiosyncratic glyphs (◆◈⊙)                                | The flow grammar and the Status values                          |
| Sections in a level 1 draft                               | Level 1 has none; `[]`                                          |
| Padding a diagram to pass `--min-viz`                     | Each block shows a real flow from the diff                      |
| Choosing the level without the developer                  | No `--level` means 2                                            |
| Adding `--auto-title`, or running `gh pr edit`, unasked   | Only the developer's flag or `auto_title` key; `build` renames  |
