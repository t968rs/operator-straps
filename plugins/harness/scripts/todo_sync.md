# `todo_sync.py` usage

`todo_sync.py` is the harness plugin's command-line driver for a project's TODO catalog (`todo.catalog`, under
`todo.folder` in `.claude/harness.json`). It checks the catalog and the research and plan artifacts around
it for drift, renders the snapshot page, adds, retires, splits and re-ranks items, queues drafted items in an
inbox, holds the catalog lease, and switches an old catalog to stable ids once.

It is a Python script, not a slash command. Skills, the `harness:todo-editor` agent and the `todo-watch` mod
run it, and a person can run it by hand. It always runs through the plugin's launcher, from the project
root:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" <command> [options]
```

`main(argv)` parses `argv` (the command line when `None`), runs one command and returns its exit code. A bad
argument raises `SystemExit(2)` from argparse instead of returning.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The command ran. |
| 1 | `check --fail-on`: a finding reached the given severity. An unexpected error also exits 1, with a traceback on stderr. |
| 2 | Refused: a configuration error, an unknown rule id, a refused operation, a lock held by another owner or a failed `gh` call. One `problem: <reason>` line goes to stderr. A bad argument also exits 2, with argparse's usage message. |

## Global options

Both go before or after the command.

| Option | Default | Meaning |
|---|---|---|
| `--project DIR` | the git top level of the working directory | The project whose `.claude/harness.json` and catalog are used. |
| `--config FILE` | `<project>/.claude/harness.json` | An alternate `harness.json` to read instead. |

## Who runs what

| Command | Run by |
|---|---|
| `check` | The `todo-watch` mod after catalog edits; `add --inbox` and `lease release` run it too. |
| `render` | A person, on demand; `init`, `add --inbox` and `lease release` render too. |
| `runner` | A person. The harness SessionStart hook writes the same pointer without the command. |
| `retire`, `split`, `refresh` | The `harness:todo-editor` agent, dispatched by `/harness:todo-edit`. |
| `init` | `/harness:add-todo` and `/harness:sync-gh-todo` when the catalog does not exist yet, or a person. |
| `untracked` | `/harness:sync-gh-todo`; the agent again when its file is missing. |
| `add --spec` | A person. No skill or agent runs it: they queue items with `inbox put` instead. |
| `add --inbox` | `/harness:add-todo` and `/harness:sync-gh-todo` after their agent returns, and the `todo-watch` mod. |
| `inbox put` | The `harness:todo-editor` agent, for `add` and `sync` runs. |
| `lease acquire`, `lease release` | The `harness:todo-editor` agent, around a retire, split or refresh run. |
| `lease break` | A person, to clear the lock of a crashed holder. |
| `migrate-ids` | A person only; the agent names it and never runs it. |

## Locking

Every catalog write (`init`, `add`, `retire`, `split`, `refresh`; never a dry run) holds the catalog lock,
`<state_dir>/locks/<catalog path with '/' as '__'>.lock`: a write lock for one command, or, with
`--lease TOKEN`, the lease that token names. A lock another owner holds is waited on for 10 seconds, then
refused naming its owner, mode and age. `check`, `render`, `runner`, `untracked`, `inbox put` and every dry
run take no lock. `add --inbox` takes the lock only when a file is queued; with nothing queued it prints
`inbox: empty` and takes none. A real `migrate-ids` run holds a catalog lease of its own for the whole run and
frees it afterwards, or, with `--lease TOKEN`, runs under that lease and leaves it held. A catalog that still
holds `TODO-NNN` ids refuses `untracked`, `add`, `retire`, `split` and `refresh`, naming `migrate-ids`.

## Commands

### `check`

Runs the sync rules and writes the report (`TodoSyncReport.schema.json`) atomically. With `todo.folder` null
the check is inactive: it prints one line, exits 0 and writes nothing.

| Option | Meaning |
|---|---|
| `--format summary\|json\|markdown` | What to print: one `todo-sync drift=...` line (default), the report as JSON, or a findings table. |
| `--out PATH` | Where to write the report (default `<state_dir>/todo-sync/report.json`). |
| `--rules S1,S2` | Run only these rule ids. Each left-out rule is marked `not selected` in `rules_skipped`, and the `todo-watch` mod ignores such a subset report. |
| `--fail-on warn\|error` | Exit 1 when a finding reaches this severity: `error` counts errors, `warn` counts warns and errors. |

### `render`

Rewrites the one snapshot page, `<todo.snapshots.dir>/TODO_Snapshot.html` (T2 header line, catalog summary,
top-N table, the remaining items folded in a second table), and its `todo_live.js` stamp, which an open page
polls to reload itself. Prints the page's path.

| Option | Meaning |
|---|---|
| `--date YYYY-MM-DD` | The render date the page shows (default today). |

### `runner`

Writes the runner pointer, `<state_dir>/todo-sync/runner.json` (interpreter, this script, project, report),
and prints its path. The `todo-watch` mod reads it to know how to run this script. No options.

### `retire`

`retire ID [ID ...]` removes finished items and records their ids in `retired_ids`, which no new id reuses.
Nothing is renumbered and no id is rewritten: the kept items take ranks 1..n in order, items that lose their
only unblocked item are rescored, the counts are recomputed, and only the catalog is written. Prints the
follow-up the catalog cannot record by itself: resolved issues to list as close candidates, trackers to
revisit, research catalog and stub lines naming a retired id (`dangling:`), and other files naming a retired
id (`reference (not rewritten):`).

| Argument | Meaning |
|---|---|
| `ID` | One or more item ids: `todo-k7qf` or `k7qf`, any case. |
| `--dry-run` | Print the same report and write nothing. |
| `--lease TOKEN` | Run under the lease this token names instead of taking the write lock. |

### `split`

`split ID --spec PATH` replaces one item with the parts in a spec file. Every part gets a new id; the
original id joins `retired_ids`, and `split_ids` records its parts in spec order. Parts inherit the item's
links, tracker and close candidates; then the catalog is rescored, re-ranked and recounted. Files naming the
split id are listed (`dangling:`, `reference (not rewritten):`), never rewritten.

| Argument | Meaning |
|---|---|
| `ID` | The item to split: `todo-k7qf` or `k7qf`, any case. |
| `--spec PATH` | Required. JSON file `{"parts": [{...}, {...}]}`: each part is a set of field overrides laid over a copy of the item; `title` is required, and `id`, `rank` and `priority` are refused. |
| `--dry-run` | Print the result with ids of its own and write nothing; the real run draws again. |
| `--lease TOKEN` | Run under the lease this token names instead of taking the write lock. |

### `refresh`

Rescores every item from `ranking_method`, re-sorts, and sets each rank to its position, after hand edits to
item fields. Ids never change, only the catalog is written, and a catalog already in order is left untouched.

| Option | Meaning |
|---|---|
| `--dry-run` | Print the result and write nothing. |
| `--lease TOKEN` | Run under the lease this token names instead of taking the write lock. |

### `init`

Creates the TODO folder, an empty schema-valid catalog (default ranking tables, no items, the current commit
in `generated_from`) and the snapshot page with its stamp (both skipped when `todo.snapshots.dir` is null).
Prints a `created <path>` line for the catalog and one for the page, then
`next: todo_sync.py check, or /harness:sync-gh-todo to add the open issues`. Refuses, exit 2, when the catalog
already exists; needs `todo.folder` and a git commit. When the catalog is written but the page render fails,
the catalog stays, no `created` or `next:` line prints, and exit 2 follows a `problem:` line on stderr that
names `todo_sync.py render` as the next step.

| Option | Meaning |
|---|---|
| `--lease TOKEN` | Run under the lease this token names instead of taking the write lock. |

### `untracked`

Lists the open GitHub issues that no catalog record covers (no resolving item, tracker, child, close candidate
or research entry; `related_gh_issues` does not count), using `gh issue list` in `todo.gh.repo`, else the
repository `gh` resolves for the checkout. Prints an `untracked: N open issue(s) in no catalog record` header,
one `#N title` line per issue, then `wrote <path>` for the rows (issue text, comments, linked PR review text)
at `<state_dir>/todo-sync/untracked.json`. Prints `untracked: none` and writes nothing when no issue is open
outside the catalog. Refuses, exit 2, when `gh` fails, returns no JSON list or hits the
listing limit. No options.

