# operator-straps

Claude Code marketplace: the `harness` plugin (Python skills, agents, hooks, scripts) plus four TypeScript mods
(`pr-review-watch`, `git-status`, `session-bookmark`, `pytest-scope`). Layout and install: `README.md`.

## Rules for changes

- **Plugins stay generic.** Nothing under `plugins/` names a consuming project: no project paths, package names,
  interpreter variables or machine paths. A project-specific value becomes a key in `.claude/harness.json`.
  `tests/contract/test_no_repo_literals.py` enforces the ban list.
- **Data goes to the project, code stays in the plugin.** Drivers and hooks write only under the consuming project
  (`cfg.path(...)`, `state_dir`, `artifacts.*`). `plugin_root()` is read-only.
  `tests/contract/test_root_separation.py` enforces it.
- **A new config key** touches four places together: `plugins/harness/config/defaults.json`,
  `config/harness.schema.json`, the dataclass and builder in `lib/harness_lib/config.py`, and the README key
  table. When `pr-review-watch` reads the key, also mirror it in `plugins/pr-review-watch/hooks/config.ts`
  (`tests/mods/test_pr_review_watch_config_mirror.py` checks the mirror).
- **Drivers activate, library code reads.** Scripts, hooks and skill commands call
  `activate(load_config(project_root(...)))` once; library modules read `active()` inside functions, never at
  import time. Hooks resolve the project from the payload `cwd`.
- **Phase 5 sentinels are per repository**: `sentinel_dir_under` anchors them at the main checkout. The Stop hook,
  `phase4_branch_safety.py`, the schema hook and `pr-review-watch` all use that rule; change it in all four or
  none.
- **Skills and agents** invoke code as `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/..."`,
  skill-local files as `${CLAUDE_SKILL_DIR}/...`, and dispatch agents as `harness:<name>`.
- **Hooks** register in `plugins/harness/hooks/hooks.json` in shell form through `hpy`. A file under `hooks/`
  without a leading underscore must be registered (`tests/contract/test_hooks_json_paths.py`).

- **Porting a file in** from another repository follows the project skill `porting-into-straps`
  (`.claude/skills/porting-into-straps/`); its `port_scan.py` lists the decoupling work before the copy.

## Tests

- Python: name test files, never a directory:
  `python -m pytest tests/<area>/test_<name>.py -q`. Tests build consuming projects with the `make_project`
  fixture (`tests/conftest.py`); no test reads a real project checkout.
- Mods: `claude plugin test plugins/<mod>`; manifests: `claude plugin validate --strict <dir>`.
- Lint: `python -m ruff check plugins tests` (line length 110, E501 on).
- CI (`.github/workflows/ci.yml`) runs pytest and ruff on Ubuntu and Windows, plus strict validation and the mod
  tests.

## Code style

Python 3.11; `Optional[X]` / `Union[X, Y]`, never `X | Y`. No first or second person in comments or docstrings.
Functions under 50 lines. Allowed runtime dependencies: the standard library, `jsonschema`, `referencing`,
`pydantic>=2`.

## Releases

Bump `version` in the changed plugin's `.claude-plugin/plugin.json`. `docs/PROVENANCE.md` maps every imported
file back to its source.
