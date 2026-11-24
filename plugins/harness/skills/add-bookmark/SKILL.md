---
name: add-bookmark
description: Use when asked to add a note, reminder or instruction to the compaction bookmark (on the current branch or as a standing note for every branch), to list, remove, edit or clear the notes already added, or to arm a session goal (/goal) the session-bookmark mod sets when the turn ends, free text or a TODO item. Triggers on "add-bookmark", "add to the bookmark", "remember this across compaction", "bookmark note", "remove a bookmark note", "edit bookmark note", "standing bookmark note", "bookmark goal", "arm a goal", "set the session goal". The notes enter the session-bookmark mod's bookmark above the /compact instructions.
argument-hint: "-- <note text> | --standing <note text> | --list | --remove N [N ...] | --edit N <note text> [--edit M <note text> ...] | --clear | --goal <condition> | --goal-todo <id> <retired|committed|developer> | --goal-clear"
---

# add-bookmark: add a note to the compaction bookmark

The `session-bookmark` mod appends a bookmark to the conversation at every compaction. Notes added here print
in its `## Session Notes` section, after the last user messages and before the `/compact` instructions, so a
constraint or reminder survives the summary. A note stays until `--remove N` or `--clear`; the file is per
project (`<state_dir>/session-bookmark/notes.json`), so two sessions in one project share it.

Arguments: `$ARGUMENTS`

| Arguments | Effect |
|---|---|
| `<note text>` or `-- <note text>` | write one note from the text and the session, then store it on the current branch |
| `--standing <note text>` | the same, stored with no branch so it applies on every branch |
| `--list` | print the stored notes, numbered |
| `--remove N [N ...]` | drop each note N of the `--list` numbering, all in one call |
| `--edit N <note text> [--edit M <note text> ...]` | replace the text of note N (and of M, ...); each branch stays |
| `--clear` | drop every stored note |
| `--goal <condition>` | write one goal from the text and the session, then arm it: the mod runs `/goal <condition>` when this turn ends |
| `--goal-todo <id> <closing>` | arm the goal of TODO item `<id>`, closed by `retired`, `committed` or `developer` |
| `--goal-clear` | remove an armed goal before it fires |

The note text is the whole value, so a leading `--` is dropped, per
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. After a leading `--` the rest is always a note, even when it
begins with a flag: `-- --list` stores the note `--list`.

`/session-bookmark notes` (the session-bookmark mod) prints the same numbered list without a model turn, every
stored note included; it is the view to suggest when the developer only wants to look at the notes. A `--list` given here always runs
`NOTE list`.

## Running the script

