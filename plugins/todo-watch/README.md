# todo-watch

A view over a project's TODO catalog and the harness plugin's `todo_sync` checks, written as a CLI plugin
of function hooks. It shows a summary toast when a session starts, adds a `TODO_SYNC` drift line to the
prompt context, toasts when drift rises or clears, and answers `/todo` with the top items and every finding.
The sync rules themselves live in Python (`harness_lib.todo_sync` behind `scripts/todo_sync.py`); the mod
only reads, gates and displays.

Every hook fails open: an unreadable file, a missing harness config, a missing runner pointer, a refused or
timed-out process run, or a malformed report or catalog degrades to "nothing to show". No hook blocks or
fails a tool call, a prompt or a turn on its own error.

## Activation and configuration

The watch is active only in a project whose `.claude/harness.json` reads and sets `todo.catalog` to a
non-blank path. Candidates for the project root are the session cwd and each folder above it, nearest
first (a subfolder or a linked worktree finds its checkout's file), then `CLAUDE_PROJECT_DIR`; the first
that holds `.claude/harness.json` is the root. Finding the root spawns no process. With `todo.catalog`
null, or no harness file, the mod registers no command, toasts nothing and spawns nothing. Configured paths
are joined to the root unless absolute.

An installed mod lives in its own plugin cache folder and cannot read the harness plugin's
`config/defaults.json`, so `hooks/config.ts` carries copies of the values it needs and merges the
project's `harness.json` over them (objects key by key, scalars replace; malformed JSON or a wrong-typed
value keeps the default):

| Key | Default | Used for |
|-----|---------|----------|
| `state_dir` | `.claude/state/harness` | `<state_dir>/todo-sync/runner.json` (runner pointer) and `report.json` (sync report) |
| `artifacts.research` | `docs/RESEARCH` | watched folder (writes under it re-check) |
| `artifacts.plans` | `docs/PLANS` | watched folder |
| `todo.catalog` | `null` | the TODO catalog the summary reads; watched file; null turns the mod off |
| `todo.catalog_schema` | `null` | watched file |
| `todo.top_n` | `10` | rows in the `/todo` table |
| `todo.snapshots.dir` | `null` | watched folder |
| `todo.research.catalog` | `null` | watched file |
| `todo.gh.max_age_hours` | `24` | `gh <age> old` suffix once the issue cache in the report is older |
| `todo.inject_context` | `true` | whether prompts carry the `TODO_SYNC` line |

`tests/mods/test_todo_watch_config_mirror.py` fails when `defaults.json` changes one of these values
without `config.ts` following.

## Behavior

