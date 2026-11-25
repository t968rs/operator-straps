/**
 * Pure text work for todo-watch: the TODO catalog's counts and top-N, the notice view, the summary line, the
 * TODO_SYNC context line and the `/todo` body. No `$`.
 */

import type { NoticeView, SyncFinding, SyncReport, TodoRow, TodoSummary } from '../types'

type Json = Readonly<Record<string, unknown>>

const SEP = ' · '
const HOUR_MS = 3_600_000
const MAX_TOP_TITLE = 60
export const UNAVAILABLE_CONTEXT = 'TODO_SYNC unavailable'
export const NO_REPORT_TEXT = 'no report yet'
export const UNAVAILABLE_TEXT = 'sync checks unavailable'
export const CLEAN_TEXT = 'sync clean'
export const IN_SYNC_TEXT = '✓ in sync'
/** The notice's item titles are folded to one line and clipped to this many characters. */
export const MAX_NOTICE_TITLE = 80
/** Joins the toast's lines: the item lines, then the status. */
export const NOTICE_TOAST_SEP = '\n'

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)
const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0
const countAt = (o: Json, key: string): number => (isCount(o[key]) ? (o[key] as number) : 0)

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

// ---------------------------------------------------------------------------
// Catalog

/** One item as a row; undefined when its id, rank, title or status is missing. */
const rowOf = (item: unknown): TodoRow | undefined => {
  if (!isObject(item)) return undefined
  const { id, rank, title, status } = item
  if (typeof id !== 'string' || typeof rank !== 'number' || typeof title !== 'string') return undefined
  if (typeof status !== 'string') return undefined
  const score = isObject(item.priority) ? item.priority.score : undefined
  const isScore = typeof score === 'number' && Number.isFinite(score)
  return { id, rank, title, status, score: isScore ? score : null }
}

/** Items ordered by rank, at most `topN`. */
const topRows = (items: readonly unknown[], topN: number): TodoRow[] =>
  items
    .map(rowOf)
    .filter((r): r is TodoRow => r !== undefined)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, topN)

/**
 * The summary of a TODO catalog text (TodoCatalog shape: `counts.items`, `counts.by_status`,
 * `counts.needs_decision`, `items[]`); undefined when malformed.
 */
export const parseCatalog = (text: string, topN: number, mtimeMs: number): TodoSummary | undefined => {
  const data = parseJson(text)
  if (!isObject(data) || !isObject(data.counts) || !Array.isArray(data.items)) return undefined
  const counts = data.counts
  if (!isCount(counts.items)) return undefined
  const byStatus = isObject(counts.by_status) ? counts.by_status : {}
  return {
    items: counts.items,
    open: countAt(byStatus, 'OPEN'),
    partial: countAt(byStatus, 'PARTIAL'),
    blocked: countAt(byStatus, 'BLOCKED'),
    needsDecision: countAt(counts, 'needs_decision'),
    top: topRows(data.items, topN),
    mtimeMs,
  }
}

// ---------------------------------------------------------------------------
// Summary line

/** What the summary line says about sync: a fresh report's drift and the issue cache's age. */
export type SyncSuffix = { drift?: number; ghAge?: string }

/** `3d` or `8h` when `fetchedAt` is older than `maxAgeHours`; undefined when fresh, null or unparsable. */
export const ghAgeText = (
  fetchedAt: string | null,
  nowMs: number,
  maxAgeHours: number,
): string | undefined => {
  if (fetchedAt === null) return undefined
  const at = Date.parse(fetchedAt)
  if (!Number.isFinite(at)) return undefined
  const hours = (nowMs - at) / HOUR_MS
  if (hours <= maxAgeHours) return undefined
  return hours < 24 ? `${Math.floor(hours)}h` : `${Math.floor(hours / 24)}d`
}

const countSegments = (s: TodoSummary): string[] => {
  const parts: Array<[number, string]> = [
    [s.open, 'open'], [s.partial, 'partial'], [s.blocked, 'blocked'], [s.needsDecision, 'need a decision'],
  ]
  return parts.filter(([n]) => n > 0).map(([n, label]) => `${n} ${label}`)
}

const syncSegments = (sync: SyncSuffix): string[] => {
  const out: string[] = []
  if (sync.drift !== undefined) out.push(sync.drift === 0 ? CLEAN_TEXT : `${sync.drift} out of sync`)
  if (sync.ghAge !== undefined) out.push(`gh ${sync.ghAge} old`)
  return out
}

/** The rank-1 title on one line, clipped so the sync parts after it stay visible. */
const topTitle = (title: string): string => clip(title.replace(/\s+/g, ' ').trim(), MAX_TOP_TITLE)

/** `TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: <title>`, then the sync parts. */
export const formatSummary = (s: TodoSummary, sync: SyncSuffix = {}): string => {
  const top = s.top[0]
  const parts = [`TODO ${s.items}`, ...countSegments(s), ...(top === undefined ? [] : [`top: ${topTitle(top.title)}`])]
  return [...parts, ...syncSegments(sync)].join(SEP)
}

// ---------------------------------------------------------------------------
// The notice

/** `<rank>  <title>`, the title folded to one line and clipped to `MAX_NOTICE_TITLE`. */
const itemLine = (r: TodoRow): string => `${r.rank}  ${clip(r.title.replace(/\s+/g, ' ').trim(), MAX_NOTICE_TITLE)}`

