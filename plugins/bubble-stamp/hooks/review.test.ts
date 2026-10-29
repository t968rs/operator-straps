import { describe, expect, test } from 'claude-code/testing'

import { closedResolutions, latestResolutions, reviewFileFor } from './review'
import type { Listed } from './review'

const review = (resolutions: unknown): string => JSON.stringify({
  verdict: 'NOT READY TO MERGE: 1 important',
  issues: { critical: [], important: [{ id: 'I1' }], minor: [] },
  post_review_resolutions: resolutions,
})

const res = (id: string, status: string, date = '2026-10-29', evidence = `ev ${id}`) => ({ id, status, date, evidence })

describe('latestResolutions', () => {
  test('one entry per id: the last one wins, with its status, date and evidence', async () => {
    const text = review([
      res('I1', 'UNRESOLVED', '2026-10-01', 'first'),
      res('M2', 'RESOLVED', '2026-10-02', 'fixed in abc1234'),
      res('I1', 'RESOLVED', '2026-10-03', 'second'),
    ])
    expect(latestResolutions(text)).toEqual([
      { id: 'I1', status: 'RESOLVED', date: '2026-10-03', evidence: 'second' },
      { id: 'M2', status: 'RESOLVED', date: '2026-10-02', evidence: 'fixed in abc1234' },
    ])
  })

  test('keeps non-closing statuses so a later one can reopen an id', async () => {
    const text = review([res('I1', 'DOWNGRADED_TO_MINOR'), res('I2', 'DEFERRED')])
    expect(latestResolutions(text)?.map(r => r.status)).toEqual(['DOWNGRADED_TO_MINOR', 'DEFERRED'])
  })

  test('a missing date or evidence reads as an empty string', async () => {
    expect(latestResolutions(review([{ id: 'I1', status: 'RESOLVED' }]))).toEqual([
      { id: 'I1', status: 'RESOLVED', date: '', evidence: '' },
    ])
  })

  test('skips entries without a string id; a missing status reads as empty and reopens the id', async () => {
    const text = review([{ status: 'RESOLVED' }, { id: 3, status: 'RESOLVED' }, 'x', null, res('I1', 'RESOLVED'), { id: 'I1' }])
    expect(latestResolutions(text)).toEqual([{ id: 'I1', status: '', date: '', evidence: '' }])
    expect(closedResolutions(text)).toEqual([])
  })

  test('no resolutions, junk values or bad JSON', async () => {
    expect(latestResolutions(review(undefined))).toEqual([])
    expect(latestResolutions(review(null))).toEqual([])
    expect(latestResolutions(review('nope'))).toEqual([])
    expect(latestResolutions('{oops')).toBeUndefined()
    expect(latestResolutions('[1]')).toBeUndefined()
    expect(latestResolutions('')).toBeUndefined()
  })
})

describe('closedResolutions (the closedOf rule)', () => {
  test('only ids whose latest status is RESOLVED or CLOSED_NO_ACTION', async () => {
    const text = review([
      res('C1', 'RESOLVED'), res('I1', 'CLOSED_NO_ACTION'), res('I2', 'RESOLVED'), res('I2', 'UNRESOLVED'),
      res('M1', 'DOWNGRADED_TO_IMPORTANT'), res('M2', 'DOWNGRADED_TO_MINOR'),
    ])
    expect(closedResolutions(text)?.map(r => r.id)).toEqual(['C1', 'I1'])
  })

  test('a later closing entry closes an id an earlier one left open', async () => {
    const text = review([res('I1', 'UNRESOLVED'), res('I1', 'CLOSED_NO_ACTION', '2026-10-05', 'not needed')])
    expect(closedResolutions(text)).toEqual([
      { id: 'I1', status: 'CLOSED_NO_ACTION', date: '2026-10-05', evidence: 'not needed' },
    ])
  })

  test('undefined when the text is not a JSON object', async () => {
    expect(closedResolutions('{oops')).toBeUndefined()
  })
})

describe('reviewFileFor (the pr-review-watch rule)', () => {
  const file = (name: string, mtimeMs: number): Listed => ({ name, mtimeMs, kind: 'file' })

  test('the newest <NNNN>_*.json of the PR', async () => {
    const entries = [file('0042_Old.json', 1), file('0042_New.json', 9), file('0043_Other.json', 20)]
    expect(reviewFileFor(42, entries)?.name).toBe('0042_New.json')
    expect(reviewFileFor(43, entries)?.name).toBe('0043_Other.json')
  })

  test('an mtime tie goes to the larger name, as the driver picks', async () => {
    const entries = [file('0042_B.json', 5), file('0042_C.json', 5), file('0042_A.json', 5)]
    expect(reviewFileFor(42, entries)?.name).toBe('0042_C.json')
  })

  test('the number pads to four digits; a longer number is not padded', async () => {
    expect(reviewFileFor(7, [file('0007_X.json', 1)])?.name).toBe('0007_X.json')
    expect(reviewFileFor(12345, [file('12345_X.json', 1)])?.name).toBe('12345_X.json')
  })

  test('skips folders, other extensions, the memo, other PRs and unpadded names', async () => {
    const entries: Listed[] = [
      { name: '0042_dir.json', mtimeMs: 5, kind: 'directory' },
      file('0042_notes.md', 6), file('PR_42_Bubbles.md', 7), file('0041_X.json', 8), file('42_X.json', 9),
    ]
    expect(reviewFileFor(42, entries)).toBeUndefined()
    expect(reviewFileFor(42, [])).toBeUndefined()
  })
})
