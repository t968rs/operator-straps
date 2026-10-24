---
name: merge-commit-msg
description: Use when asked to draft a merge commit message for a PR, prepare a PR squash-merge subject and body, or compose the commit text the developer will paste into the merge UI
model: haiku
effort: low
---

# Merge Commit Message

Compose a merge commit message for a GitHub PR. Mechanical — no review, no judgment about whether the PR should merge.
Only produces text the developer pastes.

## When to Use

- Asked to "draft a merge commit msg for PR #N"
- Asked to "prep the merge text" / "write the merge message" / "give me the commit body"
- Preparing for a squash-merge or merge commit and need the canonical text

**Don't use** for ordinary commit messages — that's a different shape. This skill is for the MERGE point of a PR, where
the message summarizes the whole branch.

## Data Gathering

Three `gh` calls. Replace `NNN`. Use stdout verbatim — never paraphrase.

```bash
# 1. PR shape
gh pr view NNN --json number,title,headRefName,baseRefName,additions,deletions,changedFiles,body

# 2. Commit headlines (--paginate: one page stops at 30 commits)
gh api --paginate repos/{owner}/{repo}/pulls/NNN/commits --jq '.[].commit.message | split("\n")[0]'

# 3. Files changed
gh pr diff NNN --name-only
```

Derive `{owner}/{repo}` from `gh repo view --json nameWithOwner -q .nameWithOwner`.

A PR made only of generated files whose message is fixed in advance (the TODO files, the review artifacts) has a
canned message. Ask for it with the PR's file list:

```bash
gh pr diff NNN --name-only | sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" canned
```

A printed message becomes the prose paragraph verbatim, its `Type(scope):` prefix included (no stripping, no
recasing); the subject line and the bullets stay as below. `canned: none` means draft the prose as usual.

## Output Shape

Save the message to a file first; chat output is a two-line receipt. This
sidesteps the Claude Code terminal renderer's fenced-block indent artifact,
which copies a visible margin into the clipboard and breaks direct paste
into `git commit -m` or the GitHub merge UI.

### File destination

```
<commit_messages>/PR<NNN>_merge.txt
```

`<commit_messages>` is the project's configured commit_messages directory:
`artifacts.commit_messages` in `.claude/harness.json` when set, else
`docs/_commit_messages`. Create the directory if it does not exist. Same
directory as `harness:c-msg` output — keeps "all things you might paste"
in one place.

### File format

Every line at column 0. No leading whitespace, no markdown fence, no
backtick wrapper. Select-all in the file = pasteable commit body.

```
Merge PR #NNN — <PR title verbatim>

<"What + why" prose. Lead with the action; explain the underlying problem.
Quote no commit SHAs in the prose — the merge UI records them
automatically. Wrap prose lines at ~110 columns; break at sentence boundaries when a paragraph exceeds one
line. Multi-sentence content should be split into 2-3 short paragraphs
rather than one long block.>

  - filename.py: key change
  - filename.py: key change
  [4-7 representative entries from the changed-files list; omit exhaustive
  enumeration — curate to the changes that explain the PR story]

Branch lineage: `<base>` -> `<parent if any>` -> `<head>`

<Optional: "Also lands" paragraph — secondary scope items that travelled
with the primary fix. Keep only if the PR actually has secondary scope;
do not invent. If the paragraph contains a long parenthetical list, break
the parenthetical across multiple lines at sub-item boundaries (commas).>

<Optional: "Companion docs:" label followed by comma-separated repo-relative
paths with parenthetical annotations — include only when the PR diff
contains companion documentation artifacts. Never use URLs.

Example: Companion docs: docs/PLANS/0008_ActionPlan.json (execution status),
docs/RESEARCH/caching/invalidation.md (technical rationale).>

Review artifacts: <{reviews}/{NNNN}_*.json path if it exists>.
<Count line only — no verdict prefix. If resolved issues exist, use:
"Includes N review fixes (Critical: N, Important: N, Minor: N)." (note
capitalized "Includes" — this is its own sentence, not a continuation).
If no review JSON exists, omit both lines entirely.>
```

### Section ordering (mandatory)

The sections appear in this fixed order:

