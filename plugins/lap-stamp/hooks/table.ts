import type { LapRow } from '../types'
import { clockOf, formatDuration } from './stamp'

/**
 * The `/lap-times` table: the laps rows as a markdown table whose cells are padded to their column's width, so
 * it lines up as plain text in the terminal and still renders as a table. Every table line fits the terminal
 * width: columns are dropped least useful first, and the stop time and the lap are never dropped. Pure.
 */

/** What `/lap-times` shows: this session or every session, and how many of the newest rows. */
export type LapArgs = { isAllSessions: boolean; limit: number }
export type TableOptions = LapArgs & { columns: number }

/** One column: its header, how a row fills it (`n` is the row's 1-based place), alignment and drop rank. */
type Column = {
  header: string
  cell: (row: LapRow, n: number) => string
  isRight: boolean
  /** Dropped highest first when the table is too wide; 0 is never dropped. */
  dropRank: number
}

export const DEFAULT_LIMIT = 50
export const USAGE = 'usage: /lap-times [all] [N]  (this session by default; all: every session; N: newest N rows)'

const ELLIPSIS = '…'
const dateOf = (iso: string): string => /^\d{4}-(\d{2}-\d{2})T/.exec(iso)?.[1] ?? '--'
const durationOr = (ms: number | null): string => (ms === null ? '' : formatDuration(ms))

const NUMBER: Column = { header: '#', cell: (_r, n) => String(n), isRight: true, dropRank: 4 }
const SESSION: Column = { header: 'Session', cell: r => r.session.slice(0, 8), isRight: false, dropRank: 5 }
const DATE: Column = { header: 'Date', cell: r => dateOf(r.stop_at), isRight: false, dropRank: 3 }
const TAIL: readonly Column[] = [
  { header: 'Stop', cell: r => clockOf(r.stop_at), isRight: false, dropRank: 0 },
  { header: 'Kind', cell: r => r.kind, isRight: false, dropRank: 2 },
  { header: 'Lap', cell: r => formatDuration(r.lap_ms), isRight: true, dropRank: 0 },
  { header: 'Since prompt', cell: r => durationOr(r.since_prompt_ms), isRight: true, dropRank: 1 },
  { header: 'Wake', cell: r => r.wake ?? '', isRight: false, dropRank: 6 },
  { header: 'Stop reason', cell: r => r.reason, isRight: false, dropRank: 7 },
]

/** `/lap-times` arguments: optional `all` and an optional positive count, in any order; null for anything else. */
export function parseLapArgs(args: string): LapArgs | null {
  let isAllSessions = false
  let limit: number | null = null
  for (const word of args.trim().split(/\s+/).filter(w => w !== '')) {
    if (word.toLowerCase() === 'all' && !isAllSessions) isAllSessions = true
    else if (/^[1-9]\d*$/.test(word) && limit === null) limit = Number(word)
    else return null
  }
  return { isAllSessions, limit: limit ?? DEFAULT_LIMIT }
}

/** The width of a markdown table line whose cells have these widths: `| a | b |`. */
export const rowWidth = (widths: readonly number[]): number =>
  widths.reduce((sum, w) => sum + w + 3, 1)

/** A cell's text with its pipes escaped, so a value never splits a column. */
const escaped = (text: string): string => text.replace(/\|/g, '\\|')

/** One column filled: its spec, its cells top to bottom and its width (header included). */
type Filled = { col: Column; cells: string[]; width: number }

/** The column filled from the rows shown; `first` is the 0-based place of the first shown row. */
function filled(col: Column, rows: readonly LapRow[], first: number): Filled {
  const cells = rows.map((r, i) => escaped(col.cell(r, first + i + 1)))
  return { col, cells, width: Math.max(col.header.length, ...cells.map(c => c.length)) }
}

/** The columns that fit `columns`: dropped by rank, highest first, until the line fits or none can go. */
function fitColumns(all: readonly Filled[], columns: number): Filled[] {
  let kept = [...all]
  while (rowWidth(kept.map(f => f.width)) > columns) {
    const droppable = kept.filter(f => f.col.dropRank > 0)
    if (droppable.length === 0) break
    const drop = droppable.reduce((a, b) => (b.col.dropRank > a.col.dropRank ? b : a))
    kept = kept.filter(f => f !== drop)
  }
  return kept
}

/** The header, delimiter and body lines of the table, each cell padded to its column's width. */
function tableLines(cols: readonly Filled[], rowCount: number): string[] {
  const pad = (f: Filled, text: string): string => (f.col.isRight ? text.padStart(f.width) : text.padEnd(f.width))
  const line = (texts: readonly string[]): string => `| ${texts.join(' | ')} |`
  const delimiter = cols.map(f => (f.col.isRight ? `${'-'.repeat(f.width + 1)}:` : '-'.repeat(f.width + 2)))
  const body = Array.from({ length: rowCount }, (_u, r) => line(cols.map(f => pad(f, f.cells[r] ?? ''))))
  return [line(cols.map(f => pad(f, f.col.header))), `|${delimiter.join('|')}|`, ...body]
}

/** The summary above the table, cut to the width with an ellipsis. */
function summaryLine(rows: readonly LapRow[], shown: number, opts: TableOptions): string {
  const scope = opts.isAllSessions ? `all sessions (${new Set(rows.map(r => r.session)).size})` : 'this session'
  const total = rows.reduce((sum, r) => sum + r.lap_ms, 0)
  const longest = Math.max(...rows.map(r => r.lap_ms))
  const turns = `${rows.length} turn${rows.length === 1 ? '' : 's'}`
  const parts = ['lap-stamp', scope, turns, `lap total ${formatDuration(total)}`, `longest ${formatDuration(longest)}`]
  if (shown < rows.length) parts.push(`last ${shown} shown`)
  const text = parts.join(' · ')
  return opts.columns > 0 && text.length > opts.columns ? `${text.slice(0, opts.columns - 1)}${ELLIPSIS}` : text
}

/** The whole `/lap-times` answer: the summary line, a blank line, then the table of the newest `limit` rows. */
export function lapTimesText(rows: readonly LapRow[], opts: TableOptions): string {
  if (rows.length === 0) {
    return `lap-stamp · no turns recorded in ${opts.isAllSessions ? 'the laps file' : 'this session'} yet`
  }
  const first = Math.max(0, rows.length - opts.limit)
  const shown = rows.slice(first)
  const specs = opts.isAllSessions ? [NUMBER, SESSION, DATE, ...TAIL] : [NUMBER, ...TAIL]
  const kept = fitColumns(specs.map(col => filled(col, shown, first)), opts.columns)
  return [summaryLine(rows, shown.length, opts), '', ...tableLines(kept, shown.length)].join('\n')
}
