import type { Engine } from 'claude-code/testing'
import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import {
  armedSwitch,
  FIRED_KEY,
  HOOK_PATH,
  HOOK_SCHEMA_VERSION,
  hookFileOf,
  markFired,
  MAX_GOAL_CHARS,
  SESSION_KEY,
  STAMP_FAILED,
} from './session_hook'

const GOAL = 'TODO todo-af2e (x) is retired'
// session_hook.ts keeps a per-load `tried` set keyed by start_time that outlives each test, so every
// turn.complete test passes its own start_time (1763600000.5 through 1763600009.5 are taken); a reused one
// would let the guard, not the behavior under test, decide whether `/goal` runs.
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
    expect(armedSwitch(file())).toEqual({ goal: GOAL, todoId: 'todo-af2e', startTime: 1763600000.5, sessionId: null })
  })

  test('the arming session is kept; a blank or non-text one reads as any session', async () => {
    expect(armedSwitch(file({ [SESSION_KEY]: 'sess-1' }))?.sessionId).toBe('sess-1')
    for (const id of ['', '  ', 7, null]) expect(armedSwitch(file({ [SESSION_KEY]: id }))?.sessionId).toBe(null)
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

  test('a free-text goal switch without an item id is armed with a null id', async () => {
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
const THIS_SESSION = 'sess-this'

type Seen = { goals: string[]; writes: Map<string, string>; toasts: string[]; clock: ReturnType<typeof mock.clock> }

/**
 * The session folders: `dir` is the cwd and CLAUDE_PROJECT_DIR; `tops` maps a folder to its git top level;
 * `writeFails` refuses every write; `session` is the id `session.id` answers (default `THIS_SESSION`, blank
 * for an id that cannot be read).
 */
type Where = { dir?: string; tops?: Record<string, string>; writeFails?: boolean; session?: string }

/** A path as the fake disk keys it: forward slashes, no drive (the engine resolves `/repo` to `C:/repo`). */
const keyOf = (p: string): string =>
  p.replace(/\\/g, '/').replace(/^(?:[^]*?\/)?[A-Za-z]:(?=\/|$)/, '').toLowerCase()

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** Answers `git rev-parse --show-toplevel` from `tops`; any other folder is no repository. */
const gitWorld = (on: On, tops: Record<string, string>): void => {
  on('process.run', (_$, e) => {
    const top = tops[e.argv[2] ?? '']
    return { value: top === undefined ? ran('', 128) : ran(`${top}\n`) }
  })
}

/** Answers env, cwd, git, files, the clock, `/goal` and toasts from memory; `goalFails` refuses the command. */
const world = (on: On, files: Record<string, string>, goalFails = false, where: Where = {}): Seen => {
  const clock = mock.clock(on, { now: NOW_MS })
  const seen: Seen = { goals: [], writes: new Map(), toasts: [], clock }
  mock.env(on, { CLAUDE_PROJECT_DIR: where.dir ?? ROOT })
  on('session.cwd', () => ({ value: where.dir ?? '' }))
  on('session.id', () => ({ value: where.session ?? THIS_SESSION }))
  gitWorld(on, where.tops ?? {})
  const disk = new Map(Object.entries(files).map(([path, text]) => [keyOf(path), text]))
  on('fs.read', (_$, e) => {
    const text = seen.writes.get(keyOf(e.path)) ?? disk.get(keyOf(e.path))
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.write', (_$, e) => {
    if (where.writeFails === true) return { deny: 'EACCES' }
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

  test("a subagent's turn sets no goal and leaves an armed switch armed", async ($, on) => {
    const seen = world(on, { [SWITCH]: file({}, { start_time: 1763600001.5 }) })
    await endTurn($, seen, 'agent-1')
    expect(seen.goals).toEqual([])
    expect(seen.writes.size).toBe(0)
    await endTurn($, seen)
    expect(seen.goals).toEqual([GOAL])
  })

  test('a fired switch sets no goal on a main-loop turn', async ($, on) => {
    const seen = world(on, { [SWITCH]: file({ [FIRED_KEY]: { at: 1 } }, { start_time: 1763600004.5 }) })
    await endTurn($, seen)
    expect(seen.goals).toEqual([])
  })

  test('a switch under a custom state_dir is found and fires', async ($, on) => {
    const custom = `${ROOT}/custom/state/${HOOK_PATH}`
    const seen = world(on, {
      [`${ROOT}/.claude/harness.json`]: JSON.stringify({ state_dir: 'custom/state' }),
      [custom]: file({}, { start_time: 1763600003.5 }),
    })
    await endTurn($, seen)
    await endTurn($, seen)
    expect(seen.goals).toEqual([GOAL])
  })

  test('a session below the repository top reads the switch under the top level', async ($, on) => {
    const sub = `${ROOT}/sub`
    const seen = world(on, { [SWITCH]: file({}, { start_time: 1763600005.5 }) }, false, {
      dir: sub,
      tops: { [sub]: ROOT },
    })
    await endTurn($, seen)
    expect(seen.goals).toEqual([GOAL])
    expect(JSON.parse(seen.writes.get(keyOf(SWITCH)) ?? '{}')[FIRED_KEY]).toEqual({ at: NOW_MS })
  })

  test('a refused /goal leaves the switch armed and says so once', async ($, on) => {
    const seen = world(on, { [SWITCH]: file({}, { start_time: 1763600002.5 }) }, true)
    await endTurn($, seen)
    await endTurn($, seen)
    expect(seen.writes.size).toBe(0)
    expect(seen.toasts).toEqual(['session-bookmark: could not set the goal for todo-af2e'])
  })

  test('a switch armed by this session fires', async ($, on) => {
    const seen = world(on, { [SWITCH]: file({ [SESSION_KEY]: THIS_SESSION }, { start_time: 1763600007.5 }) })
    await endTurn($, seen)
    expect(seen.goals).toEqual([GOAL])
  })

  test("another session's switch sets no goal and stays armed for that session", async ($, on) => {
    const text = file({ [SESSION_KEY]: 'sess-other' }, { start_time: 1763600008.5 })
    const seen = world(on, { [SWITCH]: text })
    await endTurn($, seen)
    await endTurn($, seen)
    expect(seen.goals).toEqual([])
    expect(seen.writes.size).toBe(0)
    expect(seen.toasts).toEqual([])
  })

  test('a session whose id cannot be read leaves a session-bound switch armed', async ($, on) => {
    const seen = world(on, { [SWITCH]: file({ [SESSION_KEY]: THIS_SESSION }, { start_time: 1763600009.5 }) },
      false, { session: '' })
    await endTurn($, seen)
    expect(seen.goals).toEqual([])
    expect(seen.writes.size).toBe(0)
  })

  test('a goal set whose stamp fails says the goal was set, not refused', async ($, on) => {
    const seen = world(on, { [SWITCH]: file({}, { start_time: 1763600006.5 }) }, false, { writeFails: true })
    await endTurn($, seen)
    expect(seen.goals).toEqual([GOAL])
    expect(seen.toasts).toEqual([`session-bookmark: goal set for todo-af2e; ${STAMP_FAILED}`])
  })
})
