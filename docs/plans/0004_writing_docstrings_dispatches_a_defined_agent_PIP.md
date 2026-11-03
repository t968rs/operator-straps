# Plan 0004: writing docstrings dispatches a defined agent

> Rendered by `plan.py render` from `0004_writing_docstrings_dispatches_a_defined_agent_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-03
**Spec:** `docs/superpowers/specs/2026-11-03-writing-docstrings-dispatch-design.md`
**Branch:** 1117-writing-docstrings -> main
**Base commit:** `577f516`
**Frozen:** 2026-11-03 at `7d27356`
**Execution model:** serial

## Decisions

- **D1** How are files and symbols named on the command line? Chosen: `per-file-scope` (bare path = all; file.py::name narrows; bare symbols only with one file; directory = tracked .py files). Rejected: `row-wide-symbols` (one Symbols line for the whole row). Spec D1 after the builder check: each file carries its own scope.
- **D2** How is the undocumented-symbols question answered? Chosen: `include-new-flag` (--include-new / -in, default off, sets New docstrings: yes|no). Rejected: `ask-mid-run` (the agent asks the developer during the run). Developer decision; a subagent cannot pause for an answer.
- **D3** Where does a request for new docstrings in words set -in? Chosen: `session-sets-flag` (the session reads the request and the -- tail and passes -in; restyle words never do). Rejected: `flag-only` (only the literal flag sets it). Interpreting intent is the session's job (issue goal 2).
- **D4** How does one invocation split across files? Chosen: `parallel-flag` (--parallel / -p, default off; one row per file, one row for a single file). Rejected: `always-one` (always one agent). Developer decision.
- **D5** Where do parallel agents write, and where does the tool probe edit? Chosen: `checkout-probe-beside` (direct edits in the checkout; probe file _docstring_probe.py beside the first target). Rejected: `checkout-probe-state-dir` (direct edits; probe under state_dir), `parallel2-worktrees` (one parallel2 worktree per file). Developer decision: one file per agent is disjoint by construction; the probe meets the real Edit allow rules.
- **D6** Which model runs a work row? Chosen: `opus` (opus in both modes). Rejected: `sonnet` (sonnet). Tiering turns on reading caveats (B6-B8).
- **D7** What is the dispatch row format? Chosen: `header-plus-lines` (agent=<type> model=<m>, then Project root, New docstrings, one Scope line per file, Probe: yes on the probe row). Rejected: `json` (a JSON object per row). Same header as the pr_review, strap and bubble_memo rows.
- **D8** What does the agent reply? Chosen: `per-file-sections` (per file: tier lines, Rewritten, Kept (in layout), Undocumented (rerun with --include-new), Defects (not fixed), Check). Rejected: `free-text` (free text). The session relays it unedited and concatenates -p replies in row order.
- **D9** Which tools does the agent carry? Chosen: `read-edit-grep-bash` (Read, Edit, Grep, Bash). Rejected: `plus-write-glob` (adds Write and Glob). Edits stay on Scope files; Bash runs the tier command through hpy and read-only git.
- **D10** The writing-docstrings SkillSpec is frozen (mode new): a frozen spec takes only part changes, greens and --refreeze, its behaviors stay locked, and its B5 contract pins and session-role B6-B8 scenarios no longer fit the change. How does the strap gate cover this edit? Chosen: `archive-and-edit` (git mv the frozen spec folder to docs/plans/strap/_archive/writing-docstrings-187/, then strap.py new writing-docstrings --edit opens a fresh edit spec). Rejected: `refreeze-only` (keep the frozen spec: add_part the agent and driver, greens on the new hash, freeze --refreeze; no new behaviors), `no-strap` (skip the strap gate; the plan's tests and the contract test are the proof). Developer decision: a fresh edit spec lets the new dispatch and -in behaviors take baselines and moves B6-B8 to the docstring-writer role; the frozen spec stays readable in the archive.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| work model | opus | docs/superpowers/specs/2026-11-03-writing-docstrings-dispatch-design.md D6 | opus |
| probe model | haiku | docs/superpowers/specs/2026-11-03-writing-docstrings-dispatch-design.md D5 | checkout-probe-beside |
| probe file name | _docstring_probe.py | docs/superpowers/specs/2026-11-03-writing-docstrings-dispatch-design.md D5 | checkout-probe-beside |
| agent | harness:docstring-writer | docs/superpowers/specs/2026-11-03-writing-docstrings-dispatch-design.md Intent | - |
| harness plugin version | 0.52.0 | docs/superpowers/specs/2026-11-03-writing-docstrings-dispatch-design.md Constraints | - |

## Formats

- **dispatch row**: `agent=harness:docstring-writer model=opus
Project root: C:/p
New docstrings: no
Scope: C:/p/src/a.py: all`, copied from `plugins/harness/scripts/strap.py:550`

## Sweeps

- **S1** `"\$\{CLAUDE_PLUGIN_ROOT\}/skills/writing-docstrings/commands/docstring_tiers\.py"`: `plugins/harness/skills/writing-docstrings/SKILL.md` (the measure step moves to the agent file (TASK-4)), `tests/skills/test_writing_docstrings_skill_contract.py` (the COMMAND pin moves from the SKILL.md body to the agent file (TASK-4))

## Tasks

### TASK-1: strap.target harness for this repository

**Status:** PENDING | **Model:** haiku | **Depends on:** none
**Files:** `.claude/harness.json`, `CLAUDE.md`

**Anchors:**
- `.claude/harness.json:5-7` holds `"plans": "docs/plans"`
- `CLAUDE.md:38-42` holds `` That line waits for a published release whose schema carries the `strap` key ``

Add "strap": {"target": "harness"} to .claude/harness.json (after "todo"). Rewrite the CLAUDE.md 'Strapping a harness skill' paragraph: the line is in place since 0.51.0 reached main (PR #188); strap.py new <name> here scaffolds under plugins/harness/; open specs keep their recorded plugin_dir.

- [ ] Run `python -c "import sys; sys.path.insert(0, 'plugins/harness/lib'); from pathlib import Path; from harness_lib.config import load_config; print(load_config(Path('.')).strap.target)"`: harness
- [ ] Record the commit: `plan.py record 0004 TASK-1 --sha <sha>`

**Evidence:** not started

### TASK-2: Scope, row and probe models and API

**Status:** PENDING | **Model:** sonnet | **Depends on:** TASK-1
**Files:** `plugins/harness/lib/harness_lib/writing_docstrings_models.py`, `plugins/harness/lib/harness_lib/writing_docstrings_api.py`, `tests/lib/test_writing_docstrings_dispatch_api.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/writing_docstrings_api.py:24-25` holds `"unmatched"]`
- `plugins/harness/lib/harness_lib/writing_docstrings_api.py:281` holds `def report(path: Path, wanted: Sequence[str], max_line: int) -> List[SymbolReport]:`
- `plugins/harness/lib/harness_lib/writing_docstrings_api.py:302` holds `def unmatched(rows: Sequence[SymbolReport], wanted: Sequence[str]) -> List[str]:`
- `plugins/harness/lib/harness_lib/writing_docstrings_models.py:56-59` holds `model_config = ConfigDict(extra="forbid")`

Copy docs/plans/0004/tests/tests/lib/test_writing_docstrings_dispatch_api.py to tests/lib/test_writing_docstrings_dispatch_api.py. In plugins/harness/lib/harness_lib/writing_docstrings_models.py add AGENT='harness:docstring-writer', WORK_MODEL='opus', PROBE_MODEL='haiku', PROBE_NAME='_docstring_probe.py', PROBE_SOURCE (a module with one undocumented two-line function), FileScope (path: absolute posix str; names: List[str], empty meaning all; extra forbid; line() -> 'Scope: <path>: all' or 'Scope: <path>: a, b') and DispatchRow (model, project_root, new_docstrings: bool, scopes: List[FileScope] with min_length 1, probe: bool = False; extra forbid; text() -> 'agent=<AGENT> model=<model>', 'Project root: <root>', 'New docstrings: yes|no', one Scope line per scope, then 'Probe: yes' on a probe row). In plugins/harness/lib/harness_lib/writing_docstrings_api.py add DispatchError(ValueError) carrying .problems (every defect, collected before raising), resolve_scope(root, tokens, cwd) per spec D1 (tokens resolved against cwd and kept inside root; a directory becomes its git ls-files tracked .py files, sorted; names checked through report and unmatched; every file parsed), plan_rows(root, scopes, *, new_docstrings, parallel), write_probe(scopes) (beside scopes[0], replacing a stale probe), probe_row(root, probe) and clear_probe(path) (removes only a file named PROBE_NAME; False when absent; DispatchError for any other name). Paths are resolve()d and printed as_posix. Export the new names in __all__. Functions under 50 lines; Optional/Union typing; no first or second person.

- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_bare_path_scopes_every_function` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_double_colon_narrows_its_file_only` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_bare_symbols_narrow_a_single_file` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_relative_tokens_resolve_against_cwd` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_bare_symbols_with_two_files_are_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_one_file_named_bare_and_narrowed_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_directory_expands_to_tracked_python_files` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_directory_without_tracked_python_files_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_unknown_symbol_is_refused_before_any_row` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_method_name_or_qualname_matches` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_unparsable_file_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_missing_path_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_non_python_file_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_path_outside_the_project_is_refused` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_every_defect_is_reported_together` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_one_row_without_parallel` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_one_row_per_file_with_parallel` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_parallel_over_one_file_is_one_row` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_row_text_is_the_header_then_the_prompt_lines` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_probe_is_written_beside_the_first_file_over_a_stale_one` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_probe_row_asks_for_a_new_docstring_on_the_probe_file` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_clear_probe_removes_only_a_probe_file` fails with ImportError, then passes
- [ ] Test `tests/lib/test_writing_docstrings_dispatch_api.py::test_dispatch_models_forbid_extra_keys` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/lib/test_writing_docstrings_api.py -q`: all passed
- [ ] Run `python -m ruff check --no-cache plugins/harness/lib/harness_lib/writing_docstrings_models.py plugins/harness/lib/harness_lib/writing_docstrings_api.py tests/lib/test_writing_docstrings_dispatch_api.py`: All checks passed!
- [ ] Record the commit: `plan.py record 0004 TASK-2 --sha <sha>`

