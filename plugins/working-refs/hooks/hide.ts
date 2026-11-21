import type { Refs } from '../types'
import { KEYWORD_KEY, KEYWORD_MAX, KEYWORD_PATTERN } from './mirror'

/**
 * Which override refs leave the working line (plan 2027): a TODO id the checked-out catalog lists in
 * `retired_ids`, an issue `gh` reported closed. Two feeds answer for an issue: the mod's own `gh issue view`
 * cache (`<state_dir>/working-refs/issues.json`) and the open-issue list `todo_sync.py untracked` writes
 * (`<state_dir>/todo-sync/open_issues.json`). Only `gh` answers CLOSED; the list answers OPEN for the numbers it
 * holds, and its absence from the list is no answer. Hiding never rewrites the override file (D3). The same
 * catalog also gives each TODO id its keyword label (plan 2028). Pure: no `$`.
 */

/** What `gh issue view <n> --json state` last answered; UNKNOWN when it ran but gave no usable state. */
export type IssueState = 'OPEN' | 'CLOSED' | 'UNKNOWN'

/** One cached `gh` answer: the state and when it was checked (ms); `triedAt` is the last attempt, failed or not. */
export type CachedIssue = { state: IssueState; checkedAt: number; triedAt: number }

/** The open-issue list: when it was fetched (ms) and the numbers it holds. */
export type OpenList = { fetchedAt: number; open: ReadonlySet<number> }

/** The issue cache's file version. */
export const CACHE_VERSION = 1
/** The open-issue list's file version (`todo_sync.issues.OPEN_ISSUES_VERSION`, pinned by the contract test). */
export const OPEN_LIST_VERSION = 1

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const parse = (text: string | undefined): unknown => {
  if (text === undefined) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

const isIssue = (x: unknown): x is number => Number.isInteger(x) && (x as number) > 0

/** An ISO 8601 time in ms, or null when it is not a string or does not parse. */
const timeOf = (v: unknown): number | null => {
  if (typeof v !== 'string') return null
  const ms = Date.parse(v)
  return Number.isNaN(ms) ? null : ms
}

/** What the line takes from the checked-out catalog: the retired ids and each item's keyword by id. */
export type CatalogView = { retired: ReadonlySet<string>; keywords: ReadonlyMap<string, string> }

const retiredIn = (data: unknown): ReadonlySet<string> => {
  const ids = isObject(data) && Array.isArray(data.retired_ids) ? data.retired_ids : []
  return new Set(ids.filter((x): x is string => typeof x === 'string'))
}

/** One word, a letter or digit first, at most 32 characters; `$` without the m flag ends the input only. */
const KEYWORD_SHAPE = new RegExp(KEYWORD_PATTERN)

const keywordOk = (keyword: unknown): keyword is string =>
  typeof keyword === 'string' && keyword.length <= KEYWORD_MAX && KEYWORD_SHAPE.test(keyword)

const keywordsIn = (data: unknown): ReadonlyMap<string, string> => {
  const items = isObject(data) && Array.isArray(data.items) ? data.items : []
  const found = new Map<string, string>()
  for (const item of items) {
    if (!isObject(item) || typeof item.id !== 'string') continue
    const keyword = item[KEYWORD_KEY]
    if (keywordOk(keyword)) found.set(item.id, keyword)
  }
  return found
}

/** The catalog's retired ids and keywords from one parse; both empty for an absent or malformed catalog. */
export const catalogViewOf = (text: string | undefined): CatalogView => {
  const data = parse(text)
  return { retired: retiredIn(data), keywords: keywordsIn(data) }
}

/**
 * The catalog's `retired_ids`; empty for an absent or malformed catalog, non-string members dropped. A test seam:
 * production reads the same `retiredIn` through `catalogViewOf(...).retired`, so no hook calls this.
 */
export const retiredIdsOf = (text: string | undefined): ReadonlySet<string> => retiredIn(parse(text))

/**
 * The catalog's item id -> `keyword` map (plan 2028); items without a string keyword of one word (or a string id)
 * are skipped, and an absent or malformed catalog gives an empty map. A test seam: production reads the same
 * `keywordsIn` through `catalogViewOf(...).keywords`, so no hook calls this.
 */
export const keywordsOf = (text: string | undefined): ReadonlyMap<string, string> => keywordsIn(parse(text))

/** The open-issue list, or null when absent, malformed, of another version or without a fetch time. */
export const openListOf = (text: string | undefined): OpenList | null => {
  const data = parse(text)
  if (!isObject(data) || data.version !== OPEN_LIST_VERSION || !Array.isArray(data.open)) return null
  const fetchedAt = timeOf(data.fetched_at)
  return fetchedAt === null ? null : { fetchedAt, open: new Set(data.open.filter(isIssue)) }
}

const STATES: readonly IssueState[] = ['OPEN', 'CLOSED', 'UNKNOWN']

/** One cache entry, or null when its state or check time is unusable. */
const cachedOf = (entry: unknown): CachedIssue | null => {
  if (!isObject(entry) || !STATES.includes(entry.state as IssueState)) return null
  const checkedAt = timeOf(entry.checked_at)
  if (checkedAt === null) return null
  return { state: entry.state as IssueState, checkedAt, triedAt: Math.max(checkedAt, timeOf(entry.tried_at) ?? 0) }
}

/** The issue cache by number; empty for an absent or malformed file or another version. */
export const issueCacheOf = (text: string | undefined): ReadonlyMap<number, CachedIssue> => {
  const data = parse(text)
  const found = new Map<number, CachedIssue>()
  if (!isObject(data) || data.version !== CACHE_VERSION || !isObject(data.issues)) return found
  for (const [key, entry] of Object.entries(data.issues as Json)) {
    const n = Number(key)
    const cached = cachedOf(entry)
    if (isIssue(n) && cached !== null) found.set(n, cached)
  }
  return found
}

/**
 * Whether issue `n` hides: only a cached `gh` CLOSED hides it, unless an open list fetched after that answer
 * lists it (OPEN). Absent from the list, UNKNOWN or never checked, it shows.
 */
export const isClosed = (n: number, list: OpenList | null, cache: ReadonlyMap<number, CachedIssue>): boolean => {
  const cached = cache.get(n)
  if (cached?.state !== 'CLOSED') return false
  return !(list !== null && list.open.has(n) && list.fetchedAt > cached.checkedAt)
}

/** The refs left once retired ids and closed issues are dropped, order kept. */
export const visibleRefs = (refs: Refs, retired: ReadonlySet<string>, closed: (n: number) => boolean): Refs => ({
  todoIds: refs.todoIds.filter(id => !retired.has(id)),
  issues: refs.issues.filter(n => !closed(n)),
})
