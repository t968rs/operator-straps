import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import {
  armedSwitch,
  FIRED_KEY,
  HOOK_PATH,
  HOOK_SCHEMA_VERSION,
  hookFileOf,
  markFired,
  MAX_GOAL_CHARS,
} from './session_hook'

const GOAL = 'TODO todo-af2e (x) is retired'
const hook = { closed_by: 'retired', desc: 'catalog item model', start_time: 1763600000.5, todo_id: 'todo-af2e' }
const file = (extra: Record<string, unknown> = {}, h: Record<string, unknown> = {}): string =>
  JSON.stringify({ version: HOOK_SCHEMA_VERSION, hook: { ...hook, goal: GOAL, ...h }, fired: null, ...extra })

describe('hookFileOf', () => {
  test('joins root, state dir and the hook path', async () => {
    expect(hookFileOf('C:\\repo\\', '.claude/state/harness')).toBe(`C:/repo/.claude/state/harness/${HOOK_PATH}`)
    expect(hookFileOf('/repo', '/abs/state')).toBe(`/abs/state/${HOOK_PATH}`)
  })
})

describe('armedSwitch', () => {
  test('an armed switch gives its goal, item and start time', async () => {
    expect(armedSwitch(file())).toEqual({ goal: GOAL, todoId: 'todo-af2e', startTime: 1763600000.5 })
  })

  test('a fired, foreign or goal-less switch is not armed', async () => {
    const texts = [file({ [FIRED_KEY]: { at: 1 } }), file({ version: 2 }), file({}, { goal: '  ' }), '{', '[]']
    for (const text of texts) expect(armedSwitch(text)).toBe(null)
  })

  test('the goal is folded and cut to the engine limit', async () => {
    const goal = armedSwitch(file({}, { goal: `a\n b ${'x'.repeat(600)}` }))?.goal ?? ''
    expect(goal.startsWith('a b x')).toBe(true)
    expect(goal.length).toBe(MAX_GOAL_CHARS)
  })

  test('a row-time switch without an item id is armed with a null id', async () => {
    expect(armedSwitch(file({}, { todo_id: null }))?.todoId).toBe(null)
  })
})

describe('markFired', () => {
  test('stamps fired and keeps the rest; the stamped file is no longer armed', async () => {
    const stamped = markFired(file(), 42)
    expect(JSON.parse(stamped)[FIRED_KEY]).toEqual({ at: 42 })
    expect(JSON.parse(stamped).hook.todo_id).toBe('todo-af2e')
    expect(armedSwitch(stamped)).toBe(null)
  })

  test('leaves a non-object text unchanged', async () => {
    expect(markFired('[1]', 42)).toBe('[1]')
  })
})

const ROOT = '/repo'
const SWITCH = `${ROOT}/.claude/state/harness/${HOOK_PATH}`
const NOW_MS = 1_800_000_000_000

type Seen = { goals: string[]; writes: Map<string, string>; toasts: string[]; clock: ReturnType<typeof mock.clock> }

/** A path as the fake disk keys it: forward slashes, no drive (the engine resolves `/repo` to `C:/repo`). */
const keyOf = (p: string): string =>
  p.replace(/\\/g, '/').replace(/^(?:[^]*?\/)?[A-Za-z]:(?=\/|$)/, '').toLowerCase()

/** Answers env, cwd, files, the clock, `/goal` and toasts from memory; `goalFails` refuses the command. */
const world = (on: On, files: Record<string, string>, goalFails = false): Seen => {
  const clock = mock.clock(on, { now: NOW_MS })
  const seen: Seen = { goals: [], writes: new Map(), toasts: [], clock }
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  on('session.cwd', () => ({ value: '' }))
  const disk = new Map(Object.entries(files).map(([path, text]) => [keyOf(path), text]))
  on('fs.read', (_$, e) => {
    const text = seen.writes.get(keyOf(e.path)) ?? disk.get(keyOf(e.path))
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.write', (_$, e) => {
    seen.writes.set(keyOf(e.path), e.text)
    return { value: undefined }
  })
  on('command.run', { command: 'goal' }, (_$, e) => {
    if (goalFails) throw new Error('no goal here')
    seen.goals.push(e.args)
    return { text: 'goal set' }
  })
  on('ui.toast', (_$, e) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('turn.complete', () => ({ text: '' }))
  return seen
}

/** Ends a main-loop turn (a subagent's with `agentId`), then lets the unawaited `fire` settle. */
const endTurn = async ($: Engine, seen: Seen, agentId?: string): Promise<void> => {
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer', agentId })
  for (let i = 0; i < 3; i++) await seen.clock.advance(1)
}

describe('turn.complete fires the switch', () => {
  test('an armed switch queues /goal once with its goal and is stamped fired', async ($, on) => {
    const seen = world(on, { [SWITCH]: file() })
    await endTurn($, seen)
    await endTurn($, seen)
    expect(seen.goals).toEqual([GOAL])
    expect(JSON.parse(seen.writes.get(keyOf(SWITCH)) ?? '{}')[FIRED_KEY]).toEqual({ at: NOW_MS })
  })

  test("a subagent's turn and a fired switch set no goal", async ($, on) => {
    const seen = world(on, { [SWITCH]: file({ [FIRED_KEY]: { at: 1 } }) })
    await endTurn($, seen, 'agent-1')
    await endTurn($, seen)
    expect(seen.goals).toEqual([])
  })

  test('a refused /goal leaves the switch armed and says so once', async ($, on) => {
    const seen = world(on, { [SWITCH]: file() }, true)
    await endTurn($, seen)
    await endTurn($, seen)
    expect(seen.writes.size).toBe(0)
    expect(seen.toasts).toEqual(['session-bookmark: could not set the goal for todo-af2e'])
  })
})
