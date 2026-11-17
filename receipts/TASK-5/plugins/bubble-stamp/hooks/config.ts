/**
 * The one harness key the stamp mod reads from `<project>/.claude/harness.json`, merged over a copy of the
 * harness plugin's `config/defaults.json` value: an installed mod sits in its own plugin cache folder and
 * cannot read that file. `tests/mods/test_bubble_stamp_config_mirror.py` pins the copy. Pure: no `$`.
 */

export const DEFAULT_REVIEWS = 'docs/PR_REVIEWS'

/** The reviews folder, a project-relative POSIX path or an absolute one. */
export type StampConfig = {
  reviewsDir: string
}

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const clean = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** A non-blank string value, cleaned; else the fallback. */
const pathOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && clean(v) !== '' ? clean(v) : fallback

const parse = (text: string): Json => {
  try {
    const data: unknown = JSON.parse(text)
    return isObject(data) ? data : {}
  } catch {
    return {}
  }
}

/**
 * The mod's view of a `harness.json` text: `artifacts.reviews` replaces its default. Malformed JSON or a
 * wrong-typed value keeps the default (the harness hooks report it).
 */
export const readConfig = (text: string): StampConfig => {
  const data = parse(text)
  const artifacts = isObject(data.artifacts) ? data.artifacts : {}
  return { reviewsDir: pathOr(artifacts.reviews, DEFAULT_REVIEWS) }
}

/**
 * A configured path against the project root: a relative one is joined to it, an absolute one (POSIX,
 * drive or UNC) is kept, as harness_lib's `cfg.path()` does.
 */
export const under = (root: string, path: string): string =>
  /^([A-Za-z]:)?[\\/]/.test(path) ? path : `${root}/${path}`
