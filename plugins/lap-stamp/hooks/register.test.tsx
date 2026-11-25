import type { Engine, FoundElement, MockClock } from 'claude-code/testing'
import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { LapRow } from '../types'
import { parseRows } from './row'
import { clockOf } from './stamp'

/**
 * The wired mod end to end: the plugin's own hooks (register.ts) time a turn, append its row to the laps file
 * and hold it in `$.state`, and the same module's render hooks read that state and stamp the transcript. No
 * test-only memory: the writer (lap.ts) and the reader (render.tsx) meet on the real `{plugin: 'lap-stamp'}`
 * atoms. Files, env, git, clock, session id, core and the engine's own drawing sit beneath, answered from memory.
 */

const ROOT = '/repo'
const HARNESS = `${ROOT}/.claude/harness.json`
const LAPS = `${ROOT}/.claude/state/harness/lap-stamp/laps.jsonl`
const SESSION = 'S1'
const T0 = 1_800_000_000_000
const REPLY = 'All three files are updated.'
const WAKE_REPLY = 'The background task finished.'
const VIEWPORT = { columns: 80, rows: 40 }

type World = { files: Map<string, string>; clock: MockClock }

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** A host path as the test keys it: Windows hosts hand the hooks `C:\repo\...` for `/repo/...`. */
const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')

/** Core's answers to the turn and session events, and the engine's own drawing of every component. */
const answerCore = (on: On): void => {
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }))
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('ui.render', ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    return <Box key="engine"><Text>engine line</Text></Box>
  })
}

/** Whole-file reads, stats, existence checks and writes from memory. */
const answerFiles = (on: On, w: World): void => {
  on('fs.read', (_$, e) => {
    const text = w.files.get(slash(e.path))
    return text === undefined ? { deny: `ENOENT ${e.path}` } : { value: text }
  })
  on('fs.stat', (_$, e) => {
    const text = w.files.get(slash(e.path))
    if (text === undefined) return { deny: `ENOENT ${e.path}` }
    return { value: { kind: 'file', size: new TextEncoder().encode(text).length, mtimeMs: 1, isLink: false } }
  })
  on('fs.exists', (_$, e) => ({ value: w.files.has(slash(e.path)) }))
  on('fs.write', (_$, e) => {
    w.files.set(slash(e.path), e.text)
    return { value: undefined }
  })
}

/** A project with a harness.json at ROOT, outside git, in session S1, its clock at T0. */
const world = (on: On): World => {
  const w: World = { files: new Map([[HARNESS, '{}']]), clock: mock.clock(on, { now: T0 }) }
  answerCore(on)
  answerFiles(on, w)
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  on('session.cwd', () => ({ value: ROOT }))
  on('session.id', () => ({ value: SESSION }))
  on('process.run', () => ({ value: ran('', 128) }))
  return w
}

// ---------------------------------------------------------------------------
// Driving a turn

type Kind = 'composer' | 'task-notification'

const start = ($: Engine) => $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
const press = ($: Engine, kind: Kind) => $.prompt.submit({ text: 'go', wait: false, origin: { kind } })
const begin = ($: Engine, turnId: string) => $.turn.start({ text: '', turnId } as never)
const end = ($: Engine, turnId: string, answer: string) =>
  $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId, reason: 'answer' } as never)

/** One main-loop turn from a `kind` submission: started 1 s after it, stopped `lapS` seconds after it. */
const turn = async ($: Engine, w: World, turnId: string, answer: string, kind: Kind = 'composer', lapS = 5) => {
  await press($, kind)
  await w.clock.advance(1000)
  await begin($, turnId)
  await w.clock.advance(lapS * 1000 - 1000)
  await end($, turnId, answer)
  await w.clock.settle()
}

const fileRows = (w: World): LapRow[] => parseRows(w.files.get(LAPS) ?? '', SESSION)

/** Epoch ms of a stored ISO time, as an offset from T0; null stays null. */
const sinceT0 = (iso: string | null): number | null => (iso === null ? null : Date.parse(iso) - T0)

/** A row's four stored times as offsets from T0, whatever zone offset the text carries. */
const timesOf = (row: LapRow | undefined) => ({
  prompt_at: sinceT0(row?.prompt_at ?? null),
  start_at: sinceT0(row?.start_at ?? null),
  stop_at: sinceT0(row?.stop_at ?? null),
  last_prompt_at: sinceT0(row?.last_prompt_at ?? null),
})

const HASH = /^[0-9a-f]{16}$/

/** The local `HH:MM:SS` of `ms` after T0, as a stamp shows it. */
const clockAt = (ms: number): string => clockOf(new Date(T0 + ms).toISOString())

// ---------------------------------------------------------------------------
// The transcript

const mountReply = ($: Engine, text: string) =>
  $.ui.mount({
    plugin: 'lap-stamp',
    surface: 'terminal',
    component: 'AssistantMessage',
    props: { text, isFirstOfReply: true },
    viewport: VIEWPORT,
  })

const mountDuration = ($: Engine, durationMs: number) =>
  $.ui.mount({
    plugin: 'lap-stamp',
    surface: 'terminal',
    component: 'TurnDuration',
    props: { word: 'Baked', durationMs },
    viewport: VIEWPORT,
  })

type Drawing = { findAll: (q: { type?: string; key?: string }) => Promise<FoundElement[]> }

/** The texts of the dim rows the mod drew, in document order. */
const stampTexts = async (ui: Drawing): Promise<string[]> =>
  (await ui.findAll({ type: 'Text' })).filter(n => n.props.dimColor === true).map(n => n.text)

