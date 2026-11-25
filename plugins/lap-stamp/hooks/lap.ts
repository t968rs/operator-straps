import type { EngineInterface, On, PromptOrigin } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { ClockState, LapRow, StopReason } from '../types'
import { delivered, EMPTY_CLOCK, isLapPress, seedLastPrompt, started, stopped, submitted } from './clock'
import { lapsPathOf, readConfig, type LapConfig } from './config'
import { HARNESS_CONFIG_REL, rootCandidates } from './root'
import { buildRow, newestPromptAt, parseRows, rowLine } from './row'

/**
 * Engine glue for lap-stamp: the main loop's turn events drive the clock (./clock), each stopped turn becomes
 * one row appended to `<state_dir>/lap-stamp/laps.jsonl` and pushed onto the 'lap-stamp' rows atom, and
 * `session.start` / `session.attach` read the session's rows back (D9). Active only in a project holding
 * `.claude/harness.json`. Subagent turns (`agentId`) are ignored. Fail open (D10): every host call and file
 * operation is guarded, a failure records nothing and blocks nothing, and nothing is written into a reply, a
 * prompt or a transcript row. Functions taking `$` are function declarations: the engine follows `$` past an
 * import only into one.
 */

type Dollar = EngineInterface
type Watch = { root: string; cfg: LapConfig }
/** Per-registration memory: the serial queue, the last known project and git's answered top levels ('' failed). */
type Ctx = {
  tail: Promise<unknown>
  watch: Watch | undefined
  isKnown: boolean
  toplevels: Map<string, string>
}
/** What a main-loop `turn.complete` hands the row. */
type Stop = { turnId: string; answer: string; reason: StopReason }
/** What one resolution found; `isSure` is false when a host call failed on the way. */
type Probe = { watch: Watch | undefined; isSure: boolean }
/** One submission the clock took, with the wake reason it replaced, so a dropped prompt can be taken back. */
export type Submission = { originKind: string; at: number; priorWake: string | null }

const rowsAtom = atom({ plugin: 'lap-stamp', key: 'rows' } as const, [])
const clockAtom = atom({ plugin: 'lap-stamp', key: 'clock' } as const, EMPTY_CLOCK)
const sessionAtom = atom({ plugin: 'lap-stamp', key: 'session' } as const, null)

/** Bytes per ranged read of a laps file too large for one read (the host caps one answer at 4 MiB). */
export const RANGE_BYTES = 3 * 1024 * 1024
const GIT_TIMEOUT_MS = 10_000
const BOM = [0xef, 0xbb, 0xbf]

const noop = (): undefined => undefined

/** Serializes the glue's work: a press lands before the start that follows it, and no two writes interleave. */
function serial<T>(ctx: Ctx, work: () => Promise<T>): Promise<T | undefined> {
  const run = ctx.tail.then(work, work)
  ctx.tail = run.catch(noop)
  return run.catch(noop)
}

// ---------------------------------------------------------------------------
// Pure

/** The file's text with one more line, its last line ended first when it was not. */
export function withLine(text: string, line: string): string {
  const sep = text === '' || /[\r\n]$/.test(text) ? '' : '\n'
  return `${text}${sep}${line}\n`
}

/** The file's rows, then each held row the file lacks (a write that was refused), by turn id. */
export function mergeRows(fromFile: readonly LapRow[], held: readonly LapRow[]): LapRow[] {
  const turns = new Set(fromFile.map(r => r.turn))
  return [...fromFile, ...held.filter(r => !turns.has(r.turn))]
}

/** A submission's origin kind; undefined when the event carries none. */
export function originKindOf(origin: PromptOrigin | undefined): string | undefined {
  const o: unknown = origin
  const kind: unknown = typeof o === 'object' && o !== null ? (o as { kind?: unknown }).kind : undefined
  return typeof kind === 'string' ? kind : undefined
}

/** True when a `prompt.submit` result is a drop. */
export function isDropped(result: unknown): boolean {
  return typeof result === 'object' && result !== null && typeof (result as { drop?: unknown }).drop === 'string'
}

