# strap-skills: target-aware (project skills in other repos)

Date: 2026-11-03. Status: approved by the developer (proceed to plan). Worktree base: `74f5aca`
(`1115-port-writing-docstrings` tip, PR 187 open).

## Intent

`harness:strap-skills` proves a skill test-first (failing baseline, passing green, freeze). Today it can only
write skills into a plugin named `harness`, to harness house rules. The developer wants the same gate usable in
any repository that installs the harness plugin, writing **repo-linked skills** stored in that repo's
`.claude/skills/<name>/` (or a configured equivalent), supported by models and API modules in the same repo.

## Goals

- `strap.py new <name>` in a consuming repo opens a spec for a skill under the configured skills folder.
- `scaffold` renders a project-profile SKILL.md, `<snake>_models.py`, `<snake>_api.py` and a contract test.
- The scaffolded skill's API heredoc runs through the harness plugin, reached by a documented route.
- `check`, `red`, `run`, `record-run`, `grade`, `retest` and `freeze` work unchanged in behavior for both
  profiles.
- The harness profile behaves exactly as today: same paths, same lint, same templates, same output lines.

## Non-goals

- User-scope skills (`~/.claude/skills/`) and any target outside a git repository.
- Targeting plugins other than `harness` (a third profile can come later; nothing here should preclude it).
- Scaffolded skills that run with the harness plugin absent. **The plugin is a runtime dependency** of the
  heredoc launcher (developer decision).
- A second interpreter key. The target repo points `hpy` at its own environment with `HARNESS_PY`.

## Anti-goals

- A spec format migration. The five existing specs under `docs/plans/strap/` (c-msg, merge-commit-msg,
  review-local, strap-skills, writing-docstrings) load and pass `check` with their digests and seals intact;
  no spec file is rewritten to fit a new field.
  Exception, by content not format: `writing-docstrings` lists `plugins/harness/lib/harness_lib/config.py`
  and `plugins/harness/config/defaults.json` as parts, so the new config keys change its content hash. Its
  `stale:` line is closed by the standard green re-run and `freeze --refreeze`, with the developer's OK.
- A plugin file that names a consuming project (`tests/contract/test_no_repo_literals.py`).
- Two SKILL.md files repeating the gate rules.

## Constraints (verified)

- **No plugin root in project skills.** `${CLAUDE_PLUGIN_ROOT}` is substituted only in plugin skills and is
  never exported to Bash (code.claude.com/docs/en/skills.md, plugins manifest reference). Project skills get
  `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PROJECT_DIR}` substitution in their markdown.
- **Plugin `bin/` is on the Bash `PATH`** while the plugin is enabled; files there run as bare commands. This is
  the documented route from project content to plugin code. `CLAUDE_ENV_FILE` from SessionStart is rejected:
  Bash only, PowerShell caveats, resume behavior undocumented.
- **Target-repo pytest runs without harness on `sys.path`** (its own CI, and `red`/`freeze` via
  `plan_red.tree_env`, which adds only `src/`). So scaffolded project modules and the contract test import only
  the standard library, `pydantic` and `pytest`; never `harness_lib`.
- `red`/`freeze` run pytest with `sys.executable` (`plugins/harness/scripts/strap.py:407`), the interpreter
  `hpy` resolved. The target repo's `HARNESS_PY` environment must hold `pydantic>=2`, `jsonschema`,
  `referencing`, `pytest` and the repo's own test dependencies. Documented, not enforced.
- New config keys follow the four-place rule in the repo CLAUDE.md (defaults, schema, dataclass and builder,
  README key table). No mod reads them.
- The gate depends on git (throwaway trees, `--edit` baselines via `git show <base>:<path>`); satisfied by the
  repo-linked scope.

## Approaches considered

