---
name: working
description: Use when asked to set, show or clear the TODO ids and issue numbers the working-refs banner line shows for the current branch, overriding what the branch name and its plan say. Triggers on "working", "working on todo-k69m", "set the working refs", "banner refs override". The override is stored per branch in the project's state folder.
argument-hint: "-- <todo-id|#issue>... | --clear | --list"
---

# working: the per-branch override of the working refs

The working-refs mod shows the TODO ids and issues a branch works on. By default they come from the branch name
and its plan; an override set here wins for that branch only. The file is per project
(`<state_dir>/working-refs/overrides.json`), one entry per branch, and a detached HEAD is keyed `(detached)`.

Arguments: `$ARGUMENTS`

| Arguments | Effect |
|---|---|
| `<todo-id\|#issue>...` or `-- <todo-id\|#issue>...` | store the refs as the current branch's override |
| `--list` | print every branch's override |
| `--clear` | drop the current branch's override |

Tokens are TODO ids (`todo-k69m`, `k69m`) or issue numbers (`#301`, `301`), separated by spaces or commas. When
no token names an issue, the issues come from the named TODO items in the catalog. The split between arguments
and free-text guidance follows `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the guidance never reaches the
command line.

## Running the script

Run the script with the Bash tool, one command per call, no other command and no file read or edit (the script
owns the file):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/working.py" <subcommand> ...
```

`WORKING` below stands for everything before `<subcommand>`. It stores under the project of the working
directory; pass no `--repo`. The first word of the arguments picks the action:

| First word | Action |
|---|---|
| `--list` | `WORKING list` |
| `--clear` | `WORKING clear` |
| anything else | `WORKING set <token>...`, each token as a separate argument |
| nothing | print the usage line below and stop |

Usage line: `usage: /harness:working <todo-id|#issue>... | --clear | --list`

A token that is neither a TODO id nor an issue number makes the script exit 1 with nothing written.

## Reply

The script's output, verbatim, and nothing else: `<branch>: <refs>`, `cleared <branch>`,
`no override for <branch>`, one `<branch>: <refs>` line per branch, or `no overrides`. On exit 1, the
`working:` line verbatim.
