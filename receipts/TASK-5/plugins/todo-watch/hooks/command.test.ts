import { describe, expect, test } from 'claude-code/testing'

import { COMMAND, COMMAND_DESCRIPTION } from './command'
import { CATALOG_LINE, CATALOG_REL, catalogOf, prompt, runTodo, start, TODO_DIR, world } from './testWorld'

describe('/todo', () => {
  test('registered once at session start in an active project', async ($, on) => {
    const w = world(on)
    await start($, w)
    await start($, w)
    expect(w.commands).toEqual([COMMAND])
    expect(w.descriptions).toEqual([COMMAND_DESCRIPTION])
  })

  test('summary line, top-N table, then each finding', async ($, on) => {
    const w = world(on)
    w.engine.drift = 2
    w.engine.byRule = { T2: 1, P1: 1 }
    await start($, w)
    expect((await runTodo($)).split('\n')).toEqual([
      `${CATALOG_LINE} · 2 out of sync`,
      '',
      '| Rank | Id | Status | Score | Title |',
      '|---:|---|---|---:|---|',
      '| 1 | TODO-001 | OPEN | 88 | First |',
      '| 2 | TODO-002 | PARTIAL | 70 | Second |',
      '',
      'sync drift 2: P1=1 T2=1',
      'T2 error docs/PLANS/a_PIP.md:3 X-1: T2 broke',
      'P1 error docs/PLANS/a_PIP.md:3 X-1: P1 broke',
    ])
  })

  test('a clean report says sync clean', async ($, on) => {
    const w = world(on)
    await start($, w)
    expect((await runTodo($)).split('\n\n')).toEqual([
      `${CATALOG_LINE} · sync clean`, expect.stringContaining('| 1 | TODO-001 |'), 'sync clean',
    ])
  })

  test('top_n limits the table', async ($, on) => {
    const w = world(on, { config: { todo: { folder: TODO_DIR, top_n: 1 } } })
    await start($, w)
    const text = await runTodo($)
    expect(text).toContain('| 1 | TODO-001 |')
    expect(text).not.toContain('TODO-002')
  })

  test('a smaller todo.notice.items never trims the table: /todo keeps top_n rows', async ($, on) => {
    const config = { todo: { folder: TODO_DIR, top_n: 5, notice: { items: 1 } } }
    const w = world(on, { config, catalog: catalogOf(5), hasRunner: false })
    await start($, w)
    expect(w.band).toEqual(['1  Item 1'])
    const text = await runTodo($)
    expect(text).toContain('| 1 | TODO-1 |')
    expect(text).toContain('| 5 | TODO-5 |')
  })

  test('the catalog is re-read when its mtime moved', async ($, on) => {
    const w = world(on, { hasRunner: false })
    await start($, w)
    await prompt($, w)
    w.setFile(`/repo/${CATALOG_REL}`, JSON.stringify({ counts: { items: 1 }, items: [] }))
    expect((await runTodo($)).split('\n\n')).toEqual(['TODO 1', 'sync checks unavailable'])
  })

  test('a refused registration leaves /todo to whoever else answers it', async ($, on) => {
    const w = world(on)
    w.isRegisterRefused = true
    on('command.run', () => ({ text: 'beneath' }))
    await start($, w)
    expect(await runTodo($)).toBe('beneath')
  })
})
