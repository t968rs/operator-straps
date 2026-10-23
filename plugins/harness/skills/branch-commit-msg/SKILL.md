---
name: branch-commit-msg
description: Use when asked to draft the full set of commit messages for everything pending on the current branch, as multiple Conventional Commits saved to the project's commit_messages directory (default docs/_commit_messages). Triggers on "break the branch into commits", "draft all commit messages", "commit breakdown", "branch-commit-msg".
argument-hint: "[REF] [--base REF] [--fresh] [--no-fetch]"
model: haiku
context: fork
agent: harness:messenger
---

# branch-commit-msg — Branch Commit Breakdown

`${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py` does the mechanics: capture, bucketing, pairing, split, order,
carry-forward of the existing TXT, layout, validation. The agent's job is the judgment: plan review and messages.

For one message about the current change (not the whole branch), use `harness:c-msg`.

**Rebuild assumption.** The developer mixed-resets the branch to its merge base and re-commits the TXT block by
block. So: every path differing from the merge base appears in exactly one block; each block stages that file's
final content; every block is a bisect point. Pushed history does not change the plan.

The project's `.claude/harness.json` supplies the base branch (`base_branch`, else `origin/HEAD`), the bucket path
rules (`commit_buckets`), the test registry (`tests.registry`) and the output directory
(`artifacts.commit_messages`, default `docs/_commit_messages`). Run every command below with the Bash tool from the
project root, exactly as written.

## Step 1 — Capture

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" capture --save $ARGUMENTS
```

`$ARGUMENTS` holds the developer's arguments (a bare `REF`, `--base REF`, `--fresh`, `--no-fetch`); pass them
through unchanged and add none, `--fresh` included. A bare `REF` and `--base REF` are the same (one ref as the
merge base); giving both with different refs exits 1. On any other flag, or a REF holding anything but letters,
digits and `/._-~^`, report it and stop. An argument the script rejects is reported, never removed or replaced.
Exit 1 prints `problem:` lines: report them and stop. Never choose or substitute a base yourself: the base
is the developer's ref, else the project's. Exit 0 prints `wrote <skeleton>`: the absolute path of the
skeleton in the commit_messages directory. Use that path as `<skeleton>` below.

| Flags                  | Skeleton and TXT                  | Plan                                                       |
|------------------------|-----------------------------------|------------------------------------------------------------|
| none                   | `<branch>.json` / `.txt`          | whole branch; existing TXT carried forward                 |
| `--fresh`              | `<branch>.json` / `.txt`          | whole branch, rebuilt from the rules; every message `""`   |
| `--base REF` (or bare `REF`) | `<branch>_<sha7>.json` / `.txt` | paths differing from REF; carries the `_<sha7>` TXT, else the branch TXT; the branch TXT is never overwritten |
| `--base REF --fresh` (or bare `REF --fresh`) | `<branch>_<sha7>.json` / `.txt` | paths differing from REF, rebuilt from the rules; the branch TXT is never overwritten |

`--no-fetch` skips the fetch of the project's base branch; a `--base` (or bare `REF`) capture never fetches, so it has no effect
there.

The skeleton holds `merge_base`, `split`, `captured` (status, path, old_path, bucket, added, deleted) and
`commits` — `{"1": [[paths], "message"], ...}` in landing order. Blocks from an existing TXT keep their grouping
and message; new blocks have `""`. Add `--fresh` to ignore the existing TXT: the plan is rebuilt from the rules
alone and every message is `""`. Use it only when the existing grouping is wrong (an over-split block, a stale
split), or when the developer asks for a replan.

The plan already applies the grouping rules: the test registry alone in block 1 (when the project configures one);
one block per source module (a source paired with its tests via the registry's `test_target_paths`, falling back
to name matching; `fix_*` work split from feature work); test-support files (conftest, helpers) with the first
module block holding a test in their directory, above it or below it; one Docs block (skills, agent definitions,
`.claude/**/*.md` other than `CLAUDE.md`, other prose); one Planning block (plans and specs under the configured
planning prefixes, every `CLAUDE.md`, every `DesignEvolution.json`), except that plans and specs with nothing else
in Planning join the Docs block, else the artifact block; all artifacts (PR reviews, PR summaries, matrix JSONL,
other generated files) in one final artifact block. Do not regroup to restate these.

## Step 2 — Review the plan

Module blocks are ordered by path, not by imports. Change `commits` only for these reasons, and append each change
(with its evidence) to `split`:

| Reason                                                                                     | Edit                                          |
|--------------------------------------------------------------------------------------------|-----------------------------------------------|
| A block needs something a later block adds: an import, a by-path load (`spec_from_file_location`), a conftest registration (Grep new module and file names in earlier blocks) | Move the dependent path later, or the dependency earlier |
| A PR review JSON for this branch (in the project's configured reviews directory) has verdict RESTRUCTURE and names separable concerns | Split groups along its `evidence` paths       |

Keys only set order: any integers work, and `build` renumbers 1..N. Prefer moving whole blocks over moving paths.
The test registry block stays in block 1. Never duplicate or drop a path — `build` rejects both.

**Never split a block the plan emitted as one.** A block the plan emitted (a module pair block, or a bucket block
such as Runtime, Test, Cicd, Agent, Other, Docs, Planning, Artifact) stays whole unless a table row above names
the reason; size, topic variety and tidiness are not reasons. Each extra block is a commit the developer must
stage by hand. `capture` keeps every non-doc block it finds in the existing TXT (Docs and Planning blocks
re-merge on each run), so a needless Agent, Other or Artifact split survives every later run. When the existing
TXT already holds such a non-doc split, rerun `capture --save --fresh` (Step 1, keeping the developer's `--base REF`
or bare `REF` when one was given: the rerun then replans the same `_<sha7>` files) instead of editing around it;
`--fresh` discards every carried message, so a split Docs or Planning block needs only a plain rerun of `capture`.

## Step 3 — Write messages

For each block whose message is `""` (or whose carried message no longer matches its diff), read what changed:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" diff "<skeleton>" --block <key>
```

