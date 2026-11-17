# banner-status: ccstatusline as the primary status line

Status: built on `1063-banner-branding`; see "As built" at the end for where the build departs from the
draft below. Origin: issues #57 (banner counts) and #58 (host-drawn prefix), follow-up
framework comment on #57. Source reads: sirmalloc/ccstatusline `main` (`src/types/Settings.ts`,
`src/types/Widget.ts`, `src/utils/config.ts`, `src/ccstatusline.ts`, `src/widgets/GitAheadBehind.ts`,
`src/widgets/CustomCommand.tsx`, `configTemplates/official-cc.json`) and the engine type declarations.

## Decisions

| # | Decision |
|---|----------|
| 1 | **Banner content: built-in widgets only.** `git-branch`, `git-ahead-behind` (zero state shown), working-tree counts. No custom-command script; the arrows carry the same numbers as `commits(R,L)`. |
| 2 | **New plugin `banner-status`** is the home for banner options: the setup skill, the ccstatusline defaults template and the docs. The `git-status` mod keeps its own line as the fallback. |
| 3 | **Project scope only.** The skill writes `<project>/.claude/settings.json` (`statusLine`) and `<project>/.claude/ccstatusline.json` (defaults). No `settings.local.json`, no user-level write. The agent running the skill makes the edits; the user approves the permission prompts. |
| 4 | **Pinned global install** of ccstatusline, not `npx -y ccstatusline@latest` (see below). |
| 5 | **The band stays an option.** The `oStraps:` band from `174dac4` (branch `1062-banner-branding`, #62) moves into its own mod, `band-line`, rather than replacing git-status's line; ccstatusline remains the preferred option. |

## Verified facts

| Fact | Source |
|------|--------|
| Settings default to `~/.config/ccstatusline/settings.json`; `--config <path>` overrides it in render mode too (parsed first). | `config.ts` `DEFAULT_SETTINGS_PATH`, `initConfigPath`; `ccstatusline.ts` `parseConfigArg` |
| Schema is zod, `version: 4`, `lines` = 1..3 arrays of widget items `{id, type, color?, rawValue?, metadata?, commandPath?, ...}`; unknown widget `type` strings are accepted. | `Settings.ts`, `Widget.ts` |
| A missing file is written with defaults on first run. An unreadable or invalid file is never overwritten: defaults are used in memory and a config-warning badge is prepended. | `config.ts` `loadSettings` |
| Piped stdin renders, a TTY opens the TUI. Output starts with a reset code and spaces become non-breaking. | `ccstatusline.ts` `main` |
| Git widgets (branch, changes, staged, unstaged, untracked, status, ahead/behind, ...) are cached for `gitCacheTtlSeconds` (default 5). | widget list, `Settings.ts` |
| `git-ahead-behind` prints `↑ahead↓behind` (symbols overridable), hides at 0/0 unless the `zero` hide state is turned off (`metadata.hide`), prints `(no upstream)` unless that state is hidden. Order is ahead then behind, the reverse of `commits(R,L)`. | `GitAheadBehind.ts` |
| The engine exposes `$.settings.read({ key })` (merged value of one top-level settings key) and `$.fs.read` / `$.fs.write`. | engine `index.d.ts` |
| A plugin cannot ship `statusLine`; plugin settings accept only `agent` and `subagentStatusLine`. `statusLine` runs only in trusted workspaces. | Claude Code docs (via lookup agent, not re-read by hand) |

## Pinned global vs npx

| | `npx -y ccstatusline@latest` | pinned global (`npm install -g ccstatusline@<version>`, command `ccstatusline`) |
|---|---|---|
| Per repaint | npx resolves the package every time; slow, and needs network when its cache is cold | runs the installed binary directly |
| Updates | always the newest release, silently | only when the user upgrades |
| Install step | none | one command, run once per machine |
| If missing | fetches it | command not found, status line blank |

The README states the pinned form avoids repeated package resolution. Because a project-scope `statusLine` is shared,
a teammate without the global install gets a blank status line: the skill checks `ccstatusline --version` and prints the
install command (run by the user, not the skill) when it is absent.

## Components

### `plugins/banner-status` (new)

- `skills/setup-statusline/SKILL.md`, user-invoked. Steps for the agent:
  1. Read `<project>/.claude/settings.json`. If a `statusLine` is already present and does not name ccstatusline, show it and stop unless the user says to replace it.
  2. Run `ccstatusline --version`. When absent, print `npm install -g ccstatusline@<pinned version>` for the user and stop.
  3. Copy `defaults.json` (below) to `<project>/.claude/ccstatusline.json` only when that file is absent.
  4. Merge `{"statusLine": {"type": "command", "command": "ccstatusline --config <project>/.claude/ccstatusline.json", "padding": 0, "refreshInterval": 10}}` into `settings.json`, keeping every other key; forward slashes in the path.
  5. Tell the user to restart or reload, and that the status line stays blank until workspace trust is accepted.
- `skills/setup-statusline/defaults.json`: `version: 4`, one line: `git-branch` (magenta), `git-ahead-behind` (cyan, `zero` hide state off so `↑0↓0` shows), `git-status` or the staged/unstaged/untracked widgets; `gitCacheTtlSeconds: 5`, `colorLevel: 2`.
- `.claude-plugin/plugin.json`, README section, entry in `.claude-plugin/marketplace.json` and the root README plugin table.
- Writes go to the consuming project only; nothing is written under the plugin root (`tests/contract/test_root_separation.py` stays satisfied).

### `plugins/git-status` (change)

- Before drawing, read `await $.settings.read({ key: 'statusLine' })`. When its `command` names ccstatusline **and** `ccstatusline --version` runs (`$.process.run`), clear the mod's line with `$.ui.status(undefined)`; otherwise draw as today. Checking the binary keeps a missing install from leaving the user with no banner at all.
- Re-evaluate on every refresh so removing ccstatusline brings the fallback back. The per-prompt `GIT_STATE` context is unchanged.
- The mod's `commits(R,L)` text (#57) stays for the fallback line.

## Tests

- Mod (`plugins/git-status/hooks/status.test.ts`): `statusLine` absent; another command; ccstatusline with the binary present (line cleared); ccstatusline with the binary missing (line drawn); a `statusLine` change between refreshes; a refused or throwing `$.settings.read` keeps the line.
- Plugin (`tests/`): contract tests for the new plugin (manifest valid under `claude plugin validate --strict`, skill command paths use `${CLAUDE_SKILL_DIR}`), and a check that `defaults.json` parses and holds the widget types the README names.
- Live, by the developer: glyph and prefix absent, colors honored, Windows quoting of the `--config` path, repaint cost with the pinned install.

## Open questions (resolved in the build unless marked)

1. `$.settings.read({ key: 'statusLine' })`: the engine types take any key string; covered by mod tests with a
   mocked read. **Open:** confirm against a live session.
2. Pinned version: `ccstatusline@2.2.32`, whose `CURRENT_VERSION` is 4 (`src/types/Settings.ts` at tag `v2.2.32`).
3. Binary check: no process run. `$.process.run` spawns without a shell, so a Windows npm shim (`.cmd`) would
   not start; the mod looks for the executable file under `PATH` with `$.fs.exists` and keeps the answer per
   executable and `PATH`.
4. Shared `statusLine`: kept project scope (decision 3); the skill's report says the file is shared.

## As built

| Area | Draft | Built |
|---|---|---|
| Choice of banner | ccstatusline, else git-status's line | three options: ccstatusline (preferred), `band-line` band, git-status's line (fallback) |
| git-status gives way to ccstatusline | `ccstatusline --version` per refresh | `delegateExecutable` + `executableCandidates` (`plugins/git-status/hooks/status.ts`): the `statusLine` command's first word, found as a file under `PATH` (`.cmd`, `.exe` tried); `npx`/`bunx` forms count |
| git-status gives way to the band | n/a | `band-line` hooks `ui.status` and clears the line when `next.origin.plugin` is git-status; not unit-testable (the test engine has no `ui.status`), live check |
| band-line | n/a | `plugins/band-line`: `174dac4`'s band and session figures; reads `git-status.git` (another plugin's state, read-only; `dependencies: ["git-status"]` types it) |
| pr-review-watch | unchanged | `174dac4`'s change: its band wraps what the hooks beneath drew, so both bands show (0.4.0; only `174dac4`'s hunks, not `2789881` beneath it) |
| `statusLine` command | `... "refreshInterval": 10` | `{"type": "command", "command": "ccstatusline --config <project>/.claude/ccstatusline.json", "padding": 0}`; the absolute path keeps ccstatusline from writing a stray defaults file when run from another folder |
| Defaults file | `defaults.json` | `ccstatusline.defaults.json`: branch, ahead/behind (zero shown), `+`/`~`/`?` file counts (labels via `metadata.label`, zero hidden), clean status; rendered by ccstatusline 2.2.32 with no config warning |
| Contract test | `tests/` contract | `tests/skills/test_setup_statusline_contract.py` |

Live checks left for the developer: the band-line `ui.status` suppression, `$.settings.read` of `statusLine`,
the ccstatusline line under the prompt (no glyph or prefix, colors honored), and the Windows `--config` path.
