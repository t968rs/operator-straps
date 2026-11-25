import { describe, expect, test } from 'claude-code/testing'

import type { LapRow } from '../types'
import { fingerprintOf } from './fingerprint'
import {
  blockStamp,
  clockOf,
  durationRow,
  formatDuration,
  rowsForBlock,
  stampText,
  wrapRight,
} from './stamp'

/** Local wall clock as an ISO string, so the expected HH:MM:SS holds in any time zone. */
const localIso = (h: number, m: number, s: number): string => new Date(2026, 10, 25, h, m, s).toISOString()

const fp = (text: string) => {
  const f = fingerprintOf(text)
  if (f === null) throw new Error('empty fingerprint')
  return f
}

type Over = Partial<LapRow>

/** A row with the given answer text (null: an empty answer) and optional overrides. */
const row = (answer: string | null, over: Over = {}): LapRow => {
  const f = answer === null ? null : fp(answer)
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

const wakeRow = (answer: string | null, over: Over = {}): LapRow =>
  row(answer, {
    kind: 'wake',
    wake: 'task-notification',
    prompt_at: null,
    start_at: localIso(14, 41, 17),
    stop_at: localIso(14, 41, 55),
    lap_ms: 38_000,
    since_prompt_ms: 588_000,
    ...over,
  })

describe('formatDuration', () => {
  test('under a minute is Ns', async () => {
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(1_000)).toBe('1s')
    expect(formatDuration(59_000)).toBe('59s')
  })

  test('sub-second remainders floor', async () => {
    expect(formatDuration(999)).toBe('0s')
    expect(formatDuration(59_999)).toBe('59s')
  })

  test('60 s is the first minute band', async () => {
    expect(formatDuration(60_000)).toBe('1m 0s')
    expect(formatDuration(192_000)).toBe('3m 12s')
    expect(formatDuration(3_599_000)).toBe('59m 59s')
  })

  test('3600 s is the first hour band and drops the seconds', async () => {
    expect(formatDuration(3_600_000)).toBe('1h 0m')
    expect(formatDuration(3_600_000 + 59_000)).toBe('1h 0m')
    expect(formatDuration(5_400_000)).toBe('1h 30m')
    expect(formatDuration(26 * 3_600_000 + 5 * 60_000)).toBe('26h 5m')
  })

  test('a negative or non-finite value reads as zero', async () => {
    expect(formatDuration(-5_000)).toBe('0s')
    expect(formatDuration(Number.NaN)).toBe('0s')
  })
})

describe('clockOf', () => {
  test('the local HH:MM:SS of an ISO instant, zero padded', async () => {
    expect(clockOf(localIso(14, 32, 7))).toBe('14:32:07')
    expect(clockOf(localIso(0, 5, 9))).toBe('00:05:09')
  })

  test('an unparseable value draws a placeholder', async () => {
    expect(clockOf('not a time')).toBe('--:--:--')
  })
})

describe('stampText', () => {
  test('a prompt turn shows the stop time and the lap', async () => {
    expect(stampText(row('a'))).toBe('14:32:07 · lap 3m 12s')
  })

  test('a wake turn adds the time since the last prompt', async () => {
    expect(stampText(wakeRow('a'))).toBe('14:41:55 · lap 38s · since prompt 9m 48s')
  })

  test('a wake turn with no prompt behind it shows only the lap', async () => {
    expect(stampText(wakeRow('a', { since_prompt_ms: null, last_prompt_at: null }))).toBe('14:41:55 · lap 38s')
  })

  test('a prompt turn never shows since prompt, even with a value', async () => {
    expect(stampText(row('a', { since_prompt_ms: 5_000 }))).toBe('14:32:07 · lap 3m 12s')
  })
})

describe('rowsForBlock', () => {
  test('a miss is an empty list', async () => {
    expect(rowsForBlock([row('one')], 'two')).toEqual([])
  })

  test('one match', async () => {
    const hit = row('the answer')
    expect(rowsForBlock([row('other'), hit], 'the answer')).toEqual([hit])
  })

  test('the block is normalized like the answer', async () => {
    const hit = row('hi\nthere')
    expect(rowsForBlock([hit], '<context>x</context>hi\r\nthere\n')).toEqual([hit])
  })

  test('identical replies match in file order', async () => {
    const a = row('same', { turn: 'a' })
    const b = row('same', { turn: 'b' })
    const c = row('same', { turn: 'c' })
    expect(rowsForBlock([a, row('x'), b, c], 'same').map(r => r.turn)).toEqual(['a', 'b', 'c'])
  })

  test('a hash match with another length is not a match', async () => {
    const f = fp('same')
    expect(rowsForBlock([row('same', { answer_len: f.len + 1 })], 'same')).toEqual([])
  })

  test('an empty-answer row is never matched by text', async () => {
    const empty = row(null)
    expect(rowsForBlock([empty], '')).toEqual([])
    expect(rowsForBlock([empty], '   ')).toEqual([])
    expect(rowsForBlock([empty], '<context>x</context>')).toEqual([])
    expect(rowsForBlock([empty], 'anything')).toEqual([])
  })
})

