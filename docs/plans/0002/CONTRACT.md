# Plan 0002 contract: names and signatures the planned tests pin

Spec: `docs/superpowers/specs/2026-10-29-strap-skills-design.md`. This file fixes the public surface so the
planned test files and the implementation agree. Python 3.11, `Optional`/`Union`, pydantic v2.

## `plugins/harness/lib/harness_lib/strap_models.py`

Enums, all `class X(str, Enum)`, member value == member name lower-case as listed:

- `SpecMode`: NEW="new", EDIT="edit"
- `BehaviorKind`: MECHANICAL, JUDGMENT
- `JudgmentType`: DISCIPLINE, TECHNIQUE, PATTERN, REFERENCE
- `Pressure`: TIME, SUNK_COST="sunk_cost", AUTHORITY, EXHAUSTION, SOCIAL, PRAGMATIC
- `PartKind`: SKILL_MD="skill_md", MODELS, API, DRIVER, AGENT, CONTRACT_TEST="contract_test", REFERENCE
- `CheckKind`: FILE_UNCHANGED, FILE_CHANGED, PATH_PRESENT, PATH_ABSENT, HEAD_UNCHANGED, REPLY_MATCHES,
  REPLY_LACKS (values snake_case)
- `ReplyAct`: REFUSES, ASKS_DEVELOPER="asks_developer", REDIRECTS, DEFERS, RATIONALIZES, PROCEEDS
- `GradeValue`: PRESENT, ABSENT, UNCLEAR
- `Grader`: SESSION, JUDGE
- `Arm`: BASELINE, GREEN
- `BehaviorState`: OPEN, DRAWN, RED, GREEN, RETEST, DROPPED
- `DrawReason`: INITIAL, RETEST
- `RedException`: values exactly `ImportError`, `AttributeError`, `AssertionError`, `NotImplementedError`,
  `TypeError` (member names upper snake: IMPORT_ERROR, ...)

Constants: `MIN_SCENARIOS = 2`, `MIN_DISCIPLINE_PRESSURES = 3`, `DESCRIPTION_MAX = 1024`,
`NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"`, `SPEC_FILE = "SkillSpec.json"`.

Models (`BaseModel`, `model_config = ConfigDict(extra="forbid")`):

- `Part(kind: PartKind, path: str)`: `path` repo-relative POSIX.
- `PlannedTest(node: str, red: RedException)`: `node` contains `::`.
- `Check(kind: CheckKind, target: str, expect_baseline: bool, expect_green: bool)`.
- `JudgedItem(act: ReplyAct, of: str, expect_baseline: GradeValue, expect_green: GradeValue)`;
  `UNCLEAR` is rejected for either expectation.
- `Scenario(id: str, task: str, pressures: List[Pressure] = [], tempts: str, fixture: Optional[str] = None,
  checks: List[Check] = [], judged: List[JudgedItem] = [], role: str = "session")`.
  Validators: id matches `^SC-\d+$`; at least one check or judged item; no duplicate pressures.
- `Behavior(id: str, statement: str, kind: BehaviorKind, type: Optional[JudgmentType] = None, rationale: str,
  tests: List[PlannedTest] = [], scenarios: List[Scenario] = [], state: BehaviorState = OPEN,
  dropped_reason: Optional[str] = None)`.
  Validators: id matches `^B\d+$`; `type` required iff `kind == JUDGMENT`; a judgment behavior has no
  `tests`; a mechanical behavior has no `scenarios`; when `type == DISCIPLINE` every scenario has at least
  `MIN_DISCIPLINE_PRESSURES` pressures; `state == DROPPED` iff `dropped_reason` is non-empty; scenario ids
  unique within the behavior.
  (`MIN_SCENARIOS` is not a model validator: a behavior is built up one scenario at a time. `draw` and
  `freeze` enforce it.)
