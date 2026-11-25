import type { OtherSegment, PlanLink, Refs, TodoLabel, WorkingLine } from '../types'
import { visibleRefs } from './hide'
import type { Overrides } from './overrides'
import type { PlanInfo } from './plans'
import { planColor, type Progress, progressOf } from './progress'

/**
 * The working line of a branch: the qualifying plans' links first, then the own refs (plan 2025 spec Section 2),
 * then every other branch's override as `[ <branch> <refs> ]`, most recently set first, capped at
 * `working_refs.max_chars` with ` +N` for the segments left out (plan 2027). Each TODO id is labelled with its
 * catalog keyword, `todo-x7ty stop_gates` (plan 2028 D1). The plain form goes to the `line` atom for band-line;
 * the ccstatusline form goes to the line files: each plan number an OSC 8 link to its page (D8) in its progress
 * color, each TODO label in its own color, each issue number and other branch name in theirs, and the
 * punctuation dark (plan 2030). Pure: no `$`.
 */

const SEP = ' · '
/** ANSI 256-color 240: the punctuation of the ccstatusline form (plan 2030 V5). */
export const DARK = '\x1b[38;5;240m'
/** The default-foreground reset after each colored piece. */
export const RESET_FG = '\x1b[39m'
/** ANSI 256-color 246: another branch's name (plan 2030 V4). */
export const BRANCH_FG = '\x1b[38;5;246m'
/** ANSI 256-color 180: an issue number (plan 2030 V3). */
export const ISSUE_FG = '\x1b[38;5;180m'
/** The ANSI 256 colors a TODO label is drawn in (plan 2028 V5); never 240, which is DARK. */
export const TODO_PALETTE: readonly number[] = [39, 170, 36, 214, 141, 72, 203, 178]

/** What hides on the line, how each TODO id is labelled, how far each plan is and how long the line may grow. */
export type LineView = {
  retired: ReadonlySet<string>
  isClosed: (n: number) => boolean
  /** Each catalog item's keyword by TODO id (plan 2028). */
  keywords: ReadonlyMap<string, string>
  /** Each plan's done share by plan id (plan 2030); a plan missing here counts its items' statuses. */
  progress: ReadonlyMap<string, Progress>
  maxChars: number
}

const NO_KEYWORDS: ReadonlyMap<string, string> = new Map()
const NO_KINDS: ReadonlyMap<string, string | null> = new Map()
const NO_PROGRESS: ReadonlyMap<string, Progress> = new Map()

/** A view that hides nothing, labels nothing and reads no receipts, uncapped. */
export const SHOW_ALL: LineView = {
  retired: new Set(), isClosed: () => false, keywords: NO_KEYWORDS, progress: NO_PROGRESS,
  maxChars: Number.MAX_SAFE_INTEGER,
}

/** The SGR escape of an ANSI 256 foreground color. */
const fgOf = (color: number): string => `\x1b[38;5;${color}m`

/** `text` in the foreground `fg`, then the default foreground, so the color never bleeds into the next piece. */
const ink = (fg: string) => (text: string): string => `${fg}${text}${RESET_FG}`

/**
 * How each kind of piece is drawn: the plain form passes text through, the ccstatusline form colors it. `plan`
 * draws one plan number, `label` one TODO label, `issue` one issue number (`#301` or `301`), `branch` another
 * branch's name and `punct` the plan word, separators, commas, brackets, parentheses and `+N`. An issue's `#`
 * is drawn with its number, not as punctuation.
 */
