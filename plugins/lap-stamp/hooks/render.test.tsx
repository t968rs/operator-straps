import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import type { Engine, FoundElement } from 'claude-code/testing'

import type { LapRow } from '../types'
import { fingerprintOf } from './fingerprint'
import { registerRender, STAMP_COLOR } from './render'
import { blockStamp, stampText, wrapRight } from './stamp'

/** Local wall clock as an ISO string, so a stamp's HH:MM:SS holds in any time zone. */
const localIso = (h: number, m: number, s: number): string => new Date(2026, 10, 25, h, m, s).toISOString()

const REPLY = 'All three files are updated.'
const COLUMNS = 80

type Over = Partial<LapRow>

/** A row of session `s1` with the given answer text (null: an empty answer) and optional overrides. */
const row = (answer: string | null, over: Over = {}): LapRow => {
  const f = answer === null ? null : fingerprintOf(answer)
  return {
    v: 1,
    session: 's1',
    turn: 't1',
    kind: 'prompt',
    wake: null,
    prompt_at: localIso(14, 29, 0),
    start_at: localIso(14, 29, 5),
    stop_at: localIso(14, 32, 7),
    last_prompt_at: localIso(14, 29, 0),
    lap_ms: 192_000,
    since_prompt_ms: null,
    reason: 'answer',
    answer_hash: f === null ? null : f.hash,
    answer_len: f === null ? 0 : f.len,
    ...over,
  }
}

// ---------------------------------------------------------------------------
// The world beneath the plugin

// The host grants `$.state` only to the hooks module that spells the reads (register.ts once it wires render),
// and hooks registered through a test's `on` are not that module: the memory comes from the world instead.

type World = {
  props: Array<Record<string, unknown>>
  /** The mod's memory: the rows held and the current session id. */
  rows: LapRow[]
  session: string | null
  /** When true, reading the memory rejects. */
  isBroken: boolean
}

/** The render hooks under test over the world's memory, the engine's own drawing of every component beneath. */
const world = (on: On): World => {
  const w: World = { props: [], rows: [], session: 's1', isBroken: false }
  registerRender(on, () =>
    w.isBroken ? Promise.reject(new Error('memory unreadable')) : Promise.resolve({ rows: w.rows, session: w.session }),
  )
  on('ui.render', ($, e) => {
    w.props.push({ ...e.props })
    const { Box, Text } = $.ui.resolve(e)
    return <Box key="engine"><Text>engine line</Text></Box>
  })
  return w
}

/** The session's rows and id in memory, as the turn hooks leave them. */
const seed = (w: World, rows: LapRow[], session: string | null = 's1'): void => {
  w.rows = rows
  w.session = session
}

const VIEWPORT = { columns: COLUMNS, rows: 40 }

const mountReply = ($: Engine, props: { text: string; isSummary?: true }, columns = COLUMNS) =>
  $.ui.mount({
    plugin: 'lap-stamp',
    surface: 'terminal',
    component: 'AssistantMessage',
    props: { isFirstOfReply: true, ...props },
    viewport: { ...VIEWPORT, columns },
  })

const mountDuration = ($: Engine, durationMs: number) =>
  $.ui.mount({
    plugin: 'lap-stamp',
    surface: 'terminal',
    component: 'TurnDuration',
    props: { word: 'Baked', durationMs },
    viewport: VIEWPORT,
  })

type Drawing = { findAll: (q: { type?: string; key?: string; text?: string | RegExp }) => Promise<FoundElement[]> }

/** The stamp-colored Text rows the mod drew, in document order. */
const stampRows = async (ui: Drawing): Promise<FoundElement[]> =>
  (await ui.findAll({ type: 'Text' })).filter(n => n.props.color === STAMP_COLOR)

const textsOf = (nodes: readonly FoundElement[]): string[] => nodes.map(n => n.text)

/** Whether the engine's own drawing is still in the tree. */
const hasEngine = async (ui: Drawing): Promise<boolean> => (await ui.findAll({ key: 'engine' })).length === 1

// ---------------------------------------------------------------------------