/** Takes a dropped submission back: its press leaves the queue, or its wake reason yields to the prior one. */
export function withdrawn(state: ClockState, s: Submission): ClockState {
  if (isLapPress(s.originKind)) {
    return { ...state, pending: state.pending.filter(p => !(p.at === s.at && p.origin === s.originKind)) }
  }
  return state.pendingWake === s.originKind ? { ...state, pendingWake: s.priorWake } : state
}

/**
 * The clock for a stop in `session`. The same session keeps it; the first known session seeds it from the file;
 * a switched session (a /clear or a resume, which raise no `session.start`) rebuilds the newest and consumed
 * press from that session's rows, null when none, and clears the wake reason, keeping the running turn and the
 * pending presses.
 */
export function clockFor(
  clock: ClockState,
  session: string | undefined,
  known: string | null,
  text: string | undefined,
): ClockState {
  if (session === undefined || session === known) return clock
  const newestAt = text === undefined ? null : newestPromptAt(parseRows(text, session))
  if (known === null) return seedLastPrompt(clock, newestAt)
  return { ...clock, lastPromptAt: newestAt, consumedAt: newestAt, pendingWake: null }
}

/** The bytes a standard base64 text holds. */
export function bytesOf(base64: string): Uint8Array {
  const bin = atob(base64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** UTF-8 text of byte pieces joined in order; a leading BOM is kept as U+FEFF. */
export function textOf(parts: readonly Uint8Array[]): string {
  const all = new Uint8Array(parts.reduce((n, p) => n + p.length, 0))
  let at = 0
  for (const p of parts) {
    all.set(p, at)
    at += p.length
  }
  const hasBom = BOM.every((b, i) => all[i] === b)
  const body = new TextDecoder('utf-8').decode(hasBom ? all.subarray(3) : all)
  return hasBom ? `﻿${body}` : body
}

// ---------------------------------------------------------------------------
// Host access

async function nowOf($: Dollar): Promise<number | undefined> {
  try {
    const at = await $.clock.now()
    return typeof at === 'number' && Number.isFinite(at) ? at : undefined
  } catch {
    return undefined
  }
}

async function sessionIdOf($: Dollar): Promise<string | undefined> {
  try {
    const id = await $.session.id()
    return typeof id === 'string' && id !== '' ? id : undefined
  } catch {
    return undefined
  }
}

/** `git rev-parse --show-toplevel` from `start`; undefined on any failure, which is remembered too. */
async function toplevelOf($: Dollar, ctx: Ctx, start: string | undefined): Promise<string | undefined> {
  if (start === undefined || start.trim() === '') return undefined
  const known = ctx.toplevels.get(start)
  if (known !== undefined) return known === '' ? undefined : known
  const argv = ['git', '-C', start, 'rev-parse', '--show-toplevel']
  const ran = await $.process.run(argv, { timeoutMs: GIT_TIMEOUT_MS }).catch(noop)
  const top = ran === undefined || ran.exitCode !== 0 ? '' : ran.stdout.trim()
  ctx.toplevels.set(start, top)
  return top === '' ? undefined : top
}

/**
 * The first candidate root (./root) whose `.claude/harness.json` reads, with its configuration. Sure of an
 * absence only when every host call answered and no candidate's file exists.
 */
async function resolveWatch($: Dollar, ctx: Ctx): Promise<Probe> {
  let isSure = true
  const doubt = (): undefined => {
    isSure = false
    return undefined
  }
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(doubt)
  const cwd = await $.session.cwd().catch(doubt)
  const top = await toplevelOf($, ctx, cwd).catch(noop)
  for (const root of rootCandidates(env, cwd, top)) {
    const path = `${root}/${HARNESS_CONFIG_REL}`
    const text = await $.fs.read(path).catch(noop)
    if (typeof text === 'string') return { watch: { root, cfg: readConfig(text) }, isSure: true }
    if (await $.fs.exists(path).catch(() => true)) isSure = false
  }
  return { watch: undefined, isSure }
}

/**
 * The project the glue serves: resolved afresh when asked, else once and then remembered. A resolution that
 * failed on a host call keeps the last known project; only a sure absence of the file deactivates.
 */
async function watchOf($: Dollar, ctx: Ctx, isFresh: boolean): Promise<Watch | undefined> {
  if (isFresh || !ctx.isKnown) {
    const probe = await resolveWatch($, ctx).catch((): Probe => ({ watch: undefined, isSure: false }))
    if (probe.watch !== undefined || probe.isSure) ctx.watch = probe.watch
    ctx.isKnown = true
  }
  return ctx.watch
}

/** The file read in ranges of at most RANGE_BYTES; undefined when any range fails or comes back short. */
async function readRanges($: Dollar, path: string, size: number): Promise<string | undefined> {
  const parts: Uint8Array[] = []
  for (let offset = 0; offset < size; offset += RANGE_BYTES) {
    const length = Math.min(RANGE_BYTES, size - offset)
    const got = await $.fs.read(path, { as: 'bytes', offset, length }).catch(noop)
    const bytes = got === undefined ? undefined : bytesOf(got.base64)
    if (bytes === undefined || bytes.length !== length) return undefined
    parts.push(bytes)
  }
  return textOf(parts)
}

/**
 * The laps file's text: '' when it does not exist; read in ranges when one read is refused (a file over the
 * host's 4 MiB answer); undefined when it exists (or may) but cannot be read.
 */
async function lapsText($: Dollar, path: string): Promise<string | undefined> {
  const raw = await $.fs.read(path).catch(noop)
  if (typeof raw === 'string') return raw
  const st = await $.fs.stat(path).catch(noop)
  if (st === undefined) return (await $.fs.exists(path).catch(() => true)) ? undefined : ''
  if (st.kind !== 'file' || st.size <= 0) return undefined
  return readRanges($, path, st.size)
}

// ---------------------------------------------------------------------------
// Clock moves

/** Applies one clock reducer at the time `at` resolves to; nothing when inactive or the clock was refused. */
async function moveClock(
  $: Dollar,
  ctx: Ctx,
  at: Promise<number | undefined>,
  change: (c: ClockState, at: number) => ClockState,
): Promise<void> {
  const w = await watchOf($, ctx, false)
  const t = await at
  if (w === undefined || t === undefined) return
  await update($, clockAtom, c => change(c, t))
}

/** Applies a submission to the clock; the submission as taken, else undefined (inactive, no clock). */
async function takeSubmission(
  $: Dollar,
  ctx: Ctx,
  originKind: string,
  at: Promise<number | undefined>,
): Promise<Submission | undefined> {
  const w = await watchOf($, ctx, false)
  const t = await at
  if (w === undefined || t === undefined) return undefined
  let priorWake: string | null = null
  await update($, clockAtom, c => {
    priorWake = c.pendingWake
    return submitted(c, { originKind, at: t })
  })
  return { originKind, at: t, priorWake }
}

async function withdraw($: Dollar, s: Submission): Promise<void> {
  await update($, clockAtom, c => withdrawn(c, s))
}

// ---------------------------------------------------------------------------
// Rows

/** Puts the row on the rows atom; a session other than `known` first loads its rows from `text`. */
async function keepRow($: Dollar, row: LapRow, text: string | undefined, known: string | null): Promise<void> {
  if (known === row.session) {
    await update($, rowsAtom, rows => [...rows, row])
    return
  }
  const loaded = text === undefined ? [] : parseRows(text, row.session)
  await update($, rowsAtom, () => [...loaded, row])
  await update($, sessionAtom, () => row.session)
}

/**
 * A main-loop stop: the running turn's timing becomes one row, kept in memory and then appended to the file
 * (never written when the file exists but does not read). A stray stop records nothing.
 */
async function completed($: Dollar, ctx: Ctx, e: Stop, at: Promise<number | undefined>): Promise<void> {
  const w = await watchOf($, ctx, true)
  const t = await at
  if (w === undefined || t === undefined) return
  const path = lapsPathOf(w.root, w.cfg)
  const session = await sessionIdOf($)
  const text = session === undefined ? undefined : await lapsText($, path)
  const known = await read($, sessionAtom)
  const out = stopped(clockFor(await read($, clockAtom), session, known, text), e.turnId, t)
  if (out.timing === null) return
  await update($, clockAtom, () => out.state)
  if (session === undefined) return
  const row = buildRow({ session, turn: e.turnId, timing: out.timing, reason: e.reason, answer: e.answer })
  await keepRow($, row, text, known).catch(noop)
  if (text !== undefined) await $.fs.write(path, withLine(text, rowLine(row)))
}

/** Reads the session's rows into the atom, keeping held rows the file lacks, and seeds the clock (D9). */
async function load($: Dollar, ctx: Ctx, isFresh: boolean): Promise<void> {
  const w = await watchOf($, ctx, isFresh)
  const session = w === undefined ? undefined : await sessionIdOf($)
  if (w === undefined || session === undefined) return
  const text = await lapsText($, lapsPathOf(w.root, w.cfg))
  const fromFile = text === undefined ? [] : parseRows(text, session)
  const held = (await read($, sessionAtom)) === session ? await read($, rowsAtom) : []
  const rows = mergeRows(fromFile, held)
  await update($, rowsAtom, () => rows)
  await update($, sessionAtom, () => session)
  const newestAt = newestPromptAt(rows)
  await update($, clockAtom, c => seedLastPrompt(c, newestAt))
}

// ---------------------------------------------------------------------------
// Hooks

/** A row through the delivery door: a lap press reaching the main loop attaches to its running turn (D2). */
async function afterDelivery(
  $: Dollar,
  ctx: Ctx,
  e: { origin: unknown; agentId?: string },
  at: Promise<number | undefined>,
): Promise<void> {
  const kind = originKindOf(e.origin as PromptOrigin | undefined)
  if (e.agentId !== undefined || kind === undefined || !isLapPress(kind)) return
  await serial(ctx, () => moveClock($, ctx, at, delivered))
}

/** The lap-press hooks: a submission (the press, D1) and its delivery into a running turn (D2). */
function registerPresses(on: On, ctx: Ctx): void {
  // The press is queued before `next`: the turn it starts begins inside `next`, and its start must find it.
  // A prompt dropped beneath is taken back once `next` says so.
  on('prompt.submit', async ($, e, next) => {
    const kind = originKindOf(e.origin)
    const at = nowOf($)
    const taken = kind === undefined
      ? Promise.resolve(undefined)
      : serial(ctx, () => takeSubmission($, ctx, kind, at))
    const r = await next(e)
    const sub = await taken
    if (sub !== undefined && isDropped(r)) await serial(ctx, () => withdraw($, sub))
    return r
  })

  // Door `delivery` only: a `queue` row is the message-queue record raised when a prompt is queued at Enter,
  // not a delivery into the running turn, and D2 attaches a mid-turn press only on a reported delivery.
  on('session.append', { door: 'delivery' }, async ($, e, next) => {
    const at = nowOf($)
    const r = await next(e)
    await afterDelivery($, ctx, e, at).catch(noop)
    return r
  })
}

/** The turn and session hooks: the main loop's start and stop (D2, D3), and the rows read back (D9). */
function registerTurns(on: On, ctx: Ctx): void {
  on('turn.start', async ($, e, next) => {
    const at = e.agentId === undefined ? nowOf($) : undefined
    const r = await next(e)
    if (at !== undefined) await serial(ctx, () => moveClock($, ctx, at, (c, t) => started(c, e.turnId, t)))
    return r
  })

  on('turn.complete', async ($, e, next) => {
    const at = e.agentId === undefined ? nowOf($) : undefined
    const r = await next(e)
    const stop: Stop = { turnId: e.turnId, answer: e.answer, reason: e.reason }
    if (at !== undefined) await serial(ctx, () => completed($, ctx, stop, at))
    return r
  })

  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await serial(ctx, () => load($, ctx, true))
    return r
  })

  on('session.attach', async ($, e, next) => {
    const r = await next(e)
    await serial(ctx, () => load($, ctx, false))
    return r
  })
}

/** Registers the lap hooks; each observes, returns what the host returned and never throws its own failure. */
export function registerLap(on: On): void {
  const ctx: Ctx = { tail: Promise.resolve(), watch: undefined, isKnown: false, toplevels: new Map() }
  registerPresses(on, ctx)
  registerTurns(on, ctx)
}
