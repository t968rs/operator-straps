# banner-status

Where the project's banner options live. The git state can show in one of three places; pick one:

| Option | How | Looks like |
|---|---|---|
| **ccstatusline status line** (preferred; needs Node.js and npm) | this plugin's `/banner-status:setup-statusline` | `⎇ main · ↑0↓0 · +2 · ~3 · ?1 · ✗`, each widget in its own color, no prefix |
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
| `.claude/ccstatusline.json` | ccstatusline's config, from `skills/setup-statusline/ccstatusline.defaults.json`; kept when present |

- **Optional dependency, not bundled:** installing this plugin does not install ccstatusline, and nothing
  changes on screen until the skill has run. It needs Node.js and npm and one global install,
  `npm install -g ccstatusline@2.2.32`, which writes to npm's global prefix outside the project. The skill
  checks `ccstatusline --version` and `npm --version`; when ccstatusline is missing it asks whether to run the
  install now, leave it to the user, or keep the current banner. The install runs only after a yes.
- **`PATH`:** the global bin folder (`npm prefix -g`) must be on the `PATH` of the shell that starts Claude
  Code. With a per-environment npm (conda, nvm) an install made in one environment is invisible from another;
  the skill re-checks after installing and says so when the command still does not resolve.
- **Pinned global, not `npx`:** the installed binary runs directly on every repaint and changes only on an
  upgrade; `npx -y ccstatusline@latest` resolves the package on every repaint and takes each release unasked.
- **Existing `statusLine`:** one that does not run ccstatusline is shown and kept unless the skill is run with
  `--replace`.
- **Shared:** `.claude/settings.json` is committed, so the setting reaches every checkout. A checkout without
  the install gets a blank line from ccstatusline and git-status's own line, not nothing.
- **Absolute `--config` path:** ccstatusline writes a defaults file wherever a relative path points and none
  exists, so the path is the project's absolute top level.
- **Workspace trust:** the status line stays blank until the trust dialog is accepted.

## Defaults

`ccstatusline.defaults.json` is ccstatusline's config schema version 4 (ccstatusline 2.2.32), one line:

| Widget | Color | Shows |
|---|---|---|
| `git-branch` | magenta | `⎇ <branch>` |
| `git-ahead-behind` | cyan | `↑ahead↓behind`, `↑0↓0` when in sync, `(no upstream)` |
| `git-staged-files` | green | `+<n>`, hidden at 0 |
| `git-unstaged-files` | blue | `~<n>`, hidden at 0 |
| `git-untracked-files` | red | `?<n>`, hidden at 0 |
| `git-clean-status` | green | `✓` clean, `✗` dirty |

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
