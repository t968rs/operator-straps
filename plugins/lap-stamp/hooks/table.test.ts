import { describe, expect, test } from 'claude-code/testing'

import type { LapRow } from '../types'
import { buildRow } from './row'
import { lapTimesText, parseLapArgs, rowWidth } from './table'

/**
 * The `/lap-times` table: a markdown table of laps rows whose every line fits the terminal width, columns
 * dropped least useful first; the summary line above it; and the arguments that pick the rows.
 */

const T0 = Date.UTC(2026, 10, 25, 14, 0, 0)

/** A row at T0 + `atS` seconds in UTC (offset 0), so the expected clock reads the same on any host. */
const rowAt = (atS: number, over: Partial<LapRow> = {}, kind: 'prompt' | 'wake' = 'prompt'): LapRow => ({
  ...buildRow({
    session: 'session-one-id', turn: `t${atS}`, reason: 'answer', answer: 'a reply', offsetMin: 0,
    timing: {
      kind, wake: kind === 'wake' ? 'task-notification' : null, promptAt: kind === 'prompt' ? T0 : null,
      startAt: T0, stopAt: T0 + atS * 1000, lastPromptAt: T0, lapMs: atS * 1000,
      sincePromptMs: kind === 'wake' ? atS * 1000 : null,
    },
  }),
  ...over,
})

const widest = (text: string): number => Math.max(...text.split('\n').map(line => line.length))

describe('parseLapArgs', () => {
  test('no arguments: this session, the last 50 rows', () => {
    expect(parseLapArgs('')).toEqual({ isAllSessions: false, limit: 50 })
    expect(parseLapArgs('   ')).toEqual({ isAllSessions: false, limit: 50 })
  })

  test('all and a count, in either order and any case', () => {
    expect(parseLapArgs('all')).toEqual({ isAllSessions: true, limit: 50 })
    expect(parseLapArgs('10')).toEqual({ isAllSessions: false, limit: 10 })
    expect(parseLapArgs('ALL 7')).toEqual({ isAllSessions: true, limit: 7 })
    expect(parseLapArgs('7 all')).toEqual({ isAllSessions: true, limit: 7 })
  })

  test('anything else is refused', () => {
    expect(parseLapArgs('0')).toBeNull()
    expect(parseLapArgs('-3')).toBeNull()
    expect(parseLapArgs('2.5')).toBeNull()
    expect(parseLapArgs('yesterday')).toBeNull()
    expect(parseLapArgs('all all')).toBeNull()
    expect(parseLapArgs('3 4')).toBeNull()
  })
})

describe('rowWidth', () => {
  test('cells plus a pipe and a space on each side of each cell', () => {
    expect(rowWidth([3, 5])).toBe('| abc | abcde |'.length)
    expect(rowWidth([])).toBe(1)
  })
})

describe('lapTimesText', () => {
  test('a wide terminal shows every column, aligned, under a summary line', () => {
    const rows = [rowAt(5), rowAt(75, {}, 'wake')]
    expect(lapTimesText(rows, { isAllSessions: false, limit: 50, columns: 200 }).split('\n')).toEqual([
      'lap-stamp · this session · 2 turns · lap total 1m 20s · longest 1m 15s',
      '',
      '| # | Stop     | Kind   |    Lap | Since prompt | Wake              | Stop reason |',
      '|--:|----------|--------|-------:|-------------:|-------------------|-------------|',
      '| 1 | 14:00:05 | prompt |     5s |              |                   | answer      |',
      '| 2 | 14:01:15 | wake   | 1m 15s |       1m 15s | task-notification | answer      |',
    ])
  })

  test('every line fits the width: the least useful columns go first', () => {
    const rows = [rowAt(5), rowAt(75, {}, 'wake')]
    const text = lapTimesText(rows, { isAllSessions: false, limit: 50, columns: 50 })
    expect(widest(text.split('\n').slice(2).join('\n'))).toBeLessThanOrEqual(50)
    const header = text.split('\n')[2]
    expect(header).toContain('Stop')
    expect(header).toContain('Lap')
    expect(header).not.toContain('Stop reason')
    expect(header).not.toContain('Wake')
  })

  test('the summary line is cut to the width too', () => {
    const text = lapTimesText([rowAt(5)], { isAllSessions: false, limit: 50, columns: 30 })
    expect(widest(text)).toBeLessThanOrEqual(30)
  })

  test('stop time and lap are never dropped, however narrow', () => {
    const header = lapTimesText([rowAt(5)], { isAllSessions: false, limit: 50, columns: 10 }).split('\n')[2]
    expect(header).toBe('| Stop     | Lap |')
  })

  test('all sessions add the date and a short session id', () => {
    const rows = [rowAt(5), rowAt(9, { session: 'session-two-id' })]
    const lines = lapTimesText(rows, { isAllSessions: true, limit: 50, columns: 200 }).split('\n')
    expect(lines[0]).toBe('lap-stamp · all sessions (2) · 2 turns · lap total 14s · longest 9s')
    expect(lines[2]).toContain('| Session  | Date  | Stop     |')
    expect(lines[4]).toContain('| session- | 11-25 | 14:00:05 |')
  })

  test('the limit keeps the newest rows and says how many it shows', () => {
    const rows = [rowAt(1), rowAt(2), rowAt(3)]
    const lines = lapTimesText(rows, { isAllSessions: false, limit: 2, columns: 200 }).split('\n')
    expect(lines[0]).toBe('lap-stamp · this session · 3 turns · lap total 6s · longest 3s · last 2 shown')
    expect(lines.slice(4).map(l => l.slice(0, 5))).toEqual(['| 2 |', '| 3 |'])
  })

  test('no rows says so instead of drawing an empty table', () => {
    expect(lapTimesText([], { isAllSessions: false, limit: 50, columns: 80 })).toBe(
      'lap-stamp · no turns recorded in this session yet',
    )
    expect(lapTimesText([], { isAllSessions: true, limit: 50, columns: 80 })).toBe(
      'lap-stamp · no turns recorded in the laps file yet',
    )
  })

  test('a pipe in a cell is escaped so the table keeps its columns', () => {
    const rows = [rowAt(75, { wake: 'a|b' }, 'wake')]
    expect(lapTimesText(rows, { isAllSessions: false, limit: 50, columns: 200 })).toContain('a\\|b')
  })
})