- `Draw(behavior: str, scenario: str, seed: int, reason: DrawReason, at: str)`.
- `CheckResult(index: int, held: bool, detail: str)`.
- `Run(id: str, behavior: str, scenario: str, arm: Arm, skill_hash: str, reply: str = "", reply_sha256: str = "",
  diff: List[str] = [], checks: List[CheckResult] = [], recorded: bool = False)`. Validator: when
  `recorded`, `reply_sha256 == sha256(reply.encode("utf-8")).hexdigest()`. Id `^R-\d+$`.
- `Grade(run: str, item: int, value: GradeValue, quote: str, grader: Grader)`. Validator: `quote` non-empty
  after strip.
- `Frozen(skill_hash: str, grader: Grader, at: str)`.
- `SkillSpec(name: str, mode: SpecMode, base: Optional[str] = None, judge: bool = False, plugin_dir: str,
  parts: List[Part] = [], behaviors: List[Behavior] = [], draws: List[Draw] = [], runs: List[Run] = [],
  grades: List[Grade] = [], frozen: Optional[Frozen] = None, driver_digest: str = "")`.
  Validators: `name` matches `NAME_PATTERN`; `base` set iff `mode == EDIT`; behavior ids unique; every
  draw, run and grade names a known behavior / scenario / run.

Driver-owned fields: `draws`, `runs`, `grades`, `frozen`, `driver_digest` on `SkillSpec`, and `state` on
`Behavior`. Each carries `json_schema_extra={"driver_owned": True}`. Module helpers:

- `DRIVER_OWNED_TOP: Tuple[str, ...]` and `DRIVER_OWNED_BEHAVIOR: Tuple[str, ...]`, derived from that
  metadata (not hand-listed).
- `driver_digest(spec: SkillSpec) -> str`: sha256 hex of the canonical JSON (sorted keys, no whitespace) of
  the driver-owned fields, including each behavior's `state` keyed by behavior id; excludes
  `driver_digest` itself.
- `load_spec(path: Path) -> SkillSpec` (raises `pydantic.ValidationError` or `OSError`).
- `dump_spec(spec: SkillSpec) -> str`: `json.dumps(spec.model_dump(mode="json"), indent=2) + "\n"`.
- `schema_text() -> str`: `json.dumps(SkillSpec.model_json_schema(), indent=2) + "\n"` with `"$schema":
  "https://json-schema.org/draft/2020-12/schema"` and `"$id":
  "https://github.com/t968rs/operator-straps/plugins/harness/schemas/SkillSpec.schema.json"` added first.

## `plugins/harness/lib/harness_lib/strap_runs.py` (skill-agnostic: imports only `strap_models` and stdlib)

- `content_hash(root: Path, paths: Sequence[str]) -> str`: sha256 over, for each path in sorted order,
  `path + "\0" + file bytes + "\0"`; a missing file hashes as `path + "\0<missing>\0"`.
- `draw_scenario(behavior: Behavior, exclude: Sequence[str], seed: int) -> str`: the scenario id picked by
  `random.Random(seed).choice` over the behavior's scenario ids not in `exclude`, in declared order; raises
  `ValueError("<behavior id> has no undrawn scenario")` when none remain.
- `new_seed() -> int`: `secrets.randbits(32)`.
- `evaluate_checks(checks: Sequence[Check], arm: Arm, changed: Sequence[str], present: Callable[[str], bool],
  head_moved: bool, reply: str) -> List[CheckResult]`: `held` is True when the observed fact equals the
  arm's expectation (`expect_baseline` or `expect_green`). Facts: FILE_CHANGED = target in `changed`;
  FILE_UNCHANGED = not in `changed`; PATH_PRESENT / PATH_ABSENT via `present(target)`; HEAD_UNCHANGED = not
  `head_moved`; REPLY_MATCHES = `re.search(target, reply, re.MULTILINE)`; REPLY_LACKS = no match.
- `quote_found(quote: str, reply: str) -> bool`: whitespace-normalized substring test (runs of whitespace
  collapse to one space on both sides).
- `item_matches(expected, observed) -> bool` for one check (`bool`) or judged item (`GradeValue`).
- `baseline_failed(scenario: Scenario, run: Run, grades: Sequence[Grade]) -> bool`: True when any check
  result has `held` True for the baseline arm, or any judged item's grade equals its `expect_baseline`.
  (Baseline expectations describe the tempted move, so a held baseline expectation is the failure.)
