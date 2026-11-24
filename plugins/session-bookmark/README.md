# session-bookmark

A compaction bookmark kept in session state instead of a file. It stands in for file-based `PreCompact`
and `SessionStart` compact|resume hooks that write a bookmark file and read it back after compaction.

Nothing in it is specific to one repository: it reads git state, the conversation and the project's notes
file (`.claude/harness.json` for `state_dir`). Notes need the harness plugin's add-bookmark skill, and the
session hook switch is written only by the harness plugin's add-bookmark or add-todo skills; the rest depends on
no other plugin.

## What it does

- On a `manual`, `auto` or `plugin` compaction of the main conversation, it records the branch,
  `git log --oneline -5`, `git status --porcelain` (first 40 entries, then a count of the rest), the
  last three prompts, the stored session notes and the `/compact` instructions into
  `$.state['session-bookmark'].bookmark`.
  `$.state` outlives compactions and mod reloads.
- The same bookmark is appended to the compacted conversation as its last message, opening with
  `POST-COMPACT BOOKMARK (session-bookmark)`. The model reads it on the next request, so a mid-turn
  auto-compaction is covered too, and a resumed transcript already holds it.
- Notes added with the `harness:add-bookmark` skill print in a `## Session Notes` section, after the last
  user messages and before the `/compact` instructions. They are read at each compaction from
  `<state_dir>/session-bookmark/notes.json` under the git top level of the session cwd, else of
  `CLAUDE_PROJECT_DIR`; when neither is a repository, the first of the cwd and `CLAUDE_PROJECT_DIR` that holds
  a notes file is read. `state_dir` comes from `.claude/harness.json` (default
  `.claude/state/harness`). The newest 20 notes are kept, each cut at 300 characters. An absent, malformed or
  other-version file means no notes section; a note stays until it is removed or cleared with
  `/harness:add-bookmark`.
- Each note prints as the skill's `--list` does: a standing note as its text alone, a note added on the
  bookmark's branch as `[<branch>] <text>`, and a note added on another branch as
  `[<branch>; now on <current>] <text>`. When any note carries the `now on` marker, one hint line under
  `## Session Notes` says such a note is confirmed with the developer before it is applied or skipped, never
  dropped silently. With the branch unknown or a detached HEAD, no note is marked (on a detached HEAD the
  `- Branch:` line shows `HEAD`; with the branch unknown it shows `(unknown)`).
- Git is read from the session cwd when it is a repository (a worktree the session moved into), else
  from `CLAUDE_PROJECT_DIR`. Git runs beside the summarizer (`GIT_OPTIONAL_LOCKS=0`, 5 s timeout per
  command); when core reuses a precomputed summary, the git calls and the notes read are the compaction's only
  wait. A
  repository with no commits yet still reports its branch and status. When neither folder is a
  repository, or git is missing, the git fields are `null` and the prompts are still recorded.
- Precompute and subagent compactions pass through untouched. A skipped compaction records nothing.
- Fallback: a mod before this one can answer `session.compact` without calling `next`, so this mod's hook never
  runs. The mod also watches `session.append` for the main loop's `compaction` row; when one arrives and this
  mod appended no bookmark since the last such row or prompt, the next prompt carries the bookmark as context (trigger
  `detected`, stored in state as usual). It covers a compaction whose row reaches `session.append` while this
  mod's `session.compact` hook did not run. The engine types do not say whether a compaction a mod answers
  itself with `{ messages }` still stores a `compaction` row, so it is not promised for every reroute. A
  slash-command line (`/compact`, `/clear`, `/session-bookmark`) never carries it, and the bookmark stays owed
  until a prompt enters with it: a dropped prompt leaves it for the next one. `/clear` and a resume forget it.

## Session hook (optional goal)

A goal, free text or a TODO item, can be made the session's goal. Three harness-plugin routes write the hook
switch, `<state_dir>/session-bookmark/hook.json`:

- `harness:add-bookmark --goal <condition>` (`add_note.py goal`): a free-text goal; the switch's `todo_id` is
  null and it carries only `goal`, `start_time` and `todo_id`.
- `harness:add-bookmark --goal-todo <id> <closing>` (`add_note.py goal --todo <id> --closed-by <closing>`): an
  item already in the catalog.
- `harness:add-todo --hook <closing>`: marks the run, and once the inbox drain lands the item,
  `add_todo.py hook --todo <id> --closed-by <closing>` arms it.

A switch for an item:

```json
{"version": 1, "hook": {"closed_by": "retired", "desc": "<item title>", "start_time": 1763600000.5,
 "todo_id": "todo-af2e", "goal": "TODO todo-af2e (<item title>) is retired from the TODO catalog ..."},
 "fired": null}
```

- At the end of each main-loop turn (`turn.complete`, no `agentId`), `hooks/session_hook.ts` reads the switch
  under the git top level of the session cwd, else of `CLAUDE_PROJECT_DIR` (the root the harness writers
  use); when neither is a repository, the first of the cwd and `CLAUDE_PROJECT_DIR` that holds a switch is
  read. While `fired` is null it queues `/goal <goal>` through
  `$.command.run` (the command runs once the session is idle), then stamps `fired: { at }`, so a switch sets
  its goal once. `/goal` is the engine's session-scoped Stop hook: its evaluator keeps the session working until
  the condition holds; `/goal clear` ends it, `add_note.py goal --clear` or `add_todo.py hook --clear` removes
  the switch.
- Closings, each one the agent meets by itself, since `/goal` re-checks at every stop and a condition that
  waits on the developer loops the session: `retired` (the item is retired from the catalog), `committed`
  (tests passed and the commit message is drafted), `developer` (tests passed and a reply hands the item to the
  developer with the files changed and what is left).
