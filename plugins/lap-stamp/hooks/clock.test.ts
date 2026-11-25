import { describe, expect, test } from 'claude-code/testing'

import type { ClockState } from '../types'
import {
  EMPTY_CLOCK,
  LAP_PRESS_ORIGINS,
  delivered,
  isLapPress,
  seedLastPrompt,
  started,
  stopped,
  submitted,
} from './clock'

const press = (s: ClockState, at: number, originKind = 'composer'): ClockState =>
  submitted(s, { originKind, at })

describe('lap-press origins (D1)', () => {
  test('composer and bridge are lap presses, nothing else is', async () => {
    expect([...LAP_PRESS_ORIGINS]).toEqual(['composer', 'bridge'])
    expect(isLapPress('composer')).toBe(true)
    expect(isLapPress('bridge')).toBe(true)
    expect(isLapPress('task-notification')).toBe(false)
    expect(isLapPress('unclassified')).toBe(false)
  })

  test('a lap press queues; any other origin becomes the pending wake reason', async () => {
    const s1 = press(EMPTY_CLOCK, 100)
    expect(s1.pending).toEqual([{ at: 100, origin: 'composer' }])
    expect(s1.pendingWake).toBeNull()
    const s2 = press(s1, 110, 'bridge')
    expect(s2.pending).toEqual([
      { at: 100, origin: 'composer' },
      { at: 110, origin: 'bridge' },
    ])
    const s3 = press(EMPTY_CLOCK, 120, 'task-notification')
    expect(s3.pending).toEqual([])
    expect(s3.pendingWake).toBe('task-notification')
  })

  test('each reducer leaves its input state untouched', async () => {
    const snap = (s: ClockState): ClockState => JSON.parse(JSON.stringify(s)) as ClockState
    const idle = press(EMPTY_CLOCK, 100)
    const run: ClockState = {
      ...press(idle, 300),
      running: { turnId: 't1', startAt: 200, attachedAt: 100, wake: null },
    }
    const calls: [ClockState, (s: ClockState) => unknown][] = [
      [idle, s => submitted(s, { originKind: 'composer', at: 150 })],
      [run, s => delivered(s, 400)],
      [run, s => started(s, 't2', 500)],
      [run, s => stopped(s, 't1', 900)],
      [run, s => seedLastPrompt(s, 1_000)],
    ]
    for (const [input, reduce] of calls) {
      const copy = snap(input)
      reduce(input)
      expect(input).toEqual(copy)
    }
  })
})