- `green_passed(scenario: Scenario, run: Run, grades: Sequence[Grade]) -> bool`: True only when every check
  result held and every judged item has a grade equal to `expect_green`; an UNCLEAR or missing grade is False.
- `must_pass(spec: SkillSpec, behavior_id: str) -> List[str]`: scenario ids that ever had a green run with
  `green_passed` False, plus the latest retest draw's scenario, in first-seen order.

## `plugins/harness/lib/harness_lib/strap_api.py`

Every operation takes `name: str` first (the skill name), resolves the spec at
`spec_path(name) = active().path(active().artifacts.plans) / "strap" / name / SPEC_FILE`, loads it, applies
the change, re-validates, writes `dump_spec`, and returns the re-validated `SkillSpec`. A failed validation
raises before anything is written. Requires an activated config (the `strap.py api` subcommand activates
it). Errors: `StrapError(ValueError)` with a message.

Factories (return validated models; ids assigned by `add_*`):

- `new_behavior(statement, kind, rationale, type=None, tests=()) -> Behavior` (id placeholder `"B0"`).
- `new_test(node, red) -> PlannedTest`.
- `new_scenario(task, tempts, pressures=(), checks=(), judged=(), fixture=None, role="session") -> Scenario`
  (id placeholder `"SC-0"`).
- `new_check(kind, target, baseline: bool, green: bool) -> Check`.
- `new_judged(act, of, baseline, green) -> JudgedItem`.

Operations:

- `add_behavior(name, behavior) -> SkillSpec`: assigns the next `B<n>`.
- `update_behavior(name, behavior_id, **changes) -> SkillSpec`: refuses a driver-owned field with
  `StrapError("<field> is driver-owned")`; refuses any change once `frozen` is set.
- `drop_behavior(name, behavior_id, reason) -> SkillSpec`: sets `state=DROPPED` and `dropped_reason` (the one
  API path that writes `state`, and only to DROPPED).
- `add_scenario(name, behavior_id, scenario) -> SkillSpec`: assigns the next `SC-<n>` unique across the spec.
- `record_run(name, run_id, reply: str) -> SkillSpec`: only for an existing run with `recorded == False`;
  sets `reply`, `reply_sha256`, `recorded=True`. `StrapError("<run> already recorded")` otherwise. Diff and
  check evaluation are the driver's (`strap.py record-run`), which calls this then fills `checks`/`diff`.
- `grade(name, run_id, item, value, quote, grader="session") -> SkillSpec`: refuses an unrecorded run, an
  item index outside the scenario's `judged`, a second grade for the same `(run, item)`, and a quote not
  `quote_found` in the run's reply (`StrapError("quote not found in <run>")`); a `judge` grade on a spec with
  `judge == False` is refused.
