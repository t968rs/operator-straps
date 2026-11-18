import { describe, expect, test } from 'claude-code/testing'

import { lineFileOf, overridesFileOf, plansFolderOf, readConfig, under } from './config'
import { DEFAULT_PLANS, DEFAULT_STATE_DIR, DETACHED_KEY, LINE_PATH, OVERRIDES_PATH, STORE_VERSION } from './mirror'
import { parseOverrides } from './overrides'

const SET_AT = '2026-11-18T00:00:00Z'
const file = (branches: unknown, version: unknown = STORE_VERSION): string => JSON.stringify({ version, branches })
const entry = (todo_ids?: unknown, issues?: unknown) => ({ todo_ids, issues, set_at: SET_AT })

describe('parseOverrides', () => {
  test('each branch\'s refs, set_at ignored', async () => {
    const text = file({ topic: entry(['todo-k69m'], [301]), [DETACHED_KEY]: entry([], [7]) })
    expect([...parseOverrides(text)]).toEqual([
      ['topic', { todoIds: ['todo-k69m'], issues: [301] }],
      [DETACHED_KEY, { todoIds: [], issues: [7] }],
    ])
  })

  test('a missing field reads as empty', async () => {
    expect(parseOverrides(file({ topic: { issues: [5] } })).get('topic')).toEqual({ todoIds: [], issues: [5] })
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

describe('readConfig', () => {
  test('the defaults for absent, malformed or empty text', async () => {
    for (const text of [undefined, '', '{not json', '[]', '{}']) {
      expect(readConfig(text)).toEqual({ stateDir: DEFAULT_STATE_DIR, plansDir: DEFAULT_PLANS })
    }
  })

  test('state_dir and artifacts.plans, cleaned', async () => {
    const text = JSON.stringify({ state_dir: ' var\\state/ ', artifacts: { plans: 'docs/plans/', research: 'x' } })
    expect(readConfig(text)).toEqual({ stateDir: 'var/state', plansDir: 'docs/plans' })
  })

  test('blank or wrong-typed values keep the defaults', async () => {
    const text = JSON.stringify({ state_dir: '  ', artifacts: { plans: 3 } })
    expect(readConfig(text)).toEqual({ stateDir: DEFAULT_STATE_DIR, plansDir: DEFAULT_PLANS })
    expect(readConfig(JSON.stringify({ artifacts: 'docs' })).plansDir).toBe(DEFAULT_PLANS)
  })
})

describe('the store paths', () => {
  const c = readConfig(undefined)

  test('joined under the project root', async () => {
    expect(overridesFileOf('/repo', c)).toBe(`/repo/${DEFAULT_STATE_DIR}/${OVERRIDES_PATH}`)
    expect(lineFileOf('C:\\repo\\', c)).toBe(`C:/repo/${DEFAULT_STATE_DIR}/${LINE_PATH}`)
    expect(plansFolderOf('/repo', c)).toBe(`/repo/${DEFAULT_PLANS}`)
  })

  test('an absolute configured path is kept', async () => {
    expect(under('/repo', 'D:/state')).toBe('D:/state')
    expect(lineFileOf('/repo', { ...c, stateDir: '/data/state' })).toBe(`/data/state/${LINE_PATH}`)
  })
})
