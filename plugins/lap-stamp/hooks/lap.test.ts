import type { Engine, MockClock } from 'claude-code/testing'
import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { ClockState, LapRow } from '../types'
import type { Submission } from './lap'
import { clockFor, isDropped, mergeRows, originKindOf, RANGE_BYTES, textOf, withdrawn, withLine } from './lap'
import { buildRow, parseRows, rowLine } from './row'

/**
 * Engine-level behavior of the lap glue: which host events move the clock, what the laps file and the rows atom
 * hold after a turn, and every way a host call can fail. The glue runs as the plugin's own hooks (register.ts),
 * above the files, env, git, clock, session id, state and core the test answers from memory. The host lets a
 * hook call only the `$` nouns its plugin's scanned hooks module calls, so these tests need register.ts to
 * register `registerLap`.
 */

const ROOT = '/repo'
const HARNESS = `${ROOT}/.claude/harness.json`
const LAPS = `${ROOT}/.claude/state/harness/lap-stamp/laps.jsonl`
const SESSION = 'S1'
const T0 = 1_800_000_000_000

type Files = Map<string, string>
type Seen = {
  files: Files
  /** Paths whose read is refused although they exist. */
  unreadable: Set<string>
  /** Paths a whole read refuses (an answer over the host's cap); ranged byte reads still answer. */
  capped: Set<string>
  /** Paths whose write is refused. */
  unwritable: Set<string>
  writes: string[]
  reads: string[]
  /** Every ranged read, as `offset+length`. */
  ranges: string[]
  /** The last value written to each 'lap-stamp' state key. */
  state: Map<string, unknown>
  session: string
  /** Core drops the next prompt while true. */
  isDropping: boolean
  /** How many times git ran. */
  gitRuns: number
  clock: MockClock
}

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** A host path as the test keys it: Windows hosts hand the hooks `C:\repo\...` for `/repo/...`. */
const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')

const utf8 = (text: string): Uint8Array => new TextEncoder().encode(text)

/** Standard base64 of some bytes. */
const base64Of = (bytes: Uint8Array): string => {
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin)
}

/** Host calls refused for a whole test. */
type Refused = { sessionId?: boolean; clock?: boolean; state?: boolean }

/** Stands in for the mocked clock where `$.clock.now` is refused: nothing moves, nothing waits. */
const STILL_CLOCK: MockClock = {
  now: () => T0,
  advance: async () => undefined,
  set: async () => undefined,
  settle: async () => undefined,
  sleep: async () => undefined,
}

/** A mocked clock at T0, or a refused one. */
const clockOf = (on: On, isRefused: boolean): MockClock => {
  if (!isRefused) return mock.clock(on, { now: T0 })
  on('clock.now', () => ({ deny: 'no clock' }))
  return STILL_CLOCK
}

/** Core's answers to the events the glue hooks; the kit answers `session.append` itself. */
const answerCore = (on: On, seen: Seen): void => {
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.attach', (_$, e) => ({ clientId: e.clientId }))
  on('prompt.submit', (_$, e) => (seen.isDropping ? { drop: 'held' } : { text: e.text, context: e.context }))
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
}

/** Reads from memory: whole text, or a byte range; refused for unreadable paths and whole reads of capped ones. */
const answerReads = (on: On, seen: Seen): void => {
  on('fs.read', (_$, e) => {
    const path = slash(e.path)
    seen.reads.push(path)
    if (seen.unreadable.has(path)) return { deny: `EBUSY ${e.path}` }
    const text = seen.files.get(path)
    if (text === undefined) return { deny: `ENOENT ${e.path}` }
    if (e.offset === undefined && e.length === undefined) {
      return seen.capped.has(path) ? { deny: `EFBIG ${e.path}` } : { value: text }
    }
    const offset = e.offset ?? 0
    seen.ranges.push(`${offset}+${e.length ?? 0}`)
    const slice = utf8(text).subarray(offset, offset + (e.length ?? 0))
    return { value: { base64: base64Of(slice) } }
  })
  on('fs.stat', (_$, e) => {
    const text = seen.files.get(slash(e.path))
    if (text === undefined) return { deny: `ENOENT ${e.path}` }
    return { value: { kind: 'file', size: utf8(text).length, mtimeMs: 1, isLink: false } }
  })
  on('fs.exists', (_$, e) => ({ value: seen.files.has(slash(e.path)) }))
}

