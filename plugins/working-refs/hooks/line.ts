import type { OtherSegment, PlanLink, Refs, WorkingLine } from '../types'
import { visibleRefs } from './hide'
import type { Overrides } from './overrides'
import type { PlanInfo } from './plans'

/**
 * The working line of a branch: the qualifying plans' links first, then the own refs (plan 2025 spec Section 2),
 * then every other branch's override as `[ <branch> <refs> ]`, most recently set first, capped at
 * `working_refs.max_chars` with ` +N` for the segments left out (plan 2027). The plain form goes to the `line`
 * atom for band-line; the ccstatusline form, with each plan number an OSC 8 link to its page (D8) and each other
 * branch name dark, goes to the line files. Pure: no `$`.
 */

const SEP = ' · '
/** ANSI 256-color 240 and the default-foreground reset around another branch's name (ccstatusline form). */
export const DARK = '\x1b[38;5;240m'
export const RESET_FG = '\x1b[39m'

/** What hides on the line and how long it may grow: retired ids, closed issues, the cap. */
export type LineView = {
  retired: ReadonlySet<string>
  isClosed: (n: number) => boolean
  maxChars: number
}

/** A view that hides nothing, uncapped. */
export const SHOW_ALL: LineView = { retired: new Set(), isClosed: () => false, maxChars: Number.MAX_SAFE_INTEGER }

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
 * The whole line from its drawn pieces: the head, ` · ` and the segments joined by a space, then ` +N`
 * (`head +N` when no segment is drawn).
 */
const compose = (head: string, segments: readonly string[], more: number): string => {
  const body = joinParts(head, segments.join(' '))
  return more > 0 ? `${body}${body === '' ? '' : ' '}+${more}` : body
}

/** `[ <branch> <refs> ]`, the branch name passed through `paint`. */
const segmentText = (s: OtherSegment, paint: (b: string) => string = b => b): string =>
  `[ ${paint(s.branch)} ${s.refs} ]`

/** Every other branch's visible override, empty ones dropped, by `set_at` descending, then branch name. */
const otherSegments = (branch: string, overrides: Overrides, view: LineView): OtherSegment[] =>
  [...overrides]
    .filter(([b]) => b !== branch)
    .map(([b, o]) => ({ branch: b, setAt: o.setAt, refs: formatRefs(visibleRefs(o.refs, view.retired, view.isClosed)) }))
    .filter(s => s.refs !== '')
    .sort((a, b) => (a.setAt === b.setAt ? a.branch.localeCompare(b.branch) : a.setAt < b.setAt ? 1 : -1))
    .map(s => ({ branch: s.branch, refs: s.refs }))

/**
 * How many leading segments fit: each is added while the plain line with the ` +N` it would still need stays
 * within `maxChars`; the head is never cut, and with an empty head the first segment is always drawn.
 */
const fitCount = (head: string, all: readonly OtherSegment[], maxChars: number): number => {
  const plain = all.map(s => segmentText(s))
  let k = 0
  while (k < plain.length) {
    const next = compose(head, plain.slice(0, k + 1), plain.length - k - 1)
    if (next.length > maxChars && !(k === 0 && head === '')) break
    k += 1
  }
  return k
}

/**
 * `branch`'s line from its qualifying plans and the overrides. The branch's own override entry, when there is
 * one, replaces the union of the plans' refs and loses its hidden refs; the plan refs never hide (D4) and plan
 * links are never overridden. Every other branch's override follows as a segment, within the cap. Null when the
 * line would be empty.
 */
export const buildLine = (
  branch: string, qualifying: readonly PlanInfo[], overrides: Overrides, view: LineView = SHOW_ALL,
): WorkingLine | null => {
  const sorted = [...qualifying].sort((a, b) => a.id.localeCompare(b.id))
  const plans: PlanLink[] = sorted.map(p => ({ id: p.id, page: p.page }))
  const own = overrides.get(branch)
  const refs: Refs = own !== undefined ? visibleRefs(own.refs, view.retired, view.isClosed) : {
    todoIds: union(sorted.map(p => p.refs.todoIds)),
    issues: union(sorted.map(p => p.refs.issues)),
  }
  const head = joinParts(plansPart(plans, p => p.id), formatRefs(refs))
  const all = otherSegments(branch, overrides, view)
  const k = fitCount(head, all, view.maxChars)
  const others = all.slice(0, k)
  const more = all.length - k
  const text = compose(head, others.map(s => segmentText(s)), more)
  if (text === '') return null
  return { branch, plans, todoIds: [...refs.todoIds], issues: [...refs.issues], head, others, more, text }
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

/**
 * The ccstatusline line: the plain line with each plan number an OSC 8 link to its page and each other branch
 * name dark; '' for no line.
 */
export const statusText = (line: WorkingLine | null): string => {
  if (line === null) return ''
  const refs = formatRefs({ todoIds: line.todoIds, issues: line.issues })
  const head = joinParts(plansPart(line.plans, p => osc8(fileUrl(p.page), p.id)), refs)
  const segments = line.others.map(s => segmentText(s, b => `${DARK}${b}${RESET_FG}`))
  return compose(head, segments, line.more)
}
