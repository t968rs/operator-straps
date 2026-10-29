/**
 * Review-JSON reading for the stamp mod: the latest `post_review_resolutions[]` entry per id with its status,
 * date and evidence, the `closedOf` rule of `pr-review-watch/hooks/bubbles.ts`, and review file selection.
 * Pure: no `$`.
 */

import type { Resolution } from './memo'

/** A directory entry, as `$.fs.list` reports one. */
export type Listed = { name: string; mtimeMs: number; kind: string }

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

/** The newest `<NNNN>_*.json` file entry for a PR, or undefined. */
export const reviewFileFor = (pr: number, entries: readonly Listed[]): Listed | undefined => {
  const prefix = `${String(pr).padStart(4, '0')}_`
  const hits = entries.filter(e => e.kind === 'file' && e.name.startsWith(prefix) && e.name.endsWith('.json'))
  return [...hits].sort((a, b) => b.mtimeMs - a.mtimeMs)[0]
}