describe('prompt turns (D2, D4)', () => {
  test('an idle press anchors the next turn: kind prompt, lap = stop - press', async () => {
    const run = started(press(EMPTY_CLOCK, 1_000), 't1', 1_500)
    expect(run.running).toEqual({ turnId: 't1', startAt: 1_500, attachedAt: 1_000, wake: null })
    expect(run.pending).toEqual([])
    const { state, timing } = stopped(run, 't1', 4_000)
    expect(timing).toEqual({
      kind: 'prompt',
      wake: null,
      promptAt: 1_000,
      startAt: 1_500,
      stopAt: 4_000,
      lastPromptAt: 1_000,
      lapMs: 3_000,
      sincePromptMs: null,
    })
    expect(state.running).toBeNull()
    expect(state.consumedAt).toBe(1_000)
    expect(state.lastPromptAt).toBe(1_000)
  })

  test('several presses before a turn: the last one counts', async () => {
    const s = press(press(press(EMPTY_CLOCK, 100), 200), 300)
    const { timing } = stopped(started(s, 't1', 400), 't1', 1_000)
    expect(timing?.promptAt).toBe(300)
    expect(timing?.lapMs).toBe(700)
  })

  test('a press delivered into a running turn restarts its lap from the press time', async () => {
    let s = started(press(EMPTY_CLOCK, 100), 't1', 200)
    s = press(s, 5_000)
    s = delivered(s, 5_400)
    expect(s.running?.attachedAt).toBe(5_000)
    expect(s.pending).toEqual([])
    const { state, timing } = stopped(s, 't1', 9_000)
    expect(timing?.kind).toBe('prompt')
    expect(timing?.promptAt).toBe(5_000)
    expect(timing?.lapMs).toBe(4_000)
    expect(state.consumedAt).toBe(5_000)
    expect(state.lastPromptAt).toBe(5_000)
  })

  test('a delivery turns a running wake turn into a prompt turn', async () => {
    let s = started(EMPTY_CLOCK, 't1', 100)
    s = delivered(press(s, 300), 350)
    const { timing } = stopped(s, 't1', 1_000)
    expect(timing?.kind).toBe('prompt')
    expect(timing?.lapMs).toBe(700)
  })

  test('several presses delivered together: the last one counts', async () => {
    let s = started(EMPTY_CLOCK, 't1', 100)
    s = delivered(press(press(s, 300), 400), 450)
    expect(s.running?.attachedAt).toBe(400)
    expect(s.pending).toEqual([])
  })

  test('a delivery takes only presses made by its own time; later ones stay pending', async () => {
    let s = started(EMPTY_CLOCK, 't1', 100)
    s = delivered(press(press(s, 300), 500), 400)
    expect(s.running?.attachedAt).toBe(300)
    expect(s.pending).toEqual([{ at: 500, origin: 'composer' }])
    const next = started(stopped(s, 't1', 600).state, 't2', 700)
    expect(next.running?.attachedAt).toBe(500)
  })

  test('a press during a run without delivery anchors the next turn, not the running one', async () => {
    let s = started(press(EMPTY_CLOCK, 100), 't1', 200)
    s = press(s, 5_000)
    const first = stopped(s, 't1', 6_000)
    expect(first.timing?.promptAt).toBe(100)
    expect(first.state.pending).toEqual([{ at: 5_000, origin: 'composer' }])
    const second = stopped(started(first.state, 't2', 6_100), 't2', 8_000)
    expect(second.timing?.kind).toBe('prompt')
    expect(second.timing?.promptAt).toBe(5_000)
    expect(second.timing?.lapMs).toBe(3_000)
  })

  test('a press and its delivery in the same millisecond attach', async () => {
    const s = delivered(press(started(EMPTY_CLOCK, 't1', 100), 300), 300)
    expect(s.running?.attachedAt).toBe(300)
    expect(s.pending).toEqual([])
  })

  test('a wall clock that went backwards clamps the lap to 0', async () => {
    const { timing } = stopped(started(press(EMPTY_CLOCK, 1_000), 't1', 1_100), 't1', 900)
    expect(timing?.lapMs).toBe(0)
    const wake = stopped(started(seedLastPrompt(EMPTY_CLOCK, 1_000), 't2', 800), 't2', 700)
    expect(wake.timing?.lapMs).toBe(0)
    expect(wake.timing?.sincePromptMs).toBe(0)
  })

  test('a start over a turn that never stopped folds its press in as used', async () => {
    let s = started(EMPTY_CLOCK, 't1', 100)
    s = delivered(press(s, 300), 350)
    s = started(s, 't2', 1_000)
    expect(s.running?.attachedAt).toBeNull()
    expect(s.consumedAt).toBe(300)
    expect(s.lastPromptAt).toBe(300)
    const { timing } = stopped(s, 't2', 2_000)
    expect(timing?.kind).toBe('wake')
    expect(timing?.lastPromptAt).toBe(300)
    expect(timing?.sincePromptMs).toBe(1_700)
  })

  test('a delivery with no running turn or no press changes nothing', async () => {
    const idle = press(EMPTY_CLOCK, 100)
    expect(delivered(idle, 200)).toEqual(idle)
    const run = started(EMPTY_CLOCK, 't1', 100)
    expect(delivered(run, 200)).toEqual(run)
  })
})

