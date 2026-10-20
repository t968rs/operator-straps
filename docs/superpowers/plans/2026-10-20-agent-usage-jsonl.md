# Agent Usage JSONL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pr-review-watch` appends one usage row per completed review-agent dispatch (every role, both
skills) to a new JSONL, with outcome counts on fixer and closer rows.

**Architecture:** A new harness key `agent_usage_path` and schema `pr_review_agent_usage.schema.json`
(Task 1). A pure TypeScript module `usageRow.ts` builds and validates rows and derives fixer counts from
return blocks and pr-review report files (Task 2). `tracker.ts` writes a row from `complete()` each time an
agent's result is folded, through an append helper shared with the matrix writer (Task 3). The reviewer
matrix is untouched.

**Tech Stack:** TypeScript mod on the claude-code engine (`claude plugin test`), Python 3.11 harness library,
JSON Schema draft-07, pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-agent-usage-jsonl-design.md` (frozen; this plan is the source of
truth from here on).

## Global Constraints

- Config key rule: `defaults.json`, `config/harness.schema.json`, `HarnessConfig` + `_build` in
  `lib/harness_lib/config.py`, the root README key table, the `config.ts` mirror and
  `tests/mods/test_pr_review_watch_config_mirror.py` change together.
- Default path: `docs/_harness/pr_review_agent_usage.jsonl`.
- No existing matrix row, matrix schema, matrix flush timing or matrix failure text changes.
- Append-only; a usage file that exists but cannot be read is never overwritten.
- Plugins stay generic (`tests/contract/test_no_repo_literals.py`); data goes under the project root.
- Python: `Optional` / `Union`, no `X | Y`; no first or second person in comments or docstrings; functions
  under 50 lines.
- Tests run by file. Mods: `claude plugin test plugins/pr-review-watch`; manifests:
  `claude plugin validate --strict plugins/pr-review-watch` and `claude plugin validate --strict .`.
- Versions: `harness` 0.11.0 -> 0.12.0, `pr-review-watch` 0.2.0 -> 0.3.0.

## Review Focus

1. Two fixers returning at once (parallel wave) must give exactly two rows, never a duplicate or a lost row
   (Task 3, `parallel fixer returns append one row each`).
2. A model id with no haiku/sonnet/opus token (`claude-fable-5-1`) must still log, as
   `model_family: unknown` with the full id in `model` (Task 3, `a model with no family token logs as
   unknown`).
3. A pr-review fixer that returns a FAIL block but whose `fixes/<id>.json` holds bubbles must count from the
   report; with no report, the block, then null (Task 2 `reportCounts` / `preferCounts` tests, Task 3
   `pr-review fixer counts come from waves.json and its report`).
4. An existing usage file that cannot be read stays byte-identical and the rows are toasted (Task 3).
5. A retried dispatch of the same agent id is a second cost and a second row (Task 3).

---

### Task 1: Harness config key, commit bucket suffix and usage schema

**Files:**
- Modify: `plugins/harness/config/defaults.json` (after `matrix_path`; `commit_buckets[0].suffixes`)
- Modify: `plugins/harness/config/harness.schema.json:22` (new property after `matrix_path`)
- Modify: `plugins/harness/lib/harness_lib/config.py` (`HarnessConfig` field after `matrix_path`; `_build`)
- Modify: `README.md` (key table, row after `state_dir`)
- Modify: `plugins/harness/.claude-plugin/plugin.json` (0.11.0 -> 0.12.0)
- Create: `plugins/harness/schemas/pr_review_agent_usage.schema.json`
- Test: `tests/lib/test_config.py`, `tests/lib/test_branch_commits.py`,
  `tests/schemas/test_pr_review_agent_usage_schema.py` (new)

**Interfaces:**
- Produces: config key `agent_usage_path` (str), `HarnessConfig.agent_usage_path`; the schema file, whose
  `required`, `properties.skill.enum`, `properties.role.enum`, `properties.model_family.enum`,
  `properties.logged_at.pattern`, `if.properties.role.enum` and `then.required` Task 2 pins.

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_config.py`:

