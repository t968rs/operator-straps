import { describe, expect, test } from 'claude-code/testing'

import { CATALOG_LINE, checkRuns, CONFIG, keyOf, prompt, runTodo, start, world } from './testWorld'

/** Root resolution, seen through the hooks: the start toast and the check run's `--project`. */

describe('resolveWatch', () => {
  test('a cwd below the root finds the root without spawning a process', async ($, on) => {
    const w = world(on, { cwd: '/repo/sub/dir', env: {} })
    await start($, w)
    expect(w.toasts).toEqual([CATALOG_LINE])
    expect(w.runs.filter(argv => argv[2] !== 'check')).toEqual([])
    expect(checkRuns(w).length).toBe(1)
  })

  test('a cwd outside any project falls back to CLAUDE_PROJECT_DIR', async ($, on) => {
    const w = world(on, { cwd: '/elsewhere/x', env: { CLAUDE_PROJECT_DIR: '/repo' } })
    await start($, w)
    expect(w.toasts).toEqual([CATALOG_LINE])
  })

  test('a Windows-style cwd and project dir with backslashes', async ($, on) => {
    const w = world(on, { root: 'C:/repo', cwd: 'C:\\repo\\sub\\', env: { CLAUDE_PROJECT_DIR: 'C:\\repo\\' } })
    await start($, w)
    expect(w.toasts).toEqual([CATALOG_LINE])
  })

  test('the nearest harness.json wins', async ($, on) => {
    const w = world(on, { cwd: '/repo/sub' })
    w.setFile('/repo/sub/.claude/harness.json', JSON.stringify({ todo: { catalog: null } }))
    await start($, w)
    expect([w.toasts, w.commands, w.runs]).toEqual([[], [], []])
  })

  test('the root is searched once; its harness.json is read afresh each time', async ($, on) => {
    const w = world(on, { cwd: '/repo/sub' })
    await start($, w)
    await prompt($, w)
    await prompt($, w)
    const asked = (path: string): number => w.reads.filter(p => keyOf(p) === keyOf(path)).length
    expect(asked('/repo/sub/.claude/harness.json')).toBe(1)
    expect(asked('/repo/.claude/harness.json')).toBeGreaterThan(2)
  })

  test('turning todo.catalog off mid-session stands the watch down', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.setFile('/repo/.claude/harness.json', JSON.stringify({ ...CONFIG, todo: { catalog: null } }))
    expect(await prompt($, w)).toEqual([])
    expect(await runTodo($)).toBe('todo-watch: TODO state unavailable.')
  })

  test('an unreadable harness.json is no project', async ($, on) => {
    const w = world(on, { config: '{ not json' })
    await start($, w)
    expect([w.toasts, w.commands, w.runs]).toEqual([[], [], []])
  })
})
