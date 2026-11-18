import type { Refs } from '../types'
import { BRANCHES_KEY, ISSUES_KEY, STORE_VERSION, TODO_IDS_KEY } from './mirror'

/**
 * The override file the harness `working` command writes (`<state_dir>/working-refs/overrides.json`, plan 2025
 * D6): `{ "version": 1, "branches": { <branch>: { "todo_ids", "issues", "set_at" } } }`. The mod only reads it.
 * Pure: no `$`.
 */

/** Each branch's override refs, keyed by branch name or `(detached)`. */
export type Overrides = ReadonlyMap<string, Refs>

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const NONE: Overrides = new Map()

const parse = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/** A list of `T`, or null when the value is not an array or holds anything else; absent reads as empty. */
const listOf = <T>(v: unknown, isT: (x: unknown) => x is T): T[] | null => {
  if (v === undefined) return []
  return Array.isArray(v) && v.every(isT) ? [...v] : null
}

const isText = (x: unknown): x is string => typeof x === 'string'
/** A positive whole number, the only issue shape plans.ts `uniqueIssues` keeps. */
const isIssue = (x: unknown): x is number => Number.isInteger(x) && (x as number) > 0

/** One entry's refs, or null when a field has the wrong type (`harness_lib.working_refs` skips such an entry). */
const entryRefs = (entry: unknown): Refs | null => {
  if (!isObject(entry)) return null
  const todoIds = listOf(entry[TODO_IDS_KEY], isText)
  const issues = listOf(entry[ISSUES_KEY], isIssue)
  return todoIds === null || issues === null ? null : { todoIds, issues: [...new Set(issues)] }
}

/**
 * The overrides in an `overrides.json` text. An absent file, malformed JSON, another version or no `branches`
 * object reads as none; an unusable entry is skipped.
 */
export const parseOverrides = (text: string | undefined): Overrides => {
  const data = text === undefined ? undefined : parse(text)
  if (!isObject(data) || data.version !== STORE_VERSION || !isObject(data[BRANCHES_KEY])) return NONE
  const found = new Map<string, Refs>()
  for (const [branch, entry] of Object.entries(data[BRANCHES_KEY] as Json)) {
    const refs = entryRefs(entry)
    if (refs !== null) found.set(branch, refs)
  }
  return found
}