/** Files, env, git, clock, session id, state and core beneath the glue. */
const world = (on: On, config: string | null = '{}', refused: Refused = {}): Seen => {
  const seen: Seen = {
    files: new Map(), unreadable: new Set(), capped: new Set(), unwritable: new Set(), writes: [], reads: [],
    ranges: [], state: new Map(), session: SESSION, isDropping: false, gitRuns: 0, clock: clockOf(on, refused.clock === true),
  }
  answerCore(on, seen)
  answerReads(on, seen)
  if (config !== null) seen.files.set(HARNESS, config)
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  on('session.cwd', () => ({ value: ROOT }))
  on('session.id', () => (refused.sessionId ? { deny: 'no session' } : { value: seen.session }))
  on('process.run', () => {
    seen.gitRuns += 1
    return { value: ran('', 128) }
  })
  on('fs.write', (_$, e) => {
    const path = slash(e.path)
    if (seen.unwritable.has(path)) return { deny: `EACCES ${e.path}` }
    seen.writes.push(path)
    seen.files.set(path, e.text)
    return { value: undefined }
  })
  on('state.set', (_$, e, next) => {
    if (e.plugin !== 'lap-stamp') return next(e)
    if (refused.state) return { deny: 'state store full' }
    seen.state.set(e.key, e.value)
    return next(e)
  })
  return seen
}

const start = ($: Engine) => $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
const attach = ($: Engine) => $.session.attach({ surface: 'mobile', clientId: 'mobile:default' })
type Kind = 'composer' | 'bridge' | 'task-notification' | 'scheduled-trigger'
const press = ($: Engine, kind: Kind = 'composer', turnId?: string) =>
  $.prompt.submit({ text: 'go', wait: false, origin: { kind }, ...(turnId === undefined ? {} : { turnId }) })
const begin = ($: Engine, turnId: string, agentId?: string) =>
  $.turn.start({ text: '', turnId, ...(agentId === undefined ? {} : { agentId }) } as never)
const end = ($: Engine, turnId: string, answer = 'the reply', agentId?: string) =>
  $.turn.complete({
    answer, durationMs: 1, isAborted: false, turnId, reason: 'answer',
    ...(agentId === undefined ? {} : { agentId }),
  } as never)
/** A row of the press's text through `door`, from a lap-press origin unless `kind`; main loop unless `agentId`. */
const appended = ($: Engine, door: 'delivery' | 'queue' | 'prompt', kind = 'composer', agentId?: string) =>
  $.session.append({
    message: { type: 'user', role: 'user', content: [{ type: 'text', text: 'go' }] },
    door,
    origin: { kind },
    uuid: `u-${door}-${kind}${agentId === undefined ? '' : `-${agentId}`}`,
    ...(agentId === undefined ? {} : { agentId }),
  } as Parameters<Engine['session']['append']>[0])

const fileRows = (seen: Seen): LapRow[] => parseRows(seen.files.get(LAPS) ?? '', SESSION)
const atomRows = (seen: Seen): LapRow[] => (seen.state.get('rows') as LapRow[] | undefined) ?? []
const lines = (seen: Seen): string[] => (seen.files.get(LAPS) ?? '').split('\n').filter(l => l !== '')

