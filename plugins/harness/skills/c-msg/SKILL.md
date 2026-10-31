---
name: c-msg
description: Use when asked to draft a single commit message for the current pending or staged change. Triggers on "write a commit message", "draft commit msg", "commit message for this", "c-msg". For breaking an entire branch into multiple commits, use harness:branch-commit-msg instead.
argument-hint: "[-- <what to change in the saved message>]"
model: sonnet
context: fork
agent: harness:messenger
---

# c-msg — Single Commit Message

**Requested change for this run:** `$ARGUMENTS` (blank: none).
Blank means draft as usual. A requested change is the developer's ask to rewrite the saved message (Step 2).
The whole value is the change; a leading `--` is dropped, per
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`, so `-- <change>` and `<change>` are one invocation.

`${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py` does the mechanics: capture, diff, layout, validation,
save. The agent's job is one message, in two script calls: capture, then message with build.

The pending change is everything differing from HEAD: staged, unstaged and untracked. It lands in
`<branch>_pending.txt` in the project's configured commit_messages directory (default `docs/_commit_messages`)
with `Merge base:` set to HEAD. The branch ledger (`<branch>.txt`, owned by `branch-commit-msg`) is never read or
written. Files under the commit_messages directory are excluded from the pending change, so a change only in that
directory exits with "no pending change against HEAD".

Run every command below with the Bash tool from the project root, exactly as written.

## Step 1 — Capture and read

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" capture --pending --save --diff
```

Exit 1 prints `problem:` lines (for example, nothing pending): report them and stop. Exit 0 prints
`wrote <skeleton>` (the absolute path of `<branch>_pending.json`; use it as `<skeleton>` below), then
`message: empty`, `message: carried` or `message: canned`, the message when one is set, and the block's diff.

The skeleton has one block, and the block is the commit: do not add, drop or split paths. A carried message is a
draft saved against the same HEAD. A canned message is fixed in advance for a set of generated files (the TODO
files, the review artifacts; entries in `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/canned_messages.py`), and a canned
block prints no diff.

**The printed diff is the whole input:** no `git diff`, no Read of a changed file, and no second `diff` call except the one Step 2 names for a canned block with a requested change. Each
path prints under a `=== <path> [<mode>, +A -D] ===` header as `full` (a very long diff is clipped, ending in a
`... N more diff lines omitted (character budget)` line) or as a `summary`: a hunk outline (each hunk's `@@` line
with its change counts and first changed lines), a head plus the definitions past it, or JSON key tallies. A path
over its own read budget, or past the block's line budget, is a summary, and when the block runs over its
character budget full paths turn into summaries, documentation and artifacts first; a small file printed as a
summary is expected, not broken output. A summary is sized to be enough for a bullet; write that bullet from it.
A path that still does not fit prints its header followed by `[omitted: block output budget spent]`. The header
carries no status letter and names a rename by its new path only: for that path alone, read its `status` and
`old_path` from the skeleton's `captured` entry (the skeleton is not a changed file), and write its bullet from
those and the counts.

## Step 2 — Message and build

With a requested change, rewrite the message to make that change, even when it is carried or canned; keep the
rest of it as it stands (a canned block printed no diff: when the change needs one, run
`sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" diff "<skeleton>" --block 1`
once). Without one, keep a canned message as it stands, and
keep a carried message that still matches the diff: either way, set it unchanged with the command below, which
also builds. A carried message holding a double quote (a draft from before the double-quote rule) fails the
build even when it matches: set it with only those quotes changed to backticks or single quotes. Otherwise
write the message from the diff, in the format below.

Set the message with the script, the full text on stdin (real newlines, no `\n` escapes). No `Branch:` footer:
the script adds it. Never use Edit or Write on the skeleton or the TXT.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" message "<skeleton>" --block 1 --build <<'MSG'
<subject, blank line, why, then the bullets>
MSG
```

Exit 0 writes `<branch>_pending.txt` beside the skeleton and prints the receipt: output it verbatim, nothing
else. Exit 1 keeps the message in the skeleton and prints `problem:` lines: message problems mean fix the text
and run the same command again; coverage or branch problems mean rerun Step 1.

## Format

The full rules live in `${CLAUDE_PLUGIN_ROOT}/reference/commit_format.md`; this card is what a single commit
needs, and `build` enforces the mechanical rules (the double-quote rule, filler words, vendor names, subject
shape). Open the reference only when `build` names a rule this card does not state.

```
<type>(<scope>): <subject>

What changed, and why it had to when behavior differed before: 1 sentence (never more than 3).
  - filename: what changed in this file
  - filename: what changed in this file
```

- **Type:** `Feature` (new or extended behavior), `Fix` (corrects wrong behavior), `Refactor` (behavior kept),
  `Test` (tests only), `Build` (CI, build, test infrastructure), `Docs` (documentation), `Chore` (agent config,
  artifacts, housekeeping). Runtime plus its tests is `Feature` or `Fix` by the diff; unclear means `Feature`,
  with the ambiguity noted in the body. `Plan` is not a type: plan documents are `Docs(plans)` or
  `Chore(plans)`.
- **Scope:** the shared parent module or directory (`billing`, `io`); omit it when the files span unrelated
  modules.
- **Subject:** lowercase after the colon, imperative or noun phrase, about 72 characters at most; no PR or issue
  numbers (a `Refs:` body line takes them) and no class names (bullets take them). An em dash `—` may append a
  secondary qualifier (`coordination gate updates — cleanup pass`), inside the 72 characters.
- **Body:** facts, not qualities: name the concrete change (`return [] for an empty file`), never its virtue. A
  term takes backticks or single quotes, never a double quote. No sign-offs, no co-author lines, no tool or
  vendor names. An optional last line after the bullets may state a status or result (`99/99 PASS`).
- **Bullets** (two-space indent, `filename: change`), worded by the file's status letter: `A` says what the new
  file does and why it exists; `M` says what changed, and why when behavior differed; `D` is a removal naming
  its replacement (`old.py: remove; replaced by io/writer.py`); `R###` is a relocate written `old → new`.
- Generated artifacts or a trivial chore: subject only.

## Common Mistakes

| Mistake                                                    | Fix                                                        |
|------------------------------------------------------------|------------------------------------------------------------|
| Running `git diff`, or reading a changed file, after Step 1 | The printed diff is the input; a summary is enough.       |
| Reading `commit_format.md` before drafting                 | The card above covers a single commit.                     |
| Writing the TXT by hand (Edit, or a heredoc or `>` into it) | `message --build`; the TXT is script output.              |
| Setting the message with Edit on the JSON                  | `message "<skeleton>" --block 1 --build`.                  |
| Subject or bullets derived from filenames                  | State the change the diff shows.                           |
| Editing `<branch>.txt`                                     | That is the branch ledger; c-msg writes `_pending.txt`.    |
| Pasting the message into chat                              | The receipt is the only chat output.                       |
