---
name: add-todo
description: Use when asked to add a note, reminder, idea or finding to the project's TODO catalog from free text, local-only or backed by a new GitHub issue, researched as deeply as asked. Triggers on "add-todo", "add a todo", "log this as a TODO", "put this in the TODO catalog", "make a TODO item for this". Hands the research and drafting to the harness:todo-editor agent; the main session prints the dispatch row and adds what the conversation already established.
argument-hint: "[--issue] [-r|--research 0-3] -- <note>"
---

# add-todo: one TODO item from a note

Arguments: `$ARGUMENTS`

The developer types a short note; the conversation usually already holds the rest (the files, the ids, what was
found). The main session passes that on in a `Context:` line and hands everything else to the `todo-editor`
agent, which researches at the level asked, drafts the item and runs `todo_sync.py add`. Main-session time stays
near zero, and the research is done once, by the agent, at the depth the developer chose.

## Arguments

Split `$ARGUMENTS` at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`:
the flags come before it, the note after it. The note is the skill's own argument, so with no flags `-- <note>`
and `<note>` are the same invocation. With flags and no `--` token, the text after the last flag (and its level) is the note. The note never reaches a command line.

| Flag | Effect | Default |
|---|---|---|
| `--issue` | A GitHub issue is filed for the item and recorded as its source. | Off: the item stays local, with a dated `note` source. |
| `-r N`, `--research N` | How far the agent reads before it drafts, 0 to 3; the level also picks the agent's model. | 0 |

| Level | The agent |
|---|---|
| 0 | Writes the note up as a reminder from the Note and Context lines; reads no code. |
| 1 | Reads the files the note and context name, checks each claim, cites `path:line`. |
| 2 | Also traces callers and consumers, the tests that cover them, related catalog items and open issues. |
| 3 | Also reads the files' history and linked reviews, weighs alternatives and cites `path:line` for every claim. |

An empty note, an unknown flag or a level outside 0-3 ends the run: print the `argument-hint` line above.

## Step 1: print the row

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/add_todo.py" row [--issue] [-r N]
```

Run it from the project root with the flags only. stdout is the row: an `agent=harness:todo-editor model=<model>`
line, then the `SKILL`, `Operation`, `Issue`, `Research` and `Project root` lines. A `problem:` line naming
`todo_sync.py init` means `todo.folder` is set but the catalog does not exist yet: run
`sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" init`, then the row command
again. Any other `problem:` line ends the run: relay it.

## Step 2: write the Context line

The Context line carries what the conversation has already established about the note, so the developer does
not retype it: the files and `path:line` spots it cited, the ids (TODO, issue, PR) it named, what was found or
decided, and any ask the developer made about this item ("pin every claim to a line", "keep it short"). A claim
the conversation repeated but never checked goes in as unverified. Plain sentences on one line; `none` when the
conversation holds nothing on the note.

Write it from the conversation alone. No Read, Grep, Glob, `gh`, `git` or test run happens before the dispatch:
a fact the conversation has not established is the agent's to find, at the level the developer chose.

## Step 3: dispatch

One `Agent` call: `subagent_type="harness:todo-editor"`, the model from the `agent=` line and never another,
`description="Add a TODO item"`. The prompt is the row's lines after the `agent=` line, then:

```
Note: <the note verbatim, newlines folded to spaces>
Context: <the Step 2 line, or none>
```

The prompt carries no drafted item fields (title, severity, files): the agent drafts them.

## Step 4: report

Relay the agent's reply as it stands. The edit is saved, not committed; the developer reviews the diff and
commits. With `--issue`, name the issue the reply's `Added` line gives. Name an item marked
`(needs decision)`.

## Rules

- **The main session does not research the note.** Reading the code to "help" the agent spends main-session
  context and does the agent's work twice. Even when the developer asks the session to grep first, put that
  ask in the Context line ("developer asks every claim pinned to `path:line`") and dispatch; the agent does the
  reading. A level higher than the flags give needs the developer to pass `-r`; the session never raises it.
- **A doubtful premise still gets dispatched.** When the note's claim looks wrong, checking it in the session
  or holding the dispatch to ask the developer is the same research by another name. Write the claim into the
  Context line as unverified ("the developer reports X; not checked") and dispatch; the agent confirms or
  refutes it at the level given.
- **The main session does not write the catalog.** Not one entry, not "just this once": ids, ranks and counts
  belong to `todo_sync.py`, and the drafting belongs to the agent.
- **The note goes verbatim.** The session adds context beside it, never rewrites it.
- **Only `--issue` files an issue.** A note that says "file an issue" without the flag stays local; say so in
  the report.

## Judgment

| Situation | Call |
|---|---|
| The developer asks the session to read or grep before the handoff | Carry the ask in the Context line and dispatch at the given level. |
| The note contradicts what the conversation found | State both in the Context line; the agent checks. |
| The conversation found nothing about the note | `Context: none`; level 0 records a reminder. |
| The conversation cited a file the note does not name | Include it when it bears on the note; the agent decides. |
| The note is about a GitHub issue that is already open | Dispatch as usual; the agent names `/harness:sync-gh-todo` under `Open`, since `add` cannot mark an existing issue as tracked. |

## Related

- `${CLAUDE_PLUGIN_ROOT}/scripts/add_todo.py`: the row driver.
- `${CLAUDE_PLUGIN_ROOT}/agents/todo-editor.md`: the agent; its `add` operation drafts the item.
- `${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py`: `add` (with `--file-issue`), `render` and `check`.
- `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the `--` split.
