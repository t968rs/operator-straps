# session-bookmark

A compaction bookmark kept in session state instead of a file. It stands in for file-based `PreCompact`
and `SessionStart` compact|resume hooks that write a bookmark file and read it back after compaction.

Nothing in it is specific to one repository: it reads git state and the conversation, and depends on
no other mod.

## What it does

- On a `manual`, `auto` or `plugin` compaction of the main conversation, it records the branch,
  `git log --oneline -5`, `git status --porcelain` (first 40 entries, then a count of the rest), the
  last three prompts and the `/compact` instructions into `$.state['session-bookmark'].bookmark`.
  `$.state` outlives compactions and mod reloads.
- The same bookmark is appended to the compacted conversation as its last message, opening with
  `POST-COMPACT BOOKMARK (session-bookmark)`. The model reads it on the next request, so a mid-turn
  auto-compaction is covered too, and a resumed transcript already holds it.
- Git is read from the session cwd when it is a repository (a worktree the session moved into), else
  from `CLAUDE_PROJECT_DIR`. Git runs beside the summarizer (`GIT_OPTIONAL_LOCKS=0`, 5 s timeout per
  command); when core reuses a precomputed summary, the git calls are the compaction's only wait. A
  repository with no commits yet still reports its branch and status. When neither folder is a
  repository, or git is missing, the git fields are `null` and the prompts are still recorded.
- Precompute and subagent compactions pass through untouched. A skipped compaction records nothing.

## Command

| Name | Does |
|------|------|
| `/session-bookmark` | Prints the bookmark held in this session's state, or says none is held. `$.state` is promised to survive a reload, not a resume, so a resumed session can answer none while its transcript still carries a bookmark message. |

## State

`$.state['session-bookmark']` (contract: `types/index.d.ts`):

| Key | Type | Meaning |
|-----|------|---------|
| `bookmark` | `Bookmark \| null` | Latest compaction bookmark: time, trigger, root, branch, log, status, last prompts, instructions. |

## Known limitations

- `$.state` is per session: the bookmark reaches a new process only as the message already in the
  compacted transcript. Only the latest bookmark is kept; the old `history.log` has no equivalent.
- The bookmark has no session-id line, and its time is UTC ISO 8601 rather than local time with an
  offset.
- A previous compaction's summary is a user message, so it can appear among the "last user messages"
  when fewer than three prompts followed it.
- A session without this mod loaded gets no bookmark at all. Where the mod is enabled in project
  settings, a folder whose workspace trust was never accepted, including a `claude -p` run there,
  ignores those settings and compacts with no bookmark.
- A project that also keeps file-based bookmark hooks in its settings gets two bookmarks per compaction;
  remove those hooks when enabling this mod.
- A `CLAUDE_CODE_PLUGIN_DIRS` entry points at one checkout and replaces the marketplace copy, so with it
  set, which mod code loads follows that checkout's branch, not the session worktree's.
- `claude plugin test` runs in a Linux sandbox; Windows paths are passed to git as given.

## Checks

```
claude plugin validate <mod folder>
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
    "CLAUDE_CODE_PLUGIN_DIRS": "C:\\path\\to\\operator-straps\\plugins\\session-bookmark;C:\\path\\to\\operator-straps\\plugins\\pr-review-watch;C:\\path\\to\\operator-straps\\plugins\\git-status"
  }
}
```
