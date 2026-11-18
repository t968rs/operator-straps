import type { PlanLink, Refs, WorkingLine } from '../types'
import type { Overrides } from './overrides'
import type { PlanInfo } from './plans'

/**
 * The working line of a branch: the qualifying plans' links first, then the refs (plan 2025 spec Section 2).
 * The plain form goes to the `line` atom for band-line; the ccstatusline form, with each plan number an OSC 8
 * link to its page (D8), goes to the line file. Pure: no `$`.
 */

const SEP = ' · '

const union = <T>(lists: readonly (readonly T[])[]): T[] => [...new Set(lists.flat())]

/**
 * The refs as `harness_lib.working_refs.format_refs` writes them: `todo-k69m (301, 315)`; ids alone
 * `todo-k69m`; issues alone `#301, #315`.
 */
export const formatRefs = (refs: Refs): string => {
  if (refs.todoIds.length === 0) return refs.issues.map(n => `#${n}`).join(', ')
  const ids = refs.todoIds.join(', ')
  return refs.issues.length > 0 ? `${ids} (${refs.issues.join(', ')})` : ids
}

/** `plan 2025` or `plans 2024, 2025`, each number passed through `num`; '' for no plans. */
const plansPart = (plans: readonly PlanLink[], num: (p: PlanLink) => string): string => {
  if (plans.length === 0) return ''
  return `${plans.length === 1 ? 'plan' : 'plans'} ${plans.map(num).join(', ')}`
}

const joinParts = (...parts: string[]): string => parts.filter(p => p !== '').join(SEP)

/**
 * `branch`'s line from its qualifying plans and the overrides: the branch's override, when set, replaces the
 * union of the plans' refs; plan links are never overridden. Null when the line would be empty.
 */
export const buildLine = (branch: string, qualifying: readonly PlanInfo[], overrides: Overrides): WorkingLine | null => {
  const sorted = [...qualifying].sort((a, b) => a.id.localeCompare(b.id))
  const plans: PlanLink[] = sorted.map(p => ({ id: p.id, page: p.page }))
  const override = overrides.get(branch)
  const refs: Refs = override ?? {
    todoIds: union(sorted.map(p => p.refs.todoIds)),
    issues: union(sorted.map(p => p.refs.issues)),
  }
  const text = joinParts(plansPart(plans, p => p.id), formatRefs(refs))
  return text === '' ? null : { branch, plans, todoIds: [...refs.todoIds], issues: [...refs.issues], text }
}

/** A path percent-encoded for a URL: `encodeURI`, plus `#` and `?`, which it leaves as they are. */
const escapeUrl = (path: string): string => encodeURI(path).replace(/#/g, '%23').replace(/\?/g, '%3F')

/**
 * The `file:` URL of an absolute page path: `E:/x/y.html` (or `E:\x\y.html`) is `file:///E:/x/y.html`,
 * `/x/y.html` is `file:///x/y.html`, a UNC `//host/share/y.html` is `file://host/share/y.html`.
 */
export const fileUrl = (page: string): string => {
  const path = page.replace(/\\/g, '/')
  if (/^[A-Za-z]:\//.test(path)) return `file:///${escapeUrl(path)}`
  if (path.startsWith('//')) return `file:${escapeUrl(path)}`
  return `file://${escapeUrl(path.startsWith('/') ? path : `/${path}`)}`
}

/** An OSC 8 hyperlink: `text` shown, `url` opened. */
export const osc8 = (url: string, text: string): string => `\x1b]8;;${url}\x1b\\${text}\x1b]8;;\x1b\\`

/** The plain line (`WorkingLine.text`); '' for no line. */
export const plainText = (line: WorkingLine | null): string => line?.text ?? ''

/** The ccstatusline line: the plain line with each plan number an OSC 8 link to its page; '' for no line. */
export const statusText = (line: WorkingLine | null): string => {
  if (line === null) return ''
  const refs = formatRefs({ todoIds: line.todoIds, issues: line.issues })
  return joinParts(plansPart(line.plans, p => osc8(fileUrl(p.page), p.id)), refs)
}