The script applies line budgets: a path within budget prints in full, a larger one prints as a `summary`
section (key tallies for JSON, the head of the diff otherwise), and untracked files print as additions. Added
files need only their docstring and public names; a `summary` section is enough for a JSON file or a
generated report. Run `git diff <merge_base> -- <path>` for one path only when a message cannot be written from
its summary. `captured` entries carry `added` / `deleted` counts for judging size up front. BLOCK_BUDGET (300
lines) applies per block: once earlier paths use it, later paths print as summaries. Untracked files print as
additions through diff; the git diff fallback prints nothing for them, so do not use it for untracked paths.

Format: `${CLAUDE_PLUGIN_ROOT}/reference/commit_format.md` (REQUIRED — read it). Content, per file:

| Status   | Say                                                                  |
|----------|----------------------------------------------------------------------|
| Modified | What changed; why it had to, when behavior differed before           |
| Added    | What the file does and why it exists                                 |
| Deleted  | What replaces it (no why)                                            |
| Renamed  | `old → new`, plus any content change                                 |

No quality claims. `build` rejects filler: enhance, improve, streamline, robust, reliable/reliability,
maintainability, readability, seamless, comprehensive, leverage, various. Name the change instead.

Type by bucket: Runtime+Test → `Feature`/`Fix`; Runtime → `Refactor` (or `Feature`/`Fix` when the diff says so);
Test → `Test`; Cicd → `Build`; Docs and Planning → `Docs`; Agent/Other → `Chore` for config and housekeeping, `Feature`
for a new module or tool, `Refactor` for a behavior-preserving source change; Artifact → subject only (the script
adds the footer).

Store each message in the JSON as one string (`\n` newlines). No `Branch:` footer — the script adds it.

## Step 4 — Build

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" build "<skeleton>"
```

Exit 1: each `problem:` line names a commit and a defect. Fix the JSON and rerun. Exit 0 writes the TXT named in
the Step 1 table beside the skeleton (same stem, `.txt`) and prints the receipt. When that TXT already exists and its content changes, the old copy is kept as
`<name>.txt.bak` (one generation). Output the receipt verbatim — nothing else.

## Common Mistakes

| Mistake                                              | Fix                                                                  |
|------------------------------------------------------|----------------------------------------------------------------------|
| Writing or patching the TXT by hand                  | Edit the JSON; rerun `build`. The TXT (the Step 1 name) is script output. |
| Subject/bullets derived from filenames ("modify x")  | Read the diff; state the change.                                     |
| Removing a path from the JSON to silence coverage    | Put it in the block it belongs to.                                   |
| Leaving a test block before the module it imports    | Step 2 renumber; note it in `split`.                                 |
| Pasting the breakdown into chat                      | The receipt is the only chat output.                                 |

TXT layout reference (script-owned): `${CLAUDE_SKILL_DIR}/txt_format.md`. Bucket, pairing and split rules:
`${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/branch_commits.py` and `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/commit_grouping.py`;
the bucket path rules themselves are the project's `commit_buckets`.
