/**
 * Review-JSON reading for the stamp mod: the latest `post_review_resolutions[]` entry per id with its status,
 * date and evidence, the `closedOf` rule of `pr-review-watch/hooks/bubbles.ts`, and review file selection.
 * Pure: no `$`.
 */

import type { Resolution } from './memo'

/** A directory entry, as `$.fs.list` reports one. */
export type Listed = { name: string; mtimeMs: number; kind: string }

/**
 * A review run key: a PR number, or a review-local key `local-<label>` (review file `LOCAL_<label>_<slug>.json`).
 * The constants mirror `plugins/harness/lib/harness_lib/review_local_models.py`, pinned by
 * `tests/mods/test_local_run_key_mirror.py`.
 */
export type RunKey = number | string

export const LOCAL_PREFIX = 'local-'
export const REVIEW_PREFIX = 'LOCAL_'
export const LABEL_PATTERN = '^[a-z0-9]+(-[a-z0-9]+)*$'
export const LABEL_MAX = 48

const LABEL = new RegExp(LABEL_PATTERN)

/** True for a valid `local-<label>` key. */
export const isLocalKey = (value: unknown): value is string => {
  if (typeof value !== 'string' || !value.startsWith(LOCAL_PREFIX)) return false
  const label = value.slice(LOCAL_PREFIX.length)
  return label.length <= LABEL_MAX && LABEL.test(label)
}

/** The review file name prefix: `<NNNN>_`, `LOCAL_<label>_` for a local key, undefined for any other string. */
export const reviewPrefix = (key: RunKey): string | undefined => {
  if (typeof key === 'number') return `${String(key).padStart(4, '0')}_`
  return isLocalKey(key) ? `${REVIEW_PREFIX}${key.slice(LOCAL_PREFIX.length)}_` : undefined
}

const CLOSING_STATUSES: readonly string[] = ['RESOLVED', 'CLOSED_NO_ACTION']

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const textOf = (v: unknown): string => (typeof v === 'string' ? v : '')

const parseObject = (text: string): Record<string, unknown> | undefined => {
  try {
    const doc: unknown = JSON.parse(text)
    return isRecord(doc) ? doc : undefined
  } catch {
    return undefined
  }
}

/**
 * The latest resolution per id, in order of first appearance, whatever its status (a later entry of any
 * status replaces an earlier one). A missing status, date or evidence reads as an empty string. Undefined
 * when the text is not a JSON object.
 */
export const latestResolutions = (text: string): Resolution[] | undefined => {
  const doc = parseObject(text)
  if (doc === undefined) return undefined
  const latest = new Map<string, Resolution>()
  for (const entry of list(doc.post_review_resolutions)) {
    if (!isRecord(entry) || typeof entry.id !== 'string') continue
    latest.set(entry.id, {
      id: entry.id, status: textOf(entry.status), date: textOf(entry.date), evidence: textOf(entry.evidence),
    })
  }
  return [...latest.values()]
}

/** The latest resolutions whose status is `RESOLVED` or `CLOSED_NO_ACTION`; a later non-closing entry reopens. */
export const closedResolutions = (text: string): Resolution[] | undefined =>
  latestResolutions(text)?.filter(r => CLOSING_STATUSES.includes(r.status))

/**
 * The newest review file entry for a run key (`<NNNN>_*.json`, or `LOCAL_<label>_*.json`), or undefined. An
 * mtime tie goes to the larger name, the same tie rule as `find_review` in `plugins/harness/scripts/bubble_memo.py`.
 */
export const reviewFileFor = (key: RunKey, entries: readonly Listed[]): Listed | undefined => {
  const prefix = reviewPrefix(key)
  if (prefix === undefined) return undefined
  const hits = entries.filter(e => e.kind === 'file' && e.name.startsWith(prefix) && e.name.endsWith('.json'))
  return [...hits].sort(newestFirst)[0]
}

const newestFirst = (a: Listed, b: Listed): number =>
  b.mtimeMs - a.mtimeMs || (a.name < b.name ? 1 : a.name > b.name ? -1 : 0)
