# Branch Commit-Messages TXT Format

Format for the whole-branch breakdown file `<branch-name>.txt` produced by the `branch-commit-msg` skill in the
project's configured commit_messages directory (`artifacts.commit_messages`, default `docs/_commit_messages`). Each
commit block within the file conforms to the plugin's `reference/commit_format.md`; this file defines only how
multiple blocks are assembled into one document.

Neither skill writes this layout by hand: the plugin's `scripts/branch_commit_msg.py build` renders it
(`harness_lib.commit_txt.document_to_txt`) and `capture` applies the Merge Protocol below. This file is the
reference for readers and parsers.

`c-msg` runs `capture --pending`, then `build`; `build` writes the same layout to `<branch>_pending.txt` in the
same directory: one block, `Merge base:` set to HEAD, covering the change pending against HEAD. It never reads or
writes `<branch>.txt`.

## Layout

- Plain text. Commit blocks separated by `---` on its own line.
- Scaffold and file-list lines sit at column 0 (no leading spaces/tabs): `Branch:`, `Merge base:`,
  `Messaged-through:`, `Split:`, `===`, `Commit N - ...`, quoted file paths, `---`.
- The `Branch:` footer appears once, at the end of the last commit block (see "Last Commit").
- Body bullets stay 2-space indented.
- The commit header (see "Commit header" below) is a sibling of its file list, not a parent — never indent the paths
  under it.

## Header

```
Branch: `<branch-name>`
Merge base: <sha>
Messaged-through: <HEAD-sha at this run's save>
Split: <split decision / rationale (the skeleton's `split`)>

===
```

`Merge base:` is the reset target. The developer applies the file by mixed-resetting the branch to this SHA and
re-committing every block in order (see SKILL.md "Rebuild assumption"), so the file always covers the full
merge-base diff. `Messaged-through:` records HEAD at the last save; it is a record, not a capture start.

**One path, one block.** Every path appears in exactly one commit block across the whole file. A block's file list
stages that file's final working-tree content.

## Per-commit block

Commit header, then the file list (per commit_format.md file-list rules), then the message (per commit_format.md).
Commit order is the skeleton's key order: `capture` plans it, and SKILL.md Step 2 may renumber for dependencies.

### Commit header (exact format, no variation)

```python
header = f"Commit {commit_no} - {bucket.title()} ({file_count} files)"
```

- `commit_no`: the block's 1-based position after re-sort.
- `bucket`: the block's bucket label passed through `str.title()`. The only allowed values are `Docs`,
  `Planning`, `Runtime+Test`, `Runtime`, `Test`, `Cicd`, `Agent`, `Other` and `Artifact`. Which paths land in
  which bucket is the project's `commit_buckets` (first match wins); the plugin defaults put plans and specs
  (`docs/superpowers/`, `docs/PLANS/`), every `CLAUDE.md` and every `DesignEvolution.json` in Planning. Docs covers
  other prose, including `.claude/**/*.md` other than `CLAUDE.md`.
- `file_count`: the number of quoted entries in the block's file list. Artifact glob entries count as files.
- The separator is a single ASCII hyphen with one space on each side. The noun is always `files`, including
  `(1 files)`. Never `file`, `entries`, an em dash, or a lowercase bucket.

```
Commit 2 - Test (1 files)
Commit 5 - Runtime+Test (2 files)
Commit 13 - Artifact (3 files)
```

## Last Commit

The last commit block on the branch includes a `Branch:` footer with the branch name, to signal the end of the file and
aid in copy-pasting the whole file without missing the final commit's footer. No other commit block includes a `Branch:`
footer, to avoid confusion when copy-pasting individual blocks.

## Merge Protocol (read-before-write)

`branch-commit-msg` `capture` **reads the existing `<branch-name>.txt` before writing** and preserves the
developer's grouping, under the invariant **one path, one block**. `c-msg` does not merge: its pending file carries
only its own message forward, and only while HEAD is unchanged.

1. **Read first.** Load any existing `<branch-name>.txt` from the commit_messages directory. Parse it into commit blocks (split
   on `---`; the first block carries the header scaffold). If the file is absent, there is nothing to merge — write
   the new draft and stop.
