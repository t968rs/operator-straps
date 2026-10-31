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

One file lands in the project's commit_messages directory (`artifacts.commit_messages`, default
`docs/_commit_messages`): `PR<N>_merge.txt`, script output in column 0, ready to paste into the merge UI or
`gh pr merge`. Never write it by hand; the guard hook denies it. No working document stands before it: capture
prints, and the message travels to `build` on stdin.

Run every command below with the Bash tool from the project root, exactly as written.

## Step 1 — Capture

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" capture <PR number>
```

Exit 1 prints a `problem:` line (PR not open, `gh` failure, invalid config): report it and stop. Exit 0 prints
the PR's Facts, Changed files, Commits and Branch commit subjects, then the message skeleton in a `text` fence
under `## Message`. Nothing is written to disk. The printed output is the whole input: no `git diff`, no Read of
a changed file.

Capture fills what is mechanical in the skeleton: the subject (`Merge PR #N — <title>`, verbatim),
`Branch lineage:`, the `Review artifacts:` and `Includes N review fixes (...)` lines when a review JSON exists,
and, for a PR made only of generated files whose message is fixed in advance (entries in
`${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/canned_messages.py`), the canned message as the prose. Keep those lines
as they stand.

## Step 2 — Write the message and build

Format: `${CLAUDE_SKILL_DIR}/message_format.md` (REQUIRED — read it). Start from the skeleton's lines:

1. Replace the `<Prose: ...>` placeholder with the what-and-why prose. Skip this when a canned message is
   already there: keep it as it stands.
2. Replace the `  - <file>: <key change>` placeholder with 4-7 bullets drawn from Changed files.
3. Add the optional `Also lands` paragraph and `Companion docs:` line only when the PR has that scope. Place
   them as `message_format.md` orders them.

Pass the full message, the skeleton's script-filled lines included and without the fence, to `build` on stdin
(real newlines, no `\n` escapes):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" build <PR number> <<'MSG'
<the message>
MSG
```

Exit 1: each `problem:` line names a defect in the message (placeholder left, indented line, filler word, commit
SHA, vendor name, subject changed, empty stdin). Fix the text and run the same command again. Exit 0 writes
`PR<N>_merge.txt`, keeps a replaced copy as `PR<N>_merge.txt.bak`, and prints the receipt. Output the receipt
verbatim — nothing else.

## Common Mistakes

| Mistake                                          | Fix                                                              |
|--------------------------------------------------|------------------------------------------------------------------|
| Writing or patching the TXT by hand              | Rerun `build` with the changed message on stdin.                 |
| Saving the draft to a file first                 | The heredoc to `build` is the only route; no file is needed.     |
| Paraphrasing the title in the subject            | The subject is script-filled; build rejects any change.          |
| Dropping or rewording lineage or review lines    | Keep the skeleton's script-filled lines as printed.              |
| Pasting the message into chat                    | The receipt is the only chat output.                             |
| Passing the fence markers to `build`             | Build rejects a fence line; pass the message lines only.         |