- All operations refuse a spec whose stored `driver_digest` differs from `driver_digest(spec)`, checked on
  the spec as loaded before the change (`StrapError("driver-owned fields changed outside strap.py")`), and
  recompute `driver_digest` after every write (a new behavior's `state` enters the digest). Re-validation is
  real: the changed spec is dumped and validated again (`SkillSpec.model_validate(spec.model_dump())`), so an
  object built with `model_construct` cannot slip through.
- `update_behavior` changes are validated through the same re-validation; enum fields accept members or
  their string values.

## `tools/gen_skillspec_schema.py` (repo-only)

`--path PATH` (default `<repo>/plugins/harness/schemas/SkillSpec.schema.json`, resolved from `__file__`);
puts `<repo>/plugins/harness/lib` on `sys.path` itself. Without `--check`: writes `schema_text()` with LF
endings, exit 0. With `--check`: never writes; exit 0 when the file equals `schema_text()` after CRLF->LF
folding, 1 when it differs or is missing (one `problem:` line on stderr).

## `plugins/harness/lib/harness_lib/skill_parts.py` (moved from `tests/lib/_skill_parts.py`)

- `skill_parts(path: Path) -> Tuple[Dict[str, str], str]`: unchanged behavior. `tests/lib/_skill_parts.py`
  becomes a one-line re-export so existing test imports keep working.

## `plugins/harness/lib/harness_lib/strap_lint.py`

`lint_skill(plugin_dir: Path, name: str) -> List[str]`: one problem string per defect, each prefixed
`"<name>: "`:

- `SKILL.md` missing -> `"<name>: no SKILL.md"` (and stop).
- frontmatter `name` != folder name; `description` missing, not starting with `Use when`, over
  `DESCRIPTION_MAX` characters, or containing `\b(I|we|you|your)\b` (case-insensitive word match on
  `I`, `we`, `you`, `your`).
- invocable skill (body contains `$ARGUMENTS`): `argument-hint` missing or lacking `-- <`; body lacks
  `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`; a fenced line carries `$ARGUMENTS`.
- knowledge skill (no `$ARGUMENTS`): `argument-hint` present.
- every `${CLAUDE_PLUGIN_ROOT}/scripts/<x>` and `${CLAUDE_PLUGIN_ROOT}/skills/<...>` path named in the body
  exists under `plugin_dir`; every `harness:<agent>` named in a dispatch exists as
  `plugin_dir/agents/<agent>.md` or `plugin_dir/skills/<agent>/SKILL.md`.
- a fenced line that runs `python` or `python3` directly instead of through `hpy`.
- vendor names: `\b(Anthropic|OpenAI|ChatGPT|Gemini)\b` or `\bClaude\b(?! Code)` outside
  `${CLAUDE_...}` variables and `CLAUDE.md`.

`lint_python(path: Path) -> List[str]`: first/second person (`\b(I|we|you|your|our)\b`, case-insensitive
for `we|you|your|our`, case-sensitive `I`) inside comments and docstrings only.

Repo-literal bans stay in the repository's own contract test, which already walks every plugin file.

## `plugins/harness/lib/harness_lib/strap_scaffold.py`

- `find_plugin_dir(project: Path, plugin_name: str) -> Path`: the one directory under `project` holding
  `.claude-plugin/plugin.json` whose `name` equals `plugin_name` (skipping `.git`, `node_modules`); raises
  `StrapError` for none or more than one.
- `planned_parts(spec: SkillSpec) -> List[Part]`: always `skill_md` (`skills/<name>/SKILL.md`) and
  `contract_test` (`<tests.roots[0]>skills/test_<snake>_skill_contract.py`, project-relative, from the
  active config; `tests/skills/...` under the defaults); when any behavior is
  mechanical also `models` (`lib/harness_lib/<snake>_models.py`) and `api` (`lib/harness_lib/<snake>_api.py`).
  Parts already in `spec.parts` (driver, agents, references added by the author) are kept. `<snake>` is the
  name with `-` as `_`. Plugin-relative parts are stored with the plugin dir prefix, project-relative.
- `render_parts(spec: SkillSpec, project: Path) -> List[Path]`: writes each planned part that does not exist
  from `plugins/harness/skills/strap-skills/templates/<kind>.tmpl` (read through `plugin_root()`), with
  `string.Template` substitution of `$name`, `$snake`, `$title`, `$description`. Refuses (StrapError) for
  `mode == NEW` when a target exists. For `mode == EDIT` writes only missing parts. Returns written paths.
  Rendered SKILL.md passes `lint_skill` with only the `Use when` description stub to fill; rendered Python
  passes `lint_python` and compiles.

## `plugins/harness/scripts/strap.py`

`main(argv: Optional[Sequence[str]] = None) -> int`; `--repo DIR` before the subcommand. Every refusal is one
`problem: <text>` line per defect on stderr and exit 1. Subcommands:

- `new <name> [--edit] [--judge]`: creates `<plans>/strap/<name>/SkillSpec.json`; stdout starts
  `new [done] | <name>`; `--edit` records `base = git rev-parse HEAD` and lists the skill's existing files as
  parts; an existing spec prints `resume | <name> | <n> behaviors` and exits 0; `--judge` differing from the
  stored value once grades exist is refused.
- `check <name>`: refuses `load_spec` errors, a file that differs from `dump_spec(load_spec(file))`, a
  `driver_digest` mismatch, lint problems (skill and Python parts that exist); prints `open: <B>` for each
  judgment behavior with fewer than `MIN_SCENARIOS` scenarios; `check [ok]` when clean.
- `red <name>`: mechanical behaviors' planned tests, through `plan_red.make_tree/overlay/run_red/red_problems`
  with planned files from `<plans>/strap/<name>/tests/<repo path>`; `red [ok]` when clean.
- `draw <name>`: for each judgment behavior with no draw: refuses fewer than `MIN_SCENARIOS`; appends a
  `Draw(reason=INITIAL)`, sets `state=DRAWN`; prints `draw | <B> -> <SC>`; never replaces a draw.
- `run <name> <B> --arm baseline|green`: refuses no draw, green before a recorded baseline of the same
  scenario, and a recorded run of the same `(scenario, arm, skill_hash)`; creates `Run` (`R-<n>`), builds the
  scenario tree under `<worktree root>` at `base` (edit) or HEAD (new) with the fixture overlaid, and prints a
  row: `agent=harness:strap-scenario-runner model=sonnet` then `SKILL: <name>`, `RUN: <R-n>`,
  `TREE: <abs path>`.
- `init <name> --run <R-n>`: prints the brief (task, working tree, and for green or an edit's baseline the
  skill text with `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` rewritten to absolute source paths; for a
  `role` other than `session` the agent's `.md`), ending with the exact `record-run` command.
- `record-run <name> --run <R-n>`: reply on stdin; calls `strap_api.record_run`, then fills `diff` (`git
  status --porcelain` paths of the tree) and `checks` via `evaluate_checks`; drops the tree; prints a fenced
  return block with `SIGNAL: recorded` and the run id.
- `judge-row <name>`: `--judge` specs only; one row `agent=harness:strap-judge model=sonnet` plus `SKILL:`
  and `RUNS:` (comma-separated recorded runs with ungraded judged items).
- `scaffold <name>`: `planned_parts` + `render_parts`; prints each written path and a reminder line
  `bump: <plugin_dir>/.claude-plugin/plugin.json`.
- `retest <name> <B>`: refuses when the behavior has no failed green, or `content_hash` equals the hash of its
  last failed green; appends `Draw(reason=RETEST)` via `draw_scenario` excluding every drawn scenario; sets
  `state=RETEST`.
- `freeze <name>`: refuses each unmet condition of the spec's freeze rule, one line each; on success sets
  `frozen`, prints `freeze [done] | <name> | <hash12> | grader <session|judge>`.
- `api <name>`: reads Python from stdin and runs it with `strap_api`'s public names and `name` bound; the
  config is activated first.

Every write of a driver-owned field recomputes `driver_digest`.

## Agents

- `plugins/harness/agents/strap-scenario-runner.md`: frontmatter `name: strap-scenario-runner`, `model: sonnet`,
  `tools: Read, Edit, Write, Grep, Glob, Bash`; body: first action `init`, work only inside `TREE`, finish
  with exactly one `record-run` heredoc, reply = the printed block verbatim; a session-role scenario ends by
  stating the `Agent(...)` call it would make; stop conditions.
- `plugins/harness/agents/strap-judge.md`: `name: strap-judge`, `model: sonnet`, `tools: Read, Grep, Glob,
  Bash`; grades through `strap.py api` with `grade(..., grader="judge")`, a verbatim quote per item, never
  edits files.

## Skill

`plugins/harness/skills/strap-skills/SKILL.md`: `name: strap-skills`; description starts `Use when`;
`argument-hint: "<name> [--edit] [--judge] [-- <guidance>]"`; cites
`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`; Steps name `new`, `check`, `red`, `draw`, `run`,
`record-run`, `judge-row`, `scaffold`, `retest`, `freeze`, `api`; dispatches `harness:strap-scenario-runner`
and `harness:strap-judge`; one API heredoc; a judgment table. Templates under `skills/strap-skills/templates/`:
`skill_md.tmpl`, `models.tmpl`, `api.tmpl`, `contract_test.tmpl`.

---

# Amendments after the plan review (D8-D21). These override any earlier text they contradict.

## D8. `record_run` is not reachable from `api`; check results must be complete

- `strap_api.__all__` lists exactly: `StrapError`, `spec_path`, `new_behavior`, `new_test`, `new_scenario`,
  `new_check`, `new_judged`, `add_behavior`, `update_behavior`, `drop_behavior`, `add_scenario`, `add_part`,
  `grade`. `record_run` stays importable (`strap.py record-run` calls it) but is not in `__all__`, and neither
  are `driver_digest`, `dump_spec` or any `strap_models` name.
- `strap.py api` binds `__all__` only (through `scripts/skill_api.py`, D19). Code calling `record_run(...)`
  raises `NameError`, reported as a `problem:` line, exit 1.
- `strap_runs.green_passed` is False unless the run's `CheckResult` indexes are exactly
  `range(len(scenario.checks))` and all held. `baseline_failed` counts only present results; a missing result
  never counts as the failure.

## D9. One run per (behavior, scenario, arm, skill_hash)

- `run` with an unrecorded run for the same key re-prints that run's row (same `R-n`; the tree is rebuilt
  when missing) instead of creating a run.
- `record-run` refuses when another recorded run exists for the same key: `problem: <R-n>: <SC> <arm> already
  recorded on this hash`.

## D10. Drawn scenarios are locked

- Once a behavior has any draw, `update_behavior` refuses `scenarios`, `kind` and `type`:
  `StrapError("<B> is drawn")`. `add_scenario` stays allowed (a new scenario is undrawn).

## D11. `new` refusals and `--edit --base`

- `new <name>` (no `--edit`) refuses when `<plugin_dir>/skills/<name>/SKILL.md` exists:
  `problem: <name> exists; use --edit`.
- `new <name> --edit` refuses when it does not exist at HEAD: `problem: <name> has no SKILL.md to edit`.
- `new <name> --edit --base REF`: REF must be an ancestor of HEAD (`git merge-base --is-ancestor`); recorded
  as `base` (full SHA). Without `--base`, `base = HEAD`.
- An edit's baseline arm carries the skill text at `base`; when the skill's SKILL.md is absent at `base`,
  the baseline arm carries no skill text.
- Resume (existing spec) still prints `resume | ...` and exits 0 before any of these refusals.

## D12. Freeze conditions, one `problem:` each

`freeze` refuses, per behavior or spec, with these texts (each after `problem: `):
- `already frozen` (a frozen spec never refreezes);
- `<spec>: no skill_md part`;
- `<B>: fewer than 2 scenarios` (judgment, not dropped);
- `<B>: never drawn`;
- `<B>: no recorded baseline`; `<B>: baseline did not fail`;
- `<B>: no passing green on the current hash`;
- `<B>: <SC> failed green and has not passed on the current hash` (each `must_pass` scenario);
- `<B>: unclear grade on <R-n>`; `<B>: ungraded judged item on <R-n>`;
- `<B>: red not recorded` / `<B>: planned tests fail` (mechanical, D13).
A spec whose every behavior is dropped may freeze (the design allows it). `Frozen.grader` is `judge` when
`spec.judge`, else `session`.

## D13. Mechanical red is recorded and re-checked

- `red` on success sets `state=RED` on each mechanical behavior whose nodes failed as planned (redigest).
- `freeze` runs each mechanical behavior's planned nodes on the working tree (one pytest per node through
  `sys.executable`); each must pass.

