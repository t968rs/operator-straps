---
name: c-msg
description: Use when asked to draft a single commit message for the current pending or staged change. Triggers on "write a commit message", "draft commit msg", "commit message for this", "c-msg". For breaking an entire branch into multiple commits, use harness:branch-commit-msg instead.
model: haiku
context: fork
agent: harness:messenger
---

# c-msg — Single Commit Message

`${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py` does the mechanics: capture, layout, validation, save. The
agent's job is one message.

The pending change is everything differing from HEAD: staged, unstaged and untracked. It lands in
`<branch>_pending.txt` in the project's configured commit_messages directory (default `docs/_commit_messages`)
with `Merge base:` set to HEAD. The branch ledger (`<branch>.txt`, owned by `branch-commit-msg`) is never read or
written. Files under the commit_messages directory are excluded from the pending change, so a change only in that
directory exits with "no pending change against HEAD".

Run every command below with the Bash tool from the project root, exactly as written.

## Step 1 — Capture

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" capture --pending --save
```

Exit 1 prints `problem:` lines (for example, nothing pending): report them and stop. Exit 0 prints
`wrote <skeleton>`: the absolute path of `<branch>_pending.json`. Use that path as `<skeleton>` below.

The skeleton has one block: `commits: {"1": [[paths], "message"]}`. The message is `""` unless a draft against the
same HEAD exists or the change is a canned set: only generated files whose message is fixed in advance (the TODO
files, the review artifacts; entries in `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/canned_messages.py`), for which
capture fills the canned message. Leave the `"pending": true` key in place; build uses it to write
`<branch>_pending.txt` and keep the branch ledger untouched.

Do not add, drop or split paths. The block is the commit.

## Step 2 — Write the message

Skip when the carried message still matches the diff, and keep a canned message as it stands: go to Step 3.
Otherwise read what changed:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" diff "<skeleton>" --block 1
```

Read the printed block. The block budget is the script's limit; a path over budget prints as a `summary` section.

Format: `${CLAUDE_PLUGIN_ROOT}/reference/commit_format.md` (REQUIRED — read it). Status-aware bullets, scope
rules, commit types and the bucket mapping all live there; `build` rejects filler words and bad subjects.

Store the message in the JSON as one string (`\n` newlines). No `Branch:` footer — the script adds it.

## Step 3 — Build

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" build "<skeleton>"
```

Exit 1: coverage or branch problems mean rerun Step 1 (capture); message problems mean edit the JSON message and
rerun build. Exit 0 writes `<branch>_pending.txt` beside the skeleton and prints the receipt. Output the receipt
verbatim — nothing else.

## Common Mistakes

| Mistake                                         | Fix                                                         |
|-------------------------------------------------|-------------------------------------------------------------|
| Writing the TXT by hand (Edit, heredoc, `>`)    | Edit the JSON; rerun `build`. The TXT is script output.     |
| `git diff` without `HEAD`, or `--cached` only   | `capture --pending` already has staged, unstaged, untracked |
| Subject/bullets derived from filenames          | Read the diff; state the change.                            |
| Editing `<branch>.txt`                          | That is the branch ledger; c-msg writes `_pending.txt`.     |
| Pasting the message into chat                   | The receipt is the only chat output.                        |