describe('reply blocks', () => {
  test('a matched block gains its stamp row, right-aligned under the original', async ($, on) => {
    const w = world(on)
    const r = row(REPLY)
    seed(w, [r])
    const ui = await mountReply($, { text: REPLY })
    const stamps = await stampRows(ui)
    expect(textsOf(stamps)).toEqual([stampText(r)])
    expect(await ui.drawn()).toMatchObject({
      type: 'Box',
      props: { flexDirection: 'column' },
      children: [{ props: { key: 'engine' } }, { type: 'Box', props: { alignItems: 'flex-end' } }],
    })
    await ui.unmount()
  })

  test('a block with no matching row is drawn untouched', async ($, on) => {
    const w = world(on)
    seed(w, [row('Some other reply.')])
    const ui = await mountReply($, { text: REPLY })
    expect(await stampRows(ui)).toEqual([])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'engine' } })
    await ui.unmount()
  })

  test('a summary block draws nothing even when its text matches', async ($, on) => {
    const w = world(on)
    seed(w, [row(REPLY)])
    const ui = await mountReply($, { text: REPLY, isSummary: true })
    expect(await stampRows(ui)).toEqual([])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'engine' } })
    expect(w.props.at(-1)?.isSummary).toBe(true)
    await ui.unmount()
  })

  test('a row of another session never stamps', async ($, on) => {
    const w = world(on)
    seed(w, [row(REPLY, { session: 'older' })])
    const ui = await mountReply($, { text: REPLY })
    expect(await stampRows(ui)).toEqual([])
    await ui.unmount()
  })

  test('no session known: nothing is drawn', async ($, on) => {
    const w = world(on)
    seed(w, [row(REPLY)], null)
    const ui = await mountReply($, { text: REPLY })
    expect(await stampRows(ui)).toEqual([])
    await ui.unmount()
  })

  test('identical replies draw the candidate list', async ($, on) => {
    const w = world(on)
    const first = row(REPLY)
    const second = row(REPLY, { turn: 't2', stop_at: localIso(14, 41, 55), lap_ms: 38_000 })
    seed(w, [first, second])
    const ui = await mountReply($, { text: REPLY })
    const [only, ...rest] = textsOf(await stampRows(ui))
    expect(rest).toEqual([])
    expect(only?.startsWith('identical replies: ')).toBe(true)
    expect(only).toContain(' | ')
    await ui.unmount()
  })

  test('a candidate list too wide for the transcript wraps onto further rows', async ($, on) => {
    const w = world(on)
    const first = row(REPLY)
    const second = row(REPLY, { turn: 't2', stop_at: localIso(14, 41, 55), lap_ms: 38_000 })
    seed(w, [first, second])
    const ui = await mountReply($, { text: REPLY }, 30)
    const texts = textsOf(await stampRows(ui))
    expect(texts.length).toBeGreaterThan(1)
    expect(texts).toEqual(wrapRight(blockStamp([first, second]) ?? '', 30).map(t => t.trimStart()))
    expect(texts.every(t => t.length <= 30)).toBe(true)
    await ui.unmount()
  })

  test('the block passes its props on unchanged', async ($, on) => {
    const w = world(on)
    seed(w, [row(REPLY)])
    const onScreen = { first: 0, last: 3, of: 4 }
    const ui = await $.ui.mount({
      plugin: 'lap-stamp',
      surface: 'terminal',
      component: 'AssistantMessage',
      props: { text: REPLY, isFirstOfReply: false, onScreen },
      viewport: VIEWPORT,
    })
    expect(w.props.at(-1)).toEqual({ text: REPLY, isFirstOfReply: false, onScreen })
    await ui.unmount()
  })

  test('a redraw picks up a row added since the block was drawn', async ($, on) => {
    const w = world(on)
    seed(w, [])
    const ui = await mountReply($, { text: REPLY })
    expect(await stampRows(ui)).toEqual([])
    const r = row(REPLY)
    seed(w, [r])
    await ui.redraw()
    expect(textsOf(await stampRows(ui))).toEqual([stampText(r)])
    await ui.unmount()
  })

  test('no viewport measured: one unwrapped stamp row', async ($, on) => {
    const w = world(on)
    const first = row(REPLY)
    const second = row(REPLY, { turn: 't2', stop_at: localIso(14, 41, 55), lap_ms: 38_000 })
    seed(w, [first, second])
    const ui = await $.ui.mount({
      plugin: 'lap-stamp',
      surface: 'terminal',
      component: 'AssistantMessage',
      props: { text: REPLY, isFirstOfReply: true },
    })
    expect(textsOf(await stampRows(ui))).toEqual([blockStamp([first, second])])
    await ui.unmount()
  })

  test('an unreadable memory draws the block untouched (D10)', async ($, on) => {
    const w = world(on)
    seed(w, [row(REPLY)])
    w.isBroken = true
    const ui = await mountReply($, { text: REPLY })
    expect(await stampRows(ui)).toEqual([])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'engine' } })
    await ui.unmount()
  })
})

describe('TurnDuration lines', () => {
  // the row's span (start 14:29:05, stop 14:32:07) is 182 s
  const SPAN_MS = 182_000

  test('one empty-answer row within the tolerance stamps the line on the same row', async ($, on) => {
    const w = world(on)
    const r = row(null, { reason: 'aborted' })
    seed(w, [r])
    const ui = await mountDuration($, SPAN_MS + 1500)
    expect(textsOf(await stampRows(ui))).toEqual([stampText(r)])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { flexDirection: 'row' } })
    expect(await hasEngine(ui)).toBe(true)
    await ui.unmount()
  })

  test('an answered row within the tolerance draws nothing', async ($, on) => {
    const w = world(on)
    seed(w, [row(REPLY)])
    const ui = await mountDuration($, SPAN_MS)
    expect(await stampRows(ui)).toEqual([])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'engine' } })
    await ui.unmount()
  })

  test('a line outside the tolerance draws nothing', async ($, on) => {
    const w = world(on)
    seed(w, [row(null)])
    const ui = await mountDuration($, SPAN_MS + 2500)
    expect(await stampRows(ui)).toEqual([])
    await ui.unmount()
  })

  test('two rows within the tolerance draw nothing', async ($, on) => {
    const w = world(on)
    seed(w, [row(null), row(null, { turn: 't2' })])
    const ui = await mountDuration($, SPAN_MS)
    expect(await stampRows(ui)).toEqual([])
    await ui.unmount()
  })

  test('an unreadable memory draws the line untouched (D10)', async ($, on) => {
    const w = world(on)
    seed(w, [row(null)])
    w.isBroken = true
    const ui = await mountDuration($, SPAN_MS)
    expect(await stampRows(ui)).toEqual([])
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'engine' } })
    await ui.unmount()
  })
})