## D14. `scaffold` persists parts; `add_part`

- `scaffold` writes `planned_parts(spec)` into `spec.parts` after rendering.
- `strap_api.add_part(name, kind, path) -> SkillSpec` adds a part (refuses a duplicate path).
- `run` and `freeze` refuse a spec without a `skill_md` part (`problem: <spec>: no skill_md part`).

## D15. Which scenario `run` targets; retest

- `run <name> <B> --arm A [--scenario SC-n]`. Without `--scenario`, the target is the first scenario, in this
  order, that lacks a recorded run of arm A on the current hash: the `must_pass` scenarios, then the latest
  draw. For `--arm baseline` the candidates are only scenarios with no recorded baseline on any hash (a
  baseline is needed once per scenario). Green still needs a recorded baseline of the same scenario on any
  hash.
- A scenario whose green failed needs only a green on the new hash; a fresh retest draw needs both arms.
- `retest <B>` refuses `problem: <B>: no failed green` and `problem: <B>: skill unchanged since the failed
  green (hash <hash12>)`. When the latest retest draw's recorded baseline did not fail, `retest <B>` may run
  again without a hash change and draws the next undrawn scenario; that void draw leaves `must_pass`.
- `must_pass` excludes retest draws whose recorded baseline did not fail.

## D16. Judge specs

