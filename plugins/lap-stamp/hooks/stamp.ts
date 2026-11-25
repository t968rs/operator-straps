import type { LapRow } from '../types'
import { fingerprintOf } from './fingerprint'

/**
 * Stamp text and matching for lap-stamp. Pure: no host access, no clock reads, no file I/O. The render glue
 * hands in the session's rows from memory and draws what these functions return. A stamp shows the row's own
 * stored values, never recomputed ones.
 */

/** Largest gap in ms between a TurnDuration line's `durationMs` and a row's `stop_at - start_at` that still matches. */
export const DURATION_TOLERANCE_MS = 2000

const SEP = ' · '
const BAR = ' | '
/** What ends every wrapped row but the last. */
const TRAIL = ' |'
const NO_CLOCK = '--:--:--'
const LIST_PREFIX = 'identical replies: '

const pad2 = (n: number): string => String(n).padStart(2, '0')

/** `Ns` under a minute, `Mm Ss` under an hour, `Hh Mm` above; whole seconds floored, a bad value reads as zero. */
export function formatDuration(ms: number): string {
  const total = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  if (total < 3600) return `${minutes}m ${total % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

/** The local `HH:MM:SS` of an ISO 8601 instant; a placeholder when it does not parse. */
export function clockOf(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return NO_CLOCK
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/** The lap part of a stamp: `<dur>` after `lap`, plus `since prompt <dur>` on a wake row that has one. */
function lapPart(row: LapRow): string {
  const lap = `lap ${formatDuration(row.lap_ms)}`
  if (row.kind !== 'wake' || row.since_prompt_ms === null) return lap
  return `${lap}${SEP}since prompt ${formatDuration(row.since_prompt_ms)}`
}

/** One row's stamp: `HH:MM:SS · lap <dur>`, plus ` · since prompt <dur>` on a wake row with one. */
export function stampText(row: LapRow): string {
  return `${clockOf(row.stop_at)}${SEP}${lapPart(row)}`
}

/** One candidate of an identical-replies list: `<HH:MM:SS> lap <dur>[ · since prompt <dur>]`. */
function candidateText(row: LapRow): string {
  return `${clockOf(row.stop_at)} ${lapPart(row)}`
}

/**
 * The rows whose answer fingerprint equals the block's, in file order. A block with no text after
 * normalization matches nothing, and a row with an empty answer (null hash) is never a candidate.
 */
export function rowsForBlock(rows: readonly LapRow[], text: string): LapRow[] {
  const fp = fingerprintOf(text)
  if (fp === null) return []
  return rows.filter(r => r.answer_hash === fp.hash && r.answer_len === fp.len)
}

/**
 * The stamp for the rows matching one block: null for none, the row's own stamp for one, and for several
 * identical replies one list of every candidate in file order.
 */
export function blockStamp(rows: readonly LapRow[]): string | null {
  const [first] = rows
  if (first === undefined) return null
  if (rows.length === 1) return stampText(first)
  return `${LIST_PREFIX}${rows.map(candidateText).join(BAR)}`
}

/** `stop_at - start_at` of a row in ms; NaN when either time does not parse. */
function spanOf(row: LapRow): number {
  return Date.parse(row.stop_at) - Date.parse(row.start_at)
}

/**
 * The row a TurnDuration line belongs to: the one whose span is within the tolerance of `durationMs`, when it is
 * the only such row of the session and its answer is empty; else null. The duration is a match key only.
 */
export function durationRow(rows: readonly LapRow[], durationMs: number): LapRow | null {
  const near = rows.filter(r => Math.abs(spanOf(r) - durationMs) <= DURATION_TOLERANCE_MS)
  const [only] = near
  if (near.length !== 1 || only === undefined) return null
  return only.answer_hash === null ? only : null
}

/** One wrappable piece of a stamp: its text and the joiner placed before it when it shares a row with the last. */
type Piece = { text: string; join: string }

/** Splits a stamp into the list prefix (when present) and its bar-separated candidates. */
function piecesOf(text: string): Piece[] {
  const [head = '', ...rest] = text.split(BAR)
  const pieces: Piece[] = []
  if (head.startsWith(LIST_PREFIX)) {
    pieces.push({ text: LIST_PREFIX.trimEnd(), join: '' })
    pieces.push({ text: head.slice(LIST_PREFIX.length), join: ' ' })
  } else {
    pieces.push({ text: head, join: '' })
  }
  return pieces.concat(rest.map(r => ({ text: r, join: BAR })))
}

/** The bar a row ends in when `next` (a candidate) starts the following row; none at the end or after the prefix. */
const trailBefore = (next: Piece | undefined): string => (next !== undefined && next.join === BAR ? TRAIL : '')

/** Greedy packing of the pieces into rows; every row that a candidate follows ends in a bar, and fits with it. */
function packRows(pieces: readonly Piece[], width: number): string[] {
  const rows: string[] = []
  let line = ''
  pieces.forEach((piece, i) => {
    if (line === '') {
      line = piece.text
      return
    }
    const joined = `${line}${piece.join}${piece.text}`
    if (joined.length + trailBefore(pieces[i + 1]).length <= width) {
      line = joined
      return
    }
    rows.push(`${line}${trailBefore(piece)}`)
    line = piece.text
  })
  rows.push(line)
  return rows
}

/**
 * Right-aligns a stamp to `width`. A stamp wider than the width splits into further right-aligned rows: the list
 * prefix and the candidates are separate pieces, and every row a candidate follows ends in a bar and fits with
 * it. No candidate is dropped; a piece wider than the width less its bar stays whole and overflows. A width that
 * is not a positive finite number returns the text as is.
 */
export function wrapRight(text: string, width: number): string[] {
  if (!Number.isFinite(width) || width <= 0) return [text]
  const rows = text.length <= width ? [text] : packRows(piecesOf(text), width)
  return rows.map(r => r.padStart(width))
}