- A refused `/goal` (an unknown command, past a Stop, a host limit) leaves the switch armed and shows one toast;
  the switch is tried once per mod load, so the next load retries it. When `/goal` is set but the `fired`
  stamp cannot be written, a different toast says the goal was set and the switch is still armed: the next
  load would set it again, so `add_note.py goal --clear` removes it. A switch re-armed or cleared while
  `/goal` was queued is left as it is, not stamped.
- Fallback, should `/goal` be unavailable where the mod runs: a temporary `Stop` hook in
  `.claude/settings.local.json` that the file watcher loads and drops without a restart (issue #282's gate).
  The mod does not write it; a live session confirmed `/goal` runs from `$.command.run`.

## Command

| Name | Does |
|------|------|
| `/session-bookmark` | Prints the bookmark held in this session's state, or says none is held. `$.state` is promised to survive a reload, not a resume, so a resumed session can answer none while its transcript still carries a bookmark message. |
| `/session-bookmark notes` | Reads the notes file live (no compaction needed) and prints every stored note (no 20-note cut, so a hand-edited file holding more still numbers as the script does) with the same numbering and branch markers as `/harness:add-bookmark --list`, the hint line first when a note is from another branch, or `no notes`. A file the script would refuse (not JSON, no notes list, another version) answers `notes file unreadable; /harness:add-bookmark --clear resets it`; the compaction bookmark still prints no notes section for it. Answers with text and no model turn. Any other argument prints `usage: /session-bookmark [notes]`. |

## Hooks

| Hook | Does |
|------|------|
| `session.start` | Registers `/session-bookmark`. |
| `session.compact` on triggers `manual`, `auto`, `plugin` (main loop) | Starts the git and notes capture beside the summarizer, then appends the bookmark message to the compacted conversation and stores it in state. A subagent's compaction and a skipped one pass through. |
| `session.append` (door `compaction`, main loop) | Marks the bookmark owed when this mod's `session.compact` hook appended none since the last such row or prompt (the fallback in What it does). |
| `prompt.submit` | Clears the appended mark; a prompt entered while a bookmark is owed carries it as context (trigger `detected`). A slash-command line never carries it. |
| `session.end` | After `/clear` or a resume, forgets the appended and owed marks. |
| `turn.complete` (main loop, no `agentId`) | While the hook switch is armed and not fired, queues `/goal <goal>` through `$.command.run` and stamps `fired` (Session hook). |
| `command.run` on `session-bookmark` | Answers `/session-bookmark` and `/session-bookmark notes` (Command). |

## State

`$.state['session-bookmark']` (contract: `types/index.d.ts`):

| Key | Type | Meaning |
|-----|------|---------|
| `bookmark` | `Bookmark \| null` | Latest compaction bookmark: time, trigger (`detected` for the fallback), root, branch, log, status, last prompts, notes, instructions. |

## Known limitations

- `$.state` is per session: the bookmark reaches a new process only as the message already in the
  compacted transcript. Only the latest bookmark is kept; the old `history.log` has no equivalent.
- The bookmark has no session-id line, and its time is UTC ISO 8601 rather than local time with an
  offset.
- A previous compaction's summary is a user message, so it can appear among the "last user messages"
  when fewer than three prompts followed it.
- The notes file is per project folder, not per session: two sessions in one repository share their notes, and
  a note nobody clears reaches the next session's bookmark. A linked worktree reads its own file.
- The hook switch carries no session id either: with two sessions on one checkout, the first to end a main-loop
  turn after the switch is armed queues the `/goal` and stamps it fired.
- A session without this mod loaded gets no bookmark at all. Where the mod is enabled in project
  settings, a folder whose workspace trust was never accepted, including a `claude -p` run there,
  ignores those settings and compacts with no bookmark.
- A project that also keeps file-based bookmark hooks in its settings gets two bookmarks per compaction;
  remove those hooks when enabling this mod.
- A `CLAUDE_CODE_PLUGIN_DIRS` entry points at one checkout and replaces the marketplace copy, so with it
  set, which mod code loads follows that checkout's branch, not the session worktree's.
- The compaction fallback waits for the next prompt: a mid-turn auto-compaction that another mod kept from
  this mod's `session.compact` hook leaves the rest of that turn without a bookmark. The fallback bookmark
  carries no recent prompts (the compacted ones are gone) and no `/compact` instructions.
- A mod before this one that calls `next` and then replaces the result's `messages` with its own drops the
  bookmark this mod appended, and the fallback does not catch it: the hook did run, so the compaction's row
  owes nothing.
- `claude plugin test` runs in a Linux sandbox; Windows paths are passed to git as given.

## Checks

```
claude plugin validate --strict <mod folder>
claude plugin test <mod folder>
tsc -p <mod folder>   # once the engine has generated .claude-plugin/types/ by loading the mod
```

## Loading

Install from the `operator-straps` marketplace:

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install session-bookmark@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the `env` block of the user-level
`~/.claude/settings.json` (or `claude --plugin-dir <folder>` for one session) loads the folder with hot
reload and replaces the marketplace copy of the same-named mod, so it never runs twice. The variable is
one string, `;`-separated on Windows: append to its existing value rather than replacing it. The
project's settings are not read for this variable.

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "C:\\path\\to\\operator-straps\\plugins\\session-bookmark;C:\\path\\to\\operator-straps\\plugins\\agent-watcher;C:\\path\\to\\operator-straps\\plugins\\git-status"
  }
}
```
