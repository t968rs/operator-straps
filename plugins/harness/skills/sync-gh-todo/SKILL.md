---
name: sync-gh-todo
description: Use when asked to find the open GitHub issues that the project's TODO catalog does not mention and add them as items. Triggers on "sync-gh-todo", "sync GitHub issues to the TODO catalog", "which open issues are not in the TODO catalog", "add the missing issues to RepoToDo". Hands the drafting to the harness:todo-editor agent, which runs todo_sync.py.
---

# sync-gh-todo: add untracked GitHub issues to the TODO catalog

The TODO checks compare the catalogs, stubs and snapshot with each other and never read GitHub, so an issue
reaches the catalog only when someone writes an item for it. `todo_sync.py untracked` lists the open issues no
catalog record mentions; the `todo-editor` agent drafts one item per issue from the issue text and, when the
issue links a PR review, from the review's own text; `todo_sync.py add` inserts the items and renumbers. The
catalog and the issue text never enter the main session's context.

## Step 1: list the untracked issues

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" untracked
```

Run it from the project root. `untracked: none` ends the run: report that line. A `problem:` line (no
`todo.folder` in `.claude/harness.json`, `gh` missing or failing) ends the run: relay it. Otherwise the output is
`untracked: <n> open issue(s) in no catalog record`, one `#<number> <title>` line per issue and
`wrote <path>`; the issue numbers feed Step 2.

A `problem:` line ending `RepoToDo.json: file not found` (the catalog named in `todo.catalog`) means
`todo.folder` is set but the project has no catalog yet. Create the starter one, then rerun the command above:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" init
```

`init` writes an empty catalog and the first snapshot and prints one `created <path>` line per file. It
never overwrites an existing catalog: a `problem:` line from it ends the run, relayed as it stands.

## Step 2: dispatch the agent

One `Agent` call: `subagent_type="harness:todo-editor"`, `model="opus"`, `description="Sync GitHub issues to
TODO items"`, with this prompt, the placeholders filled:

```
Operation: sync
Issues: #<n>, #<n>
Project root: <absolute project root>
Guidance: none
```

`Issues:` lists every number from Step 1.

## Step 3: report

Relay the agent's reply as it stands. The edits are saved, not committed; the developer reviews the diff and
commits. The items are the agent's best guess from the issue text: say so, and name any item the reply marks
as needing a decision.