```python
def test_agent_usage_path_default_and_override(make_project) -> None:
    assert load_config(make_project()).agent_usage_path == "docs/_harness/pr_review_agent_usage.jsonl"
    assert load_config(make_project({"agent_usage_path": "meta/u.jsonl"})).agent_usage_path == "meta/u.jsonl"
```

`tests/lib/test_branch_commits.py`, `test_default_buckets` parametrize list gains:

```python
        ("docs/_harness/pr_review_agent_usage.jsonl", Bucket.ARTIFACT),
        ("docs/_harness/pr_review_invocation_test_matrix.jsonl", Bucket.ARTIFACT),
```

`tests/schemas/test_pr_review_agent_usage_schema.py` (module docstring in the style of
`test_pr_review_invocation_test_matrix_schema.py`; schema at `PLUGIN_ROOT / "schemas" /
"pr_review_agent_usage.schema.json"`). Base row helper:

```python
def _row(role: str = "reviewer", **extra) -> dict:
    row = {
        "logged_at": "2026-10-20T21:00:00.000Z", "run_id": "pr35_20261020T210000Z", "pr": 35,
        "skill": "pr-review", "role": role, "agent_id": "runtime", "subagent_type": "harness:pr-reviewer",
        "model": "claude-opus-5-5", "model_family": "opus", "effort": "default", "tokens": 1000,
        "tool_uses": 7, "duration_s": 2.5, "signal": "DONE", "notes": "pr-review-watch auto row; reviewer DONE",
    }
    if role in ("fixer", "closer"):
        row.update(issues_assigned=2, issues_fixed=1, issues_bubbled=1, files_touched=3)
    row.update(extra)
    return row
```

Tests (each `jsonschema.validate` or `pytest.raises(jsonschema.ValidationError)`):
- `test_every_role_validates`: parametrize role over `reviewer, fixer, orchestrator, planner, closer`.
- `test_null_pr_subagent_type_model_and_counts_validate`: `_row("fixer", pr=None, subagent_type=None,
  model=None, model_family="unknown", issues_assigned=None, issues_fixed=None, issues_bubbled=None,
  files_touched=None)` validates.
