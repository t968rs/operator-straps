import {
  DEFAULT_GH_MAX_AGE_HOURS,
  DEFAULT_GH_REPO,
  DEFAULT_MAX_CHARS,
  DEFAULT_PLANS,
  DEFAULT_STATE_DIR,
  DEFAULT_TODO_CATALOG,
  DEFAULT_TODO_FOLDER,
  ISSUES_CACHE_PATH,
  LINE_JSON_PATH,
  LINE_PATH,
  OPEN_ISSUES_PATH,
  OVERRIDES_PATH,
} from './mirror'

/**
 * The harness keys the mod reads from `<project>/.claude/harness.json`, merged over the mirrored defaults of the
 * harness plugin's `config/defaults.json` (./mirror). Pure: no `$`.
 */

/** Project-relative (or absolute) POSIX paths the mod reads and writes under. */
export type WorkingRefsConfig = {
  /** `state_dir`: the override file and the line file live under it. */
  stateDir: string
  /** `artifacts.plans`: the folder the mod scans for plans and their pages. */
  plansDir: string
  /** `todo.folder`: the TODO catalog's folder; null leaves retired ids unread. */
  todoFolder: string | null
  /** `todo.catalog`: the catalog file name under `todo.folder`. */
  todoCatalog: string
  /** `todo.gh.repo`: `owner/name` passed to `gh` as `--repo`; null lets `gh` resolve the checkout's. */
  ghRepo: string | null
  /** `todo.gh.max_age_hours`: the age past which an override's issue is rechecked with `gh`. */
  ghMaxAgeHours: number
  /** `working_refs.max_chars`: the total length of the working line. */
  maxChars: number
}

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Forward slashes, no surrounding blanks, no trailing slash. */
export const cleanPath = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** A non-blank string value, cleaned; else the fallback. */
const pathOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && cleanPath(v) !== '' ? cleanPath(v) : fallback

/** A non-blank string value, cleaned; else the fallback (which may be null). */
const optionalPathOr = (v: unknown, fallback: string | null): string | null =>
  typeof v === 'string' && cleanPath(v) !== '' ? cleanPath(v) : fallback

/** A non-blank string value, trimmed; else the fallback. */
const textOr = (v: unknown, fallback: string | null): string | null =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : fallback

/** A finite number above 0; else the fallback. */
const positiveOr = (v: unknown, fallback: number): number =>
  typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : fallback

/** An integer above 0; else the fallback. */
const countOr = (v: unknown, fallback: number): number =>
  typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : fallback

const objectAt = (data: Json, key: string): Json => (isObject(data[key]) ? (data[key] as Json) : {})

const parse = (text: string): Json => {
  try {
    const data: unknown = JSON.parse(text)
    return isObject(data) ? data : {}
  } catch {
    return {}
  }
}

/**
 * The mod's view of a `harness.json` text; absent, malformed or wrong-typed values keep the defaults (the
 * harness hooks report them).
 */
export const readConfig = (text: string | undefined): WorkingRefsConfig => {
  const data = text === undefined ? {} : parse(text)
  const artifacts = objectAt(data, 'artifacts')
  const todo = objectAt(data, 'todo')
  const gh = objectAt(todo, 'gh')
  return {
    stateDir: pathOr(data.state_dir, DEFAULT_STATE_DIR),
    plansDir: pathOr(artifacts.plans, DEFAULT_PLANS),
    todoFolder: optionalPathOr(todo.folder, DEFAULT_TODO_FOLDER),
    todoCatalog: pathOr(todo.catalog, DEFAULT_TODO_CATALOG),
    ghRepo: textOr(gh.repo, DEFAULT_GH_REPO),
    ghMaxAgeHours: positiveOr(gh.max_age_hours, DEFAULT_GH_MAX_AGE_HOURS),
    maxChars: countOr(objectAt(data, 'working_refs').max_chars, DEFAULT_MAX_CHARS),
  }
}

/** Whether a path is absolute: POSIX, drive or UNC. */
export const isAbsolute = (path: string): boolean => /^([A-Za-z]:)?[\\/]/.test(path)

/**
 * A configured path against the project root, forward slashes: a relative one is joined to it, an absolute one
 * is kept, as harness_lib's `cfg.path()` does.
 */
export const under = (root: string, path: string): string =>
  isAbsolute(path) ? cleanPath(path) : `${cleanPath(root)}/${path}`

/** `<root>/<state_dir>/working-refs/overrides.json`. */
export const overridesFileOf = (root: string, c: WorkingRefsConfig): string =>
  `${under(root, c.stateDir)}/${OVERRIDES_PATH}`

/** `<root>/<state_dir>/working-refs/line.txt`. */
export const lineFileOf = (root: string, c: WorkingRefsConfig): string => `${under(root, c.stateDir)}/${LINE_PATH}`

/** `<root>/<artifacts.plans>`. */
export const plansFolderOf = (root: string, c: WorkingRefsConfig): string => under(root, c.plansDir)

/** `<root>/<state_dir>/working-refs/line.json`: the branch-stamped line the ccstatusline widget reads. */
export const lineJsonFileOf = (root: string, c: WorkingRefsConfig): string =>
  `${under(root, c.stateDir)}/${LINE_JSON_PATH}`

/** `<root>/<state_dir>/todo-sync/open_issues.json`: the open-issue list `todo_sync.py untracked` writes. */
export const openIssuesFileOf = (root: string, c: WorkingRefsConfig): string =>
  `${under(root, c.stateDir)}/${OPEN_ISSUES_PATH}`

/** `<root>/<state_dir>/working-refs/issues.json`: the mod's own cache of `gh` answers. */
export const issuesCacheFileOf = (root: string, c: WorkingRefsConfig): string =>
  `${under(root, c.stateDir)}/${ISSUES_CACHE_PATH}`

/** `<root>/<todo.folder>/<todo.catalog>`, or null while `todo.folder` is unset. */
export const catalogFileOf = (root: string, c: WorkingRefsConfig): string | null =>
  c.todoFolder === null ? null : `${under(root, c.todoFolder)}/${c.todoCatalog}`
