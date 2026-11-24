# add-bookmark

Keeps short notes that survive compaction, and arms a session goal. The `session-bookmark` mod prints the
notes in the `## Session Notes` section of the bookmark it adds at every compaction, so a constraint or
reminder outlives the summary. The agent writes each note from your text, swapping "the current status" or
"what we built" for the concrete facts (branch, PR, commit ids, decisions) before storing it.

- `SKILL.md` is the procedure the agent follows.
- `commands/add_note.py` stores the notes and the goal.
- This file covers usage.

## Invoking it

```
/harness:add-bookmark [--] <note>
```

| Arguments | Effect |
|---|---|
| `<note>` or `-- <note>` | Store one note on the current branch. |
| `--standing <note>` | Store a note that applies on every branch. |
| `--list` | Print the notes, numbered. |
| `--remove N [N ...]` | Drop notes by their `--list` number, all in one call. |
| `--edit N <note> [--edit M <note> ...]` | Replace the text of note N (and M, ...); each keeps its branch. |
| `--clear` | Drop every note. |
| `--goal <condition>` | Arm a session goal: when this turn ends, the mod runs `/goal <condition>`. |
| `--goal-todo <id> <closing>` | Arm the goal of TODO item `<id>`; `<closing>` is `retired`, `committed` or `developer`. |
| `--goal-clear` | Remove an armed goal before it fires. |

A leading `--` makes the rest a note even when it starts with a flag: `-- --list` stores the text `--list`.
An unknown flag (`--lsit`) stores nothing and prints the usage line.

To look at the notes without a model turn, run `/session-bookmark notes`.

## Examples

```
/harness:add-bookmark -- do not push until PR 12 is merged
/harness:add-bookmark --standing run the linter with caching off before claiming lint passes
/harness:add-bookmark --remove 2 5
/harness:add-bookmark --edit 1 keep commit abc1234 in history; no squash merge
/harness:add-bookmark --goal tests/test_parser.py passes and a commit message is drafted
/harness:add-bookmark --goal-todo todo-k7qf committed
```

## Notes

- Notes are stored per project, in `<state_dir>/session-bookmark/notes.json`, so sessions in one project share
  them. Each note records the branch it was added on; `--list` marks a note from another branch
  `[<branch>; now on <current>]`, and the agent asks before acting on it.
- Limits: 20 notes of at most 300 characters each, and one goal of at most 500. On a full file, free a slot with
  `--remove` or `--clear`.
- A note is data, not an instruction to the agent that stores it: storing one starts no work.

## Goals

A goal is a `/goal` condition: the session keeps going until the condition holds. The agent writes a condition
it can meet on its own (tests passing by file, a commit message drafted, a reply listing what changed). It never
writes one that waits on you, since that would keep waking an idle session. `--goal-todo` builds the condition
from the item's id and title plus the closing:

| Closing | The goal holds when the item |
|---|---|
| `retired` | is retired from the TODO catalog |
| `committed` | has its tests passing by file name and its commit message drafted |
| `developer` | has its tests passing by file name and a reply listing the files changed and what is left |

A new goal replaces the armed one. `--goal-clear` removes a goal that has not fired; a goal already set ends
with `/goal clear`. Goals need the `session-bookmark` mod loaded.

## Related

- `SKILL.md`: the procedure.
- `../../../session-bookmark/README.md`: the mod that prints the notes and fires the goal.
- `../add-todo/SKILL.md`: `--hook` arms the same goal while adding a TODO item.