### `add`

Adds items to the catalog, either from a spec file or from the inbox. Exactly one of `--spec` and `--inbox`
is required.

| Option | Meaning |
|---|---|
| `--spec PATH` | JSON file `{"items": [{...}, {...}]}`. Each entry holds the fields a person judges (never `id`, `rank` or `priority`) and names its `issue` and `url`, or neither. Each item gets a new stable id and a source (`gh_issue`, or a local `note` dated today), is scored, and the catalog is re-sorted and recounted. An issue the catalog already records is refused. Only the catalog is written: the snapshot page waits for the next render. |
| `--inbox` | Add every queued inbox file in one catalog write, oldest first. Accepted files are deleted; a refused one is renamed `<name>.rejected.json` beside a `<name>.reason.txt`. When any item lands, the page is rendered and the check run. Prints `inbox: added N item(s): ...; check drift=D`, `inbox: rejected K (<files>)`, or `inbox: empty` (without taking the lock). |
| `--dry-run` | With `--spec` only: print the result with ids of its own and write nothing. |
| `--file-issue` | With `--spec` only: file a GitHub issue (`gh issue create`) for each entry that names none, once the whole spec passes a dry run, and record it as the item's `gh_issue` source. A dry run files nothing and prints `would file N issue(s)`. |
| `--lease TOKEN` | Run under the lease this token names instead of taking the write lock. |

