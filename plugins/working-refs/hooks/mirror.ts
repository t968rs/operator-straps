/**
 * Names the mod shares with the harness plugin, copied because an installed mod sits in its own plugin cache
 * folder and cannot read the harness's files.
 *
 * - The override file and the line file live under `<state_dir>` (`harness_lib.working_refs` `OVERRIDES_REL`,
 *   `LINE_REL`); the harness writes `{ "version": 1, "branches": { <branch>: { "todo_ids", "issues", "set_at" } } }`
 *   to the first, the mod alone writes the second.
 * - A detached checkout keys its override as `(detached)` (`working_refs.DETACHED`, git-status's `branch.head`).
 * - The mod also writes the branch-stamped line `{ "version": 1, "branch", "text" }` to `LINE_JSON_PATH`
 *   (`working_refs.LINE_JSON_REL`), read by the ccstatusline widget, and keeps its own `gh` answers in
 *   `ISSUES_CACHE_PATH` (mod-only, one writer). `todo_sync.py untracked` writes the open-issue list to
 *   `OPEN_ISSUES_PATH` (`todo_sync.issues.OPEN_ISSUES_REL`); an override entry stamps `set_at`.
 * - The defaults are the harness `config/defaults.json` values of `state_dir`, `artifacts.plans`, `todo.folder`,
 *   `todo.catalog`, `todo.gh.repo`, `todo.gh.max_age_hours` and `working_refs.max_chars`.
 * - A plan is `<prefix>_ActionPlan.json` beside its page `<prefix>_PIP.html` (`harness_lib.plan_doc`).
 * - A catalog item's `keyword` (`TodoCatalog.schema.json` `$defs/item`) labels its TODO id on the line; the
 *   reader re-checks its schema `pattern` and `maxLength` before the keyword reaches the line.
 *
 * `tests/mods/test_working_refs_contract.py` pins every value. Pure: no `$`.
 */

export const OVERRIDES_PATH = 'working-refs/overrides.json'
export const LINE_PATH = 'working-refs/line.txt'
export const LINE_JSON_PATH = 'working-refs/line.json'
export const ISSUES_CACHE_PATH = 'working-refs/issues.json'
export const OPEN_ISSUES_PATH = 'todo-sync/open_issues.json'
export const STORE_VERSION = 1
export const DETACHED_KEY = '(detached)'

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const DEFAULT_PLANS = 'docs/PLANS'
export const DEFAULT_TODO_FOLDER: string | null = null
export const DEFAULT_TODO_CATALOG = 'RepoToDo.json'
export const DEFAULT_GH_REPO: string | null = null
export const DEFAULT_GH_MAX_AGE_HOURS = 24
export const DEFAULT_MAX_CHARS = 120

export const PLAN_SUFFIX = '_ActionPlan.json'
export const PIP_HTML_SUFFIX = '_PIP.html'

/** The override file's map of branch name to refs. */
export const BRANCHES_KEY = 'branches'
/** The refs fields, in an override entry and in an ActionPlan's `refs` (`PlanRefs`). */
export const TODO_IDS_KEY = 'todo_ids'
export const ISSUES_KEY = 'issues'
/** When the override entry was set (UTC ISO 8601); other branches' segments sort by it, newest first. */
export const SET_AT_KEY = 'set_at'
/** A catalog item's one-word label for its TODO id (plan 2028, a property of `$defs/item`). */
export const KEYWORD_KEY = 'keyword'
/** The keyword's `pattern` and `maxLength` in that schema; a catalog that skipped `check` can break either. */
export const KEYWORD_PATTERN = '^[A-Za-z0-9][A-Za-z0-9_.-]*$'
export const KEYWORD_MAX = 32