1. Subject line (`Merge PR #NNN — <title>`)
2. Prose paragraph(s) — wrapped, possibly split into 2-3 short paragraphs
3. Bullet list of representative file changes
4. `Branch lineage: ...` (with backticked branch names)
5. Optional `Also lands` paragraph (line-broken parentheticals)
6. Optional `Companion docs:` line
7. Optional `Review artifacts: ...` path line (only when review JSON exists)
8. Optional `Includes N review fixes (...)` count line (only when review JSON exists)

Lineage anchors the bullet list above it; "Also lands" is supplementary
context adjacent to the review-artifacts trailer.

### Save-before-chat ordering

The `Write` call that creates `PR<NNN>_merge.txt` MUST complete before any
chat output describing the message. Drafting the message in chat first and
then "saving from chat" inverts the contract: the file is the deliverable,
the chat output is the receipt. Same discipline as `harness:branch-commit-msg` Step 4 (build, then receipt).

### Chat output

After saving, emit ONLY the following — nothing before it, nothing after it:

```
Saved: <commit_messages>/PR<NNN>_merge.txt — merge message for PR #NNN
Subject: Merge PR #NNN — <PR title verbatim>
```

Subject is echoed for at-a-glance verification of the title transcription.
Never paste the body into chat — that's the renderer-margin failure mode.

## Rules

- **Verbatim transcription** of the PR title; no paraphrasing.
- **No commit SHAs in the prose.** Merge UIs record SHAs; pasting them is noise that ages badly.
- **No emojis, no marketing voice, no "Achievements" headers.**
- **No invented content.** If the PR has only one logical scope, drop the "also lands" paragraph; if no companion docs,
  drop that paragraph.
- **Branch lineage** comes from `gh pr view NNN --json body` (search for `lineage:` or arrow notation `-->`) or from the
  conversation context if explicitly stated. If unknown, write ``Branch lineage: `<base>` -> `<head>` `` (skip the parent).
- **Review artifacts line** appears only if a `{reviews}/{NNNN}_*.json` exists, where `{reviews}` is the project's
  configured reviews directory (`artifacts.reviews` in `.claude/harness.json`, default `docs/PR_REVIEWS`). No verdict prefix — the verdict
  belongs in the PR_REVIEW JSON, not duplicated in commit history. If resolved issues exist, append on the next line:
  `Includes N review fixes (Critical: N, Important: N, Minor: N).` (capitalized, sentence-final period). Do not cite
  individual review issue IDs (C1, I2, M3) anywhere.
- **Line wrapping**: wrap prose lines at ~110 columns. When a paragraph would exceed one wrapped line,
  prefer splitting it into 2-3 short paragraphs at sentence boundaries. For parenthetical lists in the "Also lands"
  paragraph, break the parenthetical across multiple lines at comma boundaries between sub-items.
- **Branch lineage placement**: appears AFTER the file-change bullet list and BEFORE the optional "Also lands"
  paragraph. Wrap each branch name in backticks (`` `main` -> `1007-feature-...` ``).
- **Bullets required.** Include a `  - filename: key change` bullet list after the prose paragraph, drawn from
  `gh pr diff NNN --name-only`. Show 4-7 representative files that tell the PR story; do not enumerate every changed
  file.
- **Plan step IDs must match the plan.** When referencing plan steps, use the exact ID from the plan document (e.g.,
  `FCC-1`), never ordinal approximations like "Phase 5" or "Step 3".
- **No forward PR references by number.** Write "next PR", "follow-up PR", or "subsequent change" — never "PR 3" or "PR
  #NNN" for a PR that doesn't exist yet.
- **No brand or tool names in narrative text.** Never write "Copilot", "Claude", or any specific tool/platform name in
  prose lines or non-verbatim bullet descriptions. Use generic terms: "review", "agent", "skill", "analysis". This ban
  does not apply inside required verbatim strings (for example file paths or the verbatim PR title).
- **No sign-offs or authoring credits.** Omit `Co-authored-by:`, `Signed-off-by:`, and any author-attribution lines.
- **Length budget**: 10-20 lines body. Bias toward shorter.

## Pre-flight

- [ ] PR is OPEN and has at least one commit (`gh pr view NNN --json state,commits`)
- [ ] Working directory has `gh` authenticated
- [ ] If the PR has a review JSON, read its `verdict` field once before composing

## Anti-patterns

