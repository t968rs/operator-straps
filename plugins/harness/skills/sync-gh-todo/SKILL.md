---
name: sync-gh-todo
description: Use when asked to find the open GitHub issues that the project's TODO catalog does not mention and add them as items. Triggers on "sync-gh-todo", "sync GitHub issues to the TODO catalog", "which open issues are not in the TODO catalog", "add the missing issues to RepoToDo". Hands the drafting to the harness:todo-editor agent, which runs todo_sync.py.
argument-hint: "[-- <guidance>]"
---

# sync-gh-todo: add untracked GitHub issues to the TODO catalog

Arguments: `$ARGUMENTS`

The skill takes no flags. A tail after a standalone `--` token is the guidance, per
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md` (how to scope or word the new items, which issues to
stress). It fills the `Guidance:` line of Step 2's prompt.

The TODO checks compare the catalogs, stubs and snapshot with each other and never read GitHub, so an issue
reaches the catalog only when someone writes an item for it. `todo_sync.py untracked` lists the open issues no
catalog record mentions; the `todo-editor` agent drafts one item per issue from the issue text and, when the
issue links a PR review, from the review's own text, and queues them with `todo_sync.py inbox put`;
`todo_sync.py add --inbox` then inserts and ranks the queued items. The catalog and the issue text never enter
the main session's context.

## Step 1: list the untracked issues

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" untracked
```

Run it from the project root. `untracked: none` ends the run: report that line. Otherwise the output is
`untracked: <n> open issue(s) in no catalog record`, one `#<number> <title>` line per issue and
`wrote <path>`; the issue numbers feed Step 2.

A `problem:` line ending `: file not found` that names the configured `todo.catalog` (default `RepoToDo.json`)
means `todo.folder` is set but the project has no catalog yet. Create the starter one, then rerun the command
above:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" init
```

`init` writes an empty catalog and, when `todo.snapshots.dir` is set, the snapshot page and its `todo_live.js`
stamp, and prints a `created <path>` line for the catalog and one for the page (the stamp is not listed). It
never overwrites an existing catalog: a `problem:` line from it ends the run, relayed as it stands. The
exception is a `problem:` line ending `was created, finish with todo_sync.py render`: the catalog landed and
only the page failed, so relay it, then rerun the untracked command and continue. Any other
`problem:` line from the untracked command (no `todo.folder` in `.claude/harness.json`, a catalog still holding
`TODO-NNN` ids, which names `todo_sync.py migrate-ids`, `gh` missing or failing) ends the run: relay it.

## Step 2: dispatch the agent

One `Agent` call: `subagent_type="harness:todo-editor"`, `model="opus"`, `description="Sync GitHub issues to
TODO items"`, with this prompt, the placeholders filled:

```
SKILL: sync-gh-todo
Operation: sync
Issues: #<n>, #<n>
Project root: <absolute project root>
Guidance: <the text after the -- token, or none>
```

`Issues:` lists every number from Step 1. The agent drafts from the `untracked.json` Step 1 wrote and reruns
`untracked` only when that file is missing, so `gh` fetches the issues and reviews once.

## Step 3: drain the inbox

The agent queues the drafted items in the inbox and never writes the catalog. Once it returns, add whatever the
inbox holds, once:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" add --inbox
```

Run it from the project root. It prints one line: `inbox: added N item(s): <id> (#N|note), ...; check drift=<d>`,
with a `; rejected M (<files>)` part when the catalog refused some queued files; `inbox: rejected M (<files>)`
when it refused all of them; or `inbox: empty`. The same drain applies field updates other runs queued
(`inbox put --update`), so the line can also carry an `updated M item(s): <id> (<fields>), ...` part (or open
with `inbox: updated` when only updates landed) and an `overwrote <id> <field>` part when two queued updates set
the same field. A refused file stays in the inbox as `<name>.rejected.json`
beside a `<name>.reason.txt` naming why: report its item as not added. `inbox: empty` means nothing was waiting:
either the agent queued nothing (its reply says why), or the todo-watch mod already drained the inbox and its
summary line arrives as context. A `problem:` line ends the run: relay it once without rerunning the drain.
A `problem:` line opening `inbox: added` or `inbox: updated` means those changes landed and only the follow-up
(render, check or inbox file cleanup) failed: report them as applied. A lock refusal naming the holder
`todo_sync.py add --inbox` means the todo-watch mod is still draining and its summary line arrives as context.
Any other `problem:` line leaves the queued items in the inbox.

## Step 4: report

Relay the agent's reply as it stands, with the Step 3 line. The edits are saved, not committed; the developer
reviews the diff and commits. The items are the agent's best guess from the issue text: say so, and name any
item the reply's `Added` line marks `(needs decision)`.