**Evidence:** not started

### TASK-3: docstring_dispatch.py driver and its root-separation case

**Status:** PENDING | **Model:** sonnet | **Depends on:** TASK-2
**Files:** `plugins/harness/skills/writing-docstrings/commands/docstring_dispatch.py`, `tests/skills/test_docstring_dispatch_command.py`, `tests/contract/test_root_separation.py`

**Anchors:**
- `plugins/harness/skills/writing-docstrings/commands/docstring_tiers.py:44` holds `cfg = activate(load_config(project_root(start)))`
- `tests/contract/test_root_separation.py:206` holds `MUST_EXIT_ZERO = frozenset({"strap new", "plan new", "plan_api write", "docstring-tiers"})`

Copy docs/plans/0004/tests/tests/skills/test_docstring_dispatch_command.py and docs/plans/0004/tests/tests/contract/test_root_separation.py to their repo paths. New plugins/harness/skills/writing-docstrings/commands/docstring_dispatch.py, shaped like docstring_tiers.py (sys.path insert of lib, one activate(load_config(project_root(start))) with start = --repo or cwd): argparse with allow_abbrev=False and an error() that raises DispatchError; options --repo, --include-new/-in, --parallel/-p, --clear-probe PATH; tokens nargs='*'. No token and no --clear-probe is a problem. Rows print separated by one blank line; with -p and two or more rows, write_probe runs first and probe_row prints before the work rows. A DispatchError or ConfigError prints one 'problem: <text>' line per defect on stderr, exit 1, nothing on stdout and no probe written. The module docstring states the usage.

- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_two_files_print_one_row` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_parallel_prints_the_probe_row_then_one_row_per_file` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_long_parallel_flag_matches_the_short_one` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_parallel_over_one_file_writes_no_probe` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_include_new_flags_set_new_docstrings` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_a_problem_prints_nothing_on_stdout` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_unknown_flag_is_a_problem_line` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_no_path_is_a_problem_line` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_clear_probe_removes_the_probe_file` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_docstring_dispatch_command.py::test_clear_probe_refuses_another_file` fails with AssertionError, then passes
- [ ] Test `tests/contract/test_root_separation.py::test_entry_point_writes_nothing_under_plugins[docstring-dispatch]` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/skills/test_docstring_tiers_command.py -q`: all passed
- [ ] Run `python -m ruff check --no-cache plugins/harness/skills/writing-docstrings/commands/docstring_dispatch.py tests/skills/test_docstring_dispatch_command.py tests/contract/test_root_separation.py`: All checks passed!
- [ ] Record the commit: `plan.py record 0004 TASK-3 --sha <sha>`

**Evidence:** not started

### TASK-4: docstring-writer agent and dispatching SKILL.md through the strap gate

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-3
**Files:** `plugins/harness/agents/docstring-writer.md`, `plugins/harness/skills/writing-docstrings/SKILL.md`, `tests/skills/test_writing_docstrings_skill_contract.py`, `docs/plans/strap/writing-docstrings/SkillSpec.json`, `docs/plans/strap/_archive/writing-docstrings-187/SkillSpec.json`

**Anchors:**
- `plugins/harness/skills/writing-docstrings/SKILL.md:38` holds `1. **Measure.** Run the tier command with the Bash tool on each file in scope`
- `plugins/harness/skills/writing-docstrings/SKILL.md:25-26` holds `Name each undocumented symbol in the reply`
- `tests/skills/test_writing_docstrings_skill_contract.py:22-23` holds `skills/writing-docstrings/commands/docstring_tiers.py`

First git mv docs/plans/strap/writing-docstrings to docs/plans/strap/_archive/writing-docstrings-187 (D10), then run strap.py new writing-docstrings --edit (base HEAD) and continue harness:strap-skills from step 2. Behaviors to cover: mechanical - SKILL.md runs docstring_dispatch.py through hpy and dispatches harness:docstring-writer; the agent file runs the tier command through hpy, reads ${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/docstring_format.md, names every flag, the full-tier threshold, the D7 prompt lines and the D8 reply headings (the contract-test pins move from the SKILL.md body to the agent file). Judgment - the session dispatches every printed row with its model and never edits a docstring itself; the session passes -in only on an explicit ask (a 'make these consistent' request over a file with undocumented functions); B6-B8 on the docstring-writer role. New plugins/harness/agents/docstring-writer.md: frontmatter name docstring-writer, model opus, tools Read, Edit, Grep, Bash, an examples block; the body holds the procedure now in SKILL.md (What a restyle touches, Procedure, Tier 1-3, All tiers), the New docstrings rule, the Scope-only edit rule and the D8 reply. SKILL.md becomes: split the arguments, interpret intent (D3), run the driver, dispatch the probe row alone and then --clear-probe it, dispatch every work row in one message with the Developer guidance line appended, relay the replies; it states the D5 departure from harness:parallel2 and its reason. The Use-when description stays; the argument-hint gains -in and -p.

- [ ] Run `git mv docs/plans/strap/writing-docstrings docs/plans/strap/_archive/writing-docstrings-187`: exit 0
- [ ] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py new writing-docstrings --edit`: new [done] | writing-docstrings
- [ ] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py check writing-docstrings`: check [ok]
- [ ] Run `sh plugins/harness/scripts/hpy plugins/harness/scripts/strap.py freeze writing-docstrings`: freeze [done] | writing-docstrings
- [ ] Run `python -m pytest tests/skills/test_writing_docstrings_skill_contract.py tests/skills/test_skill_guidance_tail_contract.py -q`: all passed
- [ ] Run `claude plugin validate --strict plugins/harness`: no errors
- [ ] Record the commit: `plan.py record 0004 TASK-4 --sha <sha>`

**Evidence:** not started

### TASK-5: README row and harness 0.52.0

**Status:** PENDING | **Model:** haiku | **Depends on:** TASK-4
**Files:** `README.md`, `plugins/harness/.claude-plugin/plugin.json`

**Anchors:**
- `README.md:28` holds `` | Docstrings by tier | `writing-docstrings` ``
- `plugins/harness/.claude-plugin/plugin.json:3` holds `"version": "0.51.0",`

README skills-table row 'Docstrings by tier': the session turns the request into arguments and dispatches harness:docstring-writer; --include-new / -in adds docstrings to undocumented functions; --parallel / -p runs one agent per file after a tool probe. Bump plugins/harness/.claude-plugin/plugin.json to 0.52.0.

- [ ] Run `claude plugin validate --strict plugins/harness`: no errors
- [ ] Record the commit: `plan.py record 0004 TASK-5 --sha <sha>`

**Evidence:** not started
