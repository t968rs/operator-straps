import { cleanPath } from './config'
import { DONE_OUTCOMES, DONE_STATUSES, RECEIPTS_DIR } from './mirror'
import type { PlanItem } from './plans'
import type { Listed } from '../types'

/**
 * A plan's done share and the color it takes on the line (plan 2030, issue #343). An item is done when its
 * receipt's outcome kind is in `DONE_OUTCOMES`, or, with no readable receipt, when its own status is in
 * `DONE_STATUSES` (V6); the plan number steps from bright to dim as items finish (V1, V2).
 * The receipt-else-status fallback applies to each item, where harness `plan_receipts.status_view` counts an
 * item of a receipts-scheme plan with no receipt as PENDING. Receipts count for any qualifying plan whatever
 * its `frozen.records` scheme (harness `book_for` reads them only for receipts plans), and a plan id that two
 * plan files share skips receipts and counts its item statuses.
 * Pure: no `$`; the caller lists the receipts folders, reads the receipts and passes the answers in.
 */

/** How many of a plan's items are done, of how many. */
export type Progress = { done: number; total: number }

/** ANSI 256 colors of the plan number, step 0 (none done) to step 4 (all done); none in the TODO palette. */
export const PLAN_RAMP: readonly number[] = [51, 45, 74, 67, 243]

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const parse = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/**
 * The outcome kind of a receipt's text; null for absent or malformed text, a kind that is not a string, or,
 * given `itemId`, a receipt that names another item (`plan_receipts` rejects one whose item is not its stem).
 */
export const outcomeKindOf = (text: string | undefined, itemId?: string): string | null => {
  const receipt = text === undefined ? null : parse(text)
  if (!isObject(receipt) || (itemId !== undefined && receipt.item !== itemId)) return null
  const outcome = receipt.outcome
  return isObject(outcome) && typeof outcome.kind === 'string' ? outcome.kind : null
}

const isDoneKind = (kind: string): boolean => (DONE_OUTCOMES as readonly string[]).includes(kind)

const isDoneStatus = (status: string | null): boolean =>
  status !== null && (DONE_STATUSES as readonly string[]).includes(status)

/** Whether one item is done: by its receipt's kind when it has one, else by its own status (V6). */
const isDone = (item: PlanItem, kinds: ReadonlyMap<string, string | null>): boolean => {
  const kind = kinds.get(item.id) ?? null
  return kind === null ? isDoneStatus(item.status) : isDoneKind(kind)
}

/** The done share of `items`, given each item id's receipt outcome kind (absent or null: no receipt). */
export const progressOf = (items: readonly PlanItem[], kinds: ReadonlyMap<string, string | null>): Progress =>
  ({ done: items.filter(item => isDone(item, kinds)).length, total: items.length })

/** The ramp step (V2): 0 with none done (or no items), 4 with all done, else 1 + floor(3 * done / total). */
export const planStep = (p: Progress): number => {
  if (p.total <= 0 || p.done <= 0) return 0
  return p.done >= p.total ? 4 : 1 + Math.floor((3 * p.done) / p.total)
}

/** The plan number's ANSI 256 color for its done share. */
export const planColor = (p: Progress): number => PLAN_RAMP[planStep(p)] ?? PLAN_RAMP[0]

/** `<plans>/<id>/receipts`, forward slashes. */
export const receiptsDirOf = (plansDir: string, id: string): string =>
  `${cleanPath(plansDir)}/${id}/${RECEIPTS_DIR}`

/**
 * The receipts signature of the plans on the line: each plan id, and the name, size and mtime of each `.json`
 * file in its receipts folder, sorted. A receipt recorded or rewritten changes it.
 */
export const receiptsSignatureOf = (byPlan: ReadonlyMap<string, readonly Listed[]>): string =>
  [...byPlan].flatMap(([id, entries]) => [
    id,
    ...entries
      .filter(e => e.kind === 'file' && e.name.endsWith('.json'))
      .map(e => `${id}/${e.name}\t${e.size}\t${e.mtimeMs}`),
  ])
    .sort()
    .join('\n')
