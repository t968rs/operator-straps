import { DEFAULT_PLANS, DEFAULT_STATE_DIR, LINE_PATH, OVERRIDES_PATH } from './mirror'

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
}

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Forward slashes, no surrounding blanks, no trailing slash. */
export const cleanPath = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** A non-blank string value, cleaned; else the fallback. */
const pathOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && cleanPath(v) !== '' ? cleanPath(v) : fallback

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
  const artifacts = isObject(data.artifacts) ? data.artifacts : {}
  return {
    stateDir: pathOr(data.state_dir, DEFAULT_STATE_DIR),
    plansDir: pathOr(artifacts.plans, DEFAULT_PLANS),
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