/** One stopped turn's row as the file would hold it, for seeding a restart. */
const storedRow = (over: Partial<LapRow> = {}): LapRow => ({
  ...buildRow({
    session: SESSION, turn: 'old', reason: 'answer', answer: 'earlier', offsetMin: 0,
    timing: {
      kind: 'prompt', wake: null, promptAt: T0 - 60_000, startAt: T0 - 59_000, stopAt: T0 - 30_000,
      lastPromptAt: T0 - 60_000, lapMs: 30_000, sincePromptMs: null,
    },
  }),
  ...over,
})

/** What the host handed back for a turn's prompt and its stop. */
type Results = { pressed: unknown; ended: unknown }

/** A prompt pressed at T0, its turn started 1 s later and stopped `lapS` seconds after the press. */
const promptedTurn = async ($: Engine, seen: Seen, turnId = 't1', lapS = 5): Promise<Results> => {
  const pressed = await press($)
  await seen.clock.advance(1000)
  await begin($, turnId)
  await seen.clock.advance(lapS * 1000 - 1000)
  const ended = await end($, turnId)
  await seen.clock.settle()
  return { pressed, ended }
}

const textIn = (r: unknown): unknown => (typeof r === 'object' && r !== null ? (r as { text?: unknown }).text : r)

/** The glue changed nothing the host returned: the prompt entered as typed and the answer came back as given. */
const expectUntouched = (r: Results, answer = 'the reply'): void => {
  expect(isDropped(r.pressed)).toBe(false)
  expect(textIn(r.pressed)).toBe('go')
  expect(textIn(r.ended)).toBe(answer)
}

const clockIn = (seen: Seen): ClockState | undefined => seen.state.get('clock') as ClockState | undefined

describe('prompted turns', () => {
  test('a prompted turn appends one row with kind prompt', async ($, on) => {
    const seen = world(on)
    await start($)
    expectUntouched(await promptedTurn($, seen))
    const rows = fileRows(seen)
    expect(rows).toHaveLength(1)
    const [row] = rows
    expect(row?.kind).toBe('prompt')
    expect(row?.turn).toBe('t1')
    expect(row?.session).toBe(SESSION)
    expect(row?.lap_ms).toBe(5000)
    expect(row?.reason).toBe('answer')
    expect(Date.parse(row?.prompt_at ?? '')).toBe(T0)
    expect(Date.parse(row?.start_at ?? '')).toBe(T0 + 1000)
    expect(row?.answer_len).toBe('the reply'.length)
    expect(seen.files.get(LAPS)?.endsWith('\n')).toBe(true)
    expect(atomRows(seen)).toEqual(rows)
  })

  test('a bridge prompt is a lap press too', async ($, on) => {
    const seen = world(on)
    await start($)
    await press($, 'bridge')
    await seen.clock.advance(2000)
    await begin($, 't1')
    await end($, 't1')
    await seen.clock.settle()
    expect(fileRows(seen)[0]?.kind).toBe('prompt')
  })

  test('a second turn appends a second line and keeps the first', async ($, on) => {
    const seen = world(on)
    await start($)
    await promptedTurn($, seen, 't1')
    await promptedTurn($, seen, 't2', 3)
    expect(lines(seen)).toHaveLength(2)
    expect(fileRows(seen).map(r => [r.turn, r.lap_ms])).toEqual([['t1', 5000], ['t2', 3000]])
    expect(atomRows(seen).map(r => r.turn)).toEqual(['t1', 't2'])
  })

  test('the turn works without a session.start: the first event activates the glue', async ($, on) => {
    const seen = world(on)
    await promptedTurn($, seen)
    expect(fileRows(seen)).toHaveLength(1)
  })

  test('a malformed line already in the file is kept, never rewritten', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, 'not json')
    await start($)
    await promptedTurn($, seen)
    expect(lines(seen)[0]).toBe('not json')
    expect(fileRows(seen)).toHaveLength(1)
  })

  test('a project outside git asks git once, not at every stop', async ($, on) => {
    const seen = world(on)
    await start($)
    await promptedTurn($, seen, 't1')
    await promptedTurn($, seen, 't2')
    expect(fileRows(seen)).toHaveLength(2)
    expect(seen.gitRuns).toBe(1)
  })

  test('the laps folder follows state_dir', async ($, on) => {
    const seen = world(on, JSON.stringify({ state_dir: 'var/state' }))
    await start($)
    await promptedTurn($, seen)
    expect(seen.writes).toEqual([`${ROOT}/var/state/lap-stamp/laps.jsonl`])
  })
})

