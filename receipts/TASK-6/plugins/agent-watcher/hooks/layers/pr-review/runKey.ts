/**
 * The run key of a pr-review run: a PR number, or a local key `local-<label>` (a PR-free review run by the
 * harness skill `review-local`). Mirrors `plugins/harness/lib/harness_lib/review_local_models.py` and the
 * `RUN_ID` rule of `review_models.py`; `tests/mods/test_local_run_key_mirror.py` pins the constants and the
 * run-id pattern to them. Pure: no `$`.
 */

/** A PR number, or a valid `local-<label>` key. */
export type RunKey = number | string

export const LOCAL_PREFIX = 'local-'
export const REVIEW_PREFIX = 'LOCAL_'
export const LABEL_PATTERN = '^[a-z0-9]+(-[a-z0-9]+)*$'
export const LABEL_MAX = 48

/**
 * `pr<N>_<stamp>` or `local-<label>_<stamp>`, stamp `yyyymmddTHHMMSSZ` (UTC). Groups: 1 the PR digits, 2 the
 * local key, 3 to 8 the stamp's year, month, day, hour, minute and second.
 */
export const RUN_ID_PATTERN =
  '^(?:pr(\\d{1,7})|(local-(?=[^_]{1,48}_)[a-z0-9]+(?:-[a-z0-9]+)*))_(\\d{4})(\\d{2})(\\d{2})T(\\d{2})(\\d{2})(\\d{2})Z$'

const LABEL = new RegExp(LABEL_PATTERN)
export const RUN_ID = new RegExp(RUN_ID_PATTERN)

/** True for a valid `local-<label>` key. */
export const isLocalKey = (value: unknown): value is string => {
  if (typeof value !== 'string' || !value.startsWith(LOCAL_PREFIX)) return false
  const label = value.slice(LOCAL_PREFIX.length)
  return label.length <= LABEL_MAX && LABEL.test(label)
}

/** A positive integer PR number, or null. */
export const toPr = (raw: string | undefined): number | null =>
  raw !== undefined && /^\d+$/.test(raw) && Number(raw) >= 1 ? Number(raw) : null

/** A PR number (digits, at least 1) or a valid local key; null for anything else. */
export const toRunKey = (raw: string | undefined): RunKey | null => toPr(raw) ?? (isLocalKey(raw) ? raw : null)

/** The key a run id names (`pr1122_<stamp>` -> 1122, `local-x_<stamp>` -> `local-x`), or null. */
export const keyOfRunId = (runId: string): RunKey | null => {
  const m = runId.match(RUN_ID)
  return m === null ? null : toPr(m[1]) ?? m[2] ?? null
}

/**
 * Epoch ms of the UTC stamp a run id carries (`pr1122_20260518T060416Z`, `local-x_20260518T060416Z`), or null
 * when absent or invalid.
 */
export const startedAtOfRunId = (runId: string): number | null => {
  const m = runId.match(RUN_ID)
  if (m === null) return null
  const [y, mo, d, h, mi, s] = m.slice(3).map(Number) as [number, number, number, number, number, number]
  const ms = Date.UTC(y, mo - 1, d, h, mi, s)
  const back = new Date(ms)
  return back.getUTCMonth() === mo - 1 && back.getUTCDate() === d && h < 24 && mi < 60 && s < 60 ? ms : null
}

/** The run directory name under `artifacts.scratch`: `<NNNN>` zero-padded, or the local key itself. */
export const runDirName = (key: RunKey): string => (typeof key === 'number' ? String(key).padStart(4, '0') : key)

/** The review file name prefix: `<NNNN>_`, or `LOCAL_<label>_` for a local key. */
export const reviewPrefix = (key: RunKey): string =>
  typeof key === 'number' ? `${String(key).padStart(4, '0')}_` : `${REVIEW_PREFIX}${key.slice(LOCAL_PREFIX.length)}_`

/**
 * How a run is named in the band and in Stop text: `PR #<N>`, or `local review <key>` (the wording of
 * `pr_review.py`). Any other id, such as an unparsed sentinel name, keeps the `PR #<id>` form; null is `PR #?`.
 */
export const runName = (key: RunKey | null): string => (isLocalKey(key) ? `local review ${key}` : `PR #${key ?? '?'}`)
