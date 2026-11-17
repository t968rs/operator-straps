# Harness port: decouple the imported floodplain harness (floodplain_development #1561)

The import commit copied the harness verbatim. This plan turns it into a generic plugin: every floodplain value moves
into the consuming project's `.claude/harness.json`, every path resolves against the project (data) or the plugin
(code), and every moved test runs against a throwaway project built by `make_project`.

## Shared contract (all units)

### Roots and config

- `harness_lib.project.project_root(start=None)`: git top level of `start`/cwd, else `CLAUDE_PROJECT_DIR`, else cwd.
- `harness_lib.project.plugin_root()`: the `plugins/harness` directory. **Never write under it.**
- `harness_lib.project.schema_path(name, cfg)`: project pinned copy (`cfg.schemas_dir`) first, else plugin `schemas/`.
- `harness_lib.config.load_config(root) -> HarnessConfig`, `activate(cfg)`, `active()`, `deactivate()`.
  - **Drivers** (scripts, hooks, skill commands) call `activate(load_config(project_root(<repo arg or cwd>)))` once
    at startup.
  - **Library code** reads `active()` wherever a module constant used to hold a floodplain value. Prefer reading it
    inside functions, never at import time.
- Field names: see `plugins/harness/lib/harness_lib/config.py` and `config/defaults.json`. Units do **not** edit
  `config.py`, `project.py`, `defaults.json`, `harness.schema.json` or `tests/conftest.py`. A unit that needs a new
  key reports it in its final summary (key, type, default, reason) and uses the closest existing key meanwhile.

### Fixed paths every unit must agree on

| What | Path |
|---|---|
| Phase 5 sentinel | `<project>/<state_dir>/pr-review/.phase5_pending_<PR>` (file content format unchanged) |
| pr-team runtime | `<project>/<state_dir>/pr-team/_runtime/` |
| Invocation matrix | `<project>/<matrix_path>` |
| Review run scratch | `<project>/<artifacts.scratch>` |
| Review / plan / summary / commit-message output | `<project>/<artifacts.{reviews,plans,summaries,commit_messages}>` |
| Schemas | `schema_path(name, cfg)` |
| Floodplain-specific lists (guard suites, registry, test roots, buckets, domain pointers) | `cfg.review.*`, `cfg.tests.*`, `cfg.commit_buckets` |
| Base branch | `cfg.resolve_base_branch()` (never a literal `dev`) |

### How code finds the library

- Scripts in `plugins/harness/scripts/*.py`: `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))`.
- Hooks in `plugins/harness/hooks/*.py`: same (`parents[1] / "lib"`).
- Skill commands `plugins/harness/skills/<s>/commands/*.py`: `parents[3] / "lib"`.
- Hooks resolve the project from the payload: `project_root(Path(payload.get("cwd") or os.getcwd()))`.

### How skills and agents invoke code

- Bash tool only (never the PowerShell tool): `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/<x>.py" ...`
- Skill-local files: `${CLAUDE_SKILL_DIR}/...`.
- Agents are dispatched by namespaced id: `harness:pr-reviewer`, `harness:pr-fixer`, `harness:pr-team-orchestrator`,
  `harness:pr-team-fixer`, `harness:messenger`, `harness:roast-my-code`. Skills are `harness:<name>`.
- No `$FPM_PY`, no `.claude/agent_scripts`, no `scripts/gh_workflows`, no `.claude/hooks/`, no `scripts/__tests__`,
  no `scripts/fpm`, no `testRegistry` literal in plugin code or skill text. Floodplain examples in prose become
  generic examples or "the project's configured X".

### Tests

- Run: `"$FPM_PY" -m pytest -c "<wt>/pyproject.toml" --rootdir "<wt>" <wt>/tests/<file>.py -q` (no `cd`; one
  command per Bash call; name files, never a directory).
- Tests build projects with the `make_project(config=..., files=...)` fixture and `activate(load_config(root))`.
  No test reads the live floodplain repo. Vendored fixture data goes in `tests/fixtures/`.
- No new conftest files: helpers go in the test module or in `tests/<area>/_<unit>_helpers.py`. `tests/conftest.py`
  is frozen.
- Code style: Python 3.11, `Optional[X]`/`Union[X, Y]`, no first/second person in comments, functions under 50 lines,
  ruff line length 110.

## Units

