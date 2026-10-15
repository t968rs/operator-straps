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

The mods (`pr-review-watch`, `git-status`, `session-bookmark`, `pytest-scope`) are independent of each other.
`pr-review-watch` stays inactive in any project without `.claude/harness.json`. `pytest-scope` does nothing
until one of its options is set.

## Install

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install harness@operator-straps
claude plugin install pr-review-watch@operator-straps
claude plugin install git-status@operator-straps
claude plugin install session-bookmark@operator-straps
claude plugin install pytest-scope@operator-straps --config python=C:/path/to/env/python.exe --config require_test_file=true
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
Store `python3` stub. Without `jsonschema` / `referencing` / `pydantic` it warns on every call: the schema hook
stands down, and `pr-review` / `pr-team` (whose driver models reviews in pydantic) cannot run. Commit, summary
and worktree tooling need only the standard library.

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
  "runlogs": {"dir": "logs/test_runs"}
}
```

| Key | Default | Used by |
|---|---|---|
| `base_branch` | `origin/HEAD`, else `main` | merge bases, `d-w`, `pr-review-watch` |
| `integration_branches` | base branch + `main` | `d-w` (fetch-and-cut targets) |
| `state_dir` | `.claude/state/harness` | Phase 5 sentinels, pr-team runtime (gitignore it) |
| `artifacts.*` | `docs/PR_REVIEWS`, `docs/PLANS`, ... | review, plan, summary and commit-message output |
| `tests.*` | `tests/`, common test-file pattern | review bucketing, commit grouping |
| `review.*` | empty | Phase 1 guard suites, lens catalog, reviewer-brief rule pointers |
| `commit_buckets` | generic `src/`, `tests/`, `docs/` rules | `c-msg`, `branch-commit-msg` grouping |
| `exclusions` | `null` | clean-tree checks ignore machine-generated files |
| `auto_approve_python_c` | `false` | `approve_python_c` hook |
| `worktree_root` | `~/.config/superpowers/worktrees/{repo}` | `d-w`, `parallel2` |
| `runlogs.dir` | `null` (the skill then needs `--dir`) | `check-runlogs` (newest run log; every subfolder at any depth, dated archives included, is searched too) |
| `runlogs.name_pattern` | a name ending in `<YYYY-MM-DD>[_<HHMMSS>].txt` or `.log` | `check-runlogs` (named groups `date`, optional `time`) |

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