describe('delivery into a running turn (D2)', () => {
  test('a press delivered into the running turn restarts its lap', async ($, on) => {
    const seen = world(on)
    await start($)
    await begin($, 't1')
    await seen.clock.advance(10_000)
    await press($, 'composer', 't1')
    await appended($, 'delivery')
    await seen.clock.advance(4000)
    await end($, 't1')
    await seen.clock.settle()
    const [row] = fileRows(seen)
    expect(row?.kind).toBe('prompt')
    expect(row?.lap_ms).toBe(4000)
  })

  test('a queue row is not a delivery: the press stays pending and anchors the next turn', async ($, on) => {
    const seen = world(on)
    await start($)
    await begin($, 't1')
    await seen.clock.advance(10_000)
    await press($, 'composer', 't1')
    await appended($, 'queue')
    await seen.clock.advance(4000)
    await end($, 't1')
    await begin($, 't2')
    await seen.clock.advance(1000)
    await end($, 't2')
    await seen.clock.settle()
    expect(fileRows(seen).map(r => [r.turn, r.kind, r.lap_ms])).toEqual([
      ['t1', 'wake', 14_000],
      ['t2', 'prompt', 5000],
    ])
  })

  test('a press with no delivery report anchors the next turn, not the running one', async ($, on) => {
    const seen = world(on)
    await start($)
    await begin($, 't1')
    await seen.clock.advance(10_000)
    await press($, 'composer', 't1')
    await appended($, 'prompt')
    await appended($, 'delivery', 'task-notification')
    await seen.clock.advance(4000)
    await end($, 't1')
    await begin($, 't2')
    await seen.clock.advance(1000)
    await end($, 't2')
    await seen.clock.settle()
    expect(fileRows(seen).map(r => [r.turn, r.kind, r.lap_ms])).toEqual([
      ['t1', 'wake', 14_000],
      ['t2', 'prompt', 5000],
    ])
  })

  test('a subagent delivery row leaves the running main turn alone', async ($, on) => {
    const seen = world(on)
    await start($)
    await begin($, 't1')
    await seen.clock.advance(10_000)
    await press($, 'composer', 't1')
    await appended($, 'delivery', 'composer', 'agent-1')
    await seen.clock.advance(4000)
    await end($, 't1')
    await seen.clock.settle()
    expect(fileRows(seen).map(r => [r.turn, r.kind, r.lap_ms])).toEqual([['t1', 'wake', 14_000]])
  })
})

describe('wake turns (D4)', () => {
  test('a task-notification turn appends a wake row with since_prompt', async ($, on) => {
    const seen = world(on)
    await start($)
    await promptedTurn($, seen, 't1', 5)
    await seen.clock.advance(60_000)
    await press($, 'task-notification')
    await begin($, 't2')
    await seen.clock.advance(8000)
    await end($, 't2')
    await seen.clock.settle()
    const wake = fileRows(seen)[1]
    expect(wake?.kind).toBe('wake')
    expect(wake?.wake).toBe('task-notification')
    expect(wake?.prompt_at).toBeNull()
    expect(wake?.lap_ms).toBe(8000)
    expect(wake?.since_prompt_ms).toBe(5000 + 60_000 + 8000)
    expect(Date.parse(wake?.last_prompt_at ?? '')).toBe(T0)
  })

  test('a wake turn with no prompt in the session has a null since_prompt', async ($, on) => {
    const seen = world(on)
    await start($)
    await begin($, 't1')
    await seen.clock.advance(3000)
    await end($, 't1', '')
    await seen.clock.settle()
    const [row] = fileRows(seen)
    expect(row?.kind).toBe('wake')
    expect(row?.wake).toBeNull()
    expect(row?.since_prompt_ms).toBeNull()
    expect(row?.answer_hash).toBeNull()
    expect(row?.answer_len).toBe(0)
  })
})

