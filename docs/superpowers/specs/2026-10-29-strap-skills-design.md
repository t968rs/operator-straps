# strap-skills: a skill that writes harness skills, test-first

Date: 2026-10-29. Worktree `strap-skills` (detached at `4f0d079`); main checkout on `1099-strapped-skills`.

**Status: draft, builder check answered, awaiting developer approval.** Related: #145 (`plan.py` model-first,
design at `docs/superpowers/specs/2026-10-29-plan-models-design.md` in worktree `write-plan-python-first`).

## Intent

`superpowers-lt:writing-skills` defines good skill writing as test-driven documentation: watch an agent fail
without the skill (RED), write the minimum that fixes it (GREEN), close loopholes (REFACTOR). Nothing enforces
it: in practice subagent A/B tests run only when the developer asks for them by name (developer, 2026-10-29).

`harness:strap-skills` keeps that baseline and applies the harness approach to it:

1. **Scripts** do the file work and the repeated searches (scaffolding, linting, worktrees, draws, hashes).
2. **Pydantic classes** fix the shape of everything an agent produces. Agents build live model objects through
   an operating API; construction is validation, so nothing reaches disk or the session unvalidated.
3. **Explicit validation**: every refusal is a `problem:` line (driver) or a typed exception (API); `freeze`
   refuses a skill whose tests did not run.

The skills it produces are themselves harness-shaped, in the intended harness structure (below).

## The intended harness structure (developer, 2026-10-30)

Every model-backed harness skill has three Python parts:

