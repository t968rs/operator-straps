import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import { MAX_NOTICES } from './band'
import { CATALOG_LINE, CATALOG_REL, start, world } from './testWorld'

const SURFACES = ['terminal', 'desktop'] as const

const bandOn = (surface: (typeof SURFACES)[number], hasSurvey = false) => ({
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

async function bandText($: Engine, surface: (typeof SURFACES)[number]): Promise<string | undefined> {
  const ui = await $.ui.mount(bandOn(surface))
  const line = await ui.find({ type: 'Text', text: /TODO/ })
  await ui.unmount()
  return line?.text
}

describe('the band above the prompt', () => {
  for (const surface of SURFACES) {
    test(`${surface}: the start summary stays until Dismiss is pressed`, async ($, on) => {
      const w = world(on, { hasRunner: false })
      engineDraws(on)
      await start($, w)
      expect(await bandText($, surface)).toContain(CATALOG_LINE)
      const ui = await $.ui.mount(bandOn(surface))
      await ui.press({ key: 'dismiss' })
      await ui.unmount()
      expect(await bandText($, surface)).toBeUndefined()
    })

    test(`${surface}: a survey takes the band`, async ($, on) => {
      const w = world(on, { hasRunner: false })
      engineDraws(on)
      await start($, w)
      const ui = await $.ui.mount(bandOn(surface, true))
      expect(await ui.find({ type: 'Text', text: /TODO/ })).toBeUndefined()
      await ui.unmount()
    })
  }

  test('nothing shows in an inactive project', async ($, on) => {
    const w = world(on, { config: '{"todo": {"folder": null}}' })
    engineDraws(on)
    await start($, w)
    expect(await bandText($, 'terminal')).toBeUndefined()
  })

  test(`the newest ${MAX_NOTICES} notices, oldest first`, async ($, on) => {
    const w = world(on)
    engineDraws(on)
    await start($, w)
    for (const drift of [1, 2, 3]) {
      w.engine.drift = drift
      w.engine.byRule = { P1: drift }
      await $.tool.call({ tool: 'Write', file_path: `${w.root}/${CATALOG_REL}`, content: '{}' })
      await w.clock.settle()
    }
    const ui = await $.ui.mount(bandOn('terminal'))
    const lines = (await ui.findAll({ type: 'Text', text: /TODO/ })).map(t => t.text.trim())
    await ui.unmount()
    expect(w.notices.length).toBeGreaterThan(MAX_NOTICES)
    expect(lines).toEqual(w.notices.slice(-MAX_NOTICES))
  })

  test('a session start replaces the notices', async ($, on) => {
    const w = world(on, { hasRunner: false })
    engineDraws(on)
    await start($, w)
    await start($, w)
    const ui = await $.ui.mount(bandOn('terminal'))
    const lines = await ui.findAll({ type: 'Text', text: /TODO/ })
    await ui.unmount()
    expect(lines.length).toBe(1)
  })
})
