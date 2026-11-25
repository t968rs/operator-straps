import { describe, expect, test } from 'claude-code/testing'

import { fingerprintOf } from './fingerprint'
import { buildRow, eastOffsetMin, isoLocal, newestPromptAt, parseRows, rowLine } from './row'
import type { LapRow, Timing } from '../types'

const T0 = Date.UTC(2026, 10, 25, 12, 30, 5, 123)

const promptTiming: Timing = {
  kind: 'prompt', wake: null, promptAt: T0, startAt: T0 + 1000, stopAt: T0 + 193000,
  lastPromptAt: T0, lapMs: 193000, sincePromptMs: null,
}

const wakeTiming: Timing = {
  kind: 'wake', wake: 'cron', promptAt: null, startAt: T0 + 400000, stopAt: T0 + 438000,
  lastPromptAt: T0, lapMs: 38000, sincePromptMs: 438000,
}

const make = (over: Partial<Parameters<typeof buildRow>[0]> = {}): LapRow =>
  buildRow({ session: 's1', turn: 't1', timing: promptTiming, reason: 'answer', answer: 'hello', offsetMin: 0, ...over })

describe('isoLocal', () => {
  test('UTC offset prints +00:00 and keeps milliseconds', async () => {
    expect(isoLocal(T0, 0)).toBe('2026-11-25T12:30:05.123+00:00')
  })

  test('positive offset shifts the wall time east', async () => {
    expect(isoLocal(T0, 60)).toBe('2026-11-25T13:30:05.123+01:00')
    expect(isoLocal(T0, 330)).toBe('2026-11-25T18:00:05.123+05:30')
  })

  test('negative offset shifts the wall time west and can cross midnight', async () => {
    expect(isoLocal(T0, -360)).toBe('2026-11-25T06:30:05.123-06:00')
    expect(isoLocal(Date.UTC(2026, 0, 1, 1, 0, 0, 0), -120)).toBe('2025-12-31T23:00:00.000-02:00')
  })

  test('the printed text parses back to the same instant', async () => {
    expect(Date.parse(isoLocal(T0, -270))).toBe(T0)
  })
})

describe('buildRow', () => {
  test('a prompt turn carries its timings, version and fingerprint', async () => {
    const fp = fingerprintOf('hello')
    expect(make()).toEqual({
      v: 1, session: 's1', turn: 't1', kind: 'prompt', wake: null,
      prompt_at: isoLocal(T0, 0), start_at: isoLocal(T0 + 1000, 0), stop_at: isoLocal(T0 + 193000, 0),
      last_prompt_at: isoLocal(T0, 0), lap_ms: 193000, since_prompt_ms: null,
      reason: 'answer', answer_hash: fp?.hash, answer_len: 5,
    })
  })

  test('a wake turn keeps null prompt_at and its since-prompt gap', async () => {
    const row = make({ timing: wakeTiming, reason: 'aborted' })
    expect(row.kind).toBe('wake')
    expect(row.wake).toBe('cron')
    expect(row.prompt_at).toBeNull()
    expect(row.last_prompt_at).toBe(isoLocal(T0, 0))
    expect(row.since_prompt_ms).toBe(438000)
    expect(row.reason).toBe('aborted')
  })

  test('a session with no prompt writes a null last_prompt_at', async () => {
    const row = make({ timing: { ...wakeTiming, lastPromptAt: null, sincePromptMs: null } })
    expect(row.last_prompt_at).toBeNull()
    expect(row.since_prompt_ms).toBeNull()
  })

  test('an empty answer has a null hash and length 0', async () => {
    for (const answer of ['', '  \r\n ', '<context>x</context>']) {
      const row = make({ answer })
      expect(row.answer_hash).toBeNull()
      expect(row.answer_len).toBe(0)
    }
  })

  test('copies of one reply that differ by context span share hash and length', async () => {
    const a = make({ answer: 'hi\r\nthere' })
    const b = make({ answer: '<context>x</context>hi\nthere\n' })
    expect(a.answer_hash).toBe(b.answer_hash)
    expect(a.answer_len).toBe(b.answer_len)
  })

  test('the row never carries the answer text or a path', async () => {
    const line = rowLine(make({ answer: 'secret answer text C:\\Users\\x' }))
    expect(line).not.toContain('secret')
    expect(line).not.toContain('Users')
  })

  test('without an explicit offset the stamps use the host zone and still round trip', async () => {
    const row = buildRow({ session: 's1', turn: 't1', timing: promptTiming, reason: 'answer', answer: 'a' })
    expect(Date.parse(row.start_at)).toBe(promptTiming.startAt)
    expect(row.start_at).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$/)
  })
})

describe('host zone sign', () => {
  test('getTimezoneOffset counts west, so a positive value prints a minus offset', async () => {
    expect(eastOffsetMin(300)).toBe(-300)
    expect(isoLocal(T0, eastOffsetMin(300)).endsWith('-05:00')).toBe(true)
  })

  test('a negative getTimezoneOffset prints a plus offset', async () => {
    expect(eastOffsetMin(-330)).toBe(330)
    expect(isoLocal(T0, eastOffsetMin(-330)).endsWith('+05:30')).toBe(true)
  })

  test('UTC gives 0, never -0', async () => {
    expect(Object.is(eastOffsetMin(0), 0)).toBe(true)
  })

  test('buildRow without an offset applies the host zone offset of each instant, in either season', async () => {
    const winter = Date.UTC(2026, 0, 15, 12, 0, 0, 0)
    const summer = Date.UTC(2026, 6, 15, 12, 0, 0, 0)
    for (const ms of [winter, summer]) {
      const timing = { ...promptTiming, startAt: ms }
      const row = buildRow({ session: 's1', turn: 't1', timing, reason: 'answer', answer: 'a' })
      expect(row.start_at).toBe(isoLocal(ms, eastOffsetMin(new Date(ms).getTimezoneOffset())))
    }
  })
})

