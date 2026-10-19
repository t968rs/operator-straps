[![ci](https://github.com/t968rs/operator-straps/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/t968rs/operator-straps/actions/workflows/ci.yml)
# operator-straps

A Claude Code plugin marketplace that carries an agent harness: PR review and fix waves, commit and PR-summary
drafting, guard hooks, worktree flow, and session mods. A project opts in with one config file; everything
project-specific (artifact folders, test layout, guard suites, commit buckets, base branch) lives there.

| Plugin | What it adds |
|---|---|
| `harness` | Skills, agents, hooks and scripts: `pr-review`, `pr-team`, `c-msg`, `branch-commit-msg`, `pr-sum`, `d-w`, `check-runlogs`, `strap-debugging` and more |
| `pr-review-watch` | Run tracking for `pr-review` / `pr-team`: Phase 5 band, `PHASE5_PENDING=` prompt line, bubble Stop guard, matrix rows |
| `git-status` | Git status line and a per-prompt `GIT_STATE` context line |
| `session-bookmark` | Compaction bookmark: git state, last prompts and `/compact` instructions survive a compaction |
| `pytest-scope` | Bare `pytest` rewritten to the configured project interpreter; pytest runs that name no test file denied |
| `todo-watch` | TODO catalog summary toast, a per-prompt `TODO_SYNC` drift line and `/todo`; drift checks run through the harness `todo_sync` engine |

The mods (`pr-review-watch`, `git-status`, `session-bookmark`, `pytest-scope`, `todo-watch`) are independent of
each other. `pr-review-watch` stays inactive in any project without `.claude/harness.json`, and `todo-watch` in
any project whose `harness.json` sets no `todo.folder`; `todo-watch` runs drift checks only while the `harness`
plugin is installed (its SessionStart hook writes the runner pointer). `pytest-scope` does nothing until one of
its options is set.

## Install

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install harness@operator-straps
claude plugin install pr-review-watch@operator-straps
claude plugin install git-status@operator-straps
claude plugin install session-bookmark@operator-straps
claude plugin install pytest-scope@operator-straps --config python=C:/path/to/env/python.exe --config require_test_file=true
claude plugin install todo-watch@operator-straps
```

This repository enables its own plugins in `.claude/settings.json` from the published marketplace (the same
`t968rs/operator-straps` GitHub source as above), so sessions here run the cached copy from the pushed default
branch, not the checkout. Edits under `plugins/` take effect only after merge, version bump and
`claude plugin marketplace update operator-straps`; to exercise them before that, run
`claude --plugin-dir plugins/<name>` or add the checkout as a local marketplace (`claude plugin marketplace add ./`).

Installing from `/plugin` inside a session opens a dialog for each unset option instead; the CLI install takes
`--config KEY=VALUE`. `pytest-scope` options (see `plugins/pytest-scope/README.md`):

| Option | Default | Meaning |
|---|---|---|
| `python` | unset | Absolute path of the interpreter bare `pytest` runs under. Unset: no rewrite |
| `require_test_file` | `false` | Deny pytest calls with no test path or a directory path |

`harness` options (`claude plugin configure harness`):

| Option | Default | Meaning |
|---|---|---|
| `python` | unset | Interpreter for harness scripts and hooks. Needs `jsonschema`, `referencing`, `pydantic>=2` |
| `bash_discipline` | `true` | Deny Bash commands chained with `&&` or `;` |
| `inject_rules` | `true` | Add `rules/HARNESS_RULES.md` to the session context at start |

### Python

Every hook and script runs through `plugins/harness/scripts/hpy`, which picks the first interpreter that starts:
`HARNESS_PY` (project settings `env`), then the `python` option, then `python`, then `py -3`. It skips the Windows
Store `python3` stub. It does not probe for `jsonschema` / `referencing` / `pydantic`; the code that needs them
reports a missing module itself: the schema hook stands down with a one-line warning, and `pr-review` /
`pr-team` (whose driver models reviews in pydantic and validates them with jsonschema / referencing) check all
three before any subcommand runs and exit 1 with one `problem:` line naming the first one missing. Commit, summary and
worktree tooling need only the standard library.

## Configure a project

Create `.claude/harness.json` in the consuming repository. Every key is optional; objects merge key by key over
`plugins/harness/config/defaults.json`, arrays and scalars replace. The schema is
`plugins/harness/config/harness.schema.json`.

```json
{
  "base_branch": "dev",
  "integration_branches": ["dev", "main"],
  "exclusions": "reference/machine_generated_exclusions.json",
  "artifacts": {"reviews": "docs/PR_REVIEWS", "plans": "docs/PLANS", "summaries": "docs/PR_SUMMARIES"},
  "tests": {"roots": ["src/tests/"], "registry": "src/tests/registry.json", "registry_names": ["registry.json"]},
  "review": {
    "guard_suite": ["src/tests/guards/test_ci_workflows.py"],
    "structural_guard_prefixes": [".github/workflows/"],
    "domain_pointers": [{"prefix": "src/geo/", "pointer": "Geometry code never imports the GIS runtime at module level."}]
  },
  "commit_buckets": [
    {"bucket": "Runtime", "prefixes": ["src/pkg/"]},
    {"bucket": "Test", "prefixes": ["src/tests/"]}
  ],
  "auto_approve_python_c": true,
  "worktree_root": "~/worktrees/{repo}",
  "runlogs": {"dir": "logs/test_runs"},
  "todo": {"folder": "docs/RESEARCH/_TODO"}
}
```

TODO sync needs only `todo.folder`. With it set, the catalog is `<folder>/RepoToDo.json`, snapshots go to
`<folder>/Snapshots`, and `<folder>/RepoToDo.schema.json` and `<folder>/ResearchImplementationCatalog.json` are
used when they exist; stubs are `_IMPL_TODO.md` files under `artifacts.research`. Set a key below only to depart
from that layout.

| Key | Default | Used by |
|---|---|---|
| `base_branch` | `origin/HEAD`, else `main` | merge bases, `d-w`, `pr-review-watch` |
| `integration_branches` | base branch + `main` | `d-w` (fetch-and-cut targets) |
| `state_dir` | `.claude/state/harness` | Phase 5 sentinels, pr-team runtime (gitignore it) |
| `artifacts.*` | `docs/PR_REVIEWS`, `docs/PLANS`, ... | review, plan, summary and commit-message output |
| `tests.*` | `tests/`, common test-file pattern | review bucketing, commit grouping |
| `tests.timings` | `null` | pr-review fixer briefs: a JSON report whose `tests` rows carry `file` (repo-relative POSIX, spelled exactly as the registry entry's `file`) and `duration` (seconds), summed per file; missing or unreadable means no runtime deferral. Stock pytest JSON reports key rows by nodeid with per-phase durations and do not match |
| `tests.fixer_test_seconds` | `null` (no runtime rule) | pr-review fixer briefs: a registered test summing over this many seconds in `tests.timings` is deferred (listed, not run; `closeout` prints it). With `tests.timings` missing or unusable, the ceiling is inactive and `waves` prints a `deferral:` notice |
| `tests.defer_flags` | `[]` | pr-review fixer briefs: dotted registry-entry paths (e.g. `properties.super_slow`); `true` at any of them defers the test |
| `review.*` | empty | Phase 1 guard suites, lens catalog, reviewer-brief rule pointers |
| `commit_buckets` | generic `src/`, `tests/`, `docs/` rules | `c-msg`, `branch-commit-msg` grouping |
| `exclusions` | `null` | clean-tree checks ignore machine-generated files |
| `auto_approve_python_c` | `false` | `approve_python_c` hook |
| `worktree_root` | `~/.config/superpowers/worktrees/{repo}` | `d-w`, `parallel2` |
| `runlogs.dir` | `null` (the skill then needs `--dir`) | `check-runlogs` (newest run log; every subfolder at any depth, dated archives included, is searched too) |
| `runlogs.name_pattern` | a name ending in `<YYYY-MM-DD>[_<HHMMSS>].txt` or `.log` | `check-runlogs` (named groups `date`, optional `time`) |
| `todo.folder` | `null` (feature off) | the one key a project sets to turn TODO sync on: the project-relative folder holding the TODO catalog and its companions. Every `todo` path below is relative to it (`..` allowed) |
| `todo.catalog` | `RepoToDo.json` | `todo_sync.py`, its SessionStart hook, `todo-watch` (ranked TODO catalog JSON) |
| `todo.catalog_schema` | `RepoToDo.schema.json` (used when present, else the harness `catalogs/TodoCatalog.schema.json`) | rule T1 (validated under the schema's own draft); `null` always uses the harness copy |
| `todo.stub_name` | `_IMPL_TODO.md` (`null`: S1-S4 off) | stub file name under the research root (`artifacts.research`) |
| `todo.top_n` | `10` | `todo-watch` summary and toast, `todo_sync.py render` |
| `todo.snapshots.dir` | `Snapshots` (`null`: T2 and `render` off) | rule T2, `todo_sync.py render` (creates the folder) |
| `todo.snapshots.name_pattern` | `TODO_Snapshot_<YYYY_MMDD>.md` | rule T2 (named group `date`; newest by date, else mtime) |
| `todo.research.catalog` | `ResearchImplementationCatalog.json` (used when present; absent or `null`: S rules, T3-T5 off) | research catalog JSON |
| `todo.research.anchor_pattern` | `catalog_entry: <path>#<id>` | rules S1, S4 (named group `id`) |
| `todo.research.ignore_folders` | `[]` | rule S6 (the folders holding the catalog and the snapshots are excluded automatically) |
| `todo.plans.pairs` | `true` | rules P1-P4 over `artifacts.plans` |
| `todo.gh.repo` | `null` (the `origin` remote) | issue fetch (Phase 3) |
| `todo.gh.max_age_hours` | `24` | rule G5, `todo-watch` toast age suffix |
| `todo.rules.disabled` | `[]` | `todo_sync.py check` skips these rule ids |
| `todo.rules.warn_counts` | `false` | warn findings count toward the drift number |
| `todo.inject_context` | `true` | `todo-watch` per-prompt `TODO_SYNC` line |

`schemas_dir` (default `.claude/agent-schemas`) pins project copies of the review schemas; anything missing
there falls back to the plugin's `schemas/`.

Two layout rules hold everywhere:

- **Data goes to the project, code stays in the plugin.** No hook or script writes under the plugin directory
  (it is a versioned cache once installed); `tests/contract/test_root_separation.py` enforces it.
- **Phase 5 sentinels are per repository.** They live under the main checkout's `state_dir`, so a fixer arming
  one from a linked worktree gates the session in the main checkout, and the reverse.

## Develop

```
python -m pip install -r requirements-dev.txt
python -m pytest tests/<area>/test_<name>.py -q
python -m ruff check plugins tests
claude plugin validate plugins/<name>
claude plugin test plugins/<name>
```

To run a working copy instead of the installed release, point `CLAUDE_CODE_PLUGIN_DIRS` (user settings `env`)
at the plugin folders of a checkout.

| Path | Holds |
|---|---|
| `plugins/harness/lib/harness_lib/` | importable library: config, project roots, review/commit/summary engines, validation |
| `plugins/harness/{scripts,hooks}/` | entry points; each puts `../lib` on `sys.path` |
| `plugins/harness/skills/`, `agents/` | skill and agent markdown; agents dispatch as `harness:<name>` |
| `plugins/harness/{config,schemas,rules,reference}/` | defaults + config schema, review schemas, session rules, commit format |
| `plugins/<mod>/hooks/` | TypeScript mods, each with its own `*.test.ts` |
| `tests/` | pytest suite; `make_project` builds throwaway consuming projects |
| `docs/PROVENANCE.md` | where every file came from |

`tests/contract/` holds the guards that keep the plugins generic: no consumer literals, no writes under the
plugin root, every `hooks.json` command resolvable.
