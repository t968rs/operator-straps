# pr-sum

Writes a PR summary document: a markdown file that says what a pull request changed and why, file by file, and
at levels 2 and 3 draws how its behavior changed. It is a summary, not a review: no verdicts, no findings, no
status or merge claims.
- `SKILL.md` is the procedure the agent follows
- `Examples/` holds rendered summaries
- this file explains what the skill produces and the shape of its flow.

## Invoking it

```
/harness:pr-sum PR [--level 1|2|3] [--min-viz [N]] [--local | --remote-head] [--committed-only] [--repo DIR] [-- <guidance>]
```

| Argument           | Effect                                                                              |
|--------------------|-------------------------------------------------------------------------------------|
| `PR`               | The PR number. Required; never guessed from the branch.                             |
| `--level 1\|2\|3`  | How much the summary draws. No `--level` means 2.                                   |
| `--min-viz [N]`    | Level 3 only: `build` requires N diagram blocks (default 3).                        |
| `--local`          | Reads the checked-out branch when it is not the PR branch, working tree included.   |
| `--remote-head`    | Reads the committed PR head `gh` reports, even on the PR branch.                    |
| `--committed-only` | Keeps the local PR head but leaves uncommitted changes out.                         |
| `--repo DIR`       | Names the project when the session runs elsewhere.                                  |
| `-- <guidance>`    | Free text after a standalone `--`: steers the prose only, never a flag or a check.  |

The agent never picks a level, a `--min-viz` count, a source flag or a repo on its own.

## Output

The summary lands in the project's summaries directory, `artifacts.summaries` in `.claude/harness.json`
(plugin default `docs/PR_SUMMARIES`), as `<NNNN>_<Title>.md`, beside its skeleton `<NNNN>_pr.json`. The
markdown is script output: changes go into the skeleton's `draft`, then `build` runs again.

## Levels

| Level | Adds                                                                                              |
|-------|---------------------------------------------------------------------------------------------------|
| 1     | Prose only: title, Summary, Files Changed with one description per file, Relocated. No sections.  |
| 2     | Default. Up to 3 behavior flows, at most one shape diagram, and a Changed Symbols table.          |
| 3     | Level 2 plus up to 5 flows and every matching shape diagram once (Sequence Diagram, Data Flow).   |

Every level adds a Source / Machine-generated / Total delta table under the Summary when any file is
machine-generated (harness outputs, `exclusions` matches, Artifact commits). The script writes that table.

## The flow

The plugin script `../../scripts/pr_sum.py` does the mechanics; the agent writes only the prose and the
visual sections.

```
capture --pr NNN ──► skeleton <NNNN>_pr.json: facts (script-owned) + draft (agent-owned)
     │
     ▼
diff SKELETON ──► the patch, source first, then tests, then docs; --path for cut sections
     │
     ▼
agent writes draft: title, summary, descriptions, sections (levels 2 and 3)
     │
     ▼
build SKELETON ──► alignment pass (levels 2 and 3), saved back to the skeleton
     │
     ▼
checks pass? ──no──► problem: lines; fix the draft, rerun build
     │yes
     ▼
<NNNN>_<Title>.md written, receipt printed
```

- **Capture** reads the PR number, title and base from one `gh pr view`; the content comes from local git. On
  the PR branch it covers local commits plus staged, unstaged and untracked changes, so pending fixes appear.
  Elsewhere it reads the committed PR head. Rerunning `capture` refreshes `facts` and keeps the draft.
- **Diff** prints the patch within a line budget and a 60k-character cap. A working-tree skeleton is refused
  once the branch or HEAD moved since capture.
- **Build** checks the draft against the skeleton's level and writes the markdown, or exits 1 with one
  `problem:` line per defect.

## Behavior flows

A behavior flow shows what a caller observes: the trigger, the conditions, the outcomes. It is not a call
graph. A `New Behavior:` section is one unlabeled fence. A `Behavior:` section draws BEFORE and AFTER from the
same trigger, in one of two forms:

- **Comparison**, when it fits in 120 columns: one fence headed `BEFORE`, `AFTER`, `[CHANGE]`. Shared steps
  are drawn once at the left; each changed step carries a gutter marker and one tag.
- **Stacked**, for a wider flow: a `BEFORE` fence, then an `AFTER` fence; `[changed]` and `[new]` go in the
  AFTER fence only, `[removed]` in the BEFORE fence.

| Marker | The row shows                                                   | Tag         |
|--------|-----------------------------------------------------------------|-------------|
| `<>`   | the BEFORE step on the left becomes the AFTER step on the right | `[changed]` |
| `>>`   | an AFTER step BEFORE lacks                                      | `[new]`     |
| `<<`   | a BEFORE step AFTER drops                                       | `[removed]` |

`[[` and `]]` mark the words that changed inside an AFTER step. `SKILL.md` holds the full grammar and an example
fence.

## The alignment pass

At levels 2 and 3, `build` aligns the section bodies before it checks them and saves the result to the
skeleton, even when a check then fails. It changes only spaces:

- pads markdown table cells so the pipes line up;
- slides a hanging `│` or `▼` (with the connectors below it) up to 4 columns to the nearest column the line
  above feeds down;
- in a comparison fence, moves the markers into one gutter column and the tags, with the `[CHANGE]` header,
  into one column two spaces right of the widest line.

What the pass cannot move stays as written and surfaces as a `problem:` line. Tables and tag columns are never
padded by hand.

## Examples

`Examples/` holds rendered summaries by level; `Examples/Level-2.md` is a level 2 summary of a PR to this
skill, with a stacked `Behavior:` flow and a Changed Symbols table.

## Related

- `SKILL.md`: the procedure.
- `../../scripts/pr_sum.py`: the driver (`capture`, `diff`, `build`).
- `../../scripts/diff_delta.py`: the source-only line count between any two refs.
- `../../lib/harness_lib/pr_summary.py`: layout and the `build` checks.
- `../../lib/harness_lib/pr_compare.py`: the comparison fence checks.
- `../../lib/harness_lib/pr_align.py`: the alignment pass.
- `../pr-review/README.md`: the review flow, which this skill never reads for content.