describe('the main loop only', () => {
  test('a subagent turn appends nothing and leaves the main clock alone', async ($, on) => {
    const seen = world(on)
    await start($)
    await press($)
    await begin($, 'a1', 'agent-1')
    await seen.clock.advance(2000)
    await end($, 'a1', 'sub reply', 'agent-1')
    await seen.clock.settle()
    expect(seen.writes).toEqual([])
    expect(atomRows(seen)).toEqual([])
    await begin($, 't1')
    await seen.clock.advance(1000)
    await end($, 't1')
    await seen.clock.settle()
    expect(fileRows(seen).map(r => [r.turn, r.kind, r.lap_ms])).toEqual([['t1', 'prompt', 3000]])
  })

  test('a stop for a turn that never started writes nothing', async ($, on) => {
    const seen = world(on)
    await start($)
    await end($, 'stray')
    await seen.clock.settle()
    expect(seen.writes).toEqual([])
  })
})

describe('fail open (D10)', () => {
  test('a refused write keeps the atom row and throws nothing', async ($, on) => {
    const seen = world(on)
    seen.unwritable.add(LAPS)
    await start($)
    expectUntouched(await promptedTurn($, seen))
    expect(seen.files.has(LAPS)).toBe(false)
    expect(atomRows(seen).map(r => r.turn)).toEqual(['t1'])
  })

  test('a laps file that exists but cannot be read is never overwritten', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, `${rowLine(storedRow())}\n`)
    seen.unreadable.add(LAPS)
    await start($)
    await promptedTurn($, seen)
    expect(seen.writes).toEqual([])
    expect(lines(seen)).toHaveLength(1)
    expect(atomRows(seen).map(r => r.turn)).toEqual(['t1'])
  })

  test('a refused session id writes no row and throws nothing', async ($, on) => {
    const seen = world(on, '{}', { sessionId: true })
    await start($)
    expectUntouched(await promptedTurn($, seen))
    expect(seen.writes).toEqual([])
    expect(atomRows(seen)).toEqual([])
  })

  test('a refused clock moves nothing and throws nothing', async ($, on) => {
    const seen = world(on, '{}', { clock: true })
    await start($)
    const pressed = await press($)
    await begin($, 't1')
    const ended = await end($, 't1')
    await seen.clock.settle()
    expectUntouched({ pressed, ended })
    expect(seen.writes).toEqual([])
  })

  test('a refused state store changes nothing the host returned and throws nothing', async ($, on) => {
    const seen = world(on, '{}', { state: true })
    await start($)
    expectUntouched(await promptedTurn($, seen))
    // The clock lives in state: with every set refused no turn ever runs, so no row reaches the file.
    expect(seen.writes).toEqual([])
  })

  test('a harness.json read refused mid-session keeps the project: no turn is lost', async ($, on) => {
    const seen = world(on)
    await start($)
    seen.unreadable.add(HARNESS)
    await promptedTurn($, seen, 't1')
    await promptedTurn($, seen, 't2')
    expect(fileRows(seen).map(r => r.turn)).toEqual(['t1', 't2'])
  })

  test('a harness.json removed mid-session deactivates the glue', async ($, on) => {
    const seen = world(on)
    await start($)
    await promptedTurn($, seen, 't1')
    seen.files.delete(HARNESS)
    await promptedTurn($, seen, 't2')
    expect(fileRows(seen).map(r => r.turn)).toEqual(['t1'])
  })
})

