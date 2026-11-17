---
name: todo-edit
description: Use when asked to edit the project's TODO catalog structurally - retire finished items, split items into parts, queue field updates of items, or refresh scores and ranks after hand edits. Triggers on "todo-edit", "retire todo-k7qf", "split todo-m3x9", "update todo-m3x9", "refresh the TODO ranking", "re-rank the TODO catalog". Hands the operation to the harness:todo-editor agent, which runs todo_sync.py and fixes the prose the script cannot.
argument-hint: "--retire ID[, ID ...] [--delete-retired] | --split ID[, ID ...] | --update ID[, ID ...] | --refresh  [-- <guidance>]"
---

# todo-edit: retire, split, update or refresh TODO catalog items

Item ids are stable random codes (`todo-k7qf`): a structural edit moves ranks, never ids. A retired or split
id joins `retired_ids` and is never drawn again, and a split's parts get new ids. `todo_sync.py` does the
mechanical part (ranks, links, scores, counts, the id records); the agent supplies what the script cannot: the
content of split parts, the new values of an update, close-candidate evidence, tracker notes and prose that
still names a retired or split id. The catalog never enters the main session's context.

## Step 1: parse the arguments

`$ARGUMENTS` holds exactly one operation, then optional guidance. Split it at the first standalone `--` token,
per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the operation, its ids and flags come before it, the
guidance (free text, paths) after it. Free text after the ids with no `--` token is read as guidance too.

| Operation | Ids | Example | Model |
|---|---|---|---|
| `--retire` | one or more, comma- or space-separated | `--retire k7qf, todo-2a2a` | `opus` |
| `--split` | one or more | `--split todo-m3x9, k7qf -- one part per module` | `opus` |
| `--update` | one or more, guidance required | `--update todo-m3x9 -- severity 4: the parser drops rows` | `opus` |
| `--refresh` | none | `--refresh` | `haiku` |

An id is `todo-k7qf` or its bare code `k7qf`, in any case: `todo-` plus four characters, or the four
characters alone, holding at least one digit and one letter. The first token after the operation that is
neither (a flag aside) starts the guidance. Split the ids at commas and whitespace and pass each piece
as typed, joined with `, ` on the `Ids:` line (`Ids: k7qf, todo-2a2a`). The script canonicalizes each id (a
trailing comma included, and a comma-joined pair read as two ids) and refuses, with the reason, a retired,
split or unknown id, or an old rank-tied id (naming the item it meant as of the migration). `--delete-retired`
is a flag of `--retire` alone: it lets the agent close out a research entry and delete its stub once every
deliverable in the stub is proven implemented. When the operation is missing or unknown, or the arguments
hold `--retire`, `--split` or `--update` with no ids, `--update` with no guidance, `--refresh` with ids, or
`--delete-retired` without `--retire`, print the `argument-hint` line above and stop. An update's guidance
says what to change; without it the agent has nothing to set.

The operation needs `todo.folder` in `.claude/harness.json`; the script reports `problem: <op> needs
todo.folder` when it is unset, and the agent relays that.

## Step 2: dispatch the agent

Every `Agent` call takes `subagent_type="harness:todo-editor"`, the model from the table and
`description="<Operation> TODO items"`. `--retire` makes one `Agent` call for all its ids, and `--refresh`
one call. `--split` and `--update` make one `Agent` call per id, all in one message, each prompt naming its one
id on the `Ids:` line and carrying the same guidance. Before dispatching per id, drop an id whose canonical
form (lower-case, without a trailing `,` or `;`, `todo-` added when missing) repeats an earlier one, and name
the dropped duplicates in the Step 4 report. When the guidance names several ids, each agent applies only what
it says about its own id, plus what applies to all. The splits then draft their parts at once and take the
catalog lease one at a time to apply them; the updates only queue, so none waits on another. The prompt is
this block with the placeholders filled:

```
SKILL: todo-edit
Operation: <retire | split | refresh | update>
Ids: <the ids as typed, comma-separated, or none>
Delete retired: <yes | no>
Project root: <absolute project root>
Guidance: <the guidance after the -- token (else the free text after the ids), or none>
```

## Step 3: drain the inbox (`--update` only)

An update agent queues its field updates in the inbox and never writes the catalog. Once every agent has
returned, apply whatever the inbox holds, once:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" add --inbox
```

Run it from the project root. It prints one line: `inbox: [added N item(s): <id> (#N|note), ...; ]updated M
item(s): <id> (<fields>), ...; [overwrote <id> <field>, ...; ][rejected K (<files>); ]check drift=<d>`. The
`added` part leads when other queued items landed with the updates; the `overwrote` part appears when two
queued updates set the same field and both land in the same drain (the later one wins); the `rejected` part
appears when the catalog refused some queued files. The line reads `inbox: rejected K (<files>)` when it
refused all of them, or `inbox: empty`. A refused file stays in the inbox as `<name>.rejected.json` beside a `<name>.reason.txt`
naming why: report its update as not applied. `inbox: empty` means nothing was waiting: either the agents
queued nothing (their replies say why), or the todo-watch mod already drained the inbox and its summary line
arrives as context. A `problem:` line ends the run: relay it once without rerunning the drain. When it
reads `problem: inbox: added <ids>; updated <ids>, then: <reason>` (either part alone when only one kind landed),
those changes landed and only the render, check or file cleanup
failed: report them as applied. When it names a lock held by `todo_sync.py add --inbox`, the todo-watch mod is
draining the updates and its summary line arrives as context. Otherwise the queued updates stay in the inbox.

## Step 4: report

Relay every agent's reply as it stands (one per id for split and update), then the Step 3 line for an update. The edits are saved,
not committed; the developer reviews the diff and commits. For a retirement the reply answers three questions:
the new state of each touched stub (`Stubs`), the research entries now fully resolved (`Resolved`), and the
GitHub issues that can be closed, each with its reason (`Close`). When a reply lists open items (a missing
close-candidate evidence, a reference outside the catalog, a stub kept for lack of proof, a failed check),
name them first. The script's reference list names only the
retired or split ids and leaves out the history folders (`artifacts.plans`, `reviews`, `commit_messages`,
`summaries`, `scratch`, each planning prefix, the snapshots, the TODO inbox (`<scratch_folder>/todo-inbox`) and
`state_dir`), in-progress plans included: an id in a record stays as written, but a live plan naming a retired id
has to be checked by hand. When the catalog still holds
rank-tied ids, the agent relays the refusal naming `todo_sync.py migrate-ids`; that switch is the developer's
to run.
