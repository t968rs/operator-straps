import type { OtherSegment, PlanLink, Refs, TodoLabel, WorkingLine } from '../types'
import { visibleRefs } from './hide'
import type { Overrides } from './overrides'
import type { PlanInfo } from './plans'

/**
 * The working line of a branch: the qualifying plans' links first, then the own refs (plan 2025 spec Section 2),
 * then every other branch's override as `[ <branch> <refs> ]`, most recently set first, capped at
 * `working_refs.max_chars` with ` +N` for the segments left out (plan 2027). Each TODO id is labelled with its
 * catalog keyword, `todo-x7ty stop_gates` (plan 2028 D1). The plain form goes to the `line` atom for band-line;
 * the ccstatusline form, with each plan number an OSC 8 link to its page (D8), each TODO label in its own color
 * and each other branch name dark, goes to the line files. Pure: no `$`.
 */

const SEP = ' · '
/** ANSI 256-color 240 and the default-foreground reset around another branch's name (ccstatusline form). */
export const DARK = '\x1b[38;5;240m'
export const RESET_FG = '\x1b[39m'
/** The ANSI 256 colors a TODO label is drawn in (plan 2028 V5); never 240, which is DARK. */
export const TODO_PALETTE: readonly number[] = [39, 170, 36, 214, 141, 72, 203, 178]

/** What hides on the line, how each TODO id is labelled and how long the line may grow. */
export type LineView = {
  retired: ReadonlySet<string>
  isClosed: (n: number) => boolean
  /** Each catalog item's keyword by TODO id (plan 2028). */
  keywords: ReadonlyMap<string, string>
  maxChars: number
}

const NO_KEYWORDS: ReadonlyMap<string, string> = new Map()

/** A view that hides nothing and labels nothing, uncapped. */
export const SHOW_ALL: LineView = {
  retired: new Set(), isClosed: () => false, keywords: NO_KEYWORDS, maxChars: Number.MAX_SAFE_INTEGER,
}

const union = <T>(lists: readonly (readonly T[])[]): T[] => [...new Set(lists.flat())]

/** FNV-1a 32-bit over the string's UTF-16 code units (a canonical TODO id is ASCII, so its bytes). */
export const fnv1a32 = (text: string): number => {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) hash = Math.imul(hash ^ text.charCodeAt(i), 0x01000193) >>> 0
  return hash
}

/** The ANSI 256 color of a TODO id's label: FNV-1a 32-bit of the id modulo the palette length (plan 2028 V6). */
export const todoColor = (id: string): number => TODO_PALETTE[fnv1a32(id) % TODO_PALETTE.length] as number

/** Each id with its keyword from `keywords`, null when it has none. */
export const labelsOf = (ids: readonly string[], keywords: ReadonlyMap<string, string>): TodoLabel[] =>
  ids.map(id => ({ id, keyword: keywords.get(id) ?? null }))

/** `todo-x7ty stop_gates`, or the id alone when it has no keyword. */
export const labelText = (label: TodoLabel): string => (label.keyword === null ? label.id : `${label.id} ${label.keyword}`)

/** A label in its TODO's color, for the ccstatusline form. */
const coloredLabel = (label: TodoLabel): string => `\x1b[38;5;${todoColor(label.id)}m${labelText(label)}${RESET_FG}`

/** Labels, then issues in parentheses; labels alone; issues alone `#301, #315`; each label through `paint`. */
const drawRefs = (
  labels: readonly TodoLabel[], issues: readonly number[], paint: (l: TodoLabel) => string = labelText,
): string => {
  if (labels.length === 0) return issues.map(n => `#${n}`).join(', ')
  const ids = labels.map(paint).join(', ')
  return issues.length > 0 ? `${ids} (${issues.join(', ')})` : ids
}

/**
 * The refs as the line draws them, each id labelled with its keyword: `todo-k69m banner (301, 315)`; an id
 * without a keyword alone `todo-k69m`; issues alone `#301, #315`. The `/harness:working` reply
 * (`harness_lib.working_refs.format_refs`) stays unlabelled.
 */
export const formatRefs = (refs: Refs, keywords: ReadonlyMap<string, string> = NO_KEYWORDS): string =>
  drawRefs(labelsOf(refs.todoIds, keywords), refs.issues)

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

/** `[ <branch> <refs> ]`, plain: the segment's formatted refs. */
const segmentText = (s: OtherSegment): string => `[ ${s.branch} ${s.refs} ]`

/** `[ <branch> <refs> ]` in the ccstatusline form: the branch name dark, each TODO label in its color. */
const segmentStatus = (s: OtherSegment): string =>
  `[ ${DARK}${s.branch}${RESET_FG} ${drawRefs(s.labels, s.issues, coloredLabel)} ]`

/** One other branch's segment from its visible refs. */
const segmentOf = (branch: string, refs: Refs, keywords: ReadonlyMap<string, string>): OtherSegment => {
  const labels = labelsOf(refs.todoIds, keywords)
  return { branch, refs: drawRefs(labels, refs.issues), labels, issues: [...refs.issues] }
}

/** Every other branch's visible override, empty ones dropped, by `set_at` descending, then branch name. */
const otherSegments = (branch: string, overrides: Overrides, view: LineView): OtherSegment[] =>
  [...overrides]
    .filter(([b]) => b !== branch)
    .map(([b, o]) => ({
      setAt: o.setAt, s: segmentOf(b, visibleRefs(o.refs, view.retired, view.isClosed), view.keywords),
    }))
    .filter(x => x.s.refs !== '')
    .sort((a, b) => (a.setAt === b.setAt ? a.s.branch.localeCompare(b.s.branch) : a.setAt < b.setAt ? 1 : -1))
    .map(x => x.s)

/**
 * How many leading segments fit: each is added while the plain line with the ` +N` it would still need stays
 * within `maxChars`; the head is never cut, and with an empty head the first segment is always drawn.
 */
const fitCount = (head: string, all: readonly OtherSegment[], maxChars: number): number => {
  const plain = all.map(segmentText)
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
  const labels = labelsOf(refs.todoIds, view.keywords)
  const refsText = drawRefs(labels, refs.issues)
  const head = joinParts(plansPart(plans, p => p.id), refsText)
  const all = otherSegments(branch, overrides, view)
  const k = fitCount(head, all, view.maxChars)
  const others = all.slice(0, k)
  const more = all.length - k
  const text = compose(head, others.map(segmentText), more)
  if (text === '') return null
  return {
    branch, plans, todoIds: [...refs.todoIds], issues: [...refs.issues], labels, refs: refsText, head, others, more,
    text,
  }
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
 * The ccstatusline line: the plain line with each plan number an OSC 8 link to its page, each TODO label in its
 * color (`todoColor`) and each other branch name dark, drawn from the line's labels and issues; '' for no line.
 */
export const statusText = (line: WorkingLine | null): string => {
  if (line === null) return ''
  const refs = drawRefs(line.labels, line.issues, coloredLabel)
  const head = joinParts(plansPart(line.plans, p => osc8(fileUrl(p.page), p.id)), refs)
  return compose(head, line.others.map(segmentStatus), line.more)
}