describe('a laps file over the host read cap', () => {
  /** A malformed line whose two-byte character straddles the first range boundary, then a stored row. */
  const bigText = (): string => `${'x'.repeat(RANGE_BYTES - 1)}\u00e9\n${rowLine(storedRow())}\n`

  test('a whole read refused above the cap still appends, reading in ranges', async ($, on) => {
    const seen = world(on)
    const before = bigText()
    seen.files.set(LAPS, before)
    seen.capped.add(LAPS)
    await start($)
    await promptedTurn($, seen)
    expect(seen.ranges.length).toBeGreaterThan(1)
    const after = seen.files.get(LAPS) ?? ''
    expect(after.startsWith(before)).toBe(true)
    expect(fileRows(seen).map(r => r.turn)).toEqual(['old', 't1'])
  })

  test('the rows load at start through ranges', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, bigText())
    seen.capped.add(LAPS)
    await start($)
    await seen.clock.settle()
    expect(atomRows(seen).map(r => r.turn)).toEqual(['old'])
    expect(clockIn(seen)?.lastPromptAt).toBe(T0 - 60_000)
  })
})

describe('a dropped prompt (D2)', () => {
  test('a dropped press is taken back: the next turn is a wake', async ($, on) => {
    const seen = world(on)
    await start($)
    seen.isDropping = true
    const pressed = await press($)
    seen.isDropping = false
    expect(isDropped(pressed)).toBe(true)
    await begin($, 't1')
    await seen.clock.advance(2000)
    await end($, 't1')
    await seen.clock.settle()
    expect(fileRows(seen).map(r => [r.turn, r.kind])).toEqual([['t1', 'wake']])
    expect(clockIn(seen)?.pending).toEqual([])
  })

  test('a dropped non-press submission restores the wake reason before it', async ($, on) => {
    const seen = world(on)
    await start($)
    await press($, 'task-notification')
    seen.isDropping = true
    await press($, 'scheduled-trigger')
    seen.isDropping = false
    await begin($, 't1')
    await seen.clock.advance(2000)
    await end($, 't1')
    await seen.clock.settle()
    expect(fileRows(seen).map(r => [r.turn, r.wake])).toEqual([['t1', 'task-notification']])
  })
})