describe('consumed-press marker (D2)', () => {
  test('a pending press never anchors two turns', async () => {
    const first = stopped(started(press(EMPTY_CLOCK, 100), 't1', 200), 't1', 300)
    const second = stopped(started(first.state, 't2', 400), 't2', 900)
    expect(second.timing?.kind).toBe('wake')
    expect(second.timing?.promptAt).toBeNull()
  })

  test('a press at or before the marker is never attached', async () => {
    const stale: ClockState = { ...EMPTY_CLOCK, pending: [{ at: 100, origin: 'composer' }], consumedAt: 100 }
    const run = started(stale, 't1', 200)
    expect(run.running?.attachedAt).toBeNull()
    expect(run.pending).toEqual([])
    const running: ClockState = { ...stale, running: { turnId: 't1', startAt: 50, attachedAt: null, wake: null } }
    expect(delivered(running, 300).running?.attachedAt).toBeNull()
  })
})

describe('wake turns (D4)', () => {
  test('a task-notification start is a wake: lap from start, since prompt from the last press', async () => {
    let s = stopped(started(press(EMPTY_CLOCK, 1_000), 't1', 1_100), 't1', 2_000).state
    s = press(s, 50_000, 'task-notification')
    s = started(s, 't2', 50_100)
    expect(s.running?.wake).toBe('task-notification')
    expect(s.pendingWake).toBeNull()
    const { timing } = stopped(s, 't2', 60_100)
    expect(timing).toEqual({
      kind: 'wake',
      wake: 'task-notification',
      promptAt: null,
      startAt: 50_100,
      stopAt: 60_100,
      lastPromptAt: 1_000,
      lapMs: 10_000,
      sincePromptMs: 59_100,
    })
  })

  test('no prompt ever in the session: since prompt is null', async () => {
    const { timing } = stopped(started(EMPTY_CLOCK, 't1', 100), 't1', 400)
    expect(timing?.kind).toBe('wake')
    expect(timing?.wake).toBeNull()
    expect(timing?.lastPromptAt).toBeNull()
    expect(timing?.sincePromptMs).toBeNull()
    expect(timing?.lapMs).toBe(300)
  })

  test('the newest prompt_at read back from the file seeds since prompt', async () => {
    const seeded = seedLastPrompt(EMPTY_CLOCK, 1_000)
    expect(seeded.lastPromptAt).toBe(1_000)
    expect(seeded.consumedAt).toBe(1_000)
    expect(seedLastPrompt(seeded, null)).toEqual(seeded)
    expect(seedLastPrompt(seeded, 500).lastPromptAt).toBe(1_000)
    const { timing } = stopped(started(seeded, 't1', 2_000), 't1', 3_000)
    expect(timing?.sincePromptMs).toBe(2_000)
  })

  test('a prompted turn clears the pending wake reason', async () => {
    const s = started(press(press(EMPTY_CLOCK, 100, 'task-notification'), 200), 't1', 300)
    expect(s.running?.wake).toBeNull()
    expect(s.pendingWake).toBeNull()
  })

  test('a submission made during a turn does not outlive its stop: the next start has a null wake', async () => {
    let s = press(started(EMPTY_CLOCK, 't1', 100), 200, 'task-notification')
    s = stopped(s, 't1', 300).state
    expect(s.pendingWake).toBeNull()
    const { timing } = stopped(started(s, 't2', 400), 't2', 500)
    expect(timing?.kind).toBe('wake')
    expect(timing?.wake).toBeNull()
  })
})

describe('stray stops', () => {
  test('a stop with no running turn or another turn id gives no timing and keeps the state', async () => {
    const idle = press(EMPTY_CLOCK, 100)
    expect(stopped(idle, 't1', 200)).toEqual({ state: idle, timing: null })
    const run = started(idle, 't1', 150)
    expect(stopped(run, 't9', 200)).toEqual({ state: run, timing: null })
  })
})
