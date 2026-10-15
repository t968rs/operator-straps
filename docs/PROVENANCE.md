# Provenance

The harness was imported from `t968rs/floodplain_development` `origin/dev` at `c5ce7313d` (2026-10-13), following
the file manifest in floodplain_development issue #1561. History was not carried over; this file is the link back.

Additional sources at import time:

| Imported path | Origin |
|---|---|
| `plugins/harness/skills/d-w/**`, `tests/skills/test_detached_worktree_script.py` | floodplain branch `skill-d-w` (`2454831be` tip at import) |
| `plugins/harness/hooks/{bash_discipline,bash_allow_shapes,powershell_allow_shapes}.py` | `t968rs/t968rs_claude` working tree, `.claude/hooks/*.py` |
| `plugins/harness/skills/{fold-in-review,agent-permissions}/**` | `t968rs/t968rs_claude` working tree, `skills/` (fold-in-review was untracked there) |
| `plugins/harness/skills/consumer-contract-audit/{SKILL.md,repo-fixtures.schema.json}` | same; the fpm `repo-fixtures.json` data stays with floodplain_development |
| `plugins/harness/skills/{merge-commit,searching-sourcegraph}/**` | floodplain `origin/dev` at `107d70a90` (2026-10-14), `.claude/skills/` |
| `plugins/harness/skills/check-runlogs/commands/latest_runlog.py` | floodplain `origin/dev` at `107d70a90`, `scripts/_script_runners/_RUN_TESTS.py`: the log-name timestamp rules (`timestamp`, `_get_console_filename_date`, `sort_paths_by_timestamp`), rewritten against `runlogs.*` config; the runner and its archiving stay with floodplain_development. No verbatim import commit |
| `plugins/harness/skills/strap-debugging/**` | `obra/superpowers` `main` at `bb92a77` (2026-10-10), `skills/systematic-debugging/` (MIT, Jesse Vincent; `LICENSE` copied beside it). Verbatim except: the `SKILL.md` frontmatter `name`/`description` and "(when installed)" on its two `superpowers:` skill pointers; `find-polluter.sh` reads paths whole (spaces survive), takes an optional test command (default `npm test`), stops on exit 126/127 and refuses a pollution target that exists before any test runs (its `.git` example became `packages/core/.git`), exits 2 when the pattern matches no test file or the usage is wrong (exit 1 is reserved for a found polluter), counts and reports test files that exited non-zero, runs each test with stdin from `/dev/null`, and its "To investigate" hints echo the configured test command with the quoted file; `root-cause-tracing.md` shows the script's skill-directory path, the test-command argument and the absent-target rule; `CREATION-LOG.md` and the `test-*.md` pressure scenarios left out |
| `plugins/pytest-scope/hooks/{interpreter,scope}{,.test}.ts` | floodplain `origin/dev` at `107d70a90`, `.claude/mods/fpm-guardrails/hooks/{interpreter,testScope,registry}{,.test}.ts`: the interpreter rewrite and the broad pytest deny; registry guard tracking and the registry lookup stay with floodplain_development |

The import commit is verbatim (paths moved, content unchanged except `.gitignore`). Every later commit is a
decoupling or packaging change against it.

## Path map

| floodplain_development | operator-straps |
|---|---|
| `scripts/gh_workflows/*.py` (minus `sync_copilot_exclusions.py`) | `plugins/harness/lib/harness_lib/` |
| `scripts/_admin_utils/git_status_filter_excluded.py` | `plugins/harness/lib/harness_lib/` |
| `.claude/hooks/hook_scripts/{id_handling,pr_json_validation}.py` | `plugins/harness/lib/harness_lib/validation/` |
| `.claude/agent_scripts/*.py`, `scripts/_admin_utils/txt_to_commit_dict.py` | `plugins/harness/scripts/` |
| `.claude/hooks/{check_phase5_sentinel,validate-pr-json-schema}.py`, `approve-python-c.sh` | `plugins/harness/hooks/` (the `.sh` became `approve_python_c.py`) |
| `.claude/agents/{messenger,pr-*,roast-my-code}.md` | `plugins/harness/agents/` |
| `.claude/agent-schemas/**` (minus `CICDActionAudit`) | `plugins/harness/schemas/` |
| `.claude/skills/<generic>/**` | `plugins/harness/skills/` |
| `.claude/CLAUDE.md` | `plugins/harness/rules/HARNESS_RULES.md` (cut to the generic half) |
| `docs/conventions/commit_format.md` | `plugins/harness/reference/commit_format.md` |
| `.claude/mods/{pr-review-watch,session-bookmark}/**` | `plugins/{pr-review-watch,session-bookmark}/` |
| `.claude/mods/fpm-guardrails/hooks/status{,.test}.ts` | `plugins/git-status/hooks/` (generic half only, after the split) |
| `scripts/__tests__/{discipline,pr_review,_admin_utils}/...` (the 23 moved + 5 split tests) | `tests/{lib,scripts,hooks,skills,schemas,mods}/` |
