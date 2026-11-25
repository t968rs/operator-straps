# git-status

A git status line and a per-prompt `GIT_STATE` context line, written as a CLI plugin of function hooks.
Cross-platform: it runs `git` through the engine, with no shell script.

## What it does

Status line (at most 80 characters):

```
⎇ feature/x ↑2 ↓1 · +3 ~3 ?2 -- commits(R,L):1,2
```

The branch (clipped to 32 characters), ahead/behind its upstream or `no upstream`, then staged (`+`),
unstaged and unmerged (`~`) and untracked (`?`) counts, or `clean`. The `commits(R,L)` tail is always
present: `R` counts commits only the remote has (behind), `L` commits only the local branch has (ahead);
both are `0` when the branch has no upstream. When the line runs over 80 characters, the part before the
tail is clipped and the tail stays whole.

Prompt context, attached only when it changed since the line last attached:

```
GIT_STATE BRANCH=feature/x UPSTREAM=origin/feature/x AHEAD=2 BEHIND=1 STAGED=3 UNSTAGED=3 UNTRACKED=2 DIRTY=true
```

After `/clear`, a resume or a compaction of the main conversation, the next prompt gets the line again even
when unchanged.

## When another banner draws the git state

The status line is the fallback banner (the engine draws it as `⚠ git-status: <line>`, in its own color). It
gives way to the other banner options (`plugins/banner-status/README.md`):

- **ccstatusline:** an optional dependency that no plugin installs on its own (Node.js and npm, then
  `npm install -g ccstatusline@~2.2.32`; `/banner-status:setup-statusline` offers to run it and writes the
  `statusLine` setting). Once the merged `statusLine` setting's command runs ccstatusline (`ccstatusline ...`, or
  through `npx` / `bunx`) and the command's first word is found (as given, or under a `PATH` folder, with
  `.cmd` and `.exe` tried; for the `npx` / `bunx` forms that word is the launcher), the mod clears its line on every refresh. The lookup is kept per executable and `PATH` for
  the life of the module, so an install made mid-session shows after a restart. Without the executable the
  mod keeps drawing, so a checkout without the install still has a banner.
- **band-line:** that mod clears this line while it is loaded.

The snapshot and the `GIT_STATE` context are kept in every case.

## Project root

`git -C <start> rev-parse --show-toplevel`, asked first from the session cwd (a linked worktree resolves to
itself) and then from `CLAUDE_PROJECT_DIR`. The first top level git answers is the root; a start
folder's top level, once found, is kept for the life of the module, and a failed lookup is asked again on
the next refresh. No repository anywhere clears the status line and
attaches nothing.

## Hooks

| Hook | Does |
|------|------|
| `session.start` | Starts a 60 s background refresh and refreshes once. Each refresh reads the `statusLine` setting to decide whether the line gives way to ccstatusline. |
| `tool.call` on `Bash`, `PowerShell`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | Refreshes after the call returns, without delaying it. |
| `turn.complete` | Refreshes. |
| `prompt.submit` | Runs its own `git status` (after a background run in flight, waiting at most 2 s) and attaches the `GIT_STATE` line when it changed. |
| `session.end`, `session.compact`, `session.append` (door `compaction`) | Force the next prompt's line after `/clear`, a resume or a main compaction; the `session.append` hook covers a compaction whose `session.compact` chain another mod ended first. |

Background runs coalesce: one `git status` in flight, at least 2 s between background starts, and a
request made while one runs is owed a single run after it. `git status` runs with
`GIT_OPTIONAL_LOCKS=0`, so it never takes the index lock. Every failure (git missing, not a repository,
a timeout) clears the status, a refused status line is ignored, and none blocks a prompt or a tool call.

## State

`$.state['git-status']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `git` | The latest snapshot (branch, upstream, ahead, behind, staged, unstaged, untracked); null after a failed run. |
| `lastContext` | The `GIT_STATE` line last attached to a prompt. |

## Known limitations

- No fetch: ahead and behind come from the last fetch made elsewhere; the mod never contacts the remote,
  so `R` stays stale until a fetch.
- A gone upstream reads as in sync: when the tracked remote branch was deleted, git prints the upstream
  but no ahead/behind line, so the line shows zero counts and not `no upstream`.
- Changes outside the tracked tools (an IDE, another terminal) show at the next turn end, prompt or 60 s
  tick.
- Untracked counts are entries: a new untracked folder counts as one, and `status.showUntrackedFiles=no`
  hides untracked files entirely.
- Every prompt pays for a `git status`: it waits up to 2 s for a background run, then runs its own with a
  10 s timeout; a slower repository gets no line and no `GIT_STATE`.
- ccstatusline is detected from the command text: a wrapper script whose command does not name
  ccstatusline is not recognized, so both lines draw.

## Checks

```
claude plugin validate --strict <mod folder>
claude plugin test <mod folder>
```

## Loading

Install from the `operator-straps` marketplace:

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install git-status@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env` block (or
`claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces the marketplace
copy of the same-named mod. The variable is one string, `;`-separated on Windows: append to its existing value
rather than replacing it.

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