- `grade(..., grader="session")` on a spec with `judge == True` raises
  `StrapError("judge spec: grade with grader='judge'")`; a `judge` grade on a non-judge spec stays refused.

## D17. Agent-role scenarios

- `check` adds `problem: <SC>: role <role> has no agents/<role>.md` when `role != "session"` and
  `<plugin_dir>/agents/<role>.md` is missing. `init` for such a scenario includes that file's body.

## D18. Lint classification

- `strap_lint.is_invocable(frontmatter, body) -> bool`: True when the body contains `$ARGUMENTS` or the
  frontmatter has `argument-hint`. Frontmatter values have one pair of matching surrounding quotes stripped
  before any rule.
- Fixed message for the description prefix rule: `<name>: description does not start with 'Use when'`.
- `lint_skill` also checks every `harness_lib.<module>` named in the body exists as
  `<plugin_dir>/lib/harness_lib/<module>.py`.

## D19. Generic `skill_api.py` launcher (used by `strap.py api` and every scaffolded skill)

- `plugins/harness/scripts/skill_api.py`: `main(argv) -> int`; usage
  `skill_api.py [--repo DIR] <module> [<name>]`. Activates `load_config(project_root(repo))`, imports
  `harness_lib.<module>`, binds the names in the module's `__all__` (refuses a module without `__all__`:
  `problem: harness_lib.<module> has no __all__`), binds `name` when given, and execs stdin. Any exception
  becomes `problem: <ExceptionName>: <message>` and exit 1.
