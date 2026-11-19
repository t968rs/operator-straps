import { describe, expect, test } from 'claude-code/testing'

import { DETACHED_KEY, STORE_VERSION } from './mirror'
import { parseOverrides } from './overrides'

const SET_AT = '2026-11-18T00:00:00Z'
const file = (branches: unknown, version: unknown = STORE_VERSION): string => JSON.stringify({ version, branches })
const entry = (todo_ids?: unknown, issues?: unknown) => ({ todo_ids, issues, set_at: SET_AT })

describe('parseOverrides', () => {
  test('each branch\'s refs and set_at', async () => {
    const text = file({ topic: entry(['todo-k69m'], [301]), [DETACHED_KEY]: entry([], [7]) })
    expect([...parseOverrides(text)]).toEqual([
      ['topic', { refs: { todoIds: ['todo-k69m'], issues: [301] }, setAt: SET_AT }],
      [DETACHED_KEY, { refs: { todoIds: [], issues: [7] }, setAt: SET_AT }],
    ])
  })

  test('a missing field reads as empty; a missing or wrong-typed set_at as empty text', async () => {
    expect(parseOverrides(file({ topic: { issues: [5] } })).get('topic')).toEqual({
      refs: { todoIds: [], issues: [5] }, setAt: '',
    })
    expect(parseOverrides(file({ topic: { issues: [5], set_at: 7 } })).get('topic')?.setAt).toBe('')
  })

  test('an absent file, malformed JSON, another version or no branches object hold none', async () => {
    const texts = [
      undefined, '', '{not json', '[]', 'null', file({}, 2), file({ topic: entry([], [1]) }, '1'),
      file({ topic: entry([], [1]) }, true), JSON.stringify({ version: 1 }), file([]),
    ]
    for (const text of texts) expect(parseOverrides(text).size).toBe(0)
  })

  test('an entry with a wrong-typed field is skipped; the others stay', async () => {
    const text = file({
      good: entry(['todo-a'], [1]), ids: entry('todo-a', [1]), nums: entry([], ['1']), frac: entry([], [1.5]),
      bare: 'todo-a', nil: null,
    })
    expect([...parseOverrides(text).keys()]).toEqual(['good'])
  })
})
