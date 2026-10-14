import { describe, expect, test } from 'claude-code/testing'

import {
  allDispositioned, keywordBlock, mentionsBubble, missingFromReview, readReview, reviewFileFor, sidecarIds, stopBlock,
  verdictPrefix,
} from './bubbles'

const review = (over: Record<string, unknown> = {}): string => JSON.stringify({
  verdict: 'NOT READY TO MERGE: 2 important',
  issues: { critical: [{ id: 'C1' }], important: [{ id: 'I1' }, { id: 'I2' }], minor: [{ id: 'M1' }] },
  post_review_resolutions: [{ id: 'C1' }],
  bubbles: ['I1'],
  bubble_up: [{ id: 'M1', classification: 'out_of_scope', reason: 'r' }],
  ...over,
})

describe('readReview (id_handling.py port)', () => {
  test('issue ids, dispositions from all three channels, bubbles, verdict', async () => {
    expect(readReview(review())).toEqual({
      verdict: 'NOT READY TO MERGE: 2 important',
      issueIds: ['C1', 'I1', 'I2', 'M1'],
      dispositioned: ['C1', 'I1', 'M1'],
      bubbles: ['I1'],
      closed: [],
    })
  })

  test('closed: the latest resolution status per id, RESOLVED or CLOSED_NO_ACTION', async () => {
    const resolutions = [
      { id: 'C1', status: 'RESOLVED' }, { id: 'I1', status: 'CLOSED_NO_ACTION' }, { id: 'I2', status: 'RESOLVED' },
      { id: 'I2', status: 'UNRESOLVED' }, { id: 'M1', status: 'DEFERRED' }, { id: 'M2' },
    ]
    expect(readReview(review({ post_review_resolutions: resolutions }))?.closed).toEqual(['C1', 'I1'])
  })

  test('tolerates nulls, junk entries and bad JSON', async () => {
    const r = readReview(JSON.stringify({ issues: { critical: null, minor: [{ id: 3 }, 'x'] }, bubbles: null }))
    expect(r).toEqual({ verdict: null, issueIds: [], dispositioned: [], bubbles: [], closed: [] })
    expect(readReview('{oops')).toBeUndefined()
    expect(readReview('[1]')).toBeUndefined()
  })
})

describe('dispositions', () => {
  test('allDispositioned needs at least one issue', async () => {
    expect(allDispositioned(readReview(review())!)).toBe(false)
    expect(allDispositioned(readReview(review({ post_review_resolutions: [{ id: 'C1' }, { id: 'I2' }] }))!)).toBe(true)
    expect(allDispositioned(readReview(JSON.stringify({ issues: {} }))!)).toBe(false)
  })

  test('missingFromReview: tracked ids not dispositioned, sorted; nothing without a review', async () => {
    expect(missingFromReview(['M3', 'I2', 'I1', 'C9'], readReview(review()))).toEqual(['C9', 'I2', 'M3'])
    expect(missingFromReview(['I2'], undefined)).toEqual([])
  })
})

describe('files and verdicts', () => {
  test('sidecarIds reads items[].id; null on junk', async () => {
    expect(sidecarIds(JSON.stringify({ run_id: 'x', items: [{ id: 'I2' }, { id: 'M4' }, {}] }))).toEqual(['I2', 'M4'])
    expect(sidecarIds('nope')).toBeNull()
  })

  test('verdictPrefix', async () => {
    expect(verdictPrefix('NOT READY TO MERGE: x')).toBe('NOT READY TO MERGE')
    expect(verdictPrefix('READY TO MERGE')).toBe('READY TO MERGE')
    expect(verdictPrefix('pending')).toBeUndefined()
    expect(verdictPrefix(null)).toBeUndefined()
  })

  test('reviewFileFor: zero-padded prefix, newest json file wins', async () => {
    const e = (name: string, mtimeMs: number, kind = 'file') => ({ name, mtimeMs, kind })
    const entries = [
      e('0916_a.json', 1), e('0916_b.json', 5), e('9160_c.json', 9), e('0916_d.md', 9), e('0916_dir.json', 9, 'dir'),
    ]
    expect(reviewFileFor(916, entries)?.name).toBe('0916_b.json')
    expect(reviewFileFor(1537, [e('1537_0093_gdb.json', 2)])?.name).toBe('1537_0093_gdb.json')
    expect(reviewFileFor(1, entries)).toBeUndefined()
  })
})

describe('keyword trigger (has_bubbles.py port)', () => {
  const doc = (over: Record<string, unknown>) =>
    readReview(JSON.stringify({ issues: { important: [{ id: 'I1' }, { id: 'I2' }] }, ...over }))

  test('mentionsBubble: any case, any inflection; absent text is no mention', async () => {
    expect(mentionsBubble('These two Bubbled up.')).toBe(true)
    expect(mentionsBubble('BUBBLES: I2')).toBe(true)
    expect(mentionsBubble('nothing to see')).toBe(false)
    expect(mentionsBubble(undefined)).toBe(false)
  })

  test('blocks when bubbles[] is empty and issues remain undispositioned', async () => {
    const block = keywordBlock(1526, 'I will bubble I2', doc({ post_review_resolutions: [{ id: 'I1' }] }), false)
    expect(block).toContain('PR #1526')
    expect(block).toContain('I2')
    expect(block).toContain('bubbles[]')
  })

  test('allows: no mention, populated bubbles, all dispositioned, no issues, no review, loop-break', async () => {
    const open = doc({})
    expect(keywordBlock(1526, 'all fixed', open, false)).toBeUndefined()
    expect(keywordBlock(1526, 'bubble', doc({ bubbles: ['I2'] }), false)).toBeUndefined()
    const closed = doc({ post_review_resolutions: [{ id: 'I1' }], bubble_up: [{ id: 'I2' }] })
    expect(keywordBlock(1526, 'bubble', closed, false)).toBeUndefined()
    expect(keywordBlock(1526, 'bubble', readReview(JSON.stringify({ issues: {} })), false)).toBeUndefined()
    expect(keywordBlock(1526, 'bubble', undefined, false)).toBeUndefined()
    expect(keywordBlock(1526, 'bubble', open, true)).toBeUndefined()
  })
})

describe('stopBlock', () => {
  test('blocks with the missing ids; allows on loop-break or nothing missing', async () => {
    expect(stopBlock(1526, ['I2', 'M3'], 'bubble_ups', false)).toContain('PR #1526')
    expect(stopBlock(1526, ['I2', 'M3'], 'bubble_ups', false)).toContain('I2, M3')
    expect(stopBlock(1526, ['I2'], 'closer', true)).toBeUndefined()
    expect(stopBlock(1526, [], 'closer', false)).toBeUndefined()
  })
})