| | A. Profile split, modules in the skill folder | B. Profile split, modules in a repo package | C. Separate skill over the same engine |
|---|---|---|---|
| Layout | `.claude/skills/<name>/scripts/<snake>_{models,api}.py` | a configured package holds every skill's modules | new `strap-project-skills` SKILL.md |
| Heredoc | `harness-skill-api --file "${CLAUDE_SKILL_DIR}/scripts/<snake>_api.py" <name>` | `harness-skill-api --package <pkg> <snake>_api <name>` | either |
| Trade-off | self-contained, folder copy moves the skill; path imports | conventional imports, needs `pythonpath` setup per repo | gate rules duplicated, drift |

**Picked: A** (developer). Matches "stored in `.claude/skills`", no per-repo setup, harness profile untouched.

## Decided design

### Configuration

| Key | Default | Meaning |
|---|---|---|
| `strap.target` (new section) | `"project"` | `"harness"` or `"project"`: which profile `new` uses. |
| `skills_dir` (existing, reused) | `".claude/skills/"` | Project profile: folder holding `<name>/SKILL.md`. Already read by review lens detection (`review_plan.py`, `pr_review.py`), so strap-written skills are seen there too. |
| `agents_dir` (new, top level beside `skills_dir`) | `".claude/agents/"` | Project profile: folder holding role agents `<role>.md`. |

Folder values are normalized (trailing slash stripped) before they are recorded in a spec, so the recorded
form never depends on how `harness.json` spells them.

This repo's `.claude/harness.json` sets `"strap": {"target": "harness"}`. The default is `project` because
every other consumer writes project skills; only this repo writes harness skills.

### Spec

The spec records the profile it was opened under, so a later config change never re-targets an open spec, and
records the skills and agents folders the profile resolved. Specs without the new field read as the harness
profile with today's `plugin_dir`, and their dump, digest and seal stay byte-identical (anti-goal above).

### Profiles

One resolver object per profile answers every path question the driver asks today with a hard-coded string:
the SKILL.md path, the skill folder, the models/API/driver paths for `--edit` part discovery and `scaffold`,
the agents folder (`_role_problems`, `_agent_text`), the template set, the lint rule set, the variable
rewrites for run briefs, and the `bump:` line.

| Question | harness | project |
|---|---|---|
| SKILL.md | `<plugin_dir>/skills/<name>/SKILL.md` | `<skills_dir>/<name>/SKILL.md` |
| models, API | `<plugin_dir>/lib/harness_lib/<snake>_{models,api}.py` | `<skills_dir>/<name>/scripts/<snake>_{models,api}.py` |
| driver (edit discovery) | `<plugin_dir>/scripts/<snake>.py` | `<skills_dir>/<name>/scripts/<snake>.py` |
| contract test | `<tests.roots[0]>/skills/test_<snake>_skill_contract.py` | same |
| agents | `<plugin_dir>/agents/` | `<agents_dir>/` |
| brief rewrites | `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_SKILL_DIR}` (unchanged) | `${CLAUDE_SKILL_DIR}` as today (green: working tree, edit baseline: run tree); `${CLAUDE_PROJECT_DIR}` always to the **run tree**, both arms |
| `bump:` line | `<plugin_dir>/.claude-plugin/plugin.json` | omitted |

### Lint

`strap_lint` splits into a generic rule set and the harness house set.

- **Generic (both profiles):** frontmatter present, `name` matches the folder, description present, starts
  with `Use when`, within `DESCRIPTION_MAX`, no first or second person; `${CLAUDE_SKILL_DIR}/...` paths the
  body names exist; `lint_python` on Python parts.
- **Harness only:** the `skill_arguments.md` pointer and `-- <guidance>` hint tail, `${CLAUDE_PLUGIN_ROOT}`
  path existence, `harness:` agent existence, `harness_lib.<module>` existence, the hpy-only fence rule, the
  vendor-name ban.

### Launcher

- New `plugins/harness/bin/harness-skill-api`: a POSIX `sh` shim that runs `hpy` on `scripts/skill_api.py`
  with its arguments, both resolved relative to the shim's own location.
