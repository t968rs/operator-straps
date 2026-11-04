# operator-straps

Claude Code marketplace: the `harness` plugin (Python skills, agents, hooks, scripts) plus eight TypeScript mods
(`agent-watcher`, `git-status`, `session-bookmark`, `pytest-scope`, `todo-watch`, `bubble-stamp`, `band-line`,
`parallel2-lanes`). Layout and install: `README.md`.

## Rules for changes

- **Plugins stay generic.** Nothing under `plugins/` names a consuming project: no project paths, package names,
  interpreter variables or machine paths. A project-specific value becomes a key in `.claude/harness.json`.
  `tests/contract/test_no_repo_literals.py` enforces the ban list.
- **Data goes to the project, code stays in the plugin.** Drivers and hooks write only under the consuming project
  (`cfg.path(...)`, `state_dir`, `artifacts.*`). `plugin_root()` is read-only.
  `tests/contract/test_root_separation.py` enforces it.
- **A new config key** touches four places together: `plugins/harness/config/defaults.json`,
  `config/harness.schema.json`, the dataclass and builder in `lib/harness_lib/config.py`, and the README key
  table. When a mod reads the key, also mirror its default in that mod's `hooks/config.ts`
  (`tests/mods/test_<mod>_config_mirror.py` checks the mirror; `agent-watcher`, `todo-watch` and `bubble-stamp` have one).
  `agent-watcher` splits it: core keys in `hooks/core/config.ts`, pr-review keys in
  `hooks/layers/pr-review/config.ts`.
  `session-bookmark` mirrors `state_dir` in `hooks/notes.ts` instead, checked by
  `tests/mods/test_session_bookmark_notes_contract.py`.
  The four places are not a cost to weigh against the key. A setting a driver can read and act on belongs in a
  config key and the driver, never in skill prose the agent must remember to follow; the key is the cheaper
  path, and the touch list above is its checklist. Do not trim a feature to a "document only" version to
  avoid it.
- **Drivers activate, library code reads.** Scripts, hooks and skill commands call
  `activate(load_config(project_root(...)))` once; library modules read `active()` inside functions, never at
  import time. Hooks resolve the project from the payload `cwd`.
- **Phase 5 sentinels are per repository**: `sentinel_dir_under` anchors them at the main checkout. The Stop hook,
  `phase4_branch_safety.py`, the schema hook and `agent-watcher` all use that rule; change it in all four or
  none.
- **Skills and agents** invoke code as `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/..."`,
  skill-local files as `${CLAUDE_SKILL_DIR}/...`, and dispatch agents as `harness:<name>`.
- **Hooks** register in `plugins/harness/hooks/hooks.json` in shell form through `hpy`. A file under `hooks/`
  without a leading underscore must be registered, or named under `COMPOSED` as decided inside a registered
  dispatcher (`bash_pretool.py` runs the three Bash hooks in one launch); both are checked by
  `tests/contract/test_hooks_json_paths.py`. Every hook launch costs an interpreter start, so a new hook
  for an event and matcher that already has a command joins that command's dispatcher (or turns it into one,
  with a `COMPOSED` entry) instead of adding a command.

- **Porting a file in** from another repository follows the project skill `porting-into-straps`
  (`.claude/skills/porting-into-straps/`); its `port_scan.py` lists the decoupling work before the copy.
- **Strapping a harness skill**: `.claude/harness.json` sets `"strap": {"target": "harness"}` (the key ships
  in 0.51.0), so `strap.py new <name>` here scaffolds under `plugins/harness/`. Open specs keep their recorded `plugin_dir`.

## Tests

- Python: name test files, never a directory:
  `python -m pytest tests/<area>/test_<name>.py -q`. Tests build consuming projects with the `make_project`
  fixture (`tests/conftest.py`); no test reads a real project checkout.
- Mods: `claude plugin test plugins/<mod>`; manifests: `claude plugin validate --strict <dir>`.
- `.claude/settings.json` enables the published marketplace (GitHub `t968rs/operator-straps`), so this repo's own
  sessions run the pushed default branch, not the checkout. Exercise local plugin edits before merge with
  `claude --plugin-dir plugins/<name>` or a local marketplace (`claude plugin marketplace add ./`).
- Lint: `python -m ruff check plugins tests tools` (line length 110, E501 on locally; CI passes
  `--extend-ignore E501`, so a long line never fails a build).
- CI (`.github/workflows/ci.yml`) runs pytest and ruff on Ubuntu, pytest on Windows limited to tests marked
  `cross_os` (shell launcher, git worktree paths, junctions; mark a new test that depends on the OS), plus strict
  validation and the mod tests. Pull requests run only what the diff reaches, chosen by `tools/select_tests.py`: a test runs when it
  changed, when its import closure holds a changed file (the closure follows the `pythonpath` entries and every
  `tests/` folder holding a `_`-prefixed helper), when its source names a changed or deleted file (the
  basename, or a `.py` file's bare module name), or when it walks a tree that holds a changed path. A
  non-`.py` basename other files share (`SKILL.md`, `README.md`, `plugin.json`) counts only with its anchor:
  the source must also name the nearest folder that tells the file apart (`pr-sum` for
  `plugins/harness/skills/pr-sum/SKILL.md`), and a shared name at the repo root must sit on a line that names
  a root or repo (`REPO_ROOT / "README.md"`). A test whose
  code walks (`rglob`, `.glob`, `iglob`, `iterdir`, `.walk` other than `ast.walk`, `copytree`, `scandir`,
  `listdir`) declares the repo folders it walks in a module-level literal
  `WALK_ROOTS = ("plugins/harness/skills/",)` and runs only for changes under them; `WALK_ROOTS = ()` marks a
  test that walks only temporary folders. A walking test without a valid marker runs on every change outside
  `docs/`, and `tests/scripts/test_select_tests.py` fails until it gets one. A data file under `plugins/` or
  `tools/` counts as a change to each `.py` file there that names it in a code string literal (docstrings and
  comments do not count, so a module that reads a data file must spell its name in code; a shared name needs
  its anchor there too, unless the module sits under the data file's folder). Ruff files and the plugin jobs are
  selected from the same diff. Shared files such as `tests/conftest.py` and deleted `.py` files force
  everything; pushes to `main` run it all. A test that reaches a file by a route the script cannot see (a path
  built at runtime) must spell that file name, and a shared name's anchor, out in its source: otherwise the
  pull request skips it and only
  the full run after the merge to `main` catches the break.
  Preview a diff with `python tools/select_tests.py --base main`.

## Code style

Python 3.11; `Optional[X]` / `Union[X, Y]`, never `X | Y`. No first or second person in comments or docstrings.
Functions under 50 lines. Allowed runtime dependencies: the standard library, `jsonschema`, `referencing`,
`pydantic>=2`.

## Releases

Bump `version` in the changed plugin's `.claude-plugin/plugin.json`. `docs/PROVENANCE.md` maps every imported
file back to its source.
