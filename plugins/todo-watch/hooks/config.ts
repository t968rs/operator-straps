/**
 * The harness keys the watch reads from `<project>/.claude/harness.json`, merged over copies of the harness
 * plugin's `config/defaults.json` values: an installed mod sits in its own plugin cache folder and cannot
 * read that file. `tests/mods/test_todo_watch_config_mirror.py` pins the copies. Pure: no `$`.
 */

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const DEFAULT_RESEARCH = 'docs/RESEARCH'
export const DEFAULT_PLANS = 'docs/PLANS'
export const DEFAULT_FOLDER: string | null = null
export const DEFAULT_CATALOG = 'RepoToDo.json'
export const DEFAULT_CATALOG_SCHEMA: string | null = 'RepoToDo.schema.json'
export const DEFAULT_TOP_N = 10
export const DEFAULT_SNAPSHOTS_DIR: string | null = 'Snapshots'
export const DEFAULT_RESEARCH_CATALOG: string | null = 'ResearchImplementationCatalog.json'
export const DEFAULT_GH_MAX_AGE_HOURS = 24
export const DEFAULT_INJECT_CONTEXT = true

/**
 * Project-relative POSIX paths and the TODO settings the watch reads; an absolute path is rejected by the
 * harness schema (`relPath`), and a rooted `todo.folder` leaves the watch inactive. The TODO paths are
 * resolved under `todo.folder` as harness_lib does; each is null while the folder is unset or rooted, its key
 * is null, or it climbs above the project root.
 */
export type TodoWatchConfig = {
  stateDir: string
  researchDir: string
  plansDir: string
  folder: string | null
  catalog: string | null
  catalogSchema: string | null
  topN: number
  snapshotsDir: string | null
  researchCatalog: string | null
  ghMaxAgeHours: number
  injectContext: boolean
}

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Forward slashes, no surrounding blanks, no trailing slash. */
export const cleanPath = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** A non-blank string value, cleaned; else the fallback. */
const pathOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && cleanPath(v) !== '' ? cleanPath(v) : fallback

/** A non-blank string value, cleaned; null when the value is null; else the fallback. */
const optionalPathOr = (v: unknown, fallback: string | null): string | null => {
  if (v === null) return null
  return typeof v === 'string' && cleanPath(v) !== '' ? cleanPath(v) : fallback
}

/** A positive whole number; else the fallback. */
const countOr = (v: unknown, fallback: number): number =>
  typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : fallback

/** A finite number at or above zero; else the fallback. */
const hoursOr = (v: unknown, fallback: number): number =>
  typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : fallback

const objectAt = (data: Json, key: string): Json => (isObject(data[key]) ? (data[key] as Json) : {})

/**
 * `name` joined to `folder` with `.` and `..` segments folded, as Python's `posixpath.normpath`; null when
 * either is null.
 */
export const inFolder = (folder: string | null, name: string | null): string | null => {
  if (folder === null || name === null) return null
  const joined = `${folder}/${cleanPath(name)}`
  const out: string[] = []
  for (const seg of joined.split('/')) {
    if (seg === '' || seg === '.') continue
    if (seg === '..' && out.length > 0 && out[out.length - 1] !== '..') out.pop()
    else out.push(seg)
  }
  const body = out.join('/') || '.'
  return joined.startsWith('/') ? `/${body}` : body
}

/**
 * A resolved TODO path, or null when it climbs above the project root (`..` or `../...`): harness_lib refuses
 * such a path at config load, so the watch treats it as unset.
 */
export const insideRoot = (path: string | null): string | null =>
  path === null || path === '..' || path.startsWith('../') ? null : path

/**
 * Whether a cleaned path is rooted or drive-prefixed (`/x`, `C:/x`, `C:x`): the harness schema rejects such a
 * `todo.folder`, so the watch stays inactive rather than reading files outside the project.
 */
const isRooted = (path: string): boolean => /^(\/|[A-Za-z]:)/.test(path)

/** `inFolder` with the project-root check applied to the result. */
const todoPath = (folder: string | null, name: string | null): string | null => insideRoot(inFolder(folder, name))

const parse = (text: string): Json => {
  try {
    const data: unknown = JSON.parse(text)
    return isObject(data) ? data : {}
  } catch {
    return {}
  }
}

/**
 * The watch's view of a `harness.json` text: each key it reads replaces its default, objects merge key by
 * key. Malformed JSON or a wrong-typed value keeps the default (the harness hooks report it).
 */
export const readConfig = (text: string): TodoWatchConfig => {
  const data = parse(text)
  const artifacts = objectAt(data, 'artifacts')
  const todo = objectAt(data, 'todo')
  const inject = todo.inject_context
  const named = optionalPathOr(todo.folder, DEFAULT_FOLDER)
  const folder = named !== null && !isRooted(named) && insideRoot(inFolder(named, '.')) !== null ? named : null
  return {
    stateDir: pathOr(data.state_dir, DEFAULT_STATE_DIR),
    researchDir: pathOr(artifacts.research, DEFAULT_RESEARCH),
    plansDir: pathOr(artifacts.plans, DEFAULT_PLANS),
    folder,
    catalog: todoPath(folder, pathOr(todo.catalog, DEFAULT_CATALOG)),
    catalogSchema: todoPath(folder, optionalPathOr(todo.catalog_schema, DEFAULT_CATALOG_SCHEMA)),
    topN: countOr(todo.top_n, DEFAULT_TOP_N),
    snapshotsDir: todoPath(folder, optionalPathOr(objectAt(todo, 'snapshots').dir, DEFAULT_SNAPSHOTS_DIR)),
    researchCatalog: todoPath(folder, optionalPathOr(objectAt(todo, 'research').catalog, DEFAULT_RESEARCH_CATALOG)),
    ghMaxAgeHours: hoursOr(objectAt(todo, 'gh').max_age_hours, DEFAULT_GH_MAX_AGE_HOURS),
    injectContext: typeof inject === 'boolean' ? inject : DEFAULT_INJECT_CONTEXT,
  }
}

/** Whether the watch runs at all: `todo.folder` is configured (the catalog path follows from it). */
export const isActive = (c: TodoWatchConfig): boolean => c.catalog !== null

/** Whether a path is absolute: POSIX, drive or UNC. */
export const isAbsolute = (path: string): boolean => /^([A-Za-z]:)?[\\/]/.test(path)

/**
 * A configured path against the project root: a relative one is joined to it, an absolute one is kept, as
 * harness_lib's `cfg.path()` does.
 */
export const under = (root: string, path: string): string => (isAbsolute(path) ? path : `${root}/${path}`)

/** `<state_dir>/todo-sync`: the runner pointer and the sync report live here. */
export const syncDirOf = (c: TodoWatchConfig): string => `${c.stateDir}/todo-sync`