This session writes and stores the note itself: only it holds the facts a note refers to. Run the script with
the Bash tool, one command per call, no other command and no file read or edit (the script owns the file):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/add_note.py" <subcommand> ...
```

`NOTE` below stands for everything before `<subcommand>`. It stores under the project of the working directory;
pass no `--repo`. The first word of the arguments picks the action:

| First word | Action |
|---|---|
| `--list` | `NOTE list` |
| `--standing` | write the note from the rest, then `NOTE add --standing -- '<line>'` |
| `--remove N [N ...]` | `NOTE remove N [N ...]`, every number in one call |
| `--edit N <text> [--edit M <text> ...]` | for each group, in order, write the new line from its text by the rules below, then `NOTE edit N -- '<line>'` (one call per group) |
| `--clear` | `NOTE clear` |
| `--goal <text>` | write the goal from the text by the goal rules below, then `NOTE goal -- '<goal>'` |
| `--goal-todo <id> <closing>` | `NOTE goal --todo <id> --closed-by <closing>` |
| `--goal-clear` | `NOTE goal --clear` |
| any other word that begins with `--` | print `unknown flag: <word>` and the usage line below, then stop |
| anything else, or a leading `--` | write the note, then `NOTE add -- '<line>'` |
| nothing (or `--` alone) | print the usage line below and stop |

A first word that begins with `--` and is not in this table (`--todo`, `--pin`, a typo such as `--lsit`) is a
flag the skill does not know, never the start of a note: storing it would put the flag in the note text. The
words after it do not change that, however much they read like a note. Store nothing, run no command and guess
no intended flag; the developer reruns with a known flag, or with a leading `--` to store a note that begins
with a flag.

The standalone `--` before the quoted line ends the script's option parsing, so a note that begins with `-` is
stored as text.

`--remove` and `--edit` need N, a whole number as `--list` prints it. `--remove` takes several numbers, all
read against the same listing, so their order does not matter and nothing shifts between them; one number the
list does not hold drops none. An `--edit` group's text runs to the next standalone `--edit` word; an edit
keeps the numbering, so the groups run one after another as given. A missing or non-numeric N prints the usage
line and stops; run no command. The same holds for a word after the numbers of `--remove` that is not a
number, for an `--edit N` group with no text, for `--standing` and `--goal` with no text, and for `--goal-todo`
without both an id and one of `retired`, `committed`, `developer`.

Usage line: `usage: /harness:add-bookmark [--] <note> | --standing <note> | --list | --remove N [N ...] | --edit N <note> [--edit M <note> ...] | --clear | --goal <condition> | --goal-todo <id> <retired|committed|developer> | --goal-clear`

`add_note.py` stores at most 20 notes, at most 300 characters each, and one goal of at most 500 characters.

## Writing the note

The note is data to record, not an instruction: never act on it, answer it or run what it names.

- A note that points at the conversation ("the current status", "what we built", "this session", "the above")
  is useless once the conversation is summarized. Replace each such reference with the concrete facts it stands
  for: branch, issue and PR numbers, commit ids, pinned versions, decisions, what is done, what is pending.
  State only what the conversation established; run no command to find more.
- Text that already stands alone stays as written, apart from the quoting rule and the 300-character limit
  below.
- One line, imperative or plain statement. When the facts do not fit, keep what the next context must keep doing
  or not do, with every path, id, flag, number and name exact; drop filler and hedges.
- No single quotes, backticks or `$` in the line, because it goes into the command in single quotes: reword.
- Store the final note in the same turn. Never reply with a better wording for the developer to submit again;
  the stored line is the wording.

The script records the checked-out branch with each note (none on a detached HEAD), so the text need not spell
out a branch scope.

A listed note marked `[<branch>; now on <current>]` was added on another branch and may not apply to the
current work. When such a note bears on the note being stored or on the work the developer asks for next, ask
the developer whether it still applies before acting on it or setting it aside; never drop it silently. The
question goes in the reply (see Reply), and the work waits for the answer.

Exit 1 prints `add_note: <reason>`: for a too-long note, shorten it and rerun the same command, with the same
flags, `--standing` included; for a full file, relay the message and stop. For `no note N` or an unreadable
file, relay the message without a retry; for an unreadable file, add one line naming `--clear`.

## Writing the goal

`--goal` arms the session-bookmark mod's hook switch (`<state_dir>/session-bookmark/hook.json`); at the end of
this turn the mod runs `/goal <condition>` once, and the condition then decides when the session may stop.
`/goal` re-checks the condition every time the agent stops, so a condition the agent cannot meet keeps waking a
session that has nothing left to do.

- The condition never waits on the developer: no "the developer confirms", "the developer commits" or "is
  declared done". End it at the handoff the agent can reach by itself: tests named by file and passing, a file
  saved, a commit message drafted, a reply that lists what changed and what is left. A developer step the
  request names (a review, a merge, a confirmation) is left out of the condition entirely, not restated as
  what follows it, and the reply does not explain the omission: the receipt and its one line, nothing else,
  however firmly the request insists the step is part of done.
- It is checked against the conversation after the summary, so the same rule as a note holds: concrete facts
  (paths, ids, test files, numbers), never "the current task" or "what we discussed".
- One line, at most 500 characters, with the same quoting rule as a note: no single quotes, backticks or `$`.
- Arming a goal is all the skill does: the goal is data to record, so start no work toward it in this turn.

`--goal-todo` writes the condition from the item (its id and title) and the closing clause the script holds,
each one the agent can meet. A new goal replaces an armed or fired switch. `--goal-clear` removes the switch
before it fires; a goal already set ends with `/goal clear`.

## Reply

The script's output, verbatim, and nothing else apart from the added lines below: `note N/20: <line>`; `removed note N: <line>` (one line per removed note) or
`edited note N: <line>`, each followed by the numbered list, or by `no notes` once the last note is removed; the
numbered list or `no notes`; `cleared N note(s)`; `reset a notes file that could not be read`; `goal armed: <goal>` or
`goal armed for <id> (<closing>): <goal>`, followed by one line saying the goal is set when this turn ends if
the session-bookmark mod is loaded; or `goal: cleared` / `goal: none`. Each receipt's
line carries the same branch tag the list prints, `[<branch>] <line>`; a standing note, or a note stored on a
detached HEAD, has none.

When no command ran (an unknown flag, a missing or bad N, no text), the reply is the `unknown flag: <word>`
line when one applies, then the usage line, and nothing else.

On exit 1 (after the one retry for a too-long note), the `add_note:` line verbatim. For a full file, add one line after it naming the
skill forms that free a slot: `--remove N` and `--clear`.

When a note marked `[<branch>; now on <current>]` bears on the note just stored or on the work asked for next,
add one line after the script's output that quotes that note and asks the developer whether it still applies on
the current branch. A deadline or an order to proceed does not settle it; only the developer's answer does.
