import { describe, expect, test } from 'claude-code/testing'

import { lineFileOf, overridesFileOf, plansFolderOf, readConfig, under } from './config'
import { DEFAULT_PLANS, DEFAULT_STATE_DIR, LINE_PATH, OVERRIDES_PATH } from './mirror'

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