- `skill_api.py` gains `--file <path>`: load that file as the API module by path, with its folder first on
  `sys.path` so `from <snake>_models import ...` resolves. Exactly one of `<module>` or `--file`. Harness's own
  config is still activated first (unchanged), so a heredoc keeps its `problem:` contract.

### Project templates

A second template set beside today's, rendered for the project profile:

- **SKILL.md:** heredoc through `harness-skill-api --file "${CLAUDE_SKILL_DIR}/scripts/<snake>_api.py"`; no
  `${CLAUDE_PLUGIN_ROOT}` and no `skill_arguments.md` pointer; same Rules / Steps / API / Judgment / Related
  skeleton and `TODO(fill)` markers.
- **models:** today's `models.tmpl` content, with its docstring no longer naming `harness_lib`.
- **API:** today's shape, without `harness_lib.config.active`. The document location resolves from the
  repository root found by walking up from **the working directory** (the nearest folder holding `.git`, file
  or folder), never from the module's own file: on a green run the module loads from the developer's working
  tree while the runner works in the run tree, and documents must land in the run tree. This matches the
  harness profile, where `active()` resolves from the working directory. Sibling import
  `from <snake>_models import ...`.
- **contract test:** loads the models and API by file path, reads SKILL.md frontmatter with its own small
  parser, finds the repository root from its own location; imports only stdlib, `pydantic`, `pytest`.

### Planned tests in the project profile

Planned tests (`<plans>/strap/<name>/tests/`) reach a project skill's modules by file path, since nothing puts
the skill's `scripts/` folder on `sys.path`. The load idiom raises `ImportError` when the file is absent, so a
module missing at the start commit fails `red` as `ImportError` (a collection error pytest reports as an
ImportError), never as `FileNotFoundError`, which `red` rejects. The idiom is inlined in each test file (a few
lines; no shared helper, which would itself be absent at the start commit). The contract test template uses
the same idiom, and the strap-skills SKILL.md step 2 states it for the project profile.

### strap-skills SKILL.md

The description and title drop "harness skill" for wording that covers both profiles. Step 5 names the profile's
templates and part paths; the `bump:` sentence applies to the harness profile. A short section states the
project profile's prerequisites: the harness plugin enabled, `HARNESS_PY` pointing at an environment with the
listed packages. The `strap-skills` spec is not frozen (`frozen: null`, zero behaviors, base `697dce2`), so
this is a direct edit; the pending self-gate (STR-11, `docs/plans/0002_strap_skills_PIP.md`) should cover the
project-profile prose when it runs. Recorded as a call, below.

### Release

Bump `plugins/harness/.claude-plugin/plugin.json` from `0.50.0` to `0.51.0`; README key table rows for
`strap.target` and `agents_dir`; `docs/PROVENANCE.md` unaffected (no imported file). The `writing-docstrings`
refreeze (anti-goal exception) runs last, on the target branch after the worktree moves, with the developer's
OK.

## Calls made during review (developer may override)

- Reuse the existing `skills_dir` key instead of adding `strap.skills_dir`; `agents_dir` sits beside it.
- `${CLAUDE_PROJECT_DIR}` rewrites to the run tree in both arms; the project API resolves its root from the
  working directory.
- Planned tests use an inlined load-by-path idiom that raises `ImportError` on a missing file.
- The strap-skills SKILL.md changes are a direct edit; STR-11 covers them later.
- The `writing-docstrings` refreeze is accepted as routine, not as a breach of the anti-goal.
- Worktree moved from `8833c3d` to `74f5aca` before any code, so the config edits sit on PR 187's fixes.

## Builder's calls

- The resolver's shape (class, protocol, functions) and module placement, within the 50-line function rule.
- The spec field name for the profile and folders, provided the anti-goal on existing specs holds.
- Where the project API's document lives under the repository root (a module constant in the rendered file is
  acceptable).
- Test names, file placement and `WALK_ROOTS` markers per `tools/select_tests.py`.
- Whether `--file` refuses a path outside the project root.