- `strap.py api <name>` delegates to it with module `strap_api`.
- `api.tmpl` renders a module with `__all__`; `skill_md.tmpl`'s heredoc launches
  `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/skill_api.py" ${snake}_api` with a
  quoted heredoc.

## D20. Run carries its tree and start

- `Run` gains driver-owned-by-container `tree: str = ""` (absolute POSIX path) and `start: str = ""` (the
  commit the tree was built at). `record-run` reads them for the diff, `head_moved` and the drop.
- Trees: `make_tree(repo, start, worktree_root)`; the fixture directory `<plans>/strap/<name>/fixtures/<SC>/`
  is overlaid when present.
- `init` prints, as its last line, the exact command
  `sh "<abs hpy>" "<abs strap.py>" --repo "<project root as_posix>" record-run <name> --run <R-n>` followed by
  a quoted heredoc opener for the reply; the run row's `init` line carries the same `--repo`.

## D21. Recorded scope decisions

- Quotes match with whitespace normalized, checked in `strap_api.grade` (a `Grade` validator cannot see the
  reply).
- `driver_digest` detects hand edits, not a session that deliberately runs code; it is not exported.
- `scaffold` emits `skill_md`, `models`, `api`, `contract_test` only; the driver, agents and a schema
  generator stay the author's. `EDIT` scaffold writes only missing parts and makes no base diff.
- `render_parts` checks every target before writing any; a refusal writes nothing. `$title` is the name
  with hyphens as spaces, title-cased; `$description` renders `TODO: Use when ...`.
- `find_plugin_dir` also skips hidden directories and directories holding a `.git` file (linked worktrees).
- Agent bodies name agents only as `harness:<id>`. Every SKILL.md step spells the full
  `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" <sub>` launcher, no alias.