type Pen = {
  plan: (p: PlanLink) => string
  label: (l: TodoLabel) => string
  issue: (text: string) => string
  branch: (text: string) => string
  punct: (text: string) => string
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
export const labelText = (label: TodoLabel): string =>
  label.keyword === null ? label.id : `${label.id} ${label.keyword}`

/** A label in its TODO's color, for the ccstatusline form. */
const coloredLabel = (label: TodoLabel): string => ink(fgOf(todoColor(label.id)))(labelText(label))

/** The text unchanged: the plain form's ink. */
const same = (text: string): string => text

/** The plain form's pen: every piece as it is. */
const PLAIN: Pen = { plan: p => p.id, label: labelText, issue: same, branch: same, punct: same }

/** Labels, then issues in parentheses; labels alone; issues alone `#301, #315`; each piece through `pen`. */
const drawRefs = (labels: readonly TodoLabel[], issues: readonly number[], pen: Pen = PLAIN): string => {
  const comma = pen.punct(', ')
  if (labels.length === 0) return issues.map(n => pen.issue(`#${n}`)).join(comma)
  const ids = labels.map(pen.label).join(comma)
  if (issues.length === 0) return ids
  return `${ids} ${pen.punct('(')}${issues.map(n => pen.issue(String(n))).join(comma)}${pen.punct(')')}`
}

/**
 * The plain refs text of the line's head and of each other branch's segment (`buildLine`, `segmentOf`), each id
 * labelled with its keyword: `todo-k69m banner (301, 315)`; an id without a keyword alone `todo-k69m`; issues
 * alone `#301, #315`. The `/harness:working` reply (`harness_lib.working_refs.format_refs`) stays unlabelled.
 */
export const formatRefs = (refs: Refs, keywords: ReadonlyMap<string, string> = NO_KEYWORDS): string =>
  drawRefs(labelsOf(refs.todoIds, keywords), refs.issues)

/** `plan 2025` or `plans 2024, 2025`, each piece through `pen`; '' for no plans. */
const plansPart = (plans: readonly PlanLink[], pen: Pen): string => {
  if (plans.length === 0) return ''
  return `${pen.punct(plans.length === 1 ? 'plan' : 'plans')} ${plans.map(pen.plan).join(pen.punct(', '))}`
}

const joinParts = (pen: Pen, ...parts: string[]): string => parts.filter(p => p !== '').join(pen.punct(SEP))

/**
 * The whole line from its drawn pieces: the head, ` · ` and the segments joined by a space, then ` +N`
 * (`head +N` when no segment is drawn); the separators and `+N` through `pen`.
 */
const compose = (head: string, segments: readonly string[], more: number, pen: Pen = PLAIN): string => {
  const body = joinParts(pen, head, segments.join(' '))
  return more > 0 ? `${body}${body === '' ? '' : ' '}${pen.punct(`+${more}`)}` : body
}

/** `[ <branch> <refs> ]`, plain: the segment's formatted refs. */
const segmentText = (s: OtherSegment): string => `[ ${s.branch} ${s.refs} ]`

/** One other branch's segment from its visible refs. */
const segmentOf = (branch: string, refs: Refs, keywords: ReadonlyMap<string, string>): OtherSegment => {
  const labels = labelsOf(refs.todoIds, keywords)
  return { branch, refs: formatRefs(refs, keywords), labels, issues: [...refs.issues] }
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
 * within `maxChars`; the head is never cut, and with an empty head the first segment is always drawn. The count
 * stops at the first segment that overflows: a later, shorter segment never takes its place.
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

/** A plan's link with its done share: from `progress`, else counted from its items' statuses alone. */
const linkOf = (p: PlanInfo, progress: ReadonlyMap<string, Progress>): PlanLink => {
  const { done, total } = progress.get(p.id) ?? progressOf(p.items, NO_KINDS)
  return { id: p.id, page: p.page, done, total }
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
  const plans: PlanLink[] = sorted.map(p => linkOf(p, view.progress))
  const own = overrides.get(branch)
  const refs: Refs = own !== undefined ? visibleRefs(own.refs, view.retired, view.isClosed) : {
    todoIds: union(sorted.map(p => p.refs.todoIds)),
    issues: union(sorted.map(p => p.refs.issues)),
  }
  const labels = labelsOf(refs.todoIds, view.keywords)
  const refsText = formatRefs(refs, view.keywords)
  const head = joinParts(PLAIN, plansPart(plans, PLAIN), refsText)
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
 * The ccstatusline form's pen (plan 2030): each plan number in its progress color (`planColor`) inside its OSC 8
 * link, each TODO label in `todoColor`, issue numbers in ISSUE_FG, other branch names in BRANCH_FG and the
 * punctuation in DARK.
 */
const STATUS: Pen = {
  plan: p => osc8(fileUrl(p.page), ink(fgOf(planColor(p)))(p.id)),
  label: coloredLabel,
  issue: ink(ISSUE_FG),
  branch: ink(BRANCH_FG),
  punct: ink(DARK),
}

/** `[ <branch> <refs> ]` in the ccstatusline form, each piece through STATUS. */
const segmentStatus = (s: OtherSegment): string =>
  `${STATUS.punct('[ ')}${STATUS.branch(s.branch)} ${drawRefs(s.labels, s.issues, STATUS)}${STATUS.punct(' ]')}`

/**
 * The ccstatusline line: the plain line drawn from the line's plans, labels, issues and segments with each piece
 * in its color (STATUS); stripped of its escapes it is the plain line. '' for no line.
 */
export const statusText = (line: WorkingLine | null): string => {
  if (line === null) return ''
  const refs = drawRefs(line.labels, line.issues, STATUS)
  const head = joinParts(STATUS, plansPart(line.plans, STATUS), refs)
  return compose(head, line.others.map(segmentStatus), line.more, STATUS)
}
