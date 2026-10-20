import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import {
  BANNER_CONFIG, CATALOG_REL, catalogOf, catalogText, prompt, start, TODO_DIR, TOAST_CONFIG, world, type World,
} from './testWorld'

const SURFACES = ['terminal', 'desktop'] as const
type Surface = (typeof SURFACES)[number]

/** An item line: `<rank>  <title>`. */
const ITEM = /^\d+  /
/** The status line's text, with the space before Dismiss. */
const STATUS = /^(✓ in sync|\d+ out of sync|sync checks unavailable) ?$/

const bandOn = (surface: Surface, hasSurvey = false) => ({
  plugin: 'todo-watch',
  component: 'AbovePrompt',
  surface,
  props: {
    hasSurvey,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
}) as const

/** Stands for the engine's own band beneath the plugin: drawn whenever the plugin passes. */
function engineDraws(on: On): void {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
}

/** The band's item and status `Text` nodes, and every `Text` in drawing order. */
async function bandNodes($: Engine, surface: Surface = 'terminal') {
  const ui = await $.ui.mount(bandOn(surface))
  const items = await ui.findAll({ type: 'Text', text: ITEM })
  const status = await ui.findAll({ type: 'Text', text: STATUS })
  const all = await ui.findAll({ type: 'Text' })
  await ui.unmount()
  return { items, status, all }
}

/** The band's item lines, then its status line, trimmed; empty while the band passes. */
async function bandLines($: Engine, surface: Surface = 'terminal'): Promise<string[]> {
  const { items, status } = await bandNodes($, surface)
  return [...items, ...status].map(t => t.text.trim())
}

/** Everything drawn above the prompt: every `Text`, trimmed, and the number of buttons. */
async function drawn($: Engine, surface: Surface = 'terminal'): Promise<{ texts: string[]; buttons: number }> {
  const ui = await $.ui.mount(bandOn(surface))
  const texts = (await ui.findAll({ type: 'Text' })).map(t => t.text.trim())
  const buttons = (await ui.findAll({ type: 'Button' })).length
  await ui.unmount()
  return { texts, buttons }
}

/** What `drawn` sees while the plugin passes: the engine's own node alone. */
const ENGINE_ONLY = { texts: ['engine'], buttons: 0 }

/** Replaces the catalog with an unreadable one, its mtime moved past the last read. */
async function breakCatalog(w: World): Promise<void> {
  await w.clock.advance(1000)
  w.setFile(`${w.root}/${CATALOG_REL}`, '{"counts": 1}')
}

async function pressDismiss($: Engine, surface: Surface = 'terminal'): Promise<void> {
  const ui = await $.ui.mount(bandOn(surface))
  await ui.press({ key: 'dismiss' })
  await ui.unmount()
}

/** A Write to a watched plans file, so a check runs, with the engine reporting `drift`. */
async function reportDrift($: Engine, w: World, drift: number): Promise<void> {
  w.engine.drift = drift
  w.engine.byRule = drift === 0 ? {} : { P1: drift }
  await $.tool.call({ tool: 'Write', file_path: `${w.root}/docs/PLANS/a.md`, content: '- [ ] x' })
  await w.clock.settle()
}

const START_LINES = ['1  First', '2  Second']

describe('the band above the prompt', () => {
  for (const surface of SURFACES) {
    test(`${surface}: the start notice stays until Dismiss is pressed`, async ($, on) => {
      const w = world(on, { config: BANNER_CONFIG, hasRunner: false })
      engineDraws(on)
      await start($, w)
      expect(await bandLines($, surface)).toEqual(START_LINES)
      await pressDismiss($, surface)
      expect(await drawn($, surface)).toEqual(ENGINE_ONLY)
    })

    test(`${surface}: a survey takes the band`, async ($, on) => {
      const w = world(on, { config: BANNER_CONFIG, hasRunner: false })
      engineDraws(on)
      await start($, w)
      const ui = await $.ui.mount(bandOn(surface, true))
      expect(await ui.find({ type: 'Text', text: ITEM })).toBeUndefined()
      await ui.unmount()
    })
  }

  test('nothing shows in an inactive project', async ($, on) => {
    const w = world(on, { config: '{"todo": {"folder": null}}' })
    engineDraws(on)
    await start($, w)
    expect(await drawn($)).toEqual(ENGINE_ONLY)
  })

  test('one live copy: the status follows each report', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG })
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual([...START_LINES, '✓ in sync'])
    const steps = [[1, '1 out of sync'], [3, '3 out of sync'], [2, '2 out of sync'], [0, '✓ in sync']] as const
    for (const [drift, text] of steps) {
      await reportDrift($, w, drift)
      expect((await bandNodes($)).status.length).toBe(1)
      expect(await bandLines($)).toEqual([...START_LINES, text])
    }
    expect(w.band.length).toBe(1)
  })

  test('a catalog edit while shown: the first line follows', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG })
    // every check fails, so no report lands: only the catalog re-read can recompute the view
    w.engine.mode = 'fail'
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual(START_LINES)
    const content = catalogText().replace('"First"', '"Renamed"')
    await $.tool.call({ tool: 'Write', file_path: `${w.root}/${CATALOG_REL}`, content })
    await w.clock.settle()
    expect((await bandLines($))[0]).toBe('1  Renamed')
  })

  test('checks unavailable while shown: the status says so, dim', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG, hasRunner: false })
    engineDraws(on)
    await start($, w)
    await prompt($, w)
    const { status } = await bandNodes($)
    expect(status.map(t => t.text.trim())).toEqual(['sync checks unavailable'])
    expect(status[0]?.props.dimColor).toBe(true)
  })

  test('Dismiss is final for the session; the next start shows the band again', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG })
    engineDraws(on)
    await start($, w)
    await pressDismiss($)
    await reportDrift($, w, 4)
    expect(await drawn($)).toEqual(ENGINE_ONLY)
    await reportDrift($, w, 0)
    expect(await drawn($)).toEqual(ENGINE_ONLY)
    await start($, w)
    expect(await bandLines($)).toEqual([...START_LINES, '✓ in sync'])
  })

  test('layout and color: items first, truncated at the edge; the status in a theme color', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG })
    engineDraws(on)
    await start($, w)
    const clean = await bandNodes($)
    expect(clean.all.map(t => t.text.trim())).toEqual([...START_LINES, '✓ in sync'])
    expect(clean.items.map(t => t.props.wrap)).toEqual(['truncate-end', 'truncate-end'])
    expect(clean.status[0]?.props.color).toBe('success')
    await reportDrift($, w, 2)
    expect((await bandNodes($)).status[0]?.props.color).toBe('warning')
  })

  test('height: todo.notice.items 1 draws one item line', async ($, on) => {
    const w = world(on, { config: { todo: { folder: TODO_DIR, notice: { items: 1 } } }, hasRunner: false })
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual(['1  First'])
  })

  test('height: todo.top_n 2 still draws 3 notice items', async ($, on) => {
    const config = { todo: { folder: TODO_DIR, top_n: 2, notice: { items: 3 } } }
    const w = world(on, { config, catalog: catalogOf(5), hasRunner: false })
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual(['1  Item 1', '2  Item 2', '3  Item 3'])
  })

  for (const [label, config] of [['band', BANNER_CONFIG], ['toast', TOAST_CONFIG]] as const) {
    test(`an empty view shows nothing (${label})`, async ($, on) => {
      const w = world(on, { config, catalog: '{"counts": 1}', hasRunner: false })
      engineDraws(on)
      await start($, w)
      expect([await drawn($), w.toasts]).toEqual([ENGINE_ONLY, []])
      await prompt($, w)
      expect([await drawn($), w.toasts]).toEqual([ENGINE_ONLY, []])
    })
  }

  test('a shown view that turns empty draws nothing, not a bare Dismiss', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG })
    w.engine.mode = 'fail'
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual(START_LINES)
    await breakCatalog(w)
    await $.tool.call({ tool: 'Write', file_path: `${w.root}/docs/PLANS/a.md`, content: '- [ ] x' })
    await w.clock.settle()
    expect(await drawn($)).toEqual(ENGINE_ONLY)
  })

  test('the default style is the band, no toast', async ($, on) => {
    const w = world(on, { hasRunner: false })
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual(START_LINES)
    expect(w.toasts).toEqual([])
  })

  test('a session start hides the band; an empty start view keeps it hidden', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG, hasRunner: false })
    engineDraws(on)
    await start($, w)
    expect(await bandLines($)).toEqual(START_LINES)
    await breakCatalog(w)
    await start($, w)
    await prompt($, w)
    expect(await drawn($)).toEqual(ENGINE_ONLY)
  })
})
