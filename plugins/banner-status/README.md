# banner-status

Where the project's banner options live. The git state can show in one of three places; pick one:

| Option | How | Looks like |
|---|---|---|
| **ccstatusline status line** (preferred; needs Node.js and npm) | this plugin's `/banner-status:setup-statusline` | `⎇ main (+38,-15)` over `Opus 5.5 \| Thinking: high \| Ctx: 110.0k - 55%`, no prefix |
| **oStraps band** above the prompt | enable the `band-line` mod | `oStraps: ⎇ main · +2 ~3 ?1 · (R,L):0,0 \| [Opus 5.5] · ctx:110k 11%` |
| **git-status's own line** (fallback) | `git-status` alone | `⚠ git-status: ⎇ main · +2 ~3 ?1 -- commits(R,L):0,0` (the engine adds the glyph, the name and the color) |

`git-status` stays installed in every case: it takes the git snapshot and attaches the per-prompt `GIT_STATE`
context. Its own line clears itself when the project's `statusLine` runs an installed ccstatusline, and
`band-line` clears it while that mod is loaded.

## `/banner-status:setup-statusline`

A plugin cannot ship a `statusLine` setting, so the skill has the agent write two project files, each edit
approved by the user:

| File | What |
|---|---|
| `.claude/settings.json` | `"statusLine": {"type": "command", "command": "ccstatusline --config <project>/.claude/ccstatusline.json", "padding": 0}` |
| `.claude/ccstatusline.json` | ccstatusline's config, from `skills/setup-statusline/ccstatusline.defaults.json`; when present, only gains the working-refs line, or has an old `working-refs/line.txt` widget's `commandPath` replaced, on a yes |

- **Optional dependency, not bundled:** installing this plugin does not install ccstatusline, and nothing
  changes on screen until the skill has run. It needs Node.js and npm and one global install,
  `npm install -g ccstatusline@~2.2.32`, which writes to npm's global prefix outside the project. The skill
  checks `ccstatusline --version` and `npm --version`; when ccstatusline is missing it asks whether to run the
  install now, leave it to the user, or keep the current banner. The install runs only after a yes.
- **`PATH`:** the global bin folder (`npm prefix -g`) must be on the `PATH` of the shell that starts Claude
  Code. With a per-environment npm (conda, nvm) an install made in one environment is invisible from another;
  the skill re-checks after installing and says so when the command still does not resolve.
- **Patch-pinned global, not `npx`:** `~2.2.32` means 2.2.32 or a later 2.2.x, never 2.3 (the range is
  resolved once, at install time, so a new minor cannot change the config schema the defaults use). The
  installed binary then runs directly on every repaint and changes only on an upgrade; `npx -y
  ccstatusline@latest` resolves the package on every repaint and takes each release unasked. The `~` form
  pastes cleanly into PowerShell, cmd and sh; `^` is cmd's escape character.
- **`state_dir`:** the skill reads `state_dir` from `.claude/harness.json` (default `.claude/state/harness`) and
  rewrites the `.claude/state/harness` part of the working-refs widget's command when it differs, written
  with forward slashes (a backslash is an escape inside the command's quoted JS string). The command passes
  the path to `path.resolve`, so a relative `state_dir` lands under the project and an absolute one is kept as
  given (and is then shared by every checkout).
- **Working-refs line, opt-in for an existing file:** an existing `.claude/ccstatusline.json` keeps its tuning;
  the skill asks, and on a yes appends only the working-refs `custom-command` line as a new last line. An
  existing widget that still names the old `working-refs/line.txt` has its `commandPath` replaced on a yes,
  and nothing else changes. A new file gets the line with the other defaults. The widget needs the
  working-refs mod.
- **Existing `statusLine`:** one that does not run ccstatusline is shown and kept unless the skill is run with
  `--replace`.
- **Shared:** `.claude/settings.json` is committed, so the setting reaches every checkout. A checkout without
  the install gets a blank line from ccstatusline and git-status's own line, not nothing.
- **Absolute `--config` path:** ccstatusline writes a defaults file wherever a relative path points and none
  exists, so the path is the project's absolute top level.
- **Workspace trust:** the status line stays blank until the trust dialog is accepted.

## Defaults

`ccstatusline.defaults.json` is ccstatusline's config schema version 4 (ccstatusline 2.2.32), three lines:

| Line | Widget | Color | Shows |
|---|---|---|---|
| 1 | `git-branch` | magenta | `⎇ <branch>` |
| 1 | `git-ahead-behind` | yellow | commits ahead of and behind the upstream |
| 1 | `git-clean-status` | default | whether the working tree is clean |
| 1 | `git-conflicts` | default | merge conflicts, when present |
| 1 | `git-sha` | default | the short SHA of `HEAD` |
| 2 | `model` | default | the model's display name, `Opus 5.5` |
| 2 | `thinking-effort` | brightCyan | `Thinking: <level>` |
| 2 | `context-length` | brightBlue | `Ctx: <tokens>`, `Ctx: 110.0k` |
| 2 | `context-percentage` | default | the context window used, whole percent |
| 3 | `custom-command` | the command's own | the working-refs line, read from `<state_dir>/working-refs/line.json` |

The third line is only useful with the working-refs mod, which writes that file. The command reads the status
JSON that ccstatusline pipes to its stdin and resolves the file against `workspace.project_dir` (else `cwd`),
so a session launched in a worktree prints that checkout's line. The widget reads the branch the line was
built for from `line.json` and the checkout's `HEAD` from `.git` (a worktree's `gitdir:` file is followed),
with no git call; when the stamped branch differs from `HEAD`'s, it prints that branch dark before the line.
When `line.json` is absent (an older working-refs wrote only `line.txt`), it falls back to `line.txt`. The mod picks the checkout from the session
`cwd` first, so a session launched elsewhere whose `cwd` later moves into a worktree shows the launch folder's
line here while band-line shows the worktree's. `customCommandCacheTtlSeconds` stays 0 so the line
follows each refresh.

Git results are cached for 5 s (`gitCacheTtlSeconds`). Edit the project file with
`ccstatusline --config <project>/.claude/ccstatusline.json` in a terminal (its editor opens when no input is
piped).

## Loading

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install banner-status@operator-straps
```

## Checks

```
claude plugin validate --strict <plugin folder>
python -m pytest tests/skills/test_setup_statusline_contract.py -q
```
