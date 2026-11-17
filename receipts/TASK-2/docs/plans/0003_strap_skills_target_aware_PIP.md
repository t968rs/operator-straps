# Plan 0003: strap skills target aware

> Rendered by `plan.py render` from `0003_strap_skills_target_aware_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-03
**Spec:** `docs/superpowers/specs/2026-11-03-strap-skills-target-aware-design.md`
**Branch:** none -> main
**Base commit:** `4e2393d`
**Frozen:** 2026-11-03 at `b56b363`
**Execution model:** serial

## Decisions

- **D1** Where do a project skill's models and API live? Chosen: `skill-folder` (<skills_dir>/<name>/scripts/, loaded by path). Rejected: `repo-package` (a configured repo package holding every skill's modules), `separate-skill` (a second SKILL.md over the same engine). Developer pick (approach A): self-contained folder, no repo setup.
- **D2** Does a scaffolded project skill need the harness plugin at runtime? Chosen: `plugin-required` (heredoc runs through the harness launcher). Rejected: `standalone` (each skill ships its own launcher). Developer decision.
- **D3** How does project skill content reach harness code? Chosen: `bin-shim` (plugins/harness/bin/harness-skill-api on the Bash PATH). Rejected: `env-file` (SessionStart writes HARNESS_ROOT to CLAUDE_ENV_FILE). Documented and survives resume; env-file is Bash-only with PowerShell caveats.
- **D4** Default strap.target for a consuming project Chosen: `project` (project profile by default; this repo sets harness). Rejected: `harness` (harness profile by default). Only operator-straps writes harness skills.
- **D5** Which key names the project skills folder? Chosen: `reuse-skills-dir` (the existing top-level skills_dir). Rejected: `strap-skills-dir` (a new strap.skills_dir). One source of truth; review lens detection already reads it.
- **D6** How does a spec record its profile without changing existing spec files? Chosen: `optional-target` (target: Optional[SkillTarget], plugin_dir Optional, exactly one set; a None target is left out of the dump and the authored digest). Rejected: `profile-field` (a profile field with a default written into every dump). Existing specs keep text, driver digest and seal byte for byte.
- **D7** Where does ${CLAUDE_PROJECT_DIR} point in a run brief? Chosen: `run-tree` (the run tree, both arms). Rejected: `source-tree` (the arm's source tree (working tree on green)). Green writes must land in the scenario tree, where record-run diffs.
- **D8** How does the project API template find the repository root? Chosen: `cwd-walk` (walk up from the working directory to the folder holding .git). Rejected: `file-walk` (walk up from the module's own file). On green the module loads from the working tree while the runner works in the run tree.
- **D9** How do planned tests reach a project skill's modules? Chosen: `inline-idiom` (inlined load-by-path that raises ImportError on a missing file). Rejected: `helper` (a scaffolded helper or conftest). A helper would itself be absent at the start commit red runs from.
- **D10** Is the strap-skills SKILL.md change proven through strap-skills itself? Chosen: `direct-edit` (direct edit; STR-11 self-gate covers it later). Rejected: `strap-now` (add judgment behaviors to the strap-skills spec now). The strap-skills spec is unfrozen with zero behaviors; STR-11 is pending.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| harness plugin version | 0.51.0 | plugins/harness/.claude-plugin/plugin.json:3 (0.50.0) plus a minor bump | - |
| skills_dir default | .claude/skills/ | plugins/harness/config/defaults.json:5 | reuse-skills-dir |
| agents_dir default | .claude/agents/ | spec, Configuration table | - |
| strap.target default | project | spec, Configuration table | project |
| project template folder | skills/strap-skills/templates/project | spec, Project templates | skill-folder |

## Formats

- **skill_api --file launch line**: `harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/<snake>_api.py" <name>`, copied from `plugins/harness/scripts/skill_api.py:65-70`
- **SkillSpec target key**: `"target": {"skills_dir": ".claude/skills", "agents_dir": ".claude/agents"}`, copied from `plugins/harness/lib/harness_lib/strap_models.py:458-463`

## Sweeps

- **S1** `spec\.plugin_dir|PLUGIN_NAME|find_plugin_dir`: `plugins/harness/lib/harness_lib/strap_scaffold.py` (rewire through strap_profile (TASK-6); find_plugin_dir stays), `plugins/harness/scripts/strap.py` (rewire through strap_profile (TASK-7)), `tests/lib/test_strap_scaffold.py` (harness-profile tests; unchanged)

