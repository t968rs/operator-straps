/**
 * Review-JSON reading for the bubble guard: a port of the harness library's `validation/id_handling.py`
 * (`issue_ids`, `disposition_ids`, `all_issues_dispositioned`) plus file selection. Pure: no `$`.
 */

/**
 * The parts of a consolidated review JSON (`<artifacts.reviews>/*.json`) the watch reads. `closed`: ids
 * whose latest `post_review_resolutions[]` status is `RESOLVED` or `CLOSED_NO_ACTION`.
 */
export type ReviewDoc = {
  verdict: string | null
  issueIds: string[]
  dispositioned: string[]
  bubbles: string[]
  closed: string[]
}

/** A directory entry, as `$.fs.list` reports one. */
export type Listed = { name: string; mtimeMs: number; kind: string }

const VERDICT_PREFIX = /^(NOT READY TO MERGE|READY TO MERGE)/

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const idOf = (v: unknown): string | undefined => (isRecord(v) && typeof v.id === 'string' ? v.id : undefined)
const isDefined = <T>(v: T | undefined): v is T => v !== undefined
const uniq = (ids: readonly string[]): string[] => [...new Set(ids)]

/** Issue ids in C, I, M order, then by number. */
const byId = (a: string, b: string): number =>
  a[0] === b[0] ? Number(a.slice(1)) - Number(b.slice(1)) : a < b ? -1 : 1

const parseObject = (text: string): Record<string, unknown> | undefined => {
  try {
    const doc: unknown = JSON.parse(text)
    return isRecord(doc) ? doc : undefined
  } catch {
    return undefined
  }
}

const issueIdsOf = (doc: Record<string, unknown>): string[] => {
  const issues = isRecord(doc.issues) ? doc.issues : {}
  return Object.values(issues).flatMap(bucket => list(bucket).map(idOf).filter(isDefined))
}

const bubblesOf = (doc: Record<string, unknown>): string[] =>
  list(doc.bubbles).filter((b): b is string => typeof b === 'string')

const dispositionedOf = (doc: Record<string, unknown>): string[] => [
  ...list(doc.post_review_resolutions).map(idOf).filter(isDefined),
  ...bubblesOf(doc),
  ...list(doc.bubble_up).map(idOf).filter(isDefined),
]

const CLOSING_STATUSES: readonly unknown[] = ['RESOLVED', 'CLOSED_NO_ACTION']

/** Ids whose last resolution entry carries a closing status; a later non-closing entry reopens. */
const closedOf = (doc: Record<string, unknown>): string[] => {
  const latest = new Map<string, unknown>()
  for (const entry of list(doc.post_review_resolutions)) {
    const id = idOf(entry)
    if (id !== undefined && isRecord(entry)) latest.set(id, entry.status)
  }
  return [...latest].filter(([, status]) => CLOSING_STATUSES.includes(status)).map(([id]) => id)
}

/** The review parts, or undefined when the text is not a JSON object. */
export const readReview = (text: string): ReviewDoc | undefined => {
  const doc = parseObject(text)
  if (doc === undefined) return undefined
  return {
    verdict: typeof doc.verdict === 'string' ? doc.verdict : null,
    issueIds: uniq(issueIdsOf(doc)),
    dispositioned: uniq(dispositionedOf(doc)),
    bubbles: uniq(bubblesOf(doc)),
    closed: closedOf(doc),
  }
}

/** `bubble_ups.json` `items[].id`, or null when the text is not a JSON object. */
export const sidecarIds = (text: string): string[] | null => {
  const doc = parseObject(text)
  return doc === undefined ? null : uniq(list(doc.items).map(idOf).filter(isDefined))
}

/** At least one issue, and every issue dispositioned. */
export const allDispositioned = (r: ReviewDoc): boolean =>
  r.issueIds.length > 0 && r.issueIds.every(id => r.dispositioned.includes(id))

/** Tracked bubbled ids the review does not disposition, sorted; none without a review. */
export const missingFromReview = (tracked: readonly string[], r: ReviewDoc | undefined): string[] =>
  r === undefined ? [] : uniq(tracked.filter(id => !r.dispositioned.includes(id))).sort(byId)

export const verdictPrefix = (verdict: string | null): string | undefined => verdict?.match(VERDICT_PREFIX)?.[1]

/** The newest `<NNNN>_*.json` file entry for a PR, or undefined. */
export const reviewFileFor = (pr: number, entries: readonly Listed[]): Listed | undefined => {
  const prefix = `${String(pr).padStart(4, '0')}_`
  const hits = entries.filter(e => e.kind === 'file' && e.name.startsWith(prefix) && e.name.endsWith('.json'))
  return [...hits].sort((a, b) => b.mtimeMs - a.mtimeMs)[0]
}

const BUBBLE_WORD = /bubble/i

/** The message talks about bubbles: the trigger `BUBBLE-watch.sh` used, any case and inflection. */
export const mentionsBubble = (text: string | undefined): boolean => BUBBLE_WORD.test(text ?? '')

/**
 * The keyword-triggered Stop block (the `has_bubbles.py` rule): a message that mentions bubbles needs a
 * populated `bubbles[]`, unless every issue is already dispositioned. Undefined to let the stop through.
 */
export const keywordBlock = (
  pr: number,
  text: string | undefined,
  r: ReviewDoc | undefined,
  isLoopBreak: boolean,
): string | undefined => {
  if (isLoopBreak || r === undefined || !mentionsBubble(text) || r.bubbles.length > 0) return undefined
  const open = r.issueIds.filter(id => !r.dispositioned.includes(id)).sort(byId)
  if (open.length === 0) return undefined
  return (
    `PR #${pr}: the last message discusses bubbles, but the review JSON's bubbles[] is empty while ` +
    `${open.join(', ')} remain undispositioned. Populate bubbles[] before discussing bubbles, unless all ` +
    'issues are already resolved.'
  )
}

/** The state-triggered Stop block text, or undefined to let the stop through. */
export const stopBlock = (
  pr: number | null,
  missing: readonly string[],
  from: string,
  isLoopBreak: boolean,
): string | undefined => {
  if (isLoopBreak || missing.length === 0) return undefined
  return (
    `PR #${pr ?? '?'}: the review JSON does not disposition bubbled ${missing.join(', ')} ` +
    `(tracked from ${from}). Add them to bubbles[] (or bubble_up[] / post_review_resolutions[]) before stopping.`
  )
}
