---
name: merge-commit-msg
description: Use when asked to draft a merge commit message for a PR, prepare a PR squash-merge subject and body, or compose the commit text the developer will paste into the merge UI. Triggers on "merge commit msg", "merge message for PR N", "merge-commit-msg".
argument-hint: "<PR number> [-- <guidance>]"
model: sonnet
context: fork
agent: harness:messenger
---

# merge-commit-msg — PR Merge Message

**Arguments for this run:** `$ARGUMENTS` (the PR number, then optionally `--` and guidance).
They are the developer's input. Split them at the first standalone `--` token, per
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the part before it is `<PR number>` below and goes on
the commands unchanged; the part after it is the guidance for the prose (emphasis, items to name), which never
reaches a command. A blank or non-numeric PR number: report it and stop.

`${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py` does the mechanics: the `gh` calls, the review-fix counts, the
canned message, the lineage, the layout checks and the TXT. The agent's job is the judgment: the prose and the
file bullets. Mechanical: no review, no verdict on whether the PR should merge.

Two files land in the project's commit_messages directory (`artifacts.commit_messages`, default
`docs/_commit_messages`):

- `PR<N>_merge.md` — the working document: the PR's facts, then one `text` fence holding the message.
- `PR<N>_merge.txt` — script output: the fence's text, column 0, ready to paste into the merge UI or
  `gh pr merge`. Never write it by hand; the guard hook denies it.

Run every command below with the Bash tool from the project root, exactly as written.

## Step 1 — Capture

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" capture <PR number>
```

Exit 1 prints a `problem:` line (PR not open, `gh` failure, invalid config): report it and stop. Exit 0 prints
`wrote <md>`: the absolute path of the MD. Use it as `<md>` below.

Capture fills what is mechanical: the subject (`Merge PR #N — <title>`, verbatim), `Branch lineage:`, the
`Review artifacts:` and `Includes N review fixes (...)` lines when a review JSON exists, and, for a PR made only
of generated files whose message is fixed in advance (entries in
`${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/canned_messages.py`), the canned message as the prose. Leave those lines
as they stand.

## Step 2 — Write the message

Read `<md>`: Facts, Changed files, Commits, Branch commit subjects. Format:
`${CLAUDE_SKILL_DIR}/message_format.md` (REQUIRED — read it).

Edit the `text` fence under `## Message`, and only that fence:

1. Replace the `<Prose: ...>` placeholder with the what-and-why prose. Skip this when a canned message is
   already there: keep it as it stands.
2. Replace the `  - <file>: <key change>` placeholder with 4-7 bullets drawn from Changed files.
3. Add the optional `Also lands` paragraph and `Companion docs:` line only when the PR has that scope. Place
   them as `message_format.md` orders them.

Never edit the Facts sections.

## Step 3 — Build

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" build <PR number>
```

Exit 1: each `problem:` line names a defect in the fence (placeholder left, indented line, filler word, commit
SHA, vendor name, subject changed). Fix the fence and rerun. Exit 0 writes `PR<N>_merge.txt` beside the MD, keeps
a replaced copy as `PR<N>_merge.txt.bak`, and prints the receipt. Output the receipt verbatim — nothing else.

## Common Mistakes

| Mistake                                          | Fix                                                              |
|--------------------------------------------------|------------------------------------------------------------------|
| Writing or patching the TXT by hand              | Edit the fence in the MD; rerun `build`.                         |
| Paraphrasing the title in the subject            | The subject is script-filled; build rejects any change.          |
| Editing Facts, lineage or review lines           | Rerun `capture` to refresh them; edit only the prose and bullets. |
| Pasting the message into chat                    | The receipt is the only chat output.                             |
| Rerunning `capture` after filling the fence      | It overwrites the MD; run `build` instead.                       |
