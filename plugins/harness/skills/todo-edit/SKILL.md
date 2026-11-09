---
name: todo-edit
description: Use when asked to edit the project's TODO catalog structurally - retire finished items, split one item into parts, or refresh scores and ranks after hand edits. Triggers on "todo-edit", "retire todo-k7qf", "split todo-m3x9", "refresh the TODO ranking", "re-rank the TODO catalog". Hands the operation to the harness:todo-editor agent, which runs todo_sync.py and fixes the prose the script cannot.
argument-hint: "--retire ID[, ID ...] [--delete-retired] | --split ID | --refresh  [-- <guidance>]"
---

# todo-edit: retire, split or refresh TODO catalog items

Item ids are stable random codes (`todo-k7qf`): a structural edit moves ranks, never ids. A retired or split
id joins `retired_ids` and is never drawn again, and a split's parts get new ids. `todo_sync.py` does the
mechanical part (ranks, links, scores, counts, the id records); the agent supplies what the script cannot: the
content of split parts, close-candidate evidence, tracker notes and prose that still names a retired or split
id. The catalog never enters the main session's context.

## Step 1: parse the arguments

`$ARGUMENTS` holds exactly one operation, then optional guidance. Split it at the first standalone `--` token,
per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the operation, its ids and flags come before it, the
guidance (free text, paths) after it. Free text after the ids with no `--` token is read as guidance too.

| Operation | Ids | Example | Model |
|---|---|---|---|
| `--retire` | one or more, comma- or space-separated | `--retire k7qf, todo-2a2a` | `opus` |
| `--split` | exactly one | `--split todo-m3x9 -- one part per module` | `opus` |
| `--refresh` | none | `--refresh` | `haiku` |

An id is `todo-k7qf` or its bare code `k7qf`, in any case: `todo-` plus four characters, or the four
characters alone, holding at least one digit and one letter. The first token after the operation that is
neither (a flag aside) starts the guidance. Split the ids at commas and whitespace and pass each piece
as typed, joined with `, ` on the `Ids:` line (`Ids: k7qf, todo-2a2a`). The script canonicalizes each id (a
trailing comma included, and a comma-joined pair read as two ids) and refuses, with the reason, a retired,
split or unknown id, or an old rank-tied id (naming the item it meant as of the migration). `--delete-retired`
is a flag of `--retire` alone: it lets the agent close out a research entry and delete its stub once every
deliverable in the stub is proven implemented. When the operation is missing or unknown, `--split` names more
than one id, `--retire` names none, `--refresh` names any, or `--delete-retired` appears without `--retire`,
print the `argument-hint` line above and stop.

The operation needs `todo.folder` in `.claude/harness.json`; the script reports `problem: <op> needs
todo.folder` when it is unset, and the agent relays that.

## Step 2: dispatch the agent

One `Agent` call: `subagent_type="harness:todo-editor"`, the model from the table, `description="<Operation>
TODO items"`. The prompt is this block with the placeholders filled:

```
SKILL: todo-edit
Operation: <retire | split | refresh>
Ids: <the ids as typed, comma-separated, or none>
Delete retired: <yes | no>
Project root: <absolute project root>
Guidance: <the guidance after the -- token (else the free text after the ids), or none>
```

## Step 3: report

Relay the agent's reply as it stands. The edits are saved, not committed; the developer reviews the diff and
commits. For a retirement the reply answers three questions: the new state of each touched stub (`Stubs`), the
research entries now fully resolved (`Resolved`), and the GitHub issues that can be closed, each with its reason
(`Close`). When the reply lists open items (a missing close-candidate evidence, a reference outside the catalog,
a stub kept for lack of proof, a failed check), name them first. The script's reference list names only the
retired or split ids and leaves out the history folders (`artifacts.plans`, `reviews`, `commit_messages`,
`summaries`, `scratch`, each planning prefix and the snapshots), in-progress plans included: an id in a record
stays as written, but a live plan naming a retired id has to be checked by hand. When the catalog still holds
rank-tied ids, the agent relays the refusal naming `todo_sync.py migrate-ids`; that switch is the developer's
to run.