// ---------------------------------------------------------------------------

describe('a prompt turn end to end', () => {
  test('one JSONL row of kind prompt, and its reply block draws the stamp right-aligned under it', async ($, on) => {
    const w = world(on)
    await start($)
    await turn($, w, 't1', REPLY)
    const rows = fileRows(w)
    expect(rows).toHaveLength(1)
    const [row] = rows
    expect(row).toMatchObject({
      v: 1, session: SESSION, turn: 't1', kind: 'prompt', wake: null, lap_ms: 5000, since_prompt_ms: null,
      reason: 'answer', answer_len: REPLY.length,
    })
    expect(row?.answer_hash).toMatch(HASH)
    expect(timesOf(row)).toEqual({ prompt_at: 0, start_at: 1000, stop_at: 5000, last_prompt_at: 0 })
    const ui = await mountReply($, REPLY)
    expect(await stampTexts(ui)).toEqual([`${clockAt(5000)} · lap 5s`])
    expect(await ui.drawn()).toMatchObject({
      type: 'Box',
      props: { flexDirection: 'column' },
      children: [{ props: { key: 'engine' } }, { type: 'Box', props: { alignItems: 'flex-end' } }],
    })
    await ui.unmount()
  })

  test('a block whose text no row matches is drawn untouched', async ($, on) => {
    const w = world(on)
    await start($)
    await turn($, w, 't1', REPLY)
    expect(fileRows(w).map(r => r.turn)).toEqual(['t1'])
    const ui = await mountReply($, 'Some other reply.')
    expect(await stampTexts(ui)).toEqual([])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'engine' } })
    await ui.unmount()
  })

  test('a second identical reply draws the candidate list', async ($, on) => {
    const w = world(on)
    await start($)
    await turn($, w, 't1', REPLY)
    await turn($, w, 't2', REPLY, 'composer', 3)
    const [first, second] = fileRows(w)
    expect([first?.turn, second?.turn]).toEqual(['t1', 't2'])
    expect(first?.answer_hash).toMatch(HASH)
    expect(second).toMatchObject({ answer_hash: first?.answer_hash, answer_len: first?.answer_len })
    expect(timesOf(second)).toEqual({ prompt_at: 5000, start_at: 6000, stop_at: 8000, last_prompt_at: 5000 })
    const ui = await mountReply($, REPLY)
    expect(await stampTexts(ui)).toEqual([
      `identical replies: ${clockAt(5000)} lap 5s | ${clockAt(8000)} lap 3s`,
    ])
    await ui.unmount()
  })
})

describe('a wake turn end to end', () => {
  test('a task-notification turn writes a wake row and its block draws since prompt', async ($, on) => {
    const w = world(on)
    await start($)
    await turn($, w, 't1', REPLY)
    await w.clock.advance(60_000)
    await turn($, w, 't2', WAKE_REPLY, 'task-notification', 8)
    const wake = fileRows(w)[1]
    // a wake lap runs from the turn's start, 1 s after the notification (D4); since prompt from the last press
    expect(wake).toMatchObject({
      turn: 't2', kind: 'wake', wake: 'task-notification', lap_ms: 7000, since_prompt_ms: 5000 + 60_000 + 8000,
      reason: 'answer', answer_len: WAKE_REPLY.length,
    })
    expect(wake?.answer_hash).toMatch(HASH)
    expect(timesOf(wake)).toEqual({ prompt_at: null, start_at: 66_000, stop_at: 73_000, last_prompt_at: 0 })
    const ui = await mountReply($, WAKE_REPLY)
    expect(await stampTexts(ui)).toEqual([`${clockAt(73_000)} · lap 7s · since prompt 1m 13s`])
    await ui.unmount()
  })
})

describe('an empty-answer turn end to end', () => {
  test('its TurnDuration line with a matching durationMs draws the stamp on the same row', async ($, on) => {
    const w = world(on)
    await start($)
    await turn($, w, 't1', '')
    const rows = fileRows(w)
    expect(rows).toHaveLength(1)
    const [row] = rows
    expect(row).toMatchObject({ turn: 't1', kind: 'prompt', lap_ms: 5000, answer_hash: null, answer_len: 0 })
    // the row's span runs from the turn's start (T0 + 1 s) to its stop (T0 + 5 s)
    expect(timesOf(row)).toEqual({ prompt_at: 0, start_at: 1000, stop_at: 5000, last_prompt_at: 0 })
    const ui = await mountDuration($, 4000)
    const stamp = `${clockAt(5000)} · lap 5s`
    expect(await stampTexts(ui)).toEqual([stamp])
    // one row: the engine's line, then the dim stamp, and nothing else
    const drawn = await ui.drawn()
    expect(drawn).toMatchObject({
      type: 'Box',
      props: { flexDirection: 'row' },
      children: [{ props: { key: 'engine' } }, { type: 'Text', props: { dimColor: true }, children: [stamp] }],
    })
    expect('children' in drawn ? drawn.children : undefined).toHaveLength(2)
    await ui.unmount()
  })
})

describe('redraw on a new row', () => {
  test('a block mounted before its turn stopped gains the stamp once the row lands, with no redraw asked', async ($, on) => {
    const w = world(on)
    await start($)
    const ui = await mountReply($, REPLY)
    expect(await stampTexts(ui)).toEqual([])
    await turn($, w, 't1', REPLY)
    expect(await stampTexts(ui)).toEqual([`${clockAt(5000)} · lap 5s`])
    await ui.unmount()
  })
})