2. **Keep the developer's groupings.** An existing block whose paths are all still in the capture keeps its file
   grouping. It also keeps its subject unless its content changed in a way the subject no longer describes; then
   update the message in place. Do not re-split files the developer combined.
3. **Place every captured path exactly once.** A captured path already listed in an existing block stays there. A
   captured path in no block joins the fresh block for its bucket (or the matching pair block). Then every block
   holding only Docs and Planning paths, existing or fresh, dissolves into exactly one Docs block and one Planning
   block (a rename's old side follows its new path); blocks mixing in any other bucket stay as they are. A merged
   block keeps its message only when it is one unchanged source block. A Planning block holding only plans and specs
   (paths under the configured `artifacts.planning_prefixes`) never commits alone: it joins the Docs block, else the artifact block
   (existing or fresh). Never list a path in a second block — an existing block's claim wins.
4. **Drop what left the capture.** Remove paths no longer in the merge-base diff (reverted or net-zero). A block left
   with zero paths is dropped. Only this step and the Docs/Planning merge in step 3 reduce the block count.
5. **Re-sort + renumber.** Order per `BUCKET_ORDER` in `harness_lib/branch_commits.py` (early registry →
   runtime+test, dependency-first → runtime → test → cicd → agent → other → docs → planning → artifact). Rewrite every header in the exact "Commit header" format above
   (renumbered, recounted) and move the `Branch:` footer to the last block.
6. **Verify.** Every quoted path is unique across blocks, and the union of the file lists equals the capture. Glob
   entries are allowed only in the artifact block.

`capture --fresh` treats the existing file as absent: steps 1, 2 and 4 and the existing-block clauses of step 3 are
skipped, every captured path goes to a fresh block, the Docs/Planning merge and planning fold in step 3 and the
step 5 re-sort still apply, and every message is empty.

Bare files (no `===` / `Commit N` scaffold) parse to zero blocks: `capture`
carries nothing from them, and the plugin's `scripts/txt_to_commit_dict.py` emits an empty `$commitDict`.

## Worked example

```
Branch: `<branch-name>`
Merge base: <sha>
Messaged-through: <head-sha>
Split: <split decision/rationale>

===

Commit 1 - Runtime+Test (4 files)
"src/billing/config.py",
"tests/billing/test_config.py",
"src/billing/helpers.py",
"tests/billing/test_helpers.py",

Fix(billing): add null-safety check to rate resolution

No guard existed for None values returned by the rate resolver, causing a TypeError on any run with an
unresolved rate config key.
  - config.py: add Optional handling in resolve_rate
  - test_config.py: cover None-input edge cases
---

Commit 2 - Docs (1 files)
".claude/skills/release-notes/SKILL.md",

Docs(skills): add release-notes skill

No skill existed for drafting release notes from merged PRs.
  - SKILL.md: new skill, PR grouping + changelog output
---

Commit 3 - Artifact (2 files)
"docs/PR_REVIEWS/41_billing.json",
"docs/PR_SUMMARIES/41_billing.md",

Chore: add PR 41 review and summary

Branch: `<branch-name>`
```

## Artifact glob patterns

The `artifact` commit (always last) may use glob patterns instead of literal paths for machine-generated file
families, since these are regenerated per-run and drift stale as literal lists. Each glob must match at least one
captured path, and no path may be matched by two blocks; `build` rejects a glob outside the artifact block, a glob
matching nothing, and an overlap. Example artifact block using globs:

```
Commit N - Artifact (3 files)
"docs/PR_REVIEWS/*.json",
"docs/PR_SUMMARIES/*.md",
"docs/_harness/*matrix.jsonl",

Chore: refresh PR review artifacts

Branch: `<branch-name>`
```

This exception is scoped to the artifact block only — an `Artifact` block, or artifact entries binned with plans
and specs (the configured planning prefixes), which heads as `Planning`. Every other block keeps the
literal-path-only rule below.

## PowerShell consumer pattern

Not part of the file output — the shape the file is designed to feed:

```powershell
$files = @(
    "src/billing/config.py",
    "tests/billing/test_config.py"
)
git add $files
```
