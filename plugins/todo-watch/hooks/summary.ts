/**
 * Pure text work for todo-watch: the TODO catalog's counts and top-N, the summary toast, the TODO_SYNC
 * context line, the drift toasts and the `/todo` body. No `$`.
 */

import type { SyncFinding, SyncReport, TodoRow, TodoSummary } from '../types'

type Json = Readonly<Record<string, unknown>>

const SEP = ' · '
const HOUR_MS = 3_600_000
const MAX_TOAST = 160
export const UNAVAILABLE_CONTEXT = 'TODO_SYNC unavailable'
export const CLEAN_TOAST = 'TODO sync clean'
export const NO_REPORT_TEXT = 'no report yet'
export const UNAVAILABLE_TEXT = 'sync checks unavailable'
export const CLEAN_TEXT = 'sync clean'

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

/** `TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: TODO-001`, then the sync parts. */
export const formatSummary = (s: TodoSummary, sync: SyncSuffix = {}): string => {
  const top = s.top[0]
  const parts = [`TODO ${s.items}`, ...countSegments(s), ...(top === undefined ? [] : [`top: ${top.id}`])]
  return [...parts, ...syncSegments(sync)].join(SEP)
}

// ---------------------------------------------------------------------------
// Drift lines

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

/** A drift toast owed by a new report, and the drift it records as toasted; undefined when none is owed. */
export type DriftToast = { text: string; toasted: number }

/**
 * Toast only when drift rises above the last toasted drift (`TODO sync drift 4 (+2): P1=1 ...`), plus once
 * when it reaches zero from a non-zero previous report (`TODO sync clean`).
 */
export const driftToast = (
  r: Pick<SyncReport, 'drift' | 'byRule'>,
  lastToasted: number | null,
  previous: number | null,
): DriftToast | undefined => {
  const base = lastToasted ?? 0
  if (r.drift > base) {
    const rules = ruleCounts(r.byRule)
    const head = `TODO sync drift ${r.drift} (+${r.drift - base})`
    return { text: clip(rules === '' ? head : `${head}: ${rules}`, MAX_TOAST), toasted: r.drift }
  }
  if (r.drift === 0 && previous !== null && previous > 0) return { text: CLEAN_TOAST, toasted: 0 }
  return undefined
}

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

/** The whole `/todo` body: summary line, top-N table, sync section. */
export const formatTodoBody = (
  summary: TodoSummary | null,
  report: SyncReport | null,
  status: SyncStatus,
  sync: SyncSuffix,
): string => {
  const head = summary === null ? 'TODO catalog unreadable' : formatSummary(summary, sync)
  const table = summary === null ? '' : formatTable(summary.top)
  return [head, table, formatSyncSection(report, status)].filter(part => part !== '').join('\n\n')
}