describe('rowLine', () => {
  test('one JSON line with no newline, keys in column order', async () => {
    const line = rowLine(make())
    expect(line.includes('\n')).toBe(false)
    expect(line.startsWith('{"v":1,"session":"s1","turn":"t1","kind":"prompt"')).toBe(true)
    expect(JSON.parse(line)).toEqual(make())
  })
})

describe('parseRows', () => {
  test('round trip keeps rows in file order', async () => {
    const rows = [make({ turn: 'a' }), make({ turn: 'b', timing: wakeTiming }), make({ turn: 'c', answer: '' })]
    const text = rows.map(rowLine).join('\n') + '\n'
    expect(parseRows(text, 's1')).toEqual(rows)
  })

  test('CRLF line endings are tolerated', async () => {
    const rows = [make({ turn: 'a' }), make({ turn: 'b' })]
    expect(parseRows(rows.map(rowLine).join('\r\n') + '\r\n', 's1')).toEqual(rows)
  })

  test('blank and whitespace lines are skipped', async () => {
    const text = ['', rowLine(make({ turn: 'a' })), '   ', '\t', rowLine(make({ turn: 'b' })), ''].join('\n')
    expect(parseRows(text, 's1').map((r) => r.turn)).toEqual(['a', 'b'])
  })

  test('a leading UTF-8 BOM does not cost the first row', async () => {
    const rows = [make({ turn: 'a' }), make({ turn: 'b' })]
    expect(parseRows('﻿' + rows.map(rowLine).join('\n') + '\n', 's1')).toEqual(rows)
  })

  test('empty text yields no rows', async () => {
    expect(parseRows('', 's1')).toEqual([])
  })

  test('malformed JSON, non-objects and a truncated tail are skipped', async () => {
    const good = rowLine(make({ turn: 'a' }))
    const text = ['{not json', '[1,2]', '42', 'null', '"str"', good, good.slice(0, 40)].join('\n')
    expect(parseRows(text, 's1').map((r) => r.turn)).toEqual(['a'])
  })

  test('a wrong row version is skipped', async () => {
    const bad = { ...make({ turn: 'x' }), v: 2 }
    const text = [JSON.stringify(bad), rowLine(make({ turn: 'a' }))].join('\n')
    expect(parseRows(text, 's1').map((r) => r.turn)).toEqual(['a'])
  })

  test('a missing or wrong-typed field is skipped', async () => {
    const base = make({ turn: 'x' }) as unknown as Record<string, unknown>
    const mutations: Array<[string, unknown]> = [
      ['session', 7], ['turn', null], ['kind', 'other'], ['wake', 5], ['prompt_at', 5], ['start_at', 5],
      ['stop_at', 'not a date'], ['last_prompt_at', false], ['lap_ms', '1'], ['lap_ms', null],
      ['since_prompt_ms', 'x'], ['reason', 'nope'], ['answer_hash', 12], ['answer_len', '5'], ['answer_len', -1],
    ]
    const lines = mutations.map(([key, value]) => JSON.stringify({ ...base, [key]: value }))
    const missing = Object.keys(base).map((key) => {
      const copy = { ...base }
      delete copy[key]
      return JSON.stringify(copy)
    })
    expect(parseRows([...lines, ...missing].join('\n'), 's1')).toEqual([])
  })

  test('a prompt row needs prompt_at and a wake row must not carry one', async () => {
    const noPrompt = { ...make({ turn: 'x' }), prompt_at: null }
    const wakeWithPrompt = { ...make({ turn: 'y', timing: wakeTiming }), prompt_at: isoLocal(T0, 0) }
    expect(parseRows([JSON.stringify(noPrompt), JSON.stringify(wakeWithPrompt)].join('\n'), 's1')).toEqual([])
  })

  test('only the asked session is kept', async () => {
    const text = [make({ session: 's1', turn: 'a' }), make({ session: 's2', turn: 'b' }), make({ session: 's1', turn: 'c' })]
      .map(rowLine).join('\n')
    expect(parseRows(text, 's1').map((r) => r.turn)).toEqual(['a', 'c'])
    expect(parseRows(text, 's3')).toEqual([])
  })

  test('unknown extra keys on a good row are tolerated and dropped', async () => {
    const extra = { ...make({ turn: 'x' }), future: 'field' }
    expect(parseRows(JSON.stringify(extra), 's1')).toEqual([make({ turn: 'x' })])
  })
})

describe('newestPromptAt', () => {
  test('no rows or no prompt gives null', async () => {
    expect(newestPromptAt([])).toBeNull()
    expect(newestPromptAt([make({ timing: { ...wakeTiming, lastPromptAt: null, sincePromptMs: null } })])).toBeNull()
  })

  test('the newest prompt_at wins as epoch ms, whatever the file order', async () => {
    const early = make({ turn: 'a', timing: { ...promptTiming, promptAt: T0 } })
    const late = make({ turn: 'b', timing: { ...promptTiming, promptAt: T0 + 5000, lastPromptAt: T0 + 5000 } })
    expect(newestPromptAt([late, early])).toBe(T0 + 5000)
    expect(newestPromptAt([early, late])).toBe(T0 + 5000)
  })

  test('a wake row last_prompt_at counts when no prompt row is newer', async () => {
    const wake = make({ timing: { ...wakeTiming, lastPromptAt: T0 + 9000 } })
    expect(newestPromptAt([make({ turn: 'a' }), wake])).toBe(T0 + 9000)
  })

  test('offsets in the stored text do not change the epoch value', async () => {
    const row = make({ offsetMin: -300 })
    expect(newestPromptAt([row])).toBe(T0)
  })
})