describe('restart (D9)', () => {
  test('a restart reads the rows back into the atom and seeds since prompt', async ($, on) => {
    const seen = world(on)
    const other = storedRow({ session: 'S0', turn: 'other' })
    seen.files.set(LAPS, `${rowLine(other)}\n${rowLine(storedRow())}\n`)
    await start($)
    await seen.clock.settle()
    expect(atomRows(seen).map(r => r.turn)).toEqual(['old'])
    expect((seen.state.get('session') as string | null | undefined)).toBe(SESSION)
    const clock = seen.state.get('clock') as ClockState | undefined
    expect(clock?.lastPromptAt).toBe(T0 - 60_000)
    await begin($, 't1')
    await seen.clock.advance(2000)
    await end($, 't1')
    await seen.clock.settle()
    const wake = fileRows(seen)[1]
    expect(wake?.kind).toBe('wake')
    expect(wake?.since_prompt_ms).toBe(62_000)
    expect(lines(seen)[0]).toBe(rowLine(other))
  })

  test('session.attach reads the file too', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, `${rowLine(storedRow())}\n`)
    await attach($)
    await seen.clock.settle()
    expect(atomRows(seen).map(r => r.turn)).toEqual(['old'])
  })

  test('an unreadable file at start leaves the atom empty and throws nothing', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, `${rowLine(storedRow())}\n`)
    seen.unreadable.add(LAPS)
    await start($)
    await seen.clock.settle()
    expect(atomRows(seen)).toEqual([])
  })

  test('a new session id loads the rows of that session before appending', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, `${rowLine(storedRow({ session: 'S2', turn: 's2-old' }))}\n`)
    await start($)
    await promptedTurn($, seen, 't1')
    seen.session = 'S2'
    await promptedTurn($, seen, 't2')
    expect(atomRows(seen).map(r => r.turn)).toEqual(['s2-old', 't2'])
    expect(seen.state.get('session')).toBe('S2')
    expect(clockIn(seen)?.lastPromptAt).toBe(T0 + 5000)
  })

  test('a switched session rebuilds the clock from its own rows: no stale since prompt', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, `${rowLine(storedRow({ session: 'S2', turn: 's2-old' }))}\n`)
    await start($)
    await promptedTurn($, seen, 't1')
    await press($, 'task-notification')
    seen.session = 'S2'
    await begin($, 't2')
    await seen.clock.advance(2000)
    await end($, 't2')
    await seen.clock.settle()
    const wake = parseRows(seen.files.get(LAPS) ?? '', 'S2')[1]
    expect(wake?.kind).toBe('wake')
    expect(Date.parse(wake?.last_prompt_at ?? '')).toBe(T0 - 60_000)
    expect(wake?.since_prompt_ms).toBe(T0 + 7000 - (T0 - 60_000))
    const clock = clockIn(seen)
    expect(clock?.lastPromptAt).toBe(T0 - 60_000)
    expect(clock?.consumedAt).toBe(T0 - 60_000)
    expect(clock?.pendingWake).toBeNull()
  })

  test('a switched session with no rows of its own has no prompt behind its wake turn', async ($, on) => {
    const seen = world(on)
    await start($)
    await promptedTurn($, seen, 't1')
    seen.session = 'S3'
    await begin($, 't2')
    await seen.clock.advance(2000)
    await end($, 't2')
    await seen.clock.settle()
    const [wake] = parseRows(seen.files.get(LAPS) ?? '', 'S3')
    expect(wake?.last_prompt_at).toBeNull()
    expect(wake?.since_prompt_ms).toBeNull()
    expect(clockIn(seen)?.lastPromptAt).toBeNull()
  })

  test('a session.start with a new session id drops the old session\'s prompt: no since prompt', async ($, on) => {
    const seen = world(on)
    await start($)
    await promptedTurn($, seen, 't1')
    seen.session = 'S3'
    await start($)
    await seen.clock.settle()
    await begin($, 't2')
    await seen.clock.advance(2000)
    await end($, 't2')
    await seen.clock.settle()
    const [wake] = parseRows(seen.files.get(LAPS) ?? '', 'S3')
    expect(wake?.kind).toBe('wake')
    expect(wake?.last_prompt_at).toBeNull()
    expect(wake?.since_prompt_ms).toBeNull()
    expect(clockIn(seen)?.lastPromptAt).toBeNull()
  })

  test('a session.attach with a new session id rebuilds the clock from that session\'s rows', async ($, on) => {
    const seen = world(on)
    seen.files.set(LAPS, `${rowLine(storedRow({ session: 'S2', turn: 's2-old' }))}\n`)
    await start($)
    await promptedTurn($, seen, 't1')
    seen.session = 'S2'
    await attach($)
    await seen.clock.settle()
    const clock = clockIn(seen)
    expect(clock?.lastPromptAt).toBe(T0 - 60_000)
    expect(clock?.consumedAt).toBe(T0 - 60_000)
    expect(clock?.pendingWake).toBeNull()
  })
})

describe('activation', () => {
  test('no harness.json, no file and no rows', async ($, on) => {
    const seen = world(on, null)
    await start($)
    await promptedTurn($, seen)
    expect(seen.writes).toEqual([])
    expect(seen.files.has(LAPS)).toBe(false)
    expect(atomRows(seen)).toEqual([])
  })
})

describe('withLine', () => {
  test('an empty file gets the line and a line ending', () => {
    expect(withLine('', 'a')).toBe('a\n')
  })

  test('a file ending in a line ending gets the line after it', () => {
    expect(withLine('x\n', 'a')).toBe('x\na\n')
    expect(withLine('x\r\n', 'a')).toBe('x\r\na\n')
  })

  test('a file whose last line is not ended gets it ended first', () => {
    expect(withLine('x', 'a')).toBe('x\na\n')
  })
})

