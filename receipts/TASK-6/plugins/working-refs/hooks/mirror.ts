/**
 * Names the mod shares with the harness plugin, copied because an installed mod sits in its own plugin cache
 * folder and cannot read the harness's files.
 *
 * - The override file and the line file live under `<state_dir>` (`harness_lib.working_refs` `OVERRIDES_REL`,
 *   `LINE_REL`); the harness writes `{ "version": 1, "branches": { <branch>: { "todo_ids", "issues", "set_at" } } }`
 *   to the first, the mod alone writes the second.
 * - A detached checkout keys its override as `(detached)` (`working_refs.DETACHED`, git-status's `branch.head`).
 * - The defaults are the harness `config/defaults.json` values of `state_dir` and `artifacts.plans`.
 * - A plan is `<prefix>_ActionPlan.json` beside its page `<prefix>_PIP.html` (`harness_lib.plan_doc`).
 *
 * `tests/mods/test_working_refs_contract.py` pins every value. Pure: no `$`.
 */

export const OVERRIDES_PATH = 'working-refs/overrides.json'
export const LINE_PATH = 'working-refs/line.txt'
export const STORE_VERSION = 1
export const DETACHED_KEY = '(detached)'

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const DEFAULT_PLANS = 'docs/PLANS'

export const PLAN_SUFFIX = '_ActionPlan.json'
export const PIP_HTML_SUFFIX = '_PIP.html'

/** The override file's map of branch name to refs. */
export const BRANCHES_KEY = 'branches'
/** The refs fields, in an override entry and in an ActionPlan's `refs` (`PlanRefs`). */
export const TODO_IDS_KEY = 'todo_ids'
export const ISSUES_KEY = 'issues'
