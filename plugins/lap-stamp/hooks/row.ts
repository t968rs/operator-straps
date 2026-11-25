/**
 * Row codec for `<state_dir>/lap-stamp/laps.jsonl`: build a row from one turn's timing, write it as one JSON line
 * and read a file's text back leniently. Pure: text and values in, text and values out, no file access. A row
 * carries no path and no prompt or answer text, only the answer's fingerprint.
 */

import { fingerprintOf } from './fingerprint'
import type { LapRow, StopReason, Timing } from '../types'

export const ROW_VERSION = 1

const REASONS: readonly string[] = ['answer', 'aborted', 'refusal', 'error']
const KINDS: readonly string[] = ['prompt', 'wake']
const ISO_LOCAL = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/

/**
 * What `buildRow` takes. `offsetMin` (minutes east of UTC) forces one offset on every stamp; absent, each instant
 * asks `offsetAt` for its own offset, which defaults to the host zone's lookup.
 */
export type RowInput = {
  session: string
  turn: string
  timing: Timing
  reason: StopReason
  answer: string
  offsetMin?: number
  offsetAt?: (ms: number) => number
}

const pad = (n: number, width = 2): string => String(n).padStart(width, '0')

/** ISO 8601 with milliseconds and a `+HH:MM` / `-HH:MM` offset. `offsetMin` is minutes east of UTC. */
export function isoLocal(ms: number, offsetMin: number): string {
  const d = new Date(ms + offsetMin * 60000)
  const date = `${pad(d.getUTCFullYear(), 4)}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
  const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}`
  const abs = Math.abs(offsetMin)
  const zone = `${offsetMin < 0 ? '-' : '+'}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
  return `${date}T${time}${zone}`
}

/** Minutes east of UTC from `Date.getTimezoneOffset`, which counts minutes west (never -0). */
export function eastOffsetMin(westMin: number): number {
  return -westMin || 0
}

/** The host zone's offset at an instant, in minutes east of UTC. */
function hostOffsetMin(ms: number): number {
  return eastOffsetMin(new Date(ms).getTimezoneOffset())
}

type OffsetAt = (ms: number) => number

/** The offset lookup for one row: a forced offset for every instant, else the per-instant lookup. */
function offsetLookup(forced: number | undefined, offsetAt: OffsetAt | undefined): OffsetAt {
  if (forced !== undefined) return () => forced
  return offsetAt ?? hostOffsetMin
}

function stampOf(ms: number, offsetAt: OffsetAt): string {
  return isoLocal(ms, offsetAt(ms))
}

function stampOrNull(ms: number | null, offsetAt: OffsetAt): string | null {
  return ms === null ? null : stampOf(ms, offsetAt)
}

/** One turn's row. The answer is fingerprinted and dropped; an empty normalized answer stores a null hash and length 0. */
export function buildRow(input: RowInput): LapRow {
  const { session, turn, timing, reason, answer } = input
  const at = offsetLookup(input.offsetMin, input.offsetAt)
  const fp = fingerprintOf(answer)
  return {
    v: ROW_VERSION,
    session,
    turn,
    kind: timing.kind,
    wake: timing.wake,
    prompt_at: stampOrNull(timing.promptAt, at),
    start_at: stampOf(timing.startAt, at),
    stop_at: stampOf(timing.stopAt, at),
    last_prompt_at: stampOrNull(timing.lastPromptAt, at),
    lap_ms: timing.lapMs,
    since_prompt_ms: timing.sincePromptMs,
    reason,
    answer_hash: fp === null ? null : fp.hash,
    answer_len: fp === null ? 0 : fp.len,
  }
}

/** The row as one JSON line, without a line ending. */
export function rowLine(row: LapRow): string {
  return JSON.stringify(row)
}

type Raw = Record<string, unknown>

const isStr = (v: unknown): v is string => typeof v === 'string'
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isNullOr = (v: unknown, test: (x: unknown) => boolean): boolean => v === null || test(v)
const isStamp = (v: unknown): boolean => isStr(v) && ISO_LOCAL.test(v) && Number.isFinite(Date.parse(v))
const isCount = (v: unknown): boolean => isNum(v) && Number.isInteger(v) && v >= 0

function fieldsOk(r: Raw): boolean {
  return (
    r.v === ROW_VERSION && isStr(r.session) && isStr(r.turn) &&
    isStr(r.kind) && KINDS.includes(r.kind) && isNullOr(r.wake, isStr) &&
    isNullOr(r.prompt_at, isStamp) && isStamp(r.start_at) && isStamp(r.stop_at) && isNullOr(r.last_prompt_at, isStamp) &&
    isNum(r.lap_ms) && isNullOr(r.since_prompt_ms, isNum) &&
    isStr(r.reason) && REASONS.includes(r.reason) &&
    isNullOr(r.answer_hash, isStr) && isCount(r.answer_len)
  )
}

/** A `prompt` row names its lap press; a `wake` row has none. */
const kindOk = (r: Raw): boolean => (r.kind === 'prompt') === (r.prompt_at !== null)

function toRow(r: Raw): LapRow {
  return {
    v: ROW_VERSION,
    session: r.session as string,
    turn: r.turn as string,
    kind: r.kind as LapRow['kind'],
    wake: r.wake as string | null,
    prompt_at: r.prompt_at as string | null,
    start_at: r.start_at as string,
    stop_at: r.stop_at as string,
    last_prompt_at: r.last_prompt_at as string | null,
    lap_ms: r.lap_ms as number,
    since_prompt_ms: r.since_prompt_ms as number | null,
    reason: r.reason as StopReason,
    answer_hash: r.answer_hash as string | null,
    answer_len: r.answer_len as number,
  }
}

function parseLine(line: string): LapRow | null {
  if (line.trim() === '') return null
  let value: unknown
  try {
    value = JSON.parse(line)
  } catch {
    return null
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const raw = value as Raw
  return fieldsOk(raw) && kindOk(raw) ? toRow(raw) : null
}

/** Rows of one session from a JSONL text, in file order. Blank, malformed, wrong-version and wrong-typed lines are skipped, never fatal. */
export function parseRows(text: string, session: string): LapRow[] {
  const rows: LapRow[] = []
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  for (const line of body.split(/\r\n|\n|\r/)) {
    const row = parseLine(line)
    if (row !== null && row.session === session) rows.push(row)
  }
  return rows
}

/** Newest lap press among the rows, epoch ms: every `prompt_at` and every `last_prompt_at`; null when none. */
export function newestPromptAt(rows: readonly LapRow[]): number | null {
  let newest: number | null = null
  for (const row of rows) {
    for (const stamp of [row.prompt_at, row.last_prompt_at]) {
      if (stamp === null) continue
      const at = Date.parse(stamp)
      if (newest === null || at > newest) newest = at
    }
  }
  return newest
}
