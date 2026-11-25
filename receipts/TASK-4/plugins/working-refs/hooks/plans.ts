import type { Refs } from '../types'
import { cleanPath } from './config'
import { DETACHED_KEY, ISSUES_KEY, PIP_HTML_SUFFIX, PLAN_SUFFIX, TODO_IDS_KEY } from './mirror'

/**
 * An ActionPlan as the mod reads it, and the rule that puts its link on a branch's line (plan 2025 D2, D3).
 * Pure: no `$`; the caller lists the folder, runs git and passes the answers in.
 */

/** One ActionItem as the mod reads it: its id and its own `status` (null when not a string). */
export type PlanItem = { id: string; status: string | null }

/** The fields of one `<prefix>_ActionPlan.json` the line needs. */
export type PlanInfo = {
  /** The 4-digit `plan_id`. */
  id: string
  branch: string | null
  baseBranch: string | null
  /** The full `base_commit`, lower case; '' when the plan records none. */
  baseCommit: string
  refs: Refs
  /** The sibling `<prefix>_PIP.html`, beside the plan file. */
  page: string
  /** The plan's items in file order (plan 2030). */
  items: PlanItem[]
}

/** The merge base of HEAD and a base branch's tip, resolved by the caller (D9); null when git gave none. */
export type MergeBaseOf = (baseBranch: string) => string | null

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const PLAN_ID = /^[0-9]{4}$/

const nonBlank = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null)

const baseName = (path: string): string => cleanPath(path).split('/').pop() ?? ''

/** The page beside a plan file: `<prefix>_ActionPlan.json` becomes `<prefix>_PIP.html`; null for any other name. */
export const pageOf = (planPath: string): string | null => {
  const path = cleanPath(planPath)
  return path.endsWith(PLAN_SUFFIX) ? path.slice(0, -PLAN_SUFFIX.length) + PIP_HTML_SUFFIX : null
}

/** Strings first-seen, duplicates dropped. */
const uniqueStrings = (v: unknown): string[] =>
  Array.isArray(v) ? [...new Set(v.filter((s): s is string => typeof s === 'string' && s !== ''))] : []

/** Positive whole numbers first-seen, duplicates dropped. */
const uniqueIssues = (v: unknown): number[] =>
  Array.isArray(v) ? [...new Set(v.filter((n): n is number => Number.isInteger(n) && n > 0))] : []

/** A `refs` object (`{todo_ids, issues}`) read leniently; anything else is no refs. */
export const refsOf = (v: unknown): Refs =>
  isObject(v) ? { todoIds: uniqueStrings(v[TODO_IDS_KEY]), issues: uniqueIssues(v[ISSUES_KEY]) }
    : { todoIds: [], issues: [] }

/** An `items` array read leniently: non-objects and blank or non-string ids dropped, the first per id kept. */
export const itemsOf = (v: unknown): PlanItem[] => {
  if (!Array.isArray(v)) return []
  const seen = new Set<string>()
  return v.filter(isObject).flatMap(e => {
    if (typeof e.id !== 'string' || e.id === '' || seen.has(e.id)) return []
    seen.add(e.id)
    return [{ id: e.id, status: typeof e.status === 'string' ? e.status : null }]
  })
}

const parse = (text: string): Json | null => {
  try {
    const data: unknown = JSON.parse(text)
    return isObject(data) ? data : null
  } catch {
    return null
  }
}

/**
 * The plan in `text`, read from `planPath`; null when the text is not a plan object, its `plan_id` is not four
 * digits, the name is not a plan file, or its `documentation` is not the sibling page (a markdown PIP has no
 * page to link; spec Builder's calls).
 */
export const parsePlan = (planPath: string, text: string): PlanInfo | null => {
  const data = parse(text)
  const page = pageOf(planPath)
  const id = data === null ? null : nonBlank(data.plan_id)
  const doc = data === null ? null : nonBlank(data.documentation)
  if (data === null || page === null || id === null || !PLAN_ID.test(id)) return null
  if (doc === null || baseName(doc) !== baseName(page)) return null
  return {
    id,
    branch: nonBlank(data.branch),
    baseBranch: nonBlank(data.base_branch),
    baseCommit: (nonBlank(data.base_commit) ?? '').toLowerCase(),
    refs: refsOf(data.refs),
    page,
    items: itemsOf(data.items),
  }
}

const ARCHIVE_TAG = /^archive\/plan\/([0-9]{4})-[^/]+\/.+$/

/** The plan ids that have an `archive/plan/<id>-<slug>/<round>` tag, from one tag name per line. */
export const archivedIdsOf = (tagNames: string): Set<string> => {
  const ids = new Set<string>()
  for (const line of tagNames.split(/\r?\n/)) {
    const match = ARCHIVE_TAG.exec(line.trim())
    if (match !== null) ids.add(match[1])
  }
  return ids
}

/**
 * Whether `plan` shows on `branch`'s line: it is not archived (D3), and either its `branch` is the current one
 * (never for a detached checkout) or its `base_commit` is the merge base the caller resolves for its
 * `base_branch` (D2, D9).
 */
export const qualifies = (
  plan: PlanInfo, branch: string, mergeBaseOf: MergeBaseOf, archivedIds: ReadonlySet<string>,
): boolean => {
  if (archivedIds.has(plan.id)) return false
  if (branch !== DETACHED_KEY && plan.branch === branch) return true
  if (plan.baseBranch === null || plan.baseCommit === '') return false
  return mergeBaseOf(plan.baseBranch)?.trim().toLowerCase() === plan.baseCommit
}
