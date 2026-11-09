---
name: merge-commit-msg
description: Use when asked to draft a merge commit message for a PR, prepare a PR squash-merge commit (pass squash or --squash after the PR number; without it the run drafts the merge form), or compose the commit text the developer will paste into the merge UI. Triggers on "merge commit msg", "merge message for PR N", "squash message", "squash-merge commit for PR N", "merge-commit-msg".
argument-hint: "<PR number> [squash | --squash | -s] [--auto-title] [-- <guidance>]"
model: sonnet
context: fork
agent: harness:messenger
---

# merge-commit-msg — PR Merge Message

**Arguments for this run:** `$ARGUMENTS` (the PR number, an optional mode token, then optionally `--` and
guidance). They are the developer's input. Split them at the first standalone `--` token, per
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before `--` comes the PR number, then an optional mode
token: `--squash`, `-s` or a bare `squash` selects squash mode, and an optional `--auto-title`. On every command below, `<PR number>` stands
for the number, followed by ` --squash` in squash mode; all three forms go on the commands as `--squash`.
`--auto-title` goes on `capture` only. The
part after `--` is the guidance for the prose (emphasis, items to name), which never reaches a command; a
`squash` after `--` is guidance, not a mode, and so is an `--auto-title` after it. A blank or non-numeric PR number, or anything before `--` beyond
the number, at most one mode token and `--auto-title`: report it as a `problem:` line and stop.

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
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" capture <PR number> [--auto-title]
```

Exit 1 prints a `problem:` line (PR not open, unusable PR title (in squash mode, also one that is not a
`Word(scope): summary` subject: a word, an optional scope, a colon and a non-empty summary; the developer
retitles with `gh pr edit <N> --title` or reruns with `--auto-title`), `gh` failure, invalid config): report it and stop. Exit 0 prints the PR's Facts, Changed files, Diff, Commits
and Branch commit subjects, then the message skeleton in a `text` fence under `## Message`. Nothing is written
to disk. The printed output, diffs included, is the whole input: capture pulls the diffs itself (one section
per file, size-capped, a file past the cap keeps its header), so the agent runs no `git diff` or `gh pr diff`
and Reads no changed file.

The `- Mode: merge` or `- Mode: squash` fact names the mode capture ran in (squash mode also heads the output
`# PR #N squash message`); build runs in that mode. Capture fills what is mechanical in the skeleton: the
subject per mode, title verbatim (`Merge PR #N -- <title>` with an ASCII separator, or `<title> (#N)` in
squash mode), `Branch lineage:`, the `Review artifacts:` and `Includes N review fixes (...)` lines when a
review JSON exists, and, for a PR made only of generated files whose message is fixed in advance (entries in
`${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/canned_messages.py`), the canned message as the prose. Keep those lines
as they stand.

**`--auto-title`** is the developer's consent to rename the PR. Use it only when the invocation carries it.
With the flag, a title the mode refuses no longer stops capture. The Facts gain a `- Title problem:` line, and
line 1 of the skeleton is a `<Subject: ...>` placeholder. Write a new title from the Facts, Commits and Diff.
Its prefix is the `Type(scope):` the branch's commit subjects use most, or, when none has one, the type that
fits the change (`Feature`, `Fix`, `Docs`), and it names what the PR changes, in one ASCII line. Then run:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" retitle <PR number> --title "<new title>"
```

`retitle` sets the PR title with `gh pr edit` and prints `Retitled PR #N: '<old>' -> '<new>'`, then a
`Subject:` line. Put that subject, without `Subject: `, on line 1 of the message. It exits 1 and changes
nothing when the new title is not a `Word(scope): summary` subject (pick another and rerun), when the PR title
already heads the subject (rerun capture without the flag), or when the PR is not open or `gh` fails (report
it and stop). A title
the mode accepts is never replaced: with such a title, `--auto-title` changes nothing. Report the `Retitled`
line with the receipt.

## Step 2 — Write the message and build

Format: `${CLAUDE_SKILL_DIR}/message_format.md` (REQUIRED — read it). Start from the skeleton's lines:

1. Replace the `<Prose: ...>` placeholder with the what-and-why prose. Skip this when a canned message is
   already there: keep it as it stands.
2. Replace the `  - <file>: <key change>` placeholder with 4-7 bullets drawn from Changed files and the printed Diff.
3. Add the optional `Also lands` paragraph and `Companion docs:` line only when the PR has that scope. Place
   them as `message_format.md` orders them.

Pass the full message, the skeleton's script-filled lines included and without the fence, to `build` on stdin
(real newlines, no `\n` escapes), in the same mode as capture (`<PR number>` carries ` --squash` in squash
mode):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_commit_msg.py" build <PR number> <<'MSG'
<the message>
MSG
```

Exit 1 prints `problem:` lines. A line about the PR state, title, `gh` or the config (PR not open, a PR title
with non-ASCII characters or one that reads as the branch name, a squash-mode title that is not
a `Word(scope): summary` subject, `gh pr view failed`, invalid config): report it and stop; editing the text cannot fix it,
and the developer retitles the PR or reruns the skill with `--auto-title`, which starts over at capture
(`build` does not take the flag). An unknown mode token is an argument error: report it and stop. Any other
`problem:` line names a defect in the message (placeholder left, indented line, filler word, commit SHA,
vendor name, subject changed, empty stdin): fix the text and run the same command again. A merge subject under
`--squash` gets a problem line that names the flag and prints the squash subject; when the developer asked for
squash mode, replace line 1 with that subject, otherwise drop the flag. Exit 0 writes `PR<N>_merge.txt` (the same name in both modes), keeps a
replaced copy as `PR<N>_merge.txt.bak`, and prints the receipt (`squash message for PR #N` in squash mode).
Output the receipt verbatim — nothing else, except the `Retitled` line of an `--auto-title` run, above it.

## Changing a saved message

Only on the developer's ask. Read `PR<N>_merge.txt` in the commit_messages directory, then rerun `build` with that
text changed as asked, on stdin: pass the whole text to the same heredoc as Step 2 (build keeps the replaced copy
as `.txt.bak`). A rebuild needs no flag: without `--squash`, build takes the mode from the saved subject. Do
not rerun capture: it would rewrite the prose from the skeleton.

## Common Mistakes

| Mistake                                          | Fix                                                              |
|--------------------------------------------------|------------------------------------------------------------------|
| Writing or patching the TXT by hand              | Rerun `build` with `PR<N>_merge.txt`, changed as asked, on stdin. |
| Saving the draft to a file first                 | The heredoc to `build` is the only route; no file is needed.     |
| Paraphrasing the title in the subject            | The subject is script-filled; build rejects any change.          |
| Dropping or rewording lineage or review lines    | Keep the skeleton's script-filled lines as printed.              |
| Pasting the message into chat                    | The receipt is the only chat output.                             |
| Passing the fence markers to `build`             | Build rejects a fence line; pass the message lines only.         |
| Passing `--squash` to build for a merge skeleton | Run capture with `--squash` too, or drop the flag from build.    |
| Running `retitle` or `gh pr edit` unasked        | Only with `--auto-title` in the invocation, and only `retitle`.  |