## Tasks

### TASK-1: Config keys strap.target and agents_dir

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/config/defaults.json`, `plugins/harness/config/harness.schema.json`, `plugins/harness/lib/harness_lib/config.py`, `README.md`, `tests/lib/test_strap_target_config.py`

**Anchors:**
- `plugins/harness/config/defaults.json:5` holds `"skills_dir": ".claude/skills/",`
- `plugins/harness/config/harness.schema.json:20` holds `"skills_dir": {"$ref": "#/$defs/relPath"`
- `plugins/harness/lib/harness_lib/config.py:169` holds `skills_dir: str`
- `plugins/harness/lib/harness_lib/config.py:299` holds `skills_dir=m["skills_dir"]`

Add top-level agents_dir (relPath, default '.claude/agents/') beside skills_dir, and a strap object with target (enum harness|project, default 'project') in defaults.json and harness.schema.json (additionalProperties false). In config.py add a frozen StrapConfig(target: str) dataclass, HarnessConfig.agents_dir and HarnessConfig.strap, built in _build. README key table: rows for agents_dir and strap.target. This repo's .claude/harness.json stays unchanged: its sessions run the published plugin, whose schema rejects an unknown strap key, so the line lands after a release (deferred). config.py and defaults.json are parts of the writing-docstrings spec, so its hash goes stale (closed by TASK-9).

- [x] Test `tests/lib/test_strap_target_config.py::test_strap_target_defaults_to_project` fails with AttributeError, then passes
- [x] Test `tests/lib/test_strap_target_config.py::test_strap_target_reads_the_override` fails with AssertionError, then passes
- [x] Test `tests/lib/test_strap_target_config.py::test_agents_dir_defaults_beside_skills_dir` fails with AttributeError, then passes
- [x] Test `tests/lib/test_strap_target_config.py::test_schema_declares_both_keys` fails with AssertionError, then passes
- [x] Test `tests/lib/test_strap_target_config.py::test_readme_key_table_lists_both_keys` fails with AssertionError, then passes
- [x] Record the commit: `plan.py record 0003 TASK-1 --sha <sha>`

**Evidence:** commit 6d25327: 5 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/lib/test_strap_target_config.py::test_strap_target_defaults_to_project tests/lib/test_strap_target_config.py::test_strap_target_reads_the_override tests/lib/test_strap_target_config.py::test_agents_dir_defaults_beside_skills_dir tests/lib/test_strap_target_config.py::test_schema_declares_both_keys tests/lib/test_strap_target_config.py::test_readme_key_table_lists_both_keys`

### TASK-2: SkillSpec target field, legacy dumps unchanged

**Status:** COMPLETE | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/strap_models.py`, `plugins/harness/schemas/SkillSpec.schema.json`, `tests/lib/test_strap_target_spec.py`, `tests/lib/test_strap_models.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/strap_models.py:383` holds `plugin_dir: str`
- `plugins/harness/lib/harness_lib/strap_models.py:458-463` holds `dumped = spec.model_dump(mode="json")`
- `plugins/harness/lib/harness_lib/strap_models.py:466-475` holds `dumped = spec.model_dump(mode="json")`
- `plugins/harness/scripts/strap.py:349` holds `if path.read_text(encoding="utf-8") != sm.dump_spec(spec):`

In strap_models add SkillTarget(skills_dir: str, agents_dir: str; extra forbid). SkillSpec: plugin_dir: Optional[str] = None, target: Optional[SkillTarget] = None, and a validator requiring exactly one. _dumped drops the 'target' key when None; authored_digest drops it the same way, so every existing spec keeps its canonical text, driver digest and seal. Regenerate SkillSpec.schema.json with tools/gen_skillspec_schema.py. Guard: strap.py check on each existing spec still prints check [ok]. test_strap_models.py::test_dump_and_load_round_trip compares against the dump minus a None target.

- [x] Test `tests/lib/test_strap_target_spec.py::test_project_spec_round_trips_through_its_dump` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_target_spec.py::test_harness_spec_dump_has_no_target_key` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_target_spec.py::test_spec_needs_exactly_one_of_plugin_dir_and_target` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_target_spec.py::test_existing_specs_are_found` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_target_spec.py::test_existing_spec_keeps_its_text_digest_and_seal` fails with ImportError, then passes
- [x] Run `sh plugins/harness/scripts/hpy tools/gen_skillspec_schema.py`: exit 0
- [x] Run `sh plugins/harness/scripts/hpy tools/gen_skillspec_schema.py --check`: exit 0
- [x] Run `python -m pytest tests/schemas/test_skillspec_schema_drift.py tests/lib/test_strap_models.py -q`: all passed
- [x] Record the commit: `plan.py record 0003 TASK-2 --sha <sha>`

**Evidence:** commit 6d25327: 5 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/lib/test_strap_target_spec.py::test_project_spec_round_trips_through_its_dump tests/lib/test_strap_target_spec.py::test_harness_spec_dump_has_no_target_key tests/lib/test_strap_target_spec.py::test_spec_needs_exactly_one_of_plugin_dir_and_target tests/lib/test_strap_target_spec.py::test_existing_specs_are_found tests/lib/test_strap_target_spec.py::test_existing_spec_keeps_its_text_digest_and_seal`

### TASK-3: strap_profile resolver

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-2
**Files:** `plugins/harness/lib/harness_lib/strap_profile.py`, `tests/lib/test_strap_profile.py`

**Anchors:**
- `plugins/harness/scripts/strap.py:575-579` holds `return text.replace(PLUGIN_VAR, plugin).replace(SKILL_DIR_VAR, skill_dir)`
- `plugins/harness/scripts/strap.py:282-284` holds `(PartKind.DRIVER, f"{spec.plugin_dir}/scripts/{snake}.py")`
- `plugins/harness/lib/harness_lib/strap_scaffold.py:101-104` holds `in_plugin(PartKind.MODELS, f"lib/harness_lib/{snake}_models.py")`
- `plugins/harness/lib/harness_lib/strap_api.py:260` holds `from harness_lib.strap_scaffold import scaffold_parts`

New module harness_lib/strap_profile.py: profile_of(spec) returns a frozen Profile with skill_folder, skill_md, models, api, driver, agents_dir (project-relative POSIX), bump (Optional[str]), templates (path parts under the plugin root) and rewrite(text, source, run_tree). Harness: today's paths from strap.py:277-284 and strap_scaffold.py:101-104, and the ${CLAUDE_PLUGIN_ROOT} / ${CLAUDE_SKILL_DIR} rewrite against source as strap.py:575-579 does. Project: <skills_dir>/<name>/ with scripts/<snake>_{models,api}.py and scripts/<snake>.py, agents_dir from the target, bump None, templates plus 'project', ${CLAUDE_SKILL_DIR} against source and ${CLAUDE_PROJECT_DIR} against run_tree. Also new_fields(cfg, root) -> dict for cmd_new: harness -> plugin_dir via find_plugin_dir (function-local import, as strap_api.py:260 does), project -> SkillTarget with trailing slashes stripped from skills_dir and agents_dir. Functions under 50 lines. new_fields records the folders in canonical POSIX form (backslashes, ./ and the trailing slash folded) and keeps a linked plugin folder's absolute path when it resolves outside the project, as the driver's _rel did.

- [x] Test `tests/lib/test_strap_profile.py::test_harness_profile_keeps_todays_paths` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_profile.py::test_project_profile_puts_modules_in_the_skill_folder` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_profile.py::test_harness_rewrite_matches_today` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_profile.py::test_project_rewrite_points_project_dir_at_the_run_tree` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_profile.py::test_new_fields_records_canonical_project_folders` fails with ImportError, then passes
- [x] Record the commit: `plan.py record 0003 TASK-3 --sha <sha>`

**Evidence:** commit 6d25327: 5 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/lib/test_strap_profile.py::test_harness_profile_keeps_todays_paths tests/lib/test_strap_profile.py::test_project_profile_puts_modules_in_the_skill_folder tests/lib/test_strap_profile.py::test_harness_rewrite_matches_today tests/lib/test_strap_profile.py::test_project_rewrite_points_project_dir_at_the_run_tree tests/lib/test_strap_profile.py::test_new_fields_records_canonical_project_folders`

### TASK-4: Lint split: generic rules for project skills

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/strap_lint.py`, `tests/lib/test_strap_lint_project.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/strap_lint.py:117-134` holds `def lint_skill(plugin_dir: Path, name: str) -> List[str]:`
- `plugins/harness/lib/harness_lib/strap_lint.py:24` holds `_PLUGIN_PATH = re.compile(`

In strap_lint add lint_project_skill(skill_folder: Path, name: str): frontmatter present, name matches the folder, the _description_problems rules, and each ${CLAUDE_SKILL_DIR}/<rel> path the body names exists under skill_folder (trailing '.' stripped, placeholders skipped as _PLUGIN_PATH does). No argument-pointer, hpy-fence, vendor, harness: agent or harness_lib rules. lint_skill output for harness skills stays byte-identical (tests/lib/test_strap_lint.py unchanged).

- [x] Test `tests/lib/test_strap_lint_project.py::test_clean_project_skill_skips_the_harness_house_rules` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint_project.py::test_description_rules_still_apply` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint_project.py::test_folder_name_must_match` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint_project.py::test_missing_skill_dir_path_is_a_problem` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_lint_project.py::test_every_problem_is_prefixed_with_the_skill_name` fails with ImportError, then passes
- [x] Run `python -m pytest tests/lib/test_strap_lint.py -q`: all passed
- [x] Record the commit: `plan.py record 0003 TASK-4 --sha <sha>`

**Evidence:** commit 6d25327: 5 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/lib/test_strap_lint_project.py::test_clean_project_skill_skips_the_harness_house_rules tests/lib/test_strap_lint_project.py::test_description_rules_still_apply tests/lib/test_strap_lint_project.py::test_folder_name_must_match tests/lib/test_strap_lint_project.py::test_missing_skill_dir_path_is_a_problem tests/lib/test_strap_lint_project.py::test_every_problem_is_prefixed_with_the_skill_name`

### TASK-5: skill_api --file and the bin/harness-skill-api shim

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** none
**Files:** `plugins/harness/scripts/skill_api.py`, `plugins/harness/bin/harness-skill-api`, `tests/scripts/test_skill_api_file.py`, `.gitattributes`

**Anchors:**
- `plugins/harness/scripts/skill_api.py:44-47` holds `return importlib.import_module(f"{PACKAGE}.{module}")`
- `plugins/harness/scripts/skill_api.py:58-62` holds `space = _namespace(_load_module(args.module), args.name)`
- `plugins/harness/scripts/strap.py:853-857` holds `spec_from_file_location("strap_skill_api", SCRIPT_DIR / "skill_api.py")`

skill_api.py: the module positional becomes optional; add --file PATH. Exactly one of module or --file, else a LauncherError problem line (exit 1, never an argparse exit). --file loads the file by path under a unique module name with its folder first on sys.path; a missing file is 'no API module at <path>'. Config activation order unchanged. New plugins/harness/bin/harness-skill-api: POSIX sh, resolves its own folder and execs sh ../scripts/hpy ../scripts/skill_api.py "$@"; LF endings; index mode 100755. Update the skill_api.py docstring usage line. The API folder is appended to sys.path (never shadows the standard library); a --file heredoc runs with the activated project root as its working directory, restored afterwards. The shim resolves its folder with pwd -W where MSYS has it. .gitattributes keeps plugins/harness/bin/* on LF. The shim run test looks sh up on PATH and skips without one.

- [x] Test `tests/scripts/test_skill_api_file.py::test_file_binds_the_api_module_and_its_sibling` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api_file.py::test_module_and_file_together_are_refused` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api_file.py::test_missing_file_is_one_problem_line` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api_file.py::test_shim_is_executable_in_the_index` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api_file.py::test_shim_runs_the_launcher` fails with AssertionError, then passes
- [x] Test `tests/scripts/test_skill_api_file.py::test_file_heredoc_runs_in_the_repo_root` fails with AssertionError, then passes
- [x] Run `git update-index --chmod=+x plugins/harness/bin/harness-skill-api`: exit 0
- [x] Run `python -m pytest tests/scripts/test_skill_api.py -q`: all passed
- [x] Run `claude plugin validate --strict plugins/harness`: no errors
- [x] Record the commit: `plan.py record 0003 TASK-5 --sha <sha>`

**Evidence:** commit 6d25327: 6 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/scripts/test_skill_api_file.py::test_file_binds_the_api_module_and_its_sibling tests/scripts/test_skill_api_file.py::test_module_and_file_together_are_refused tests/scripts/test_skill_api_file.py::test_missing_file_is_one_problem_line tests/scripts/test_skill_api_file.py::test_shim_is_executable_in_the_index tests/scripts/test_skill_api_file.py::test_shim_runs_the_launcher tests/scripts/test_skill_api_file.py::test_file_heredoc_runs_in_the_repo_root`

### TASK-6: Project template set and profile-driven scaffold

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-3, TASK-4, TASK-5
**Files:** `plugins/harness/lib/harness_lib/strap_scaffold.py`, `plugins/harness/skills/strap-skills/templates/project/skill_md.tmpl`, `plugins/harness/skills/strap-skills/templates/project/models.tmpl`, `plugins/harness/skills/strap-skills/templates/project/api.tmpl`, `plugins/harness/skills/strap-skills/templates/project/contract_test.tmpl`, `tests/lib/test_strap_scaffold_project.py`, `plugins/harness/skills/strap-skills/templates/project/api_section.tmpl`

**Anchors:**
- `plugins/harness/lib/harness_lib/strap_scaffold.py:26-33` holds `_TEMPLATE_DIR = ("skills", "strap-skills", "templates")`
- `plugins/harness/lib/harness_lib/strap_scaffold.py:136-137` holds `return plugin_root().joinpath(*_TEMPLATE_DIR, _TEMPLATES[kind])`
- `plugins/harness/skills/strap-skills/templates/api.tmpl:16` holds `from harness_lib.config import active`
- `plugins/harness/skills/strap-skills/templates/contract_test.tmpl:13` holds `from harness_lib.project import plugin_root`
- `plugins/harness/lib/harness_lib/plan_red.py:162-171` holds `src = tree / "src"`

Add skills/strap-skills/templates/project/{skill_md,models,api,contract_test}.tmpl. skill_md: heredoc through harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/${snake}_api.py", no ${CLAUDE_PLUGIN_ROOT}, no skill_arguments pointer, same skeleton and TODO(fill) markers. models: today's models.tmpl without the harness_lib mention. api: today's shape, sibling import from ${snake}_models, root found by walking up from Path.cwd() to the folder holding .git (file or folder), document under a DOCUMENT_DIR constant; no harness_lib. contract_test: stdlib, pydantic and pytest only; finds the repo root from its own file, loads models and API by path with the ImportError idiom, parses SKILL.md frontmatter itself, skips a missing optional module as today. strap_scaffold: scaffold_parts and _template_text use profile_of(spec) for paths and the template folder; spell each project template name in a code literal with its 'project/' anchor for tools/select_tests.py; add a skill_folder substitution. Harness rendering stays byte-identical. The API section and Related bullets render from project/api_section.tmpl only when an API part is planned; a prose-only skill gets a fill-in note and names no missing module, and its contract test skips the launcher check. strap_scaffold keeps its own templates folder literal (the anchor tools/select_tests.py needs for the shared harness basenames). The contract test appends the scripts folder to sys.path and registers each loaded module in sys.modules.

- [x] Test `tests/lib/test_strap_scaffold_project.py::test_parts_land_in_the_skill_folder` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold_project.py::test_skill_md_drives_the_api_through_the_bin_launcher` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold_project.py::test_python_parts_import_no_harness_lib` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold_project.py::test_rendered_skill_is_clean_under_the_project_lint` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold_project.py::test_contract_test_passes_without_harness_on_the_path` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold_project.py::test_api_writes_under_the_working_directory` fails with ImportError, then passes
- [x] Test `tests/lib/test_strap_scaffold_project.py::test_prose_only_skill_names_no_missing_module` fails with ImportError, then passes
- [x] Run `python -m pytest tests/lib/test_strap_scaffold.py -q`: all passed
- [x] Run `python tools/select_tests.py --base main`: tests/lib/test_strap_scaffold_project.py listed
- [x] Record the commit: `plan.py record 0003 TASK-6 --sha <sha>`

**Evidence:** commit 6d25327: 7 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/lib/test_strap_scaffold_project.py::test_parts_land_in_the_skill_folder tests/lib/test_strap_scaffold_project.py::test_skill_md_drives_the_api_through_the_bin_launcher tests/lib/test_strap_scaffold_project.py::test_python_parts_import_no_harness_lib tests/lib/test_strap_scaffold_project.py::test_rendered_skill_is_clean_under_the_project_lint tests/lib/test_strap_scaffold_project.py::test_contract_test_passes_without_harness_on_the_path tests/lib/test_strap_scaffold_project.py::test_api_writes_under_the_working_directory tests/lib/test_strap_scaffold_project.py::test_prose_only_skill_names_no_missing_module`

### TASK-7: Driver wiring through the profile

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-1, TASK-3, TASK-4, TASK-6
**Files:** `plugins/harness/scripts/strap.py`, `tests/scripts/test_strap_driver.py`, `tests/scripts/test_strap_gate.py`, `tests/contract/test_root_separation.py`, `tests/scripts/test_strap_project_profile.py`

**Anchors:**
- `plugins/harness/scripts/strap.py:73` holds `PLUGIN_NAME = "harness"`
- `plugins/harness/scripts/strap.py:297-306` holds `plugin_dir = _rel(find_plugin_dir(root, PLUGIN_NAME))`
- `plugins/harness/scripts/strap.py:275-289` holds `def _edit_parts(root: Path, spec: SkillSpec, skill_rel: str) -> List[Part]:`
- `plugins/harness/scripts/strap.py:325-326` holds `problems += lint_skill(root / spec.plugin_dir, spec.name)`
- `plugins/harness/scripts/strap.py:332-336` holds `agents = _root() / spec.plugin_dir / "agents"`
- `plugins/harness/scripts/strap.py:582-594` holds `return _rewrite(path.read_text(encoding="utf-8"), root, spec, part.path)`
- `plugins/harness/scripts/strap.py:601-602` holds `path = source / spec.plugin_dir / "agents" / f"{scenario.role}.md"`
- `plugins/harness/scripts/strap.py:722` holds `print(f"bump: {spec.plugin_dir}/.claude-plugin/plugin.json")`
- `tests/scripts/test_strap_driver.py:80-83` holds `config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()}`
- `tests/scripts/test_strap_gate.py:91-94` holds `config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()}`
- `tests/contract/test_root_separation.py:150-151` holds `def _strap_new_args(root: Path) -> List[str]:`

strap.py: cmd_new takes plugin_dir or target from profile new_fields(active(), root) per active().strap.target and checks the profile's skill_md for exists / --edit. _edit_parts lists the profile's skill_folder and gives the profile's models / api / driver paths their kinds when tracked inside the folder (project) or appends them when outside (harness). _lint_problems: harness -> lint_skill as today, project -> lint_project_skill. _role_problems and _agent_text read profile.agents_dir. _rewrite delegates to profile.rewrite(text, source, Path(run.tree)). cmd_scaffold prints the bump: line only when profile.bump is set. Harness-layout fixtures (tests/scripts/test_strap_driver.py, tests/scripts/test_strap_gate.py) add "strap": {"target": "harness"} to their config; the _strap_new_args docstring in tests/contract/test_root_separation.py no longer claims a plugin is required. A project role agent's body goes through the same rewrite as the SKILL.md (its ${CLAUDE_PROJECT_DIR} points at the run tree); a harness agent body is copied unchanged.

- [x] Test `tests/scripts/test_strap_project_profile.py::test_new_records_the_project_target` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_new_refuses_an_existing_project_skill` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_edit_gives_scripts_their_part_kinds` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_scaffold_writes_the_skill_folder_without_a_bump_line` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_check_applies_the_project_lint` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_check_finds_role_agents_in_agents_dir` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_init_reads_the_role_agent_from_agents_dir` fails with ImportError, then passes
- [x] Test `tests/scripts/test_strap_project_profile.py::test_init_green_rewrites_project_dir_to_the_run_tree` fails with ImportError, then passes
- [x] Run `python -m pytest tests/scripts/test_strap_driver.py tests/scripts/test_strap_gate.py tests/contract/test_root_separation.py -q`: all passed
- [x] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py check writing-docstrings`: check [ok] apart from the stale: line TASK-9 closes
- [x] Record the commit: `plan.py record 0003 TASK-7 --sha <sha>`

**Evidence:** commit 6d25327: 8 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/scripts/test_strap_project_profile.py::test_new_records_the_project_target tests/scripts/test_strap_project_profile.py::test_new_refuses_an_existing_project_skill tests/scripts/test_strap_project_profile.py::test_edit_gives_scripts_their_part_kinds tests/scripts/test_strap_project_profile.py::test_scaffold_writes_the_skill_folder_without_a_bump_line tests/scripts/test_strap_project_profile.py::test_check_applies_the_project_lint tests/scripts/test_strap_project_profile.py::test_check_finds_role_agents_in_agents_dir tests/scripts/test_strap_project_profile.py::test_init_reads_the_role_agent_from_agents_dir tests/scripts/test_strap_project_profile.py::test_init_green_rewrites_project_dir_to_the_run_tree`

### TASK-8: strap-skills SKILL.md for both profiles, version bump

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-7
**Files:** `plugins/harness/skills/strap-skills/SKILL.md`, `plugins/harness/.claude-plugin/plugin.json`, `tests/skills/test_strap_skills_project_profile_contract.py`, `README.md`

**Anchors:**
- `plugins/harness/skills/strap-skills/SKILL.md:3` holds `description: Use when writing a new harness skill`
- `plugins/harness/skills/strap-skills/SKILL.md:7` holds `# strap-skills: a harness skill, written test-first`
- `plugins/harness/skills/strap-skills/SKILL.md:108-111` holds `` per file and a `bump:` line naming the plugin manifest ``
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.50.0"`

Edit plugins/harness/skills/strap-skills/SKILL.md: description and title cover harness and project skills (drop 'harness skill', name 'project skill'); a short Profiles section naming strap.target, skills_dir, agents_dir and the project prerequisites (harness plugin enabled so harness-skill-api is on PATH; HARNESS_PY pointing at an environment with pydantic>=2, jsonschema, referencing, pytest and the repo's test dependencies); step 2 states the planned-test idiom for project skills (load by path, raise ImportError on a missing file); step 5 names the profile's part paths and template folder, the bump: line for the harness profile only. Keep tests/skills/test_strap_skills_skill_contract.py passing. Bump harness to 0.51.0. Direct edit per D10. The README feature row describes both profiles.

- [x] Test `tests/skills/test_strap_skills_project_profile_contract.py::test_description_is_not_limited_to_harness_skills` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_project_profile_contract.py::test_body_names_the_target_key_and_the_launcher` fails with AssertionError, then passes
- [x] Test `tests/skills/test_strap_skills_project_profile_contract.py::test_body_states_the_project_prerequisites` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/skills/test_strap_skills_skill_contract.py -q`: all passed
- [x] Run `claude plugin validate --strict plugins/harness`: no errors
- [x] Record the commit: `plan.py record 0003 TASK-8 --sha <sha>`

**Evidence:** commit 6d25327: 3 test node(s) passed

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
- `python -m pytest -q tests/skills/test_strap_skills_project_profile_contract.py::test_description_is_not_limited_to_harness_skills tests/skills/test_strap_skills_project_profile_contract.py::test_body_names_the_target_key_and_the_launcher tests/skills/test_strap_skills_project_profile_contract.py::test_body_states_the_project_prerequisites`

### TASK-9: Refreeze writing-docstrings after the config edits

**Status:** COMPLETE | **Model:** opus | **Depends on:** TASK-1, TASK-8
**Files:** `docs/plans/strap/writing-docstrings/SkillSpec.json`

On the target branch after harness:a-w, with the developer's OK: config.py and defaults.json are writing-docstrings parts, so its hash is stale. Run strap.py check writing-docstrings (expect the stale: line), run and grade a green per judgment behavior on the new hash, then freeze writing-docstrings --refreeze. Command-only item.

- [x] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py check writing-docstrings`: stale: frozen at <old12>
- [x] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py freeze writing-docstrings --refreeze`: freeze [done] | writing-docstrings | ... | was <old12>
- [x] Record the commit: `plan.py record 0003 TASK-9 --sha <sha>`

**Evidence:** commit 6d25327

- `6d2532769986bd8572d242799377a71f4c0b3664`
- `tree 45d59ce26bafe8be1d267282bcaae45f981ad9dd`