describe('mergeRows', () => {
  test('the file rows come first, then held rows the file lacks, by turn id', () => {
    const a = storedRow({ turn: 'a' })
    const b = storedRow({ turn: 'b' })
    const c = storedRow({ turn: 'c' })
    expect(mergeRows([a, b], [b, c]).map(r => r.turn)).toEqual(['a', 'b', 'c'])
    expect(mergeRows([], [c]).map(r => r.turn)).toEqual(['c'])
    expect(mergeRows([a], []).map(r => r.turn)).toEqual(['a'])
  })
})

describe('originKindOf', () => {
  test('the kind of an origin; undefined for none or a malformed one', () => {
    expect(originKindOf({ kind: 'composer' })).toBe('composer')
    expect(originKindOf({ kind: 'plugin', name: 'p' } as never)).toBe('plugin')
    expect(originKindOf(undefined)).toBeUndefined()
    expect(originKindOf({} as never)).toBeUndefined()
    expect(originKindOf(null as never)).toBeUndefined()
  })
})

describe('withdrawn', () => {
  const clock = (over: Partial<ClockState> = {}): ClockState => ({
    pending: [], running: null, consumedAt: null, lastPromptAt: null, pendingWake: null, ...over,
  })

  test('a dropped press leaves the pending queue; other presses stay', () => {
    const sub: Submission = { originKind: 'composer', at: 5, priorWake: null }
    const state = clock({ pending: [{ at: 3, origin: 'composer' }, { at: 5, origin: 'composer' }] })
    expect(withdrawn(state, sub).pending).toEqual([{ at: 3, origin: 'composer' }])
  })

  test('a dropped wake reason gives way to the prior one, unless another replaced it since', () => {
    const sub: Submission = { originKind: 'peer', at: 5, priorWake: 'task-notification' }
    expect(withdrawn(clock({ pendingWake: 'peer' }), sub).pendingWake).toBe('task-notification')
    expect(withdrawn(clock({ pendingWake: 'channel' }), sub).pendingWake).toBe('channel')
  })
})

describe('clockFor', () => {
  const held = (): ClockState => ({
    pending: [{ at: 9, origin: 'composer' }], running: { turnId: 't', startAt: 8, attachedAt: null, wake: null },
    consumedAt: 7, lastPromptAt: 7, pendingWake: 'peer',
  })
  const s2 = `${rowLine(storedRow({ session: 'S2' }))}\n`

  test('the same session or no session id keeps the clock', () => {
    expect(clockFor(held(), 'S1', 'S1', s2)).toEqual(held())
    expect(clockFor(held(), undefined, 'S1', s2)).toEqual(held())
  })

  test('a switched session takes its newest press, or null, and clears the wake reason', () => {
    expect(clockFor(held(), 'S2', 'S1', s2)).toEqual({
      ...held(), consumedAt: T0 - 60_000, lastPromptAt: T0 - 60_000, pendingWake: null,
    })
    expect(clockFor(held(), 'S3', 'S1', s2)).toEqual({ ...held(), consumedAt: null, lastPromptAt: null, pendingWake: null })
  })

  test('the first known session seeds the clock from the file', () => {
    expect(clockFor(held(), 'S2', null, s2).lastPromptAt).toBe(T0 - 60_000)
  })
})

describe('textOf', () => {
  test('byte pieces join before decoding, so a split character survives; a BOM is kept', () => {
    const bytes = new TextEncoder().encode('\uFEFFcaf\u00e9')
    expect(textOf([bytes.subarray(0, 7), bytes.subarray(7)])).toBe('\uFEFFcaf\u00e9')
    expect(textOf([])).toBe('')
  })
})

describe('isDropped', () => {
  test('a drop result only', () => {
    expect(isDropped({ drop: 'held' })).toBe(true)
    expect(isDropped({ text: 'go' })).toBe(false)
    expect(isDropped(undefined)).toBe(false)
  })
})
