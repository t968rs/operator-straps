# band-line

The oStraps banner in a band above the prompt: git-status's git snapshot, then the main loop's model and
context window. One of the banner options listed in `plugins/banner-status/README.md`.

## What it does

```
oStraps: ⎇ feature/x ↑2 ↓1 · +3 ~3 ?2 · (R,L):1,2 | [Opus 5.5] · ctx:110k 11%
```

- Branch (clipped to 32 characters), ahead/behind or `no upstream`, staged (`+`), unstaged and unmerged
  (`~`) and untracked (`?`) counts or `clean`, then `(R,L):<behind>,<ahead>`.
- `[model]` from `$.session.model()`, `ctx:<tokens> <percent>%` from `$.session.usage()`; each is left out
  until known (a fresh or just compacted session has no context figure yet).
- A branch with no upstream (or a detached head) draws in the warning color with a leading `⚠`.
- When the band is narrower than the line, the branch and tree are clipped (keeping at least 12
  characters); the commit counts and the session figures stay whole.

## Working line (optional)

When `working-refs` holds a working line, it draws as a second line in the subtle color directly under the
banner (`plan 2025 · todo-k69m banner (301) · [ other todo-zz99 ] +1`). The source is the `working-refs` mod's `line`
state value (`$.state['working-refs'].line`), read as an atom so the line redraws when it changes.
`working-refs` is optional and not listed under `dependencies`: while it is not installed, or its line is
null or empty, only the banner draws, exactly as before.

The second line's segments, in order, drawn from the `head`, `others` and `more` fields:

- `head`: the plans part and the branch's own refs, plain (`plan 2025 · todo-k69m banner (301)`); left out when empty.
- ` · ` between the head and the first other-branch segment, only when both exist.
- One `[ <branch> <refs> ]` per other branch, most recent first, separated by a space; the branch name draws
  dim (`dimColor`), the rest in the subtle color.
- ` +N` when `more` segments did not fit under working-refs's cap: after the last segment or the head, with a
  single space and no ` · `; with nothing before it, just `+N`.

The characters are those of the line's `text`, which is what an older working-refs sends alone (no `others`);
that `text` draws verbatim, with no dim names.

## Needs git-status

`git-status` takes the snapshot (`$.state['git-status'].git`) and attaches the per-prompt `GIT_STATE`
context; this mod only reads the snapshot, so it lists `git-status` under `dependencies`. With no snapshot
yet, the band draws nothing.

While this mod is loaded, git-status's own status line is cleared: a `ui.status` hook answers git-status's
calls with an empty line, so the git state shows once.

## Hooks

| Hook | Does |
|------|------|
| `session.start` | Reads the session figures and starts a 60 s refresh of them. |
| `turn.complete`, `prompt.submit` | Read the session figures; a write only when they moved. |
| `ui.status` | Clears the line when git-status sets it; every other plugin's line passes. |
| `ui.render` `AbovePrompt` | Draws the banner, then working-refs's working line (other-branch names dim) when one is set, above whatever the hooks beneath drew (agent-watcher's band stays on screen); yields to a survey. |

## State

`$.state['band-line']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `session` | The model id and context tokens and percentage the banner shows; all null before the first reading. |

## Known limitations

- The band draws only while git-status holds a snapshot. Outside a repository, or after a failed or
  timed-out `git status`, the model and context figures disappear along with the git part.
- The clipped head keeps at least 12 characters and the tail is never clipped, so a band narrower than the
  tail plus 12 overflows and wraps. The working line is not clipped at all.
- Width is counted in UTF-16 code units, not terminal cells: a wide character (CJK, emoji) in a branch name
  counts as one column, and a character outside the Basic Multilingual Plane as two.
- Only `claude-<family>-<n>[-<n>]` ids and bare aliases are shortened. Older-scheme ids
  (`claude-3-5-sonnet-...`) and provider-style ids show raw, cut to 24 characters.
- The context figure is read at session start, prompt submit, turn end and every 60 s, so during a long
  turn it can lag by up to 60 s.
- A branch whose upstream was deleted on the remote draws as in sync, without the warning glyph (see the
  git-status README).

## Checks

```
claude plugin validate --strict <mod folder>
claude plugin test <mod folder>
```

The `ui.status` hook is not covered by `claude plugin test` (the test engine raises no `ui.status`); check it
in a live session with both mods loaded: no `⚠ git-status:` line under the prompt.

## Loading

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install git-status@operator-straps
claude plugin install band-line@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env` block (or
`claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces the marketplace
copy of the same-named mod. The variable is one string, `;`-separated on Windows: append to its existing value
rather than replacing it.

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