describe('blockStamp', () => {
  test('no row draws nothing', async () => {
    expect(blockStamp([])).toBeNull()
  })

  test('one row is its own stamp', async () => {
    expect(blockStamp([row('a')])).toBe('14:32:07 · lap 3m 12s')
  })

  test('three identical replies list every candidate in file order', async () => {
    const a = row('same', { stop_at: localIso(14, 32, 7), lap_ms: 192_000 })
    const b = wakeRow('same')
    const c = row('same', { stop_at: localIso(15, 0, 0), lap_ms: 61_000 })
    expect(blockStamp([a, b, c])).toBe(
      'identical replies: 14:32:07 lap 3m 12s | 14:41:55 lap 38s · since prompt 9m 48s | 15:00:00 lap 1m 1s',
    )
  })

  test('two candidates join with a bar', async () => {
    expect(blockStamp([row('s'), row('s')])).toBe('identical replies: 14:32:07 lap 3m 12s | 14:32:07 lap 3m 12s')
  })
})

describe('durationRow', () => {
  const emptyRow = (stopS: number, over: Over = {}): LapRow =>
    row(null, {
      start_at: localIso(10, 0, 0),
      stop_at: localIso(10, 0, stopS),
      ...over,
    })

  test('no row in tolerance is null', async () => {
    expect(durationRow([], 30_000)).toBeNull()
    expect(durationRow([emptyRow(10)], 30_000)).toBeNull()
  })

  test('exactly one row in tolerance with an empty answer matches', async () => {
    const hit = emptyRow(30)
    expect(durationRow([emptyRow(10), hit], 31_500)).toBe(hit)
  })

  test('the tolerance is 2000 ms, inclusive', async () => {
    const hit = emptyRow(30)
    expect(durationRow([hit], 32_000)).toBe(hit)
    expect(durationRow([hit], 28_000)).toBe(hit)
    expect(durationRow([hit], 32_001)).toBeNull()
    expect(durationRow([hit], 27_999)).toBeNull()
  })

  test('one row in tolerance but answered is null', async () => {
    expect(durationRow([row('answered', { start_at: localIso(10, 0, 0), stop_at: localIso(10, 0, 30) })], 30_000)).toBeNull()
  })

  test('two rows in tolerance is null, even when only one is empty', async () => {
    const empty = emptyRow(30)
    const other = emptyRow(31, { turn: 't2' })
    const answered = row('x', { start_at: localIso(10, 0, 0), stop_at: localIso(10, 0, 31) })
    expect(durationRow([empty, other], 30_500)).toBeNull()
    expect(durationRow([empty, answered], 30_500)).toBeNull()
  })

  test('a row with an unparseable time never matches', async () => {
    expect(durationRow([emptyRow(30, { stop_at: 'bad' })], 30_000)).toBeNull()
  })
})

describe('wrapRight', () => {
  test('a stamp that fits is one right-aligned row', async () => {
    expect(wrapRight('abc', 6)).toEqual(['   abc'])
  })

  test('a stamp exactly the width gets no padding', async () => {
    expect(wrapRight('abcdef', 6)).toEqual(['abcdef'])
  })

  test('a too-wide list splits on the bars into further right-aligned rows', async () => {
    const text = 'identical replies: 14:32:07 lap 3m 12s | 14:41:55 lap 38s | 15:00:00 lap 1m 1s'
    expect(wrapRight(text, 40)).toEqual([
      'identical replies: 14:32:07 lap 3m 12s |',
      '14:41:55 lap 38s | 15:00:00 lap 1m 1s'.padStart(40),
    ])
  })

  test('no candidate is ever dropped', async () => {
    const cands = ['14:32:07 lap 3m 12s', '14:41:55 lap 38s', '15:00:00 lap 1m 1s', '16:01:02 lap 9s']
    const text = `identical replies: ${cands.join(' | ')}`
    for (const width of [20, 30, 45, 60, 200]) {
      const joined = wrapRight(text, width).join(' ')
      for (const c of cands) expect(joined).toContain(c)
      expect(joined).toContain('identical replies:')
    }
  })

  test('rows are right-aligned and a wrapped row keeps its bar', async () => {
    expect(wrapRight('aaaa | bbbb | cccc', 11)).toEqual(['aaaa |'.padStart(11), 'bbbb | cccc'])
  })

  test('every wrapped row fits the width when each candidate does', async () => {
    const text = 'identical replies: 14:32:07 lap 3m 12s | 14:41:55 lap 38s | 15:00:00 lap 1m 1s'
    for (const width of [38, 39, 40, 45, 60]) {
      for (const line of wrapRight(text, width)) expect(line.length).toBeLessThanOrEqual(width)
    }
  })

  test('one candidate wider than the width stays whole', async () => {
    expect(wrapRight('x'.repeat(30), 10)).toEqual(['x'.repeat(30)])
  })

  test('a non-positive or non-finite width returns the text unwrapped', async () => {
    expect(wrapRight('a | b', 0)).toEqual(['a | b'])
    expect(wrapRight('a | b', Number.POSITIVE_INFINITY)).toEqual(['a | b'])
    expect(wrapRight('a | b', Number.NaN)).toEqual(['a | b'])
  })
})
