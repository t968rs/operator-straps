---
name: doctor
description: Use when a harness skill or hook fails on setup (a missing module, an interpreter that will not start, an unreadable harness.json), when starting the harness in a new repository, or when asked to check that the harness can run here. Triggers on "doctor", "harness doctor", "is the harness set up", "why does pr-review fail to start".
argument-hint: "[-- <guidance>]"
---

# doctor: check that the harness can run here

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. There is
nothing before the token to pass on. The part after it is the guidance, for example the symptom that prompted the
run; it never reaches the command.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/doctor/commands/doctor.py"
```

Run it with the Bash tool from the project checkout. It is read-only: nothing is installed, written or changed.
The first stdout line is the status (`doctor [ok|warn|fail] | ...`), then one line per check. Exit 1 means at
least one check failed; warnings exit 0.

| Check | Fails or warns when |
|---|---|
| `python` | The interpreter `hpy` picked is older than 3.11 (fail). |
| `interpreter` | `HARNESS_PY` or the plugin's `python` option is set but did not start, so `hpy` fell through (warn). Also warns when the `python` option is set in `~/.claude/settings.json` but the shell never received it, so `hpy` ran the PATH `python` instead. |
| `modules` | `pydantic>=2`, `referencing` or `jsonschema` is missing from that interpreter (fail). |
| `git` / `gh` | Not on PATH: `git` fails, `gh` warns (review and summary skills need it). |
| `repository` | The directory is not a git checkout (warn). |
| `config` | `.claude/harness.json` is unreadable or fails the schema (fail); an absent file is fine, defaults apply. |
| `worktree_root` | The configured worktree folder cannot be created (warn). |

## Afterward

- Report the status line and every `[warn]` or `[fail]` line with its `fix:` text, verbatim.
- Never run a `fix:` command. The install changes the developer's environment: hand over the exact line and wait
  for them to say it ran, then rerun the doctor.
- A `modules` failure names the interpreter the line installs into. That is the one `hpy` runs, which may differ
  from the `pip` first on PATH.
- To pin an interpreter for one project, the developer sets `HARNESS_PY` under `env` in the project's
  `.claude/settings.local.json`. A machine path does not belong in the committed `.claude/settings.json`.
- To pin one for every project, `HARNESS_PY` goes under `env` in `~/.claude/settings.json`. Prefer `HARNESS_PY`
  to the plugin's `python` option for skill commands: `settings.json` `env` reaches every shell command, while
  the option (`pluginConfigs` > `harness@<marketplace>` > `options` > `python`, set with
  `claude plugin configure harness`) was not exported to the shell skill commands run in, so `hpy` never saw it.
