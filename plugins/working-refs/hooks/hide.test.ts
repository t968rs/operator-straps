import { describe, expect, test } from 'claude-code/testing'

import type { CachedIssue, OpenList } from './hide'
import { isClosed, issueCacheOf, openListOf, retiredIdsOf, visibleRefs } from './hide'

const T0 = Date.parse('2026-11-19T10:00:00Z')
const HOUR = 3_600_000

const list = (fetchedAt: number, open: number[]): OpenList => ({ fetchedAt, open: new Set(open) })
const cache = (entries: Array<[number, CachedIssue['state'], number]>): Map<number, CachedIssue> =>
  new Map(entries.map(([n, state, checkedAt]) => [n, { state, checkedAt, triedAt: checkedAt }]))
const NO_CACHE = cache([])

describe('retiredIdsOf', () => {
  test('the catalog\'s retired_ids', async () => {
    const text = JSON.stringify({ items: [], retired_ids: ['todo-48q2', 'todo-k69m'] })
    expect([...retiredIdsOf(text)]).toEqual(['todo-48q2', 'todo-k69m'])
  })

  test('no catalog, malformed JSON, no list or non-string members retire nothing', async () => {
    for (const text of [undefined, '', '{x', '[]', '{}', JSON.stringify({ retired_ids: 'todo-a' })]) {
      expect(retiredIdsOf(text).size).toBe(0)
    }
    expect([...retiredIdsOf(JSON.stringify({ retired_ids: ['todo-a', 3, null] }))]).toEqual(['todo-a'])
  })
})

describe('openListOf', () => {
  test('the fetch time and the open numbers', async () => {
    const text = JSON.stringify({ version: 1, fetched_at: '2026-11-19T10:00:00Z', open: [11, 200, 300] })
    const got = openListOf(text)
    expect(got?.fetchedAt).toBe(T0)
    expect([...(got?.open ?? [])]).toEqual([11, 200, 300])
  })

  test('absent, malformed, another version or no fetch time reads as no list', async () => {
    const texts = [
      undefined, '{x', '[]', JSON.stringify({ version: 2, fetched_at: '2026-11-19T10:00:00Z', open: [] }),
      JSON.stringify({ version: 1, open: [1] }), JSON.stringify({ version: 1, fetched_at: 'soon', open: [1] }),
      JSON.stringify({ version: 1, fetched_at: '2026-11-19T10:00:00Z', open: 'x' }),
    ]
    for (const text of texts) expect(openListOf(text)).toBeNull()
  })
})

describe('issueCacheOf', () => {
  test('each usable entry by number, tried_at defaulting to checked_at', async () => {
    const text = JSON.stringify({
      version: 1,
      issues: {
        301: { state: 'CLOSED', checked_at: '2026-11-19T10:00:00Z' },
        7: { state: 'OPEN', checked_at: '2026-11-19T10:00:00Z', tried_at: '2026-11-19T11:00:00Z' },
        8: { state: 'MERGED', checked_at: '2026-11-19T10:00:00Z' },
        9: { state: 'OPEN' },
        x: { state: 'OPEN', checked_at: '2026-11-19T10:00:00Z' },
      },
    })
    const got = issueCacheOf(text)
    expect([...got.keys()].sort((a, b) => a - b)).toEqual([7, 301])
    expect(got.get(301)).toEqual({ state: 'CLOSED', checkedAt: T0, triedAt: T0 })
    expect(got.get(7)?.triedAt).toBe(T0 + HOUR)
  })

  test('absent, malformed or another version holds nothing', async () => {
    for (const text of [undefined, '{x', JSON.stringify({ version: 2, issues: {} }), JSON.stringify({ version: 1 })]) {
      expect(issueCacheOf(text).size).toBe(0)
    }
  })
})

describe('isClosed', () => {
  test('a cached gh CLOSED hides the issue', async () => {
    expect(isClosed(301, null, cache([[301, 'CLOSED', T0]]))).toBe(true)
  })

  test('OPEN, UNKNOWN or no answer shows it', async () => {
    expect(isClosed(301, null, cache([[301, 'OPEN', T0]]))).toBe(false)
    expect(isClosed(301, null, cache([[301, 'UNKNOWN', T0]]))).toBe(false)
    expect(isClosed(301, null, NO_CACHE)).toBe(false)
  })

  test('an open list fetched after a CLOSED answer that lists the issue unhides it', async () => {
    expect(isClosed(301, list(T0 + HOUR, [301]), cache([[301, 'CLOSED', T0]]))).toBe(false)
  })

  test('a CLOSED answer newer than the open list hides the issue the list holds', async () => {
    expect(isClosed(301, list(T0 - HOUR, [301]), cache([[301, 'CLOSED', T0]]))).toBe(true)
  })

  test('an issue missing from the list is no answer: shown until gh reports it closed', async () => {
    expect(isClosed(512, list(T0, [301]), NO_CACHE)).toBe(false)
    expect(isClosed(512, list(T0 + HOUR, [301]), cache([[512, 'CLOSED', T0]]))).toBe(true)
  })

  test('a PR number in an override shows until gh answers CLOSED', async () => {
    const pr = 330
    expect(isClosed(pr, list(T0, [301]), cache([[pr, 'OPEN', T0]]))).toBe(false)
    expect(isClosed(pr, list(T0, [301]), cache([[pr, 'CLOSED', T0 + HOUR]]))).toBe(true)
  })
})

describe('visibleRefs', () => {
  const closed = (n: number): boolean => n === 301

  test('retired ids and closed issues drop independently, order kept', async () => {
    const refs = { todoIds: ['todo-b', 'todo-k69m', 'todo-a'], issues: [5, 301, 2] }
    expect(visibleRefs(refs, new Set(['todo-k69m']), closed)).toEqual({ todoIds: ['todo-b', 'todo-a'], issues: [5, 2] })
  })

  test('nothing hidden leaves the refs as they are', async () => {
    const refs = { todoIds: ['todo-a'], issues: [7] }
    expect(visibleRefs(refs, new Set(), () => false)).toEqual(refs)
  })
})
