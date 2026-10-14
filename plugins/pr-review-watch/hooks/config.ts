/**
 * The harness keys the watch reads from `<project>/.claude/harness.json`, merged over copies of the harness
 * plugin's `config/defaults.json` values: an installed mod sits in its own plugin cache folder and cannot
 * read that file. `tests/mods/test_pr_review_watch_config_mirror.py` pins the copies. Pure: no `$`.
 */

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const DEFAULT_MATRIX_PATH = 'docs/_harness/pr_review_invocation_test_matrix.jsonl'
export const DEFAULT_REVIEWS = 'docs/PR_REVIEWS'
export const DEFAULT_SCRATCH = 'docs/_scratch/pr_review'
export const DEFAULT_BASE_BRANCH: string | null = null

/** Project-relative POSIX paths and the configured base branch (null: resolve it from git). */
export type WatchConfig = {
  stateDir: string
  matrixPath: string
  reviewsDir: string
  scratchDir: string
  baseBranch: string | null
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
 * The watch's view of a `harness.json` text: each key it reads replaces its default, `artifacts` merges
 * key by key. Malformed JSON or a wrong-typed value keeps the default (the harness hooks report it).
 */
export const readConfig = (text: string): WatchConfig => {
  const data = parse(text)
  const artifacts = isObject(data.artifacts) ? data.artifacts : {}
  const base = data.base_branch
  return {
    stateDir: pathOr(data.state_dir, DEFAULT_STATE_DIR),
    matrixPath: pathOr(data.matrix_path, DEFAULT_MATRIX_PATH),
    reviewsDir: pathOr(artifacts.reviews, DEFAULT_REVIEWS),
    scratchDir: pathOr(artifacts.scratch, DEFAULT_SCRATCH),
    baseBranch: typeof base === 'string' && base.trim() !== '' ? base.trim() : DEFAULT_BASE_BRANCH,
  }
}

/**
 * A configured path against the project root: a relative one is joined to it, an absolute one (POSIX,
 * drive or UNC) is kept, as harness_lib's `cfg.path()` does.
 */
export const under = (root: string, path: string): string =>
  /^([A-Za-z]:)?[\\/]/.test(path) ? path : `${root}/${path}`

/** `<state_dir>/pr-review`: where Phase 5 sentinels live. */
export const sentinelDirOf = (c: WatchConfig): string => `${c.stateDir}/pr-review`

/** `<state_dir>/pr-team/_runtime`: the pr-team run folders. */
export const runtimeBaseOf = (c: WatchConfig): string => `${c.stateDir}/pr-team/_runtime`
