---
name: add-bookmark
description: Use when asked to add a note, reminder or instruction to the compaction bookmark, or to list or clear the notes already added. Triggers on "add-bookmark", "add to the bookmark", "remember this across compaction", "bookmark note". The notes enter the session-bookmark mod's bookmark above the /compact instructions.
argument-hint: "<note text> | --list | --clear"
model: haiku
context: fork
agent: harness:bookmark-noter
---

# add-bookmark: add a note to the compaction bookmark

The `session-bookmark` mod appends a bookmark to the conversation at every compaction. Notes added here print
in its `## Session Notes` section, after the last user messages and before the `/compact` instructions, so a
constraint or reminder survives the summary. A note stays until `--clear`; the file is per project
(`<state_dir>/session-bookmark/notes.json`), so two sessions in one project share it.

`add_note.py` (this skill's `commands/` folder) does the storing: at most 20 notes, at most 300 characters each.
The agent condenses the text to fit.

Arguments: `$ARGUMENTS`

| Arguments | Effect |
|---|---|
| `<note text>` | condense and store one note |
| `--list` | print the stored notes, numbered |
| `--clear` | drop every stored note |