| Unit | Branch | Owns |
|---|---|---|
| U1 commit | `wt/u1-commit` | lib `branch_capture`, `branch_commits`, `commit_diff`, `commit_grouping`, `commit_txt`, `git_status_filter_excluded`; scripts `branch_commit_msg.py`, `txt_to_commit_dict.py`; skills `c-msg`, `branch-commit-msg`, `merge-commit-msg`; agent `messenger.md`; `reference/commit_format.md`; tests `tests/lib/test_{branch_capture,branch_commits,commit_diff,commit_grouping,commit_txt,git_status_filter_excluded}.py`, `tests/scripts/test_{branch_commit_msg,txt_to_commit_dict}.py` |
| U2 summary | `wt/u2-summary` | lib `pr_capture`, `pr_summary`; script `pr_sum.py`; skills `pr-sum`, `pr-sum-viz`, `pr-sum-alt`; tests `tests/lib/test_pr_summary.py`, `tests/scripts/test_pr_sum.py` |
| U3 review | `wt/u3-review` | lib `review_models`, `review_merge`, `review_plan`; script `pr_review.py`; skills `pr-review/**` (incl. `commands/`), `pr-team/**` (incl. `commands/qa_review_json.py`), `fold-in-review`, `post-forcepush`; agents `pr-reviewer`, `pr-fixer`, `pr-team-orchestrator`, `pr-team-fixer`; tests `tests/lib/test_{review_models,review_merge,review_plan}.py`, `tests/scripts/test_{pr_review_driver,phase4_branch_safety_second_run,phase4_second_run_no_exclusions_fixture}.py`, `tests/skills/test_{pr_review_skill_description,canonical_prompt_template_referenced,pr_review_shim_slug_rule_byte_identical,pr_review_skill_contract,terminals_fixer_schema}.py`, `tests/fixtures/pr1558_issues.json` |
| U4 hooks+schemas | `wt/u4-guards` | hooks `validate_pr_json_schema.py`, `check_phase5_sentinel.py`; lib `validation/**`; `schemas/**`; tests `tests/hooks/**`, `tests/schemas/**` |
| U5 mods | `wt/u5-mods` | `plugins/pr-review-watch/**`, `plugins/session-bookmark/**`, `plugins/git-status/**`; test `tests/mods/test_pr_review_watch_matrix_contract.py` |
| U6 general | `wt/u6-general` | hooks `bash_discipline.py`, `bash_allow_shapes.py`, `powershell_allow_shapes.py`, `approve-python-c.sh` -> `approve_python_c.py`, new `session_rules.py`, `hooks/hooks.json`; `rules/HARNESS_RULES.md`; skills `d-w`, `parallel2`, `dev-pipeline`, `decompose-module`, `spatialist`, `subagent-reporting`, `efficient-file-reading`, `roast-my-code`, `agent-permissions`, `consumer-contract-audit`; agent `roast-my-code.md`; tests `tests/skills/test_detached_worktree_script.py`, new `tests/hooks/test_<hook>.py` for its own hooks, new `tests/contract/test_hooks_json_paths.py` |

### Cross-unit interfaces (do not break)

- U1 keeps these importable with compatible signatures: `branch_capture.{CaptureError, git, git_out}`,
  `branch_commits.{Bucket, path_bucket}`. `path_bucket` reads `active().commit_buckets`. `resolve_merge_base` becomes
  `resolve_merge_base(repo, base, fetch=True)`.
- U2 keeps `pr_capture.{PrMeta, budgeted_diff, capture_pr, file_patches, gh_metadata, read_rank}` and
  `pr_summary.{PrFacts, PrFile}` importable with compatible signatures (new parameters keyword-only, defaulted).
- U4 keeps `validation.id_handling` / `validation.pr_json_validation` public function names; U3's `review_merge`
  imports them as `harness_lib.validation.*` instead of loading `.claude/hooks/...` by file path.
- U6's `hooks.json` registers U4's hooks by these exact file names (shell form, `${CLAUDE_PLUGIN_ROOT}`):
  `PostToolUse Write|Edit|Bash -> validate_pr_json_schema.py`, `Stop -> check_phase5_sentinel.py`.

### Out of scope here

Repo README / CLAUDE.md / CI / the grep-ban and root-separation contract tests (main session, after merge), and every
floodplain_development change (cutover PRs).