- `test_pr_team_skill_validates`: `_row(skill="pr-team", agent_id="orchestrator_plan", role="orchestrator")`.
- `test_count_field_on_a_reviewer_row_rejected`: `_row(issues_fixed=1)`.
- `test_fixer_row_without_counts_rejected`: `_row("fixer")` with `issues_fixed` popped.
- `test_unknown_family_token_rejected`: `_row(model_family="fable")`.
- `test_negative_tokens_rejected`: `_row(tokens=-1)`.
- `test_unknown_key_rejected`: `_row(cell="x")`.
- `test_unknown_role_rejected`: `_row(role="roaster")`.
- `test_logged_at_must_be_utc_iso`: `_row(logged_at="2026-10-20 21:00")` rejected.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/lib/test_config.py tests/lib/test_branch_commits.py tests/schemas/test_pr_review_agent_usage_schema.py -q`
Expected: FAIL (`agent_usage_path` attribute missing; the usage path buckets as Docs; schema file missing).

- [ ] **Step 3: Add the key and the bucket suffix**

- `defaults.json`: `"agent_usage_path": "docs/_harness/pr_review_agent_usage.jsonl"` after `matrix_path`;
  Artifact rule `"suffixes": ["matrix.jsonl", "agent_usage.jsonl"]`.
- `harness.schema.json`: `"agent_usage_path": {"$ref": "#/$defs/relPath", "description": "pr-review-watch
  agent usage JSONL: one row per review-agent dispatch (repo data)."}`.
- `config.py`: `agent_usage_path: str` after `matrix_path`; `_build` passes `agent_usage_path=m["agent_usage_path"]`.
- Root `README.md` key table, after `state_dir`:
  `` | `agent_usage_path` | `docs/_harness/pr_review_agent_usage.jsonl` | `pr-review-watch` (one usage row per review-agent dispatch: model, tokens, runtime, fixer counts) | ``.

- [ ] **Step 4: Write `plugins/harness/schemas/pr_review_agent_usage.schema.json`**

Draft-07, `$id` `https://github.com/t968rs/operator-straps/plugins/harness/schemas/pr_review_agent_usage.schema.json`,
`additionalProperties: false`, a `description` naming it as JSONL (one object per line), field descriptions
from the spec's Row fields tables. Exact values:

- `required`: `["logged_at", "run_id", "pr", "skill", "role", "agent_id", "subagent_type", "model",
  "model_family", "effort", "tokens", "tool_uses", "duration_s", "signal", "notes"]` (this order).
- `logged_at`: string, `pattern` `^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z$`.
- `pr`: `["integer", "null"]`, `minimum` 1. `run_id`, `agent_id`, `effort`, `signal`: string, `minLength` 1.
  `notes`: string. `subagent_type`, `model`: `["string", "null"]`.
- `skill` enum `["pr-review", "pr-team"]`; `role` enum `["reviewer", "fixer", "orchestrator", "planner",
  "closer"]`; `model_family` enum `["haiku", "sonnet", "opus", "unknown"]`.
- `tokens`, `tool_uses`: integer, `minimum` 0; `duration_s`: number, `minimum` 0.
- `issues_assigned`, `issues_fixed`, `issues_bubbled`, `files_touched`: `["integer", "null"]`, `minimum` 0.
- Role gate: `"if": {"properties": {"role": {"enum": ["fixer", "closer"]}}, "required": ["role"]}`,
  `"then": {"required": ["issues_assigned", "issues_fixed", "issues_bubbled", "files_touched"]}`,
  `"else": {"not": {"anyOf": [{"required": ["issues_assigned"]}, {"required": ["issues_fixed"]},
  {"required": ["issues_bubbled"]}, {"required": ["files_touched"]}]}}`.

- [ ] **Step 5: Bump `plugins/harness/.claude-plugin/plugin.json` to 0.12.0**

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/lib/test_config.py tests/lib/test_branch_commits.py tests/schemas/test_pr_review_agent_usage_schema.py tests/mods/test_pr_review_watch_config_mirror.py -q`
Expected: PASS (the mirror test is unaffected until Task 2 adds the constant).

- [ ] **Step 7: Lint and commit**

Run: `python -m ruff check --no-cache plugins/harness/lib/harness_lib/config.py tests/lib/test_config.py tests/lib/test_branch_commits.py tests/schemas/test_pr_review_agent_usage_schema.py`
Commit in the worktree: `Feature(harness): agent_usage_path key and agent usage row schema`.

---

### Task 2: Usage row module, block counts and the config mirror

**Files:**
- Create: `plugins/pr-review-watch/hooks/usageRow.ts`, `plugins/pr-review-watch/hooks/usageRow.test.ts`
- Modify: `plugins/pr-review-watch/hooks/contract.ts` (`ReturnBlock`, `toBlock`), `contract.test.ts`
- Modify: `plugins/pr-review-watch/hooks/config.ts` (`DEFAULT_AGENT_USAGE_PATH`, `WatchConfig.agentUsagePath`,
  `readConfig`), `config.test.ts`
- Modify: `plugins/pr-review-watch/types/index.d.ts` (`AgentRec.subagentType`, `AgentRec.usageLoggedAt`)
- Modify: `plugins/pr-review-watch/hooks/runs.ts` (`newAgent`, `recovered` set the two new fields)
- Create: `tests/mods/test_pr_review_watch_usage_contract.py`
- Modify: `tests/mods/test_pr_review_watch_config_mirror.py`

**Interfaces:**
- Consumes: the Task 1 schema.
- Produces (all exported from `usageRow.ts`):
  - constants `USAGE_REQUIRED`, `USAGE_COUNT_FIELDS`, `USAGE_ROLES`, `USAGE_COUNTED_ROLES`, `USAGE_SKILLS`,
    `USAGE_MODEL_FAMILIES` (each `export const X = [...] as const`), `LOGGED_AT_PATTERN` (string literal);
  - `type FixerCounts = { issues_assigned: number | null; issues_fixed: number | null; issues_bubbled: number | null; files_touched: number | null }`, `NO_COUNTS: FixerCounts` (all null);
  - `type Ending = 'ok' | 'errored'`;
  - `type UsageInput = { runId: string; skill: Skill; pr: number | null; agent: AgentRec; ending: Ending; isMeasured: boolean; loggedAt: number; counts: FixerCounts }`;
  - `type UsageRow` (the schema's fields; count fields optional);
  - `buildUsageRow(i: UsageInput): UsageRow`;
  - `validateUsageRow(row: Readonly<Record<string, unknown>>): string[]`;
  - `blockCounts(b: ReturnBlock | undefined): FixerCounts`;
  - `reportCounts(wavesText: string | undefined, reportText: string | undefined, agentId: string): FixerCounts`;
  - `preferCounts(primary: FixerCounts, fallback: FixerCounts): FixerCounts`.
- Produces from `contract.ts`: `ReturnBlock.fixed: string[] | null` (null when the block has no `FIXED:`
  line) and `ReturnBlock.edited: number | null` (`EDITED:` as a non-negative integer, else null).
- Produces from `config.ts`: `DEFAULT_AGENT_USAGE_PATH = 'docs/_harness/pr_review_agent_usage.jsonl'`,
  `WatchConfig.agentUsagePath: string` (read with `pathOr(data.agent_usage_path, ...)`).
- Produces in `types/index.d.ts`: `AgentRec.subagentType: string | null` (the dispatch's `subagent_type`)
  `AgentRec.usageLoggedAt: number | null` (epoch ms of the usage-row attempt; null before it), and
  `AgentRec.launchModel: string | null` (the engine's `resolvedModel` from the async launch result, set by
  `registerLoop(..., model)`; null otherwise; read only by usage rows as the model fallback).
  `newAgent(d, meta: { model?: string; effort?: string; subagentType?: string })` sets
  `subagentType: meta.subagentType ?? null, usageLoggedAt: null, launchModel: null`; `recovered` sets all
  three to null.

- [ ] **Step 1: Write the failing Python contract and mirror tests**

`tests/mods/test_pr_review_watch_usage_contract.py` (same fixture style as the matrix contract test,
reading `usageRow.ts` and the Task 1 schema):
- `USAGE_REQUIRED` == `schema["required"]`
- `USAGE_COUNT_FIELDS` == `schema["then"]["required"]`, and `set(schema["properties"]) - set(schema["required"])`
  == `set(USAGE_COUNT_FIELDS)`
- `USAGE_ROLES` == `role.enum`; `USAGE_COUNTED_ROLES` == `schema["if"]["properties"]["role"]["enum"]`
- `USAGE_SKILLS` == `skill.enum`; `USAGE_MODEL_FAMILIES` == `model_family.enum`
- `LOGGED_AT_PATTERN` (via `ts_string`) == `logged_at.pattern`

`tests/mods/test_pr_review_watch_config_mirror.py`: `_MIRRORED[("agent_usage_path",)] =
"DEFAULT_AGENT_USAGE_PATH"`; `loaded["DEFAULT_AGENT_USAGE_PATH"] = cfg.agent_usage_path`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/mods/test_pr_review_watch_usage_contract.py tests/mods/test_pr_review_watch_config_mirror.py -q`
Expected: FAIL (`usageRow.ts` missing; `DEFAULT_AGENT_USAGE_PATH not found`).

- [ ] **Step 3: Write the failing mod tests**

`contract.test.ts`:
- the existing reviewer-block expectation (line ~92) becomes `fixed: null, edited: null`.
- `test('EDITED is read as a count; a missing FIXED line is null, an empty one is []')`:
  `parseReturnBlock('---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: C1,I3\nBUBBLED:\nEDITED: 4\n---')` has
  `fixed ['C1','I3']`, `bubbled []`, `edited 4`; `'---\nSIGNAL: DONE\nFIXED:\nEDITED: x\n---'` has
  `fixed []`, `edited null`; `'---\nSIGNAL: FAIL\n---'` has `fixed null`.

`config.test.ts`: the defaults object gains `agentUsagePath: DEFAULT_AGENT_USAGE_PATH`; the override case
sets `agent_usage_path: 'meta/u.jsonl'` and expects `agentUsagePath: 'meta/u.jsonl'`; the malformed case
(`agent_usage_path: '  '`) keeps the default.

`usageRow.test.ts`, with an `agent(over: Partial<AgentRec>)` helper (id `runtime`, role `reviewer`, model
`claude-opus-5-5`, effort null, tokens 1000, toolUses 7, durationMs 2500, isMeasured true, signal `DONE`,
counts null, loggedAt null, subagentType `harness:pr-reviewer`, usageLoggedAt null) and
`input(over: Partial<UsageInput>)` (runId `pr35_20261020T210000Z`, skill `pr-review`, pr 35, ending `ok`,
isMeasured true, loggedAt `Date.UTC(2026, 9, 20, 21, 0, 0)`, counts `NO_COUNTS`):
- `test('a measured reviewer row')`: `buildUsageRow(input())` equals
  `{ logged_at: '2026-10-20T21:00:00.000Z', run_id: 'pr35_20261020T210000Z', pr: 35, skill: 'pr-review',
  role: 'reviewer', agent_id: 'runtime', subagent_type: 'harness:pr-reviewer', model: 'claude-opus-5-5',
  model_family: 'opus', effort: 'default', tokens: 1000, tool_uses: 7, duration_s: 2.5, signal: 'DONE',
  notes: 'pr-review-watch auto row; reviewer DONE' }` and `validateUsageRow` of it is `[]`.
- `test('fixer and closer rows carry the counts; other roles never do')`: fixer with counts
  `{2,1,1,3}` has those four keys; a reviewer input given the same counts has none of them.
- `test('unmeasured and errored notes')`: `isMeasured: false` gives notes ending `; usage not measured`;
  `ending: 'errored'` gives `signal: 'ERROR'` and notes `pr-review-watch auto row; fixer ERROR; usage not measured; agent errored`.
- `test('no family token logs unknown with the full id')`: model `claude-fable-5-1` gives
  `model_family: 'unknown'`, `model: 'claude-fable-5-1'`; model null gives `model: null`, `model_family: 'unknown'`.
- `test('null signal logs NO_BLOCK')`.
- `test('validateUsageRow names each break')`: a row with `cell` added, `tokens: -1`, `role: 'roaster'`,
  `logged_at: 'x'`, and a reviewer row with `issues_fixed: 0` each yield a problem naming the field; a
  fixer row missing `files_touched` yields `files_touched: missing`.
- `test('USAGE_MODEL_FAMILIES is MODEL_FAMILIES plus unknown')`.
- `test('blockCounts')`: undefined -> `NO_COUNTS`; a fixer block `FIXED: C1,I3 / BUBBLED: M2 / EDITED: 4`
  -> `{ issues_assigned: null, issues_fixed: 2, issues_bubbled: 1, files_touched: 4 }`; a block without
  those lines -> all null.
- `test('reportCounts reads waves.json and fixes/<id>.json')`: waves
  `{"waves": [[{"id": "w1_fix_1", "issue_ids": ["M1","I2"]}], [{"id": "w2_fix_1", "issue_ids": ["C1"]}]]}`,
  report `{"fixer": "w1_fix_1", "fixed": [{"id": "M1", "what": "w", "files": ["a.py", "b.py"]}, {"id": "I2",
  "what": "w", "files": ["b.py"], "no_change": ["c.py"]}], "bubbled": []}` -> `{2, 2, 0, 2}` for `w1_fix_1`;
  for `w2_fix_1` with an undefined report -> `{1, null, null, null}`; `'not json'` for both -> all null; an
  agent id absent from waves -> `issues_assigned: null`.
- `test('preferCounts fills nulls from the fallback, field by field')`.

- [ ] **Step 4: Run the mod tests to verify they fail**

Run: `claude plugin test plugins/pr-review-watch`
Expected: FAIL (module `./usageRow` missing; contract and config expectations unmet).

- [ ] **Step 5: Implement**

- `contract.ts`: `ReturnBlock` gains `edited: number | null`; `fixed` becomes `string[] | null`
  (`f.FIXED === undefined ? null : idList(f.FIXED)`); `edited` from `/^\d+$/` on `f.EDITED`.
- `config.ts`: constant, field, `readConfig` line.
- `types/index.d.ts` and `runs.ts`: the three `AgentRec` fields as in Interfaces. The `AgentRec` literals in
  `matrixRow.test.ts` (its `agent()` helper) and `usageRow.test.ts` gain `subagentType`, `usageLoggedAt` and
  `launchModel` as needed (`launchModel: null`).
- `usageRow.ts`: pure (no `$`), header comment naming the schema and the contract test, as `matrixRow.ts`
  does. `model_family` via `modelFamily(agent.model) ?? 'unknown'`; `duration_s` as
  `Math.max(0, Math.round(durationMs)) / 1000` (the matrix rule); `logged_at` via `new Date(loggedAt).toISOString()`.
  Count fields are added only when `role` is in `USAGE_COUNTED_ROLES`. `files_touched` from a report is the
  distinct `files` across `fixed` entries (`no_change` not counted). Malformed JSON or a wrong-typed array
  gives null for the fields that file feeds.

- [ ] **Step 6: Run everything for this task**

Run: `claude plugin test plugins/pr-review-watch`
Run: `python -m pytest tests/mods/test_pr_review_watch_usage_contract.py tests/mods/test_pr_review_watch_config_mirror.py tests/mods/test_pr_review_watch_matrix_contract.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

Commit in the worktree: `Feature(pr-review-watch): agent usage row builder, validator and fixer counts`.

---

### Task 3: Write usage rows from the tracker

**Files:**
- Modify: `plugins/pr-review-watch/hooks/runs.ts` (`Completion.ending`; `usageToLog`, `markUsageLogged`)
- Modify: `plugins/pr-review-watch/hooks/tracker.ts` (dispatch meta, `recordResult`, `recordLoopEnd`,
  `complete`, shared append helper, `logUsage`)
- Modify: `plugins/pr-review-watch/hooks/runs.test.ts`, `plugins/pr-review-watch/hooks/tracker.test.ts`
- Modify: `plugins/pr-review-watch/README.md`, `plugins/pr-review-watch/.claude-plugin/plugin.json`
  (0.3.0, description), `.claude-plugin/marketplace.json` (description)

**Interfaces:**
- Consumes: everything Task 2 produces; `WatchConfig.agentUsagePath`.
- Produces in `runs.ts`:
  - `Completion.ending: 'ok' | 'errored' | 'denied'`;
  - `usageToLog(run: Run, agentId: string): AgentRec | undefined` (the agent when its `signal` is set and
    `usageLoggedAt` is null);
  - `markUsageLogged(run: Run, agentId: string, now: number): Run`.

- [ ] **Step 1: Write the failing tests**

`runs.test.ts`: `usageToLog` returns the agent once it has a signal and not after `markUsageLogged`;
returns undefined for an unknown id or a running agent. `applyDispatch` of the same id again resets
`usageLoggedAt` to null (the new `AgentRec`).

`tracker.test.ts`, new `describe('agent usage rows')` with `const USAGE = `${ROOT}/docs/_harness/pr_review_agent_usage.jsonl``
and a `usageRows(seen)` reader like `matrixRows`. The fixer block helper:
`fixerBlock = (fixed: string, bubbled: string, edited: number) => `---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: ${fixed}\nBUBBLED: ${bubbled}\nEDITED: ${edited}\nOUTPUT: o\n---``.
- `a reviewer row is written on return, before any verdict`: dispatch `reviewerPrompt('r1', 'PR: 1526')`
  with subagent type `harness:pr-reviewer`; `usageRows` is one row matching `{ run_id: RUN, pr: 1526,
  skill: 'pr-review', role: 'reviewer', agent_id: 'r1', subagent_type: 'harness:pr-reviewer', model:
  'claude-opus-5-5', model_family: 'opus', tokens: 1000, tool_uses: 7, duration_s: 2.5, signal: 'DONE' }`;
  `seen.files.has(MATRIX)` is false.
- `pr-review fixer counts come from waves.json and its report`: `current` names RUN; `waves.json` assigns
  `w1_fix_1` `['M1','I2','C3']`; `fixes/w1_fix_1.json` fixes M1 (files `a.py`, `b.py`) and bubbles I2; the
  agent returns a FAIL block (`---\nSIGNAL: FAIL\nAGENT_ROLE: fixer\nREASON: r\n---`). Row:
  `{ role: 'fixer', signal: 'FAIL', issues_assigned: 3, issues_fixed: 1, issues_bubbled: 1, files_touched: 2 }`.
- `a pr-review fixer with no report falls back to its block, then null`: no `current`; block
  `fixerBlock('M1', '', 1)` -> `{ issues_assigned: null, issues_fixed: 1, issues_bubbled: 0, files_touched: 1 }`.
- `pr-team fixer and closer rows count from their blocks; orchestrator rows carry no counts`: dispatch a
  pr-team slot fixer (`AGENT_ID: f1\nAGENT_ROLE: fixer\nRUN_ID: ${RUN}\nOUTPUT_FILE: ${DIR}/outputs/f1.json`)
  returning `fixerBlock('C1,I3', 'M2', 4)`, a closer (`MODE=CLOSEOUT\nPR_NUMBER=1526\nRUN_ID=${RUN}\nRUNTIME_DIR=${DIR}`,
  type `pr-team-fixer`) returning `fixerBlock('C1,I3', 'M2', 1)`, and an orchestrator PLAN. Rows: f1
  `{ skill: 'pr-team', role: 'fixer', issues_assigned: null, issues_fixed: 2, issues_bubbled: 1, files_touched: 4 }`;
  closer `{ role: 'closer', issues_fixed: 2, issues_bubbled: 1, files_touched: 1 }`; the orchestrator row
  has no `issues_fixed` key.
- `a roast slot is a reviewer row with its subagent type`: pr-team slot `AGENT_ID: r9_roast` dispatched as
  `harness:roast-my-code` -> `{ role: 'reviewer', subagent_type: 'harness:roast-my-code' }`.
- `background launch: the row is written when the loop turn ends`: as the matrix background test; no row
  after the launch, one row `{ tokens: 100, tool_uses: 1, duration_s: 4, model_family: 'sonnet' }` after
  the loop's `turn.complete`. A second loop turn with no `usage` for another agent gives notes ending
  `; usage not measured` and tokens 0.
- `a denied dispatch writes no row; an errored one logs ERROR`: Agent answer `{ deny: 'no' }` -> no usage
  file; answer `{ isError: true, text: 'boom' }` -> one row `{ signal: 'ERROR', tokens: 0 }` with notes
  ending `; usage not measured; agent errored`.
- `a model with no family token logs as unknown`: `completed(doneBlock(ZERO), 'claude-fable-5-1')` ->
  `{ model: 'claude-fable-5-1', model_family: 'unknown' }`.
- `parallel fixer returns append one row each`: `Promise.all` of two pr-review fixer dispatches
  (`w1_fix_1`, `w1_fix_2`) plus `mainTurnEnd` -> exactly two rows, agent ids `['w1_fix_1', 'w1_fix_2']` in
  any order.
- `a retried dispatch is a second row`: dispatch `r1` twice -> two rows with agent id `r1`.
- `rows append after existing rows; an unreadable usage file is untouched and toasted`: an existing
  `{"run_id":"old"}\n` stays first; with `seen.unreadable.add(USAGE)` the text is unchanged and a toast
  contains `usage log unreadable`.
- `agent_usage_path comes from harness.json`: config `{ agent_usage_path: 'meta/u.jsonl' }` writes to
  `${ROOT}/meta/u.jsonl`.
- `a recovered pr-team run's rebuilt reviewers write no usage rows`: the existing `claimedRun` setup plus a
  review written after the run start: the matrix gets `pr1526_r1`, the usage file does not exist.

- [ ] **Step 2: Run them to verify they fail**

Run: `claude plugin test plugins/pr-review-watch`
Expected: FAIL (no usage file is written).

- [ ] **Step 3: Implement**

- `recordDispatch` passes `subagentType: e.subagent_type` into `newAgent` (the `tool.call` hook hands it
  through with model and effort).
- `recordResult` sets `ending`: `'denied'` when `r.deny` is set; `'errored'` when `r.isError === true` or
  the result's status is not `completed` (after the `async_launched` early return); else `'ok'`.
  `recordLoopEnd` sets `'ok'`.
- `complete($, key, c)`: after `applyCompletion` and `claimMatrix`, call `logUsage($, key, c)`.
- `logUsage($, key, c): Promise<void>`: returns at once when `c.ending === 'denied'` (a denied dispatch
  never ran); else resolve the watch; claim the agent inside one `updateRun`
  (`usageToLog`, then `markUsageLogged` with `$.clock.now()`), returning early when nothing is claimed;
  counts: role `fixer` on a `pr-review` run -> `preferCounts(reportCounts(<run dir>/waves.json,
  <run dir>/fixes/<agentId>.json, agentId), blockCounts(c.block))` with the run dir from `prReviewRunDir`
  (both texts undefined when it is undefined); role `fixer` or `closer` otherwise -> `blockCounts(c.block)`;
  else `NO_COUNTS`. Model: `c.model ?? claimed.launchModel ?? claimed.model` (the engine's launch model
  covers background agents that returned no usage). Build with `buildUsageRow`, then append through the
  serialized tail.
- Shared append: generalize the write half of `writeRows` into
  `appendValid<R>($, path, rows, check: RowCheck<R>, now)` returning `LogFailure[]`, where
  `RowCheck<R> = { label: string; problems: (r: R) => string[]; cellOf: (r: R) => string }` (module-private
  in `tracker.ts`, with `MATRIX_CHECK` and `USAGE_CHECK` constants), with reasons
  `${check.label} unreadable; not overwritten` and `${check.label} write refused`.
  The matrix passes `MATRIX_CHECK` (label `matrix`; its failure text stays byte-identical, pinned by the
  existing test); usage passes `USAGE_CHECK` (label `usage log`, `cellOf` = `${run_id}/${agent_id}`). `appendRows` in `matrixRow.ts`
  widens its row type to `readonly object[]` (no behavior change). `recordFailures` takes a noun
  (`matrix` / `usage`) for its toast: `pr-review-watch: N usage row(s) not appended (...)`.
- Usage appends ride the same `flushTail` promise chain as matrix flushes, so no two read-modify-writes of
  either file interleave.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `claude plugin test plugins/pr-review-watch`
Expected: PASS, including every pre-existing matrix test unchanged.

- [ ] **Step 5: Docs and manifests**

- `plugins/pr-review-watch/README.md`:
  - key table row `` | `agent_usage_path` | `docs/_harness/pr_review_agent_usage.jsonl` | the agent usage rows are appended to | ``;
  - rule row R7: `Every completed review-agent dispatch gets a usage row` / `One row per reviewer, fixer,
    orchestrator, planner and closer dispatch, written when the agent returns, validated against
    pr_review_agent_usage.schema.json; fixer and closer rows add issues_assigned, issues_fixed,
    issues_bubbled and files_touched (null when unknown). A denied dispatch writes none.`;
  - a short `## Agent usage rows` section after `## Matrix-row ownership`: when a row is written, the count
    sources (the spec's table, in two sentences), the unreadable-file rule, and that rebuilt reviewers of a
    recovered run write none;
  - the contract paragraph names `tests/mods/test_pr_review_watch_usage_contract.py`.
- `plugin.json`: version `0.3.0`; description and the marketplace entry's description:
  `pr-review / pr-team run tracking: Phase 5 band, engine-measured matrix and agent usage rows, bubble Stop guard`.

- [ ] **Step 6: Validate and run the Python guards**

Run: `claude plugin validate --strict plugins/pr-review-watch`
Run: `claude plugin validate --strict .`
Run: `python -m pytest tests/mods/test_pr_review_watch_usage_contract.py tests/mods/test_pr_review_watch_matrix_contract.py tests/mods/test_pr_review_watch_config_mirror.py tests/contract/test_no_repo_literals.py tests/contract/test_root_separation.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

Commit in the worktree: `Feature(pr-review-watch): append an agent usage row for every review-agent dispatch`.