/**
 * The status line: a fresh report wins (`✓ in sync` or `<N> out of sync`); without one, `sync checks
 * unavailable` once checks are known to be unavailable, else none.
 */
const noticeStatus = (report: Pick<SyncReport, 'drift'> | null, status: SyncStatus): NoticeView['status'] => {
  if (report === null) return status === 'unavailable' ? { text: UNAVAILABLE_TEXT, tone: 'dim' } : null
  if (report.drift === 0) return { text: IN_SYNC_TEXT, tone: 'ok' }
  return { text: `${report.drift} out of sync`, tone: 'warn' }
}

/** The notice: the first `count` summary rows by rank, then the sync status. */
export const formatNotice = (
  summary: TodoSummary | null,
  report: Pick<SyncReport, 'drift'> | null,
  status: SyncStatus,
  count: number,
): NoticeView => ({
  items: summary === null ? [] : summary.top.slice(0, count).map(itemLine),
  status: noticeStatus(report, status),
})

/** The toast text: the item lines, then the status text, joined by `NOTICE_TOAST_SEP`; never clipped whole. */
export const noticeText = (view: NoticeView): string =>
  [...view.items, ...(view.status === null ? [] : [view.status.text])].join(NOTICE_TOAST_SEP)

/** Whether the view has nothing to show: no item lines and no status. */
export const isEmptyView = (view: NoticeView): boolean => view.items.length === 0 && view.status === null

// ---------------------------------------------------------------------------
// The context line

/** Rule id order: the letter, then the number (`G2`, `P1`, `S5`, `S10`, `T2`). */
const byRuleId = (a: string, b: string): number => {
  const letters = a.replace(/\d+$/, '').localeCompare(b.replace(/\d+$/, ''))
  return letters !== 0 ? letters : Number(a.replace(/^\D+/, '')) - Number(b.replace(/^\D+/, ''))
}

/** `P1=1 S5=1 T2=1`, rules sorted by id. */
export const ruleCounts = (byRule: Readonly<Record<string, number>>): string =>
  Object.keys(byRule)
    .sort(byRuleId)
    .map(rule => `${rule}=${byRule[rule]}`)
    .join(' ')

/** The prompt context line: `TODO_SYNC drift=4 P1=1 S5=1 T2=1`. */
export const formatContextLine = (r: Pick<SyncReport, 'drift' | 'byRule'>): string => {
  const rules = ruleCounts(r.byRule)
  return rules === '' ? `TODO_SYNC drift=${r.drift}` : `TODO_SYNC drift=${r.drift} ${rules}`
}

/**
 * The line a prompt should carry: a fresh report's drift, `TODO_SYNC unavailable` once checks are known to
 * be unavailable, else none (before any fresh report, and while the runner lookup is pending).
 */
export const contextLineFor = (report: SyncReport | null, status: SyncStatus): string | undefined => {
  if (report !== null) return formatContextLine(report)
  return status === 'unavailable' ? UNAVAILABLE_CONTEXT : undefined
}

const clip = (text: string, max: number): string => (text.length <= max ? text : `${text.slice(0, max - 1)}…`)

// ---------------------------------------------------------------------------
// The /todo body

const cell = (text: string): string => text.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')
const scoreText = (score: number | null): string => (score === null ? '-' : String(Math.round(score * 100) / 100))

/** The top-N rows as a Markdown table; empty when there are none. */
export const formatTable = (rows: readonly TodoRow[]): string => {
  if (rows.length === 0) return ''
  const head = ['| Rank | Id | Status | Score | Title |', '|---:|---|---|---:|---|']
  const body = rows.map(r => `| ${r.rank} | ${r.id} | ${r.status} | ${scoreText(r.score)} | ${cell(r.title)} |`)
  return [...head, ...body].join('\n')
}

/** `rule severity file:line subject: message (fix)`, null parts left out. */
export const formatFinding = (f: SyncFinding): string => {
  const where = f.file === null ? '' : f.line === null ? ` ${f.file}` : ` ${f.file}:${f.line}`
  const subject = f.subject === null ? '' : ` ${f.subject}`
  const fix = f.fix === null ? '' : ` (${f.fix})`
  return `${f.rule} ${f.severity}${where}${subject}: ${f.message}${fix}`
}

/** Whether sync checks have a runner: still looking, found, or not after the retry. */
export type SyncStatus = 'pending' | 'found' | 'unavailable'

/** The sync part of `/todo`: the findings, `sync clean`, `sync checks unavailable` or `no report yet`. */
export const formatSyncSection = (report: SyncReport | null, status: SyncStatus): string => {
  if (report === null) return status === 'unavailable' ? UNAVAILABLE_TEXT : NO_REPORT_TEXT
  const head = report.drift === 0 ? CLEAN_TEXT : `sync drift ${report.drift}: ${ruleCounts(report.byRule)}`
  return [head, ...report.findings.map(formatFinding)].join('\n')
}

/**
 * The whole `/todo` body: summary line, the table of the first `topN` rows (every parsed row when not given),
 * sync section.
 */
export const formatTodoBody = (
  summary: TodoSummary | null,
  report: SyncReport | null,
  status: SyncStatus,
  sync: SyncSuffix,
  topN?: number,
): string => {
  const head = summary === null ? 'TODO catalog unreadable' : formatSummary(summary, sync)
  const table = summary === null ? '' : formatTable(summary.top.slice(0, topN))
  return [head, table, formatSyncSection(report, status)].filter(part => part !== '').join('\n\n')
}
