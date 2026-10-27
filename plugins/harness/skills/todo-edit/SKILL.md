---
name: todo-edit
description: Use when asked to edit the project's TODO catalog structurally - retire finished items, split one item into parts, or refresh scores and ranks after hand edits. Triggers on "todo-edit", "retire TODO-003", "split TODO-001", "refresh the TODO ranking", "re-rank the TODO catalog". Hands the operation to the harness:todo-editor agent, which runs todo_sync.py and fixes the prose the script cannot.
argument-hint: "--retire ID[, ID ...] [--delete-retired] | --split ID | --refresh  [-- <guidance>]"
---

# todo-edit: retire, split or refresh TODO catalog items

Ids in the catalog equal their rank (rule T6), so every structural edit renumbers items and rewrites ids in the
catalog, the research catalog and the `_IMPL_TODO.md` stubs. `todo_sync.py` does that mechanically; the agent
supplies what the script cannot: the content of split parts, close-candidate evidence, tracker notes and prose
that named a moved or removed id. The catalog never enters the main session's context.

## Step 1: parse the arguments

`$ARGUMENTS` holds exactly one operation, then optional guidance. Split it at the first standalone `--` token,
per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the operation, its ids and flags come before it, the
guidance (free text, paths) after it. Free text after the ids with no `--` token is read as guidance too.

| Operation | Ids | Example | Model |
|---|---|---|---|
| `--retire` | one or more, comma- or space-separated | `--retire 1, 3` | `opus` |
| `--split` | exactly one | `--split 001 -- one part per module` | `opus` |
| `--refresh` | none | `--refresh` | `haiku` |

An id may be `TODO-007`, `007` or `7`; normalize each to `TODO-NNN`. `--delete-retired` is a flag of `--retire`
alone: it lets the agent close out a research entry and delete its stub once every deliverable in the stub is
proven implemented. When the operation is missing or unknown, `--split` names more than one id, `--retire` names
none, `--refresh` names any, or `--delete-retired` appears without `--retire`, print the `argument-hint` line
above and stop.

The operation needs `todo.folder` in `.claude/harness.json`; the script reports `problem: <op> needs
todo.folder` when it is unset, and the agent relays that.

## Step 2: dispatch the agent

One `Agent` call: `subagent_type="harness:todo-editor"`, the model from the table, `description="<Operation>
TODO items"`. The prompt is this block with the placeholders filled:

```
Operation: <retire | split | refresh>
Ids: <TODO-NNN, ... or none>
Delete retired: <yes | no>
Project root: <absolute project root>
Guidance: <the guidance after the -- token (else the free text after the ids), or none>
```

## Step 3: report

Relay the agent's reply as it stands. The edits are saved, not committed; the developer reviews the diff and
commits. For a retirement the reply answers three questions: the new state of each touched stub (`Stubs`), the
research entries now fully resolved (`Resolved`), and the GitHub issues that can be closed, each with its reason
(`Close`). When the reply lists open items (a missing close-candidate evidence, a reference outside the catalog,
a stub kept for lack of proof, a failed check), name them first. The script's reference list leaves out every
file under `artifacts.plans` and `artifacts.reviews`, in-progress plans included: a TODO id in an old plan or
review is not a follow-up, but a live plan naming a moved id has to be checked by hand.