| Anti-pattern                                                                         | Why wrong                                                                                                                                         |
|--------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| Listing every commit by SHA + headline                                               | Merge UI already records that                                                                                                                     |
| "🎉 Closes #NNN" emoji or hype                                                       | Style ban                                                                                                                                         |
| Per-fix subsections                                                                  | Merge messages summarize, they don't enumerate                                                                                                    |
| Inventing follow-up tracking ("see Issue #XXX") if none exists                       | No fabrication                                                                                                                                    |
| Paraphrasing the PR title to sound prettier                                          | Verbatim only                                                                                                                                     |
| Omitting branch lineage when it's known                                              | Bisect tool needs it                                                                                                                              |
| Putting branch lineage AFTER "Also lands" or at the very bottom                      | Lineage anchors the file-change bullets above it — burying it separates structure from content                                                    |
| Omitting backticks around branch names in lineage                                    | Unbackticked names blur into prose; backticks make the lineage scannable                                                                          |
| Prefixing the review-artifacts count with a verdict ("READY TO MERGE — includes...") | Verdict belongs in the PR_REVIEW JSON; duplicating it in commit history is noise. Count line stands alone, capitalized "Includes"                 |
| One long unwrapped prose paragraph                                                   | Wrap at ~110 cols; split multi-sentence content into 2-3 short paragraphs at sentence boundaries                                                  |
| Citing specific review issue IDs (C1, I2, M3)                                        | Internal tracking codes clutter permanent history; use count format: "includes N review fixes (Critical: N, Important: N)"                        |
| Referencing a future PR by number ("PR 3", "PR #1025")                               | PR numbers are assigned at creation time; hard-coding creates fragile forward-pointing links — write "next PR" or "follow-up PR" instead          |
| Using generic ordinals instead of plan IDs ("Phase 5" when plan says "FCC-5")        | Ordinals detach the message from traceable plan artifacts — copy the exact plan step ID                                                           |
| Including brand or tool names in narrative prose (Copilot, Claude)                   | Brand names in commit history are noisy and date poorly — use "review", "agent", "analysis"; verbatim strings (file paths/title text) are allowed |
| Omitting the bullet list                                                             | Bullets are required — they give reviewers a scannable file-change summary that aligns with the shared `commit_format.md` output                  |
| Sign-offs or authoring credits                                                       | git tracks authorship natively; `Co-authored-by:` and `Signed-off-by:` are noise                                                                  |
| Wrapping the file body in a fenced code block inside `Write`                         | Fences become literal characters in the saved file                                                                                                |
| Emitting the message body in chat alongside the save                                 | Defeats the renderer-margin workaround — clipboard inherits the indent artifact                                                                   |
| Skipping the save and falling back to chat-only                                      | The two-line chat receipt is the contract                                                                                                         |

## Worked Example (PR #887)

File written to `docs/_commit_messages/PR887_merge.txt` (default directory; column-0, no fences):

```
Merge PR #887 — [BUG] Worker pool crash on spawn

Diagnoses and fixes a BrokenProcessPool failure in the export ProcessPoolExecutor.
Spawned children under pythonw.exe attach to invalid stdio handles; a defensive
_silence_invalid_streams() helper at init_worker entry prevents the OSError cascade.

  - workers/export.py: add _silence_invalid_streams() worker guard
  - test_export_full_run.py: full-run integration test
  - worker_utils.py: CPU-scaling worker-count helper
  - probe_stdio.py: diagnostic probe used to isolate root cause

Branch lineage: `main` -> `250-TEST-export_full_run` -> `850-BUG-worker_spawn`

Also lands diagnostic probe infrastructure and a CPU-scaling worker-count helper uncovered
during the investigation.

Companion docs: docs/RESEARCH/workers/spawn_debug.md (diagnostic chain),
docs/RESEARCH/workers/init_worker_snapshot.md (research).

Review artifacts: docs/PR_REVIEWS/0887_BUG_worker_spawn.json.
Includes 24 review fixes (Critical: 1, Important: 11, Minor: 12).
```

Chat output (the only thing the user sees in conversation):

```
Saved: docs/_commit_messages/PR887_merge.txt — merge message for PR #887
Subject: Merge PR #887 — [BUG] Worker pool crash on spawn
```
