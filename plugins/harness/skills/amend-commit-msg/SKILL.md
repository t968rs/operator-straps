---
name: amend-commit-msg
description: Use when asked to amend, edit or regroup the commit messages already drafted for the current branch, such as after review fixes changed what a block says, or to move files and their descriptions between commit blocks. Triggers on "amend the commit messages", "edit the commit breakdown", "regroup the commits", "amend-commit-msg". Needs an existing branch-commit-msg TXT.
argument-hint: "[REF] [--base REF] [--no-fetch] -- <what to change>"
---

# amend-commit-msg: amend a drafted commit breakdown

`harness:branch-commit-msg` drafts the breakdown once and runs in a fork, with no view of this conversation.
This skill amends that draft in the main session, which holds what changed since: review fixes, a decision, a
file moved on purpose. `${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py` does the mechanics (capture,
regrouping, validation); this session does the judgment. Grouping and rebuild rules are those of
`${CLAUDE_PLUGIN_ROOT}/skills/branch-commit-msg/SKILL.md`: every path in exactly one block, each block a
bisect point.

Arguments: `$ARGUMENTS`

Split them at the first ` -- `. Before it: the capture arguments (a bare `REF` or `--base REF`, `--no-fetch`),
passed through unchanged and with none added; they name the TXT to amend, exactly as they named it for
`harness:branch-commit-msg`. After it: the change the developer wants. With no change text, print
`usage: /harness:amend-commit-msg [REF] [--base REF] [--no-fetch] -- <what to change>` and stop. `--fresh` and
`--pending` are never passed: `--fresh` discards the messages being kept, and the script rejects both.

One command per Bash call, run from the project root:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py" <subcommand> ...
```

`SCRIPT` below stands for everything before `<subcommand>`.

## Step 1: Capture

```bash
SCRIPT capture --save --edit <capture arguments>
```

Exit 1 prints `problem:` lines: report them and stop. `no TXT to amend: <path>` means no draft exists for those
arguments: tell the developer to run `harness:branch-commit-msg` first, with the same `REF` or `--base`. Exit 0
prints `wrote <skeleton>`; that absolute path is `<skeleton>` below. The skeleton carries the TXT's groupings
and messages. A path new since the draft joins the block of its bucket, with an empty message when that block
is new.

## Step 2: Plan the change

From the change text and this conversation, list the blocks to rewrite and the paths to move. Touch only what
the change names and what it forces: a block whose paths changed, a bullet left stale, an empty message. Every
other message stays byte for byte. For each block to rewrite, read what is in it now:

```bash
SCRIPT diff "<skeleton>" --block <key>
```

The conversation says why something changed; the diff says what. State only what the diff shows.

## Step 3: Regroup (only when the change asks for it)

```bash
SCRIPT move "<skeleton>" --path <entry> [--path <entry> ...] --to <N|new>
```

Each `--path` is an entry of a block exactly as the skeleton lists it; a rename's old side follows its new
path. The bullet naming the path moves with it, after the target's last bullet. `--to new` makes a block
right after the lowest source block, with an empty message. An emptied block is dropped and the blocks are
renumbered 1..N, so read the skeleton again before the next move. Never edit the path lists by hand: the
script keeps each bullet with its path, and `build` rejects a bullet whose file is not in its block.

- `note: unplaced bullet for block N: ...`: the target has no message yet; the line belongs in the one written in
  Step 4.
- `note: bullet for <file> is ambiguous ...`: two paths of the block share that name; move the bullet by hand.
- Keep the test registry in block 1 when the project configures one, and never leave a block needing a path
  that only a later block adds (an import, a by-path load, a conftest registration).

A moved path can change both blocks' buckets, so rewrite both subjects: type by bucket, per
`${CLAUDE_PLUGIN_ROOT}/reference/commit_format.md`.

## Step 4: Write the messages

Edit only the message strings of the skeleton JSON. Read `${CLAUDE_PLUGIN_ROOT}/reference/commit_format.md` first
(required). A rewritten block states its change as of now, with one `file: what changed` bullet for every
non-artifact path in it. When the change text points at the conversation ("the review fixes", "what we just
did"), replace each reference with the concrete facts it stands for: file names, what changed, why. `build`
rejects filler and quality claims, so name the change instead.

## Step 5: Build

```bash
SCRIPT build "<skeleton>"
```

Exit 1: each `problem:` line names a commit and a defect, including `bullet names X, not in this block`; fix the
JSON and rerun. Exit 0 writes the TXT beside the skeleton (same stem, `.txt`), keeps the replaced copy as
`<name>.txt.bak`, and prints the receipt. Output the receipt verbatim and nothing else.

## Common Mistakes

| Mistake                                              | Fix                                                                 |
|------------------------------------------------------|---------------------------------------------------------------------|
| Rerunning the capture with `--fresh` to start over   | Never; it drops the messages. Edit the blocks that are wrong.       |
| Moving a path by editing the lists in the JSON       | `move`; the bullet goes with the path.                              |
| Rewriting every block to be safe                     | Only blocks the change or a moved path touches.                     |
| Writing "as discussed" or "the review fixes"         | Name the files and the change.                                      |
| Pasting the breakdown into chat                      | The receipt is the only chat output.                                |