| # | Rule | Behavior |
|---|------|----------|
| M1 | TODO state is visible when a session starts | One toast at `session.start`, from the catalog: `TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: TODO-001` (`counts.items`, `counts.by_status` `OPEN` / `PARTIAL` / `BLOCKED`, `counts.needs_decision`, the rank-1 id; zero segments other than the total are left out). The start toast never carries drift: a report older than the session start is never shown. |
| M2 | The model sees drift without anyone pasting it | `TODO_SYNC drift=4 G2=1 P1=1 S5=1` on `prompt.submit` (rule ids sorted by letter, then number), attached only when it changed since the line last attached, and again after `/clear`, a resume or a main compaction. No line before a report newer than the session start; `TODO_SYNC unavailable` once when checks are unavailable. |
| M3 | Changing a watched file re-checks within the turn | After a `Write`, `Edit`, `MultiEdit` or `NotebookEdit` call (`file_path`, or `notebook_path`) on a watched path (equal to `todo.catalog`, `todo.catalog_schema` or `todo.research.catalog`, or under `artifacts.research`, `artifacts.plans` or `todo.snapshots.dir`; backslashes and a project-relative spelling accepted, case-insensitive on a Windows-style root), one check runs. After `Bash` / `PowerShell`, which name no path, the watched files and folders (and the folders' top-level entries) are stat-ed; a check runs only when one mtime is newer than the last check start (else the last report). Any other call spawns nothing. |
| M3b | Edits made outside the session are re-checked too | The same mtime probe on `prompt.submit` and on the main `turn.complete`. |
| M4 | New drift is noticed, old drift does not nag | A toast only when a new report's drift rises above the last toasted drift (`TODO sync drift 4 (+2): P1=1 S5=3`), and once when it reaches zero from non-zero (`TODO sync clean`). |
| M5 | Full detail on demand | `/todo` prints the summary line (with ` · 4 out of sync`, ` · sync clean` and ` · gh 3d old` once a fresh report says so), the top-N table (`Rank \| Id \| Status \| Score \| Title`), then `sync drift N: <rules>` and each finding as `rule severity file:line subject: message (fix)`, or `sync clean`, `sync checks unavailable`, or `no report yet`. |
| M6 | The summary needs no engine | The mod reads `todo.catalog` itself; the catalog and the report are re-read only when their mtime moved (`$.fs.stat`). |

### Check runs

The harness SessionStart hook writes `<state_dir>/todo-sync/runner.json`:
`{"schema_version": 1, "python", "script", "project", "report", "written_at"}`. The mod looks it up at
`session.start`; when it is missing (or its `script` does not exist), it looks once more on the first
`prompt.submit` or main `turn.complete`. Only after that retry also finds none does it report
`sync checks unavailable` (on `/todo` and the context line; no toast). While the lookup is pending nothing
says unavailable.

A check runs `[python, script, "check", "--project", project]` through `$.process.run` with a 20 s cap,
always after the dispatch that asked for it (`$.clock.after(0, ...)`), so no tool result or prompt waits
on it. One run is in flight at a time: a request while the engine process runs is owed one run after it, a
request before it starts folds into it. The pointer is read again before each run. The engine writes the
report itself and its stdout is ignored; a refusal, a timeout or a non-zero exit shows nothing. After a run
of its own the mod re-reads `report.json` (the pointer's `report`, else `<state_dir>/todo-sync/report.json`)
and keeps it only when its `generated_at` (else its mtime) is not older than the session start.

The report fields read are pinned to `plugins/harness/schemas/TodoSyncReport.schema.json` by
`tests/mods/test_todo_watch_report_contract.py`: `schema_version` (must be 1), `generated_at`, `drift`,
`by_rule`, `counts.error` / `counts.warn`, `gh_fetched_at` and `findings[]` (`rule`, `severity`, `counted`,
`file`, `line`, `subject`, `message`, `fix`). A report missing one of the top-level keys is ignored; a
malformed finding is skipped.

## Hooks

| Hook | Does |
|------|------|
| `session.start` | Registers `/todo`, toasts the catalog summary, looks up the runner pointer and schedules the first check. |
| `tool.call` on `Bash`, `PowerShell`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | After the call returns, schedules the path gate or the mtime probe (M3). |
| `turn.complete` (main loop) | The runner retry, then the catalog re-read and the mtime probe (M3b). |
| `prompt.submit` | The runner retry, the report re-read, the probe, and the `TODO_SYNC` line (M2). |
| `session.end`, `session.compact` | After `/clear`, a resume or a main compaction, the next prompt gets the line again. |
| `command.run` on `todo` | Answers `/todo` while the mod registered it; otherwise passes the command on. |

## State

`$.state['todo-watch']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `summary` | The catalog's counts and its top `todo.top_n` items, with the catalog mtime; null when unreadable. |
| `report` | The latest report newer than the session start (drift, by rule, counts, issue cache time, findings, mtime). |
| `lastContext` | The `TODO_SYNC` line last attached to a prompt. |
| `lastToastDrift` | The drift last toasted; null before any drift toast. |

## Known limitations

- The root search is remembered per cwd for the life of the hooks module: a `.claude/harness.json` created
  mid-session is seen after a reload. The file itself is read afresh on every hook, so a `todo` change in it
  applies at once.
- A nested `.claude/harness.json` between the cwd and the checkout root wins over the checkout's own, where
  the harness library's `project_root` (git's top level) would pick the checkout's.
- The mtime probe lists only the top level of each watched folder; a change deep inside `artifacts.research`
  made by a shell command or an IDE is seen only when it moves a watched file or a top-level entry.
- A Bash or IDE change made between a check's start and its report is caught by the next probe; one made in
  the same millisecond as the check start is not.

## Checks

```
claude plugin validate --strict <mod folder>
claude plugin test <mod folder>
```

`hooks/testWorld.ts` is the mocked world the hook tests share (never imported by `register.ts`): the plugin
test sandbox cannot read repository files, so every `$` call is answered from memory, under `/repo` and
`C:/repo` roots alike.

## Loading

Install from the `operator-straps` marketplace:

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install todo-watch@operator-straps
```

For development, `claude --plugin-dir <folder>` loads the folder for one session, or a
`CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env` block loads it with hot
reload (see `plugins/pr-review-watch/README.md`, Loading).

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
