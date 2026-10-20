# todo-watch

A view over a project's TODO catalog and the harness plugin's `todo_sync` checks, written as a CLI plugin
of function hooks. It shows the next TODO items with a small sync status line when a session starts, adds a
`TODO_SYNC` drift line to the prompt context, and answers `/todo` with the top items and every finding. The
notice is a band above the prompt by default, kept until its Dismiss button is pressed, its status line
following each sync change; `todo.notice.style: "toast"` posts it once as a toast instead, kept for
`todo.notice.toast_seconds` (60 s, the engine's ceiling).
The sync rules themselves live in Python (`harness_lib.todo_sync` behind `scripts/todo_sync.py`); the mod
only reads, gates and displays.

Every hook fails open: an unreadable file, a missing harness config, a missing runner pointer, a refused or
timed-out process run, or a malformed report or catalog degrades to "nothing to show". No hook blocks or
fails a tool call, a prompt or a turn on its own error.

## Activation and configuration

The watch is active only in a project whose `.claude/harness.json` reads and sets `todo.folder` to a
non-blank path; that one key is the whole setup (`"todo": {"folder": "docs/RESEARCH/_TODO"}`). Candidates for
the project root are the session cwd and each folder above it, nearest first (a subfolder, or a worktree
nested inside its checkout, finds the checkout's file), then `CLAUDE_PROJECT_DIR`; the first that holds
`.claude/harness.json` is the root. Finding the root spawns no process. With `todo.folder` null, or no
harness file, the mod registers no command, shows no notice and spawns nothing. The TODO paths are resolved
under `todo.folder` (`..` folds), as harness_lib resolves them. The folder and `artifacts.*` are
project-relative: they are joined to the root, and an absolute value is not supported. The harness schema
rejects it (`relPath`), and a rooted or drive-prefixed `todo.folder` leaves the mod inactive, as a null one
does, so it never reads files outside the project.

An installed mod lives in its own plugin cache folder and cannot read the harness plugin's
`config/defaults.json`, so `hooks/config.ts` carries copies of the values it needs and merges the
project's `harness.json` over them (objects key by key, scalars replace; malformed JSON or a wrong-typed
value keeps the default):

| Key | Default | Used for |
|-----|---------|----------|
| `state_dir` | `.claude/state/harness` | `<state_dir>/todo-sync/runner.json` (runner pointer) and `report.json` (sync report) |
| `artifacts.research` | `docs/RESEARCH` | watched folder (writes under it re-check) |
| `artifacts.plans` | `docs/PLANS` | watched folder |
| `todo.folder` | `null` | where the TODO files live; null turns the mod off |
| `todo.catalog` | `RepoToDo.json` (under the folder) | the TODO catalog the summary reads; watched file |
| `todo.catalog_schema` | `RepoToDo.schema.json` (under the folder) | watched file; null: not watched |
| `todo.top_n` | `10` | rows in the `/todo` table (the catalog read keeps `max(top_n, notice.items)` rows) |
| `todo.snapshots.dir` | `Snapshots` (under the folder) | watched folder; null: not watched |
| `todo.research.catalog` | `ResearchImplementationCatalog.json` (under the folder) | watched file; null: not watched |
| `todo.gh.max_age_hours` | `24` | `gh <age> old` suffix once the issue cache in the report is older |
| `todo.inject_context` | `true` | whether prompts carry the `TODO_SYNC` line |
| `todo.notice.style` | `banner` | `banner` or `toast` (M7); another value keeps the default |
| `todo.notice.toast_seconds` | `60` | seconds a toast stays; a value outside (0, 60] keeps the default |
| `todo.notice.items` | `3` | item lines in the notice (M1); a value that is not a whole number from 1 to 10 keeps the default |

`tests/mods/test_todo_watch_config_mirror.py` fails when `defaults.json` changes one of these values
without `config.ts` following.

## Behavior

| # | Rule | Behavior |
|---|------|----------|
| M1 | The next items are visible when a session starts | One notice at `session.start` (also after `/clear` or a resume): the first `todo.notice.items` catalog items by rank, one `<rank>  <title>` line each (the title on one line, clipped to 80 characters), then one status line: `✓ in sync` (theme color `success`) once a fresh report has no drift, `<N> out of sync` (`warning`) when it has drift, `sync checks unavailable` (dim) after the runner retry finds none, and no status line before any of these. A shorter catalog shows fewer lines; an unreadable one shows none. A view with no item line and no status shows nothing at all. A report older than the session start is never shown. |
| M2 | The model sees drift without anyone pasting it | `TODO_SYNC drift=4 G2=1 P1=1 S5=1` on `prompt.submit` (rule ids sorted by letter, then number), attached only when it changed since the line last attached, and again after `/clear`, a resume or a main compaction. No line before a report newer than the session start; `TODO_SYNC unavailable` once when checks are unavailable. |
| M3 | Changing a watched file re-checks within the turn | After a `Write`, `Edit`, `MultiEdit` or `NotebookEdit` call (`file_path`, or `notebook_path`) on a watched path (equal to the resolved TODO catalog, catalog schema or research catalog, or under `artifacts.research`, `artifacts.plans` or the snapshots folder; backslashes and a project-relative spelling accepted, case-insensitive on a Windows-style root), one check runs. After `Bash` / `PowerShell`, which name no path, the watched files and folders (and the folders' top-level entries, plus the entries one level under each `artifacts.research` subfolder) are stat-ed; a check runs only when one mtime is newer than the last check start (else the last report). Any other call spawns nothing. |
| M3b | Edits made outside the session are re-checked too | The same mtime probe on `prompt.submit` and on the main `turn.complete`. |
| M4 | Sync changes never nag | A new report, a catalog edit or checks becoming unavailable only recompute the notice view: a shown band updates its lines and status in place. Nothing ever shows, re-shows or posts on its own after the session start. |
| M5 | Full detail on demand | `/todo` prints the summary line (with ` · 4 out of sync`, ` · sync clean` and ` · gh 3d old` once a fresh report says so), the top-N table (`Rank \| Id \| Status \| Score \| Title`), then `sync drift N: <rules>` and each finding as `rule severity file:line subject: message (fix)`, or `sync clean`, `sync checks unavailable`, or `no report yet`. |
| M6 | The summary needs no engine | The mod reads the TODO catalog itself; the catalog and the report are re-read only when their mtime moved (`$.fs.stat`). |
| M7 | The notice shows as the project chose | `todo.notice.style` `banner` (default): the band above the prompt (`ui.render` on `AbovePrompt`) draws one live copy of the notice, each item line cut at the terminal edge, with a Dismiss button beside the status line (beside the last item line while there is no status). Dismiss hides it for the rest of the session; the next session start shows it again. `toast`: one toast at session start with the item lines (no sync status is known yet), its `timeoutMs` = `todo.notice.toast_seconds` x 1000 (a click takes it off sooner, the pointer over it holds it); later changes post nothing. The band yields to a survey and passes while hidden or empty, so in toast style it never draws. |

### Check runs

The harness SessionStart hook writes `<state_dir>/todo-sync/runner.json`:
`{"schema_version": 1, "python", "script", "project", "report", "written_at"}`. The mod looks it up at
`session.start`; when it is missing (or its `script` does not exist), it looks once more on the first
`prompt.submit` or main `turn.complete`. Only after that retry also finds none does it report
`sync checks unavailable` (on `/todo`, the context line and a shown band's status line; no new notice). While the lookup is pending nothing
says unavailable.

A check runs `[python, script, "check", "--project", project]` through `$.process.run` with a 20 s cap,
always after the dispatch that asked for it (`$.clock.after(0, ...)`), so no tool result or prompt waits
on it. One run is in flight at a time: a request while the engine process runs is owed one run after it, a
request before it starts folds into it. The pointer is read again before each run. The engine writes the
report itself and its stdout is ignored; a refusal, a timeout or a non-zero exit shows nothing. After a run
of its own the mod re-reads `report.json` (the pointer's `report`, else `<state_dir>/todo-sync/report.json`)
and keeps it only when its `generated_at` (else its mtime) is not older than the session start, floored to
the whole second (a check finishing in the start's own second may carry a whole-second stamp).

The report fields read are pinned to `plugins/harness/schemas/TodoSyncReport.schema.json` by
`tests/mods/test_todo_watch_report_contract.py`: `schema_version` (must be 1), `generated_at`, `drift`,
`by_rule`, `counts.error` / `counts.warn`, `gh_fetched_at` and `findings[]` (`rule`, `severity`, `counted`,
`file`, `line`, `subject`, `message`, `fix`). A report missing one of the top-level keys is ignored; a
malformed finding (or one whose severity is not `error` / `warn`) is skipped. A report from a
`check --rules` run (a `rules_skipped` reason `not selected`) covers only the selected rules and is ignored,
so a manual or test-suite subset run never shows as the project's drift. The same test pins the runner
pointer's `schema_version` and the keys `parseRunner` requires (`python`, `script`, `project`) to what the
harness `write_runner` emits, and checks that the finding parser reads its keys and severities through the
pinned constants.

## Hooks

| Hook | Does |
|------|------|
| `session.start` | Registers `/todo`, shows the start notice, looks up the runner pointer and schedules the first check. |
| `tool.call` on `Bash`, `PowerShell`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | After the call returns, schedules the path gate or the mtime probe (M3). |
| `turn.complete` (main loop) | The runner retry, then the catalog re-read and the mtime probe (M3b). |
| `prompt.submit` | The runner retry, the report re-read, the probe, and the `TODO_SYNC` line (M2). |
| `session.end`, `session.compact` | After `/clear`, a resume or a main compaction, the next prompt gets the line again. |
| `command.run` on `todo` | Answers `/todo` while the mod registered it; otherwise passes the command on. |
| `ui.render` on `AbovePrompt` | Draws the notice band with its Dismiss button (M7, banner style); passes while hidden, empty or under a survey. |

## State

`$.state['todo-watch']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `summary` | The catalog's counts and its top `max(todo.top_n, todo.notice.items)` items, with the catalog mtime; null when unreadable. |
| `report` | The latest report newer than the session start (drift, by rule, counts, issue cache time, findings, mtime). |
| `lastContext` | The `TODO_SYNC` line last attached to a prompt. |
| `notice` | The one live notice view (item lines, then the status text and tone), recomputed on every catalog, report or checks-status change; null at a session start. |
| `isNoticeShown` | Whether the band draws the notice: set at session start (banner style, non-empty view), cleared by Dismiss and at the next session start. |

## Known limitations

- The root search is remembered per cwd for the life of the hooks module: a `.claude/harness.json` created
  mid-session is seen after a reload. The file itself is read afresh on every hook, so a `todo` change in it
  applies at once.
- A nested `.claude/harness.json` between the cwd and the checkout root wins over the checkout's own, where
  the harness library's `project_root` (git's top level) would pick the checkout's.
- A linked worktree outside its checkout's folder (the `~/.config/superpowers/worktrees` convention) is not
  walked up to the main checkout. It finds only its own tracked `.claude/harness.json`, else falls back to
  `CLAUDE_PROJECT_DIR`. The mod then watches the main checkout while the harness hook (git's top level)
  resolves the worktree.
- The mtime probe lists the top level of each watched folder, and under `artifacts.research` one level
  deeper (the `<DOMAIN>/<stub>` files, so an in-place stub edit is seen); a change deeper than that made by a
  shell command or an IDE is seen only when it moves a watched file or a listed entry.
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
