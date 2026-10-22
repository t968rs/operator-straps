---
name: setup-statusline
description: Use when asked to set up, install, switch to or repair the ccstatusline status line for a project, or to replace the git-status mod's own status line (the one drawn with the warning glyph and the mod's name). Triggers on "setup-statusline", "set up ccstatusline", "use ccstatusline", "banner-status". Writes the project's statusLine setting and a ccstatusline defaults file.
argument-hint: "[--replace]"
---

# setup-statusline: ccstatusline as the project's status line

A plugin cannot ship a `statusLine` setting, so this skill writes it into the project. The result is one status
line drawn by ccstatusline from a config file in the project, with each widget in its own color and no
engine-drawn prefix. The git-status mod notices the setting and clears its own line while ccstatusline is
installed; without the install, the mod keeps drawing its line.

Arguments: `$ARGUMENTS` (`--replace`: replace an existing `statusLine` that does not run ccstatusline).

## Files written (project scope only)

| File | What |
|---|---|
| `<project>/.claude/settings.json` | the `statusLine` key; every other key kept as it is |
| `<project>/.claude/ccstatusline.json` | ccstatusline's config, copied from `${CLAUDE_SKILL_DIR}/ccstatusline.defaults.json` |

`<project>` is the repository's top level (`git rev-parse --show-toplevel`), written with forward slashes.
Nothing is written to the user's home folder: ccstatusline reads the project's file through `--config`, so the
user's own `~/.config/ccstatusline/settings.json` is left alone. The one write outside the project is the
optional global `npm install` of step 2, made only after the user says yes. `.claude/settings.json` is shared through the
repository, so the change reaches everyone who checks it out; say so in the report.

## Steps

1. **Find the project.** Run `git rev-parse --show-toplevel`; stop when it fails (not a repository).
2. **Check the install.** Run `ccstatusline --version`. A version other than 2.2.32 is fine to keep; mention
   it in the report. When the command fails, ccstatusline is an optional dependency that is not installed:
   offer to install it.

   1. Run `npm --version`. When it fails, Node.js and npm are missing: say so, name
      <https://nodejs.org/> and stop. Nothing below works without them.
   2. Ask with `AskUserQuestion` (header `ccstatusline`), stating that the install is global (it writes to
      npm's global prefix, outside the project) and runs `npm install -g ccstatusline@2.2.32`:
      - **Install now (Recommended):** run the command, then go to the check below.
      - **I will install it myself:** print the command and stop.
      - **Keep the current banner:** stop; mention the `band-line` mod as the option that needs no install.
   3. After an install, run `ccstatusline --version` again. When it still fails, npm's global bin folder is
      not on this session's `PATH`: print `npm prefix -g`, tell the user to put that folder on `PATH` and
      restart, and stop.

   ```
   npm install -g ccstatusline@2.2.32
   ```

   The pinned global install runs the binary directly on every repaint and changes only when the user
   upgrades; `npx -y ccstatusline@latest` would resolve the package on every repaint and pick up each new
   release unasked.
3. **Read the current setting.** Read `<project>/.claude/settings.json` when it exists.
   - A `statusLine` whose `command` already runs ccstatusline: go on (the run repairs it).
   - Any other `statusLine`: show it and stop, unless the arguments hold `--replace`.
4. **Write the defaults** to `<project>/.claude/ccstatusline.json`, only when that file is absent. An existing
   file is the user's tuning; keep it and say so.
5. **Write the setting.** Set this key in `<project>/.claude/settings.json` (create the file with only this
   key when it is absent), keeping every other key and the file's indentation:

   ```json
   "statusLine": {
     "type": "command",
     "command": "ccstatusline --config <project>/.claude/ccstatusline.json",
     "padding": 0
   }
   ```

   `<project>` is the absolute top level from step 1. ccstatusline resolves a relative `--config` against the
   folder the command runs in and writes a fresh defaults file where none is found, so an absolute path keeps
   a command run from another folder from creating a stray file.
6. **Report** the two paths and whether each was written or kept, then: restart the session to pick the
   setting up; the status line stays blank until the workspace trust dialog is accepted; `ccstatusline` run in
   a terminal with no piped input opens its editor (pass the same `--config` to edit this project's file).

## Undo

Remove the `statusLine` key from `<project>/.claude/settings.json`. The git-status mod draws its own line
again on its next refresh. `<project>/.claude/ccstatusline.json` can stay or go.