### `inbox put`

Queues the items of an `add` spec in the inbox (`<scratch_folder>/todo-inbox/`), one file per item, after a
dry run of the whole spec against the catalog. The catalog is never written and no lock is taken. Prints one
`queued <path>` line per file and one `filed #N <url>` line per issue filed.

| Option | Meaning |
|---|---|
| `--spec PATH` | Required. The same JSON file `add --spec` takes. |
| `--file-issue` | File a GitHub issue for each entry that names none first, as `add` does. |

### `lease acquire`

Takes the catalog lease for a run of several commands and prints `lease: <token>`. Until it is released,
every catalog write without `--lease <token>` (the `todo-watch` drain included) waits, then refuses naming
the holder. A lease turns stale after 30 minutes.

| Option | Meaning |
|---|---|
| `--owner TEXT` | Required. Who holds the lease; named in every refusal. |

### `lease release`

`lease release TOKEN` recounts the catalog (written only when the counts change), renders the snapshot page
(when `todo.snapshots.dir` is set), runs the check, writes its report and frees the lease. Prints
`lease released; counts updated|unchanged`, `rendered <path>` and `check drift=D`. A wrong token or no lease
refuses and frees nothing; a recount, render or check failure still frees the lease and exits 2.

| Argument | Meaning |
|---|---|
| `TOKEN` | The token `lease acquire` printed. |

### `lease break`

Removes whatever lock or lease the catalog holds: the manual override for a crashed holder. Prints the
removed holder's owner, mode and age, or `lease: none held`. No options.

### `migrate-ids`

Switches a catalog from rank-tied `TODO-NNN` ids to stable `todo-xxxx` ids, once. Each new id is seeded from
the old id and the title, so a dry run, its real run and two checkouts of one catalog agree; the
`old -> new` map is stored in the catalog's `legacy_ids`. Every live file naming an old id is rewritten
through the map (research catalog, stubs, and each text file `git grep` finds), except the catalog schema,
the history folders and each `--exclude`. A rerun on a migrated catalog rewrites the remaining references
through the stored map.

| Option | Meaning |
|---|---|
| `--dry-run` | Print the new ids and the files it would rewrite; write nothing. |
| `--exclude PATH` | Leave files under `PATH` as written. Repeatable; absolute or relative to the working directory, below the project root, matched by path component (`vendor` skips `vendor/x.md`, never `vendored.md`). |
| `--lease TOKEN` | Run under this held lease and leave it held. Without it, a real run takes a lease of its own for the whole run and frees it afterwards. |
