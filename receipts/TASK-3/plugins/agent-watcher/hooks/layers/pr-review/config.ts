import { isObject, pathOr, type HarnessJson } from '../../core/config'

/**
 * The harness keys the pr-review layer reads from the parsed `harness.json` core keeps (`matrix_path`,
 * `artifacts.reviews`, `artifacts.scratch`, `base_branch`), merged over copies of the harness plugin's
 * `config/defaults.json` values; `state_dir` is core's. `tests/mods/test_agent_watcher_config_mirror.py`
 * pins the copies. Pure: no `$`.
 */

export const DEFAULT_MATRIX_PATH = 'docs/_harness/pr_review_invocation_test_matrix.jsonl'
export const DEFAULT_REVIEWS = 'docs/PR_REVIEWS'
export const DEFAULT_SCRATCH = 'docs/_scratch/pr_review'
export const DEFAULT_BASE_BRANCH: string | null = null

/** Project-relative POSIX paths and the configured base branch (null: resolve it from git). */
export type PrReviewConfig = {
  matrixPath: string
  reviewsDir: string
  scratchDir: string
  baseBranch: string | null
}

/**
 * The layer's keys of a parsed `harness.json`: each key replaces its default, `artifacts` merges key by key.
 * A missing, blank or wrong-typed value keeps the default (the harness hooks report it).
 */
export const prReviewConfigOf = (data: HarnessJson): PrReviewConfig => {
  const artifacts = isObject(data.artifacts) ? data.artifacts : {}
  const base = data.base_branch
  return {
    matrixPath: pathOr(data.matrix_path, DEFAULT_MATRIX_PATH),
    reviewsDir: pathOr(artifacts.reviews, DEFAULT_REVIEWS),
    scratchDir: pathOr(artifacts.scratch, DEFAULT_SCRATCH),
    baseBranch: typeof base === 'string' && base.trim() !== '' ? base.trim() : DEFAULT_BASE_BRANCH,
  }
}

/** `<state_dir>/pr-review`: where Phase 5 sentinels live. */
export const sentinelDirOf = (c: { stateDir: string }): string => `${c.stateDir}/pr-review`

/** `<state_dir>/pr-team/_runtime`: the pr-team run folders. */
export const runtimeBaseOf = (c: { stateDir: string }): string => `${c.stateDir}/pr-team/_runtime`