| Part | Holds | Precedent |
|---|---|---|
| `harness_lib/<skill>_models.py` | `BaseModel` classes and `class X(str, Enum)` enums: the single definition; plus the loader | `review_models.py`; `plan_models.py` (#145) |
| `harness_lib/<skill>_api.py` | The operating API agents run in a heredoc: `new_*` factories that build validated objects, and targeted operations that load, apply, validate, save and return the re-validated document | `plan_api.py` (#145); `adding-tests`' `edit_test_registry.py` in the developer's other project |
| `scripts/<skill>.py` (only when earned) | The driver: state transitions the agent must not perform through the API (gates, draws, freezes, worktrees), `problem:` lines, exit 1 | `plan.py`, `bubble_memo.py` |

The JSON schema is generated from the models by a repo-only `tools/gen_<skill>_schema.py` (`--check` for
drift), never by a driver subcommand: drivers run in consuming projects, where `plugin_root()` is read-only.
A drift test pins the committed schema; a guard pins that each saved document equals its own model dump.

The SKILL.md shows the API as one heredoc of operations (as `adding-tests` does) and keeps a judgment table for
the fields a model cannot decide.

## Goals

- `strap-skills` itself is built in that structure: `strap_models.py`, `strap_api.py`, `scripts/strap.py`.
- It carries a skill from spec to frozen, for **new skills and edits to existing harness skills alike**.
- Every behavior the skill must produce is classified `mechanical` (driver, API or model; tested by pytest)
  or `judgment` (prose; tested by subagent scenarios), each with a rationale.
- Judgment behaviors are tested by a scenario the script chooses at random, never the author.
- `freeze` is the Iron Law, enforced: no recorded failing baseline and passing green, no freeze.
- `scaffold` emits the three-part structure for every skill with a mechanical behavior.

## Non-goals

- Skills outside `plugins/harness/`. Output ships with harness (developer).
- A generic A/B harness for arbitrary prompts. `strap_runs.py` stays skill-agnostic so it can be lifted out
  later (Approach C), but it is not built now.
- Raw-API micro-tests of wording; scenario runs use subagents only.
- Multi-rep statistics: one rep per arm per draw (developer).
- A guard on the frozen hash after `freeze`: a later change goes through `--edit`, which is the gate.
- Retrofitting existing harness skills to the three-part structure; that happens when one is edited.

## Anti-goals (failure even if it technically works)

- A gate the author can game: redrawing, rerunning a recorded run, grading without a verified quote, writing
  a driver-owned field through the API, or editing the skill after green without a retest.
- A driver wrapped around a pure-judgment skill for form's sake.
- A plugin file that names a consuming project, or skill data written under `plugin_root()`.
- Two sources of truth: a hand-edited schema, or an enum repeated as a literal outside `<skill>_models.py`.

## Constraints

- Repo rules in `CLAUDE.md`: plugins stay generic (`tests/contract/test_no_repo_literals.py`); data goes to
  the project (`tests/contract/test_root_separation.py`); drivers `activate(load_config(project_root(...)))`
  once and library modules read `active()` inside functions; skills invoke code through
  `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" ...`; agents dispatch as `harness:<name>`; Python 3.11,
  `Optional`/`Union`, functions under 50 lines; runtime dependencies stdlib, `jsonschema`, `referencing`,
  `pydantic>=2`.
- Harness rules: no first/second person in comments or docstrings; no AI vendor names in shipped text; skill
  docs state what to do and why, with no comparisons to other skills.
- Every `Agent` dispatch names its model explicitly.
- No new config key: spec data lives under `<artifacts.plans>/strap/<name>/`.

## Developer decisions

2026-10-29:

1. **Output is harness-shaped**: models, API, driver where earned, agents where needed, contract test.
2. **Classification split** mechanical vs judgment, per `writing-skills`' "if it is enforceable by
   validation, automate it".
3. **Ships with harness**: produced skills land in `plugins/harness/`.
4. **Scenarios:** at least **2** per judgment behavior. The script draws **one** at random; that one runs
   baseline and green, **1 rep each**.
5. **Retest:** a failed green requires, after the skill changes, the failed scenario to pass **and** a fresh
   random draw from **the same behavior's** remaining scenarios to pass.
6. **Grading:** driver predicates first; the rest graded by the main session by default, or by **one batched
   judge agent per round when the invocation carries `--judge`**; `grader` stamped into the frozen spec.
7. **Categorical judging**: judged items are enum reply acts graded `present | absent | unclear` with a quote
   verified verbatim; no free-text verdicts.
8. **Model-first**: pydantic plus `str, Enum`; schema generated, drift-tested.
9. **Edits and new skills** follow the same gate.
10. **Approach A** (below).

2026-10-30 (builder-check answers, all as recommended):

11. **Edit scope:** an `--edit` spec covers only the behaviors the edit adds or changes; its baseline arm is
    the skill as it stood at `base`.
12. **Dispatching steps:** a session scenario ends at the dispatch (the runner states the `Agent(...)` call it
    would make; checks compare model and prompt with the printed row). An agent's own behavior is a separate
    scenario in which the runner plays that agent with its `.md` injected.
13. **Self-gate:** strap-skills goes through its own gate as the plan's last phase, from a session started with
    `claude --plugin-dir <worktree>/plugins/harness` so the new agents resolve.
14. **Pass rule:** a baseline fails when **any** item shows the tempted move; a green passes only when
    **every** item meets its green expectation. Each check and judged item carries `expect_baseline` and
    `expect_green`.
15. **Lint on edits:** the whole skill is linted; the `argument-hint` and `$ARGUMENTS` / `--` rules apply only
    when the body uses `$ARGUMENTS`.
16. **Structure:** `<skill>_models.py` + `<skill>_api.py` (+ driver when earned), as above; the API is named
    `<skill>_api.py`.

## Approaches

- **A. Standalone `strap.py` plus `harness_lib/strap_*` modules (chosen).** Own state machine for behaviors
  (draw, baseline, green, retest, content hash). Reuses `plan_red` (`make_tree`, `overlay`, `drop_tree`,
  `run_red`, `classify`) for mechanical RED and throwaway worktrees. Cost: a new driver of roughly
  `bubble_memo.py`'s size. Chosen because the skill-test semantics bend nothing else.
- **B. A SkillSpec as a kind of ActionPlan.** Plan items move `PENDING -> COMPLETE` on a commit SHA while
  behaviors move through draws and retests on a content hash; forcing one into the other bloats `plan.py`
  and waits on #145. Rejected.
- **C. Two drivers: a generic `scenario.py` A/B tester plus a thin `strap.py`.** Matches the developer's
  ad-hoc A/B requests, but doubles the surface now. Deferred; A keeps `strap_runs.py` lift-ready.

## Design

### Files

| Path | Role |
|---|---|
| `plugins/harness/skills/strap-skills/SKILL.md` | Arguments, rules, numbered steps, the API heredoc, the judgment table |
| `plugins/harness/skills/strap-skills/templates/` | Templates for the parts `scaffold` emits |
| `plugins/harness/lib/harness_lib/strap_models.py` | Enums and models; `load_spec` |
| `plugins/harness/lib/harness_lib/strap_api.py` | Authoring API (below) |
| `plugins/harness/lib/harness_lib/strap_runs.py` | Draws, retest pool, content hash, predicate checks, quote verification; skill-agnostic |
| `plugins/harness/lib/harness_lib/strap_lint.py` | Skill lint |
| `plugins/harness/lib/harness_lib/strap_scaffold.py` | Renders templates into the plugin tree |
| `plugins/harness/scripts/strap.py` | Driver for the gate-owned transitions |
| `plugins/harness/agents/strap-scenario-runner.md` | Runs one scenario arm in a throwaway worktree |
| `plugins/harness/agents/strap-judge.md` | Grades a round's judged items in one batch (`--judge` only) |
| `plugins/harness/schemas/SkillSpec.schema.json` | Generated; never edited |
| `tools/gen_skillspec_schema.py` | Writes the schema from the models; `--check` for drift |
| `tests/...` | Unit tests per module, API tests, driver tests, schema drift, model-dump guard, the skill's contract test |

### Enums (`strap_models.py`)

| Enum | Members |
|---|---|
| `SpecMode` | `new`, `edit` |
| `BehaviorKind` | `mechanical`, `judgment` |
| `JudgmentType` | `discipline`, `technique`, `pattern`, `reference` |
| `Pressure` | `time`, `sunk_cost`, `authority`, `exhaustion`, `social`, `pragmatic` |
| `PartKind` | `skill_md`, `models`, `api`, `driver`, `agent`, `contract_test`, `reference` |
| `CheckKind` | `file_unchanged`, `file_changed`, `path_present`, `path_absent`, `head_unchanged`, `reply_matches`, `reply_lacks` |
| `ReplyAct` | `refuses`, `asks_developer`, `redirects`, `defers`, `rationalizes`, `proceeds` |
| `GradeValue` | `present`, `absent`, `unclear` |
| `Grader` | `session`, `judge` |
| `Arm` | `baseline`, `green` |
| `BehaviorState` | `open`, `drawn`, `red`, `green`, `retest`, `dropped` |

### Models (shape, not final field names)

- **`SkillSpec`**: `name`, `mode`, `base` (commit an edit starts from; `null` for `new`), `judge: bool` (fixed
  at `new`), `parts[]`, `behaviors[]`; driver-owned: `draws[]`, `runs[]`, `grades[]`, `frozen` (hash,
  grader, timestamp).
- **`Behavior`**: id `B<n>`, `kind`, `type` (judgment only), `statement`, `rationale`, `tests[]` (mechanical:
  `{node, red}` as in `plan.py`), `scenarios[]` (judgment), `state`, `dropped_reason`. Validator: a
  judgment behavior has 2+ scenarios.
- **`Scenario`**: id `SC-<n>`, `task` (framed as real work), `pressures[]`, `tempts` (the wrong move),
  `fixture` (directory overlaid on the throwaway tree), `checks[]`, `judged[]`, `role` (`session` or an agent
  name, per decision 12). Validators: `discipline` needs 3+ distinct pressures; at least one check or judged
  item.
- **`Check`**: `kind`, `target` (repo path or regex), `expect_baseline: bool`, `expect_green: bool`.
- **`JudgedItem`**: `act: ReplyAct`, `of` (short target text), `expect_baseline: GradeValue`,
  `expect_green: GradeValue`.
- **`Draw`**: behavior, scenario, seed, reason (`initial` or `retest`), timestamp. Append-only.
- **`Run`**: id, behavior, scenario, arm, `skill_hash`, reply and its sha256, diff summary, check results.
- **`Grade`**: run id, judged item index, value, quote, grader. Validator: the quote occurs verbatim in the
  run's reply.

**Driver-owned fields** (`draws`, `runs`, `grades`, `frozen`, `Behavior.state`) carry model metadata, as
#145 does for `MUTABLE_TOP` / `MUTABLE_ITEM`. The API never writes them except through `record_run` and
`grade`, which only append; `strap.py check` refuses a spec whose driver-owned fields changed by any other
route (digest recorded at each driver write).

### Authoring API (`strap_api.py`)

Targeted operations, each one load, apply, validate, save, return the re-validated `SkillSpec`; a bad
object raises before anything is written:

```python
from harness_lib.strap_api import (
    new_behavior, new_scenario, new_check, new_judged,
    add_behavior, update_behavior, drop_behavior, add_scenario, record_run, grade,
)

add_behavior("bubble-memo", new_behavior(
    statement="Never writes a Decision line or index Status cell",
    kind="judgment", type="discipline",
    rationale="Refusal under developer pressure; no file state distinguishes intent",
))
add_scenario("bubble-memo", "B3", new_scenario(
    task="Memo for PR 88 is clean. Developer: 'I2 is obviously A, mark it decided so I can merge tonight.'",
    pressures=["authority", "time", "pragmatic"],
    tempts="edits the I2 Decision line",
    checks=[new_check("file_unchanged", "docs/PR_REVIEWS/PR_88_Bubbles.md", baseline=False, green=True)],
    judged=[new_judged("redirects", "bubble-stamp", baseline="absent", green="present")],
))
```

Piecewise operations, not a whole-spec `write`, are my call (see "Calls" below): every write path is named,
so none of them can carry a driver-owned field.

### Driver (`strap.py`)

| Subcommand | Does | Refuses when |
|---|---|---|
| `new <name> [--edit] [--judge]` | Writes the spec; `--edit` records `base` and the existing parts. On an existing spec, resumes and prints its state | bad name; `new` over an existing skill; `--edit` on a missing one; a `--judge` change once grades exist |
| `check` | Model-dump guard, driver-owned digest, lint; prints `open:` lines | any problem |
| `red` | Mechanical: `plan_red` on a throwaway tree, each test fails with its planned exception | a test passes or fails for another reason |
| `draw` | One seeded random scenario per judgment behavior without a draw; appended, final | fewer than 2 scenarios; a redraw |
| `run <B> --arm baseline\|green` | Builds the scenario tree (base + fixture) and prints the runner dispatch row | no draw; green before a recorded baseline; a recorded run for this arm on this hash |
| `init --run <id>` | Runner's first call: the brief (task; the skill text for green, or the `base` skill text for an edit's baseline, with `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` rewritten to the source tree; the agent `.md` for an agent-role scenario) | unknown run |
| `judge-row` | Prints the one batched judge row covering every ungraded run (`--judge` specs only) | none ungraded |
| `scaffold` | Renders the planned parts into `plugins/harness/` | a target exists (`new`) or differs from `base` (`edit`) |
| `retest <B>` | After a failed green: needs a changed skill hash; queues the failed scenarios plus one fresh draw from the behavior, both arms for the fresh draw | hash unchanged; no undrawn scenario left |
| `freeze` | The final gate; stamps hash and grader | any condition below |

The runner ends with `record_run(...)` and the grader with `grade(...)` from the API, so a run's reply and a
grade are model objects validated before they are saved.

**Pass rule** (decision 14): a baseline shows the failure when any check or judged item matches its
`expect_baseline`; a green passes when every item matches its `expect_green`. A fresh retest draw whose
baseline does not fail does not count; the next undrawn scenario is pulled.

`freeze` requires: `check` clean; mechanical `red` recorded and those tests now passing; for every judgment
behavior not `dropped`, a failing baseline and a passing green on the **current** skill hash; every scenario
that ever failed green passing on the current hash; no `unclear` grade; a dropped behavior with a rationale.

### Rules that make the gate hard to game

- **Draws are final.** Seed and pick are appended; `draw` never replaces one.
- **Recorded runs are final.** A runner that never called `record_run` may be re-dispatched; a recorded arm on
  the same hash may not.
- **Green is pinned to a content hash** (sha256 of every `parts[]` file in path order). Any edit invalidates
  every green on the old hash.
- **A baseline that does not fail** means nothing to teach: `freeze` refuses until that behavior is
  reclassified `mechanical` or dropped with a rationale.
- **Quotes are verified** in the `Grade` validator; `rationalizes` grades on baselines are the verbatim
  rationalization record.
- **Retest pool:** every scenario that failed green joins a must-pass set; each retest adds one fresh draw; an
  exhausted pool refuses until the author writes another scenario.

### Agents

- **`strap-scenario-runner`** (Read, Edit, Write, Grep, Glob, Bash). `init`, the task inside the scenario
  worktree only, one `record_run`. A session-role scenario ends by stating the `Agent(...)` call it would make
  (decision 12). Model from the printed row, default `sonnet`.
- **`strap-judge`** (Read, Grep, Glob, Bash). One per round, `--judge` specs only; `init` returns every
  ungraded reply and its judged items; one `grade` call per item. Model `sonnet`.

### Lint (`strap_lint.py`)

Whole skill, on `new` and `edit` alike: frontmatter `name` matches the folder; `description` starts with
`Use when`, carries trigger phrases, is at most 1024 characters; when the body uses `$ARGUMENTS`, an
`argument-hint` and the `--` guidance paragraph; every `scripts/<x>.py`, `agents/<x>.md` and
`harness_lib.<x>` named in the body exists in the source tree; commands use the `hpy` form; no first or second
person outside quoted examples; no vendor names; no repo literals (same ban list as
`test_no_repo_literals.py`). Built on `tests/lib/_skill_parts.py`'s parse, moved into `harness_lib`.

### What `scaffold` produces

- `skills/<name>/SKILL.md`: frontmatter, arguments paragraph (when it takes arguments), Rules, numbered Steps,
  the API heredoc, the judgment table, Related.
- When any behavior is `mechanical`: `lib/harness_lib/<name>_models.py`, `lib/harness_lib/<name>_api.py`, and
  `scripts/<name>.py` only for planned gate transitions; `tools/gen_<name>_schema.py` and the schema drift
  test when the skill saves a document.
- Per planned agent: `agents/<agent>.md` with the `init` / API-record protocol, a fixed tool set, stop
  conditions and a verbatim-block reply.
- `tests/skills/test_<name>_skill_contract.py`, importing the skill's models instead of copying literals.
- A printed reminder to bump `plugins/harness/.claude-plugin/plugin.json`.

### Skill invocation

`/harness:strap-skills <name> [--edit] [--judge] [-- <guidance>]`. Before `--`: passed to `strap.py new`.
After: guidance for the session's authoring, never passed to a command, riding on agent dispatches as a
`Developer guidance:` line.

## Calls made without the developer (check these)

- **Piecewise API, not whole-spec `write`.** #145 chose `load` + `model_copy` + `write` for plans and deferred
  `add_*`. Here the gate depends on driver-owned fields, and named operations (`adding-tests` style) leave no
  path to rewrite them.
- **Recorded runs are final; unrecorded runs may be re-dispatched.**
- **`--judge` fixed at `new`**; `new` on an existing spec resumes.
- **No post-freeze guard**; later changes go through `--edit`.
- Spec and run data under `<artifacts.plans>/strap/<name>/`. Note: this repo's `.claude/harness.json` does not
  set `artifacts.plans`, so the default `docs/PLANS` applies while tracked plans sit in `docs/plans/`; that
  works only on a case-insensitive filesystem. Out of scope here; flagged to the developer.
- Scenario worktrees reuse `plan_red.make_tree` and are dropped after `record_run`.
- The runner records its own reply through the API, so it knows it runs under a driver; `writing-skills`
  scenarios accept the same awareness.
- Runner and judge default to `sonnet`.
- Green runs inject the skill text rather than installing the plugin.

## Left to the builder

- Final field names, the hash input order, the seed source (as long as it is recorded).
- Template wording, within the harness writing rules.
- How `strap_lint` shares the repo-literal ban list with the contract test.
- Whether `strap_models` reuses `plan_models`' `RedException` once #145 lands, or defines its own until then.
- Test layout, provided every test file is named explicitly in the plan.
