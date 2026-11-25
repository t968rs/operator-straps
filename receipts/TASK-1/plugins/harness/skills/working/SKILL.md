---
name: working
description: Use when asked to set, show or clear the TODO ids and issue numbers the working-refs banner line shows for the current branch, overriding the refs of the plans that qualify for the branch; the line shows every branch's override, other branches bracketed after the current one's. Triggers on "/harness:working", "working on todo-k69m", "set the working refs", "banner refs override". The override is stored per branch in the checkout's state folder.
argument-hint: "<todo-id|#issue>... | --clear | --list [-- <guidance>]"
---

# working: the per-branch override of the working refs

The working-refs mod shows the TODO ids and issues a branch works on. By default they are the union of the
`refs` of the plans that qualify for the branch (its own plan, or a plan whose base commit is the branch's merge
base); an override set here replaces them for that branch only. The file is per checkout
(`<state_dir>/working-refs/overrides.json`), one entry per branch, and a detached HEAD is keyed `(detached)`.

Arguments: `$ARGUMENTS`

| Arguments | Effect |
|---|---|
| `<todo-id\|#issue>...` | store the refs as the current branch's override |
| `--list` | print every branch's override |
| `--clear` | drop the current branch's override |

Tokens are TODO ids (`todo-k69m`, `k69m`) or issue numbers (`#301`, `301`), separated by spaces or commas. When
no token names an issue, the issues come from the named TODO items in the catalog. The split between arguments
and free-text guidance follows `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: only the words before the
first standalone `--` are tokens; the words after it are guidance for the session and never reach the command
line. Tokens are ids, not free text, so the free-text rule that treats a leading `--` as optional does not
apply: `--` alone or first leaves no tokens.

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
| `--` (alone or first) | print the usage line below and stop |
| anything else | `WORKING set '<token>'...`, each word before a standalone `--` as a separate single-quoted argument |
| nothing | print the usage line below and stop |

Usage line: `usage: /harness:working <todo-id|#issue>... | --clear | --list [-- <guidance>]`

Quote every token in single quotes: in the Bash tool an unquoted word that starts with `#` opens a shell comment,
so `set todo-k69m #301` would run as `set todo-k69m` and drop the issue. For example,
`/harness:working todo-k69m #301 -- only the banner` runs `WORKING set 'todo-k69m' '#301'`. A word holding a
single quote is no valid token: print the usage line and stop.

A token that is neither a TODO id nor an issue number makes the script exit 1 with nothing written.

## Reply

The script's output, verbatim, and nothing else: `<branch>: <refs>`, `cleared <branch>`,
`no override for <branch>`, one `<branch>: <refs>` line per branch, or `no overrides`. On exit 1, the
`working:` line verbatim. On exit 2 (an argparse usage error), its stderr verbatim.
