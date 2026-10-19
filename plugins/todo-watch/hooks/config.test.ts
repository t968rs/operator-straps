import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_GH_MAX_AGE_HOURS, DEFAULT_INJECT_CONTEXT, DEFAULT_PLANS, DEFAULT_RESEARCH, DEFAULT_STATE_DIR,
  DEFAULT_TOP_N, isActive, readConfig, syncDirOf, under,
} from './config'

const DEFAULTS = {
  stateDir: DEFAULT_STATE_DIR, researchDir: DEFAULT_RESEARCH, plansDir: DEFAULT_PLANS, catalog: null,
  catalogSchema: null, topN: DEFAULT_TOP_N, snapshotsDir: null, researchCatalog: null,
  ghMaxAgeHours: DEFAULT_GH_MAX_AGE_HOURS, injectContext: DEFAULT_INJECT_CONTEXT,
}

describe('readConfig', () => {
  test('an empty or malformed file is the defaults, inactive', async () => {
    expect(readConfig('{}')).toEqual(DEFAULTS)
    expect(readConfig('{')).toEqual(DEFAULTS)
    expect(readConfig('[1]')).toEqual(DEFAULTS)
    expect(isActive(readConfig('{}'))).toBe(false)
  })

  test('every key read, objects merged key by key', async () => {
    const text = JSON.stringify({
      state_dir: '.claude\\state\\h\\',
      artifacts: { research: 'docs/R/', reviews: 'x' },
      todo: {
        catalog: 'docs/R/todo.json', catalog_schema: 'docs/R/todo.schema.json', top_n: 5,
        snapshots: { dir: 'docs/R/TODO', name_pattern: 'x' }, research: { catalog: 'docs/R/cat.json' },
        gh: { max_age_hours: 6.5 }, inject_context: false,
      },
    })
    expect(readConfig(text)).toEqual({
      ...DEFAULTS, stateDir: '.claude/state/h', researchDir: 'docs/R', catalog: 'docs/R/todo.json',
      catalogSchema: 'docs/R/todo.schema.json', topN: 5, snapshotsDir: 'docs/R/TODO',
      researchCatalog: 'docs/R/cat.json', ghMaxAgeHours: 6.5, injectContext: false,
    })
    expect(isActive(readConfig(text))).toBe(true)
  })

  test('a wrong-typed value keeps its default; blank strings count as unset', async () => {
    const text = JSON.stringify({
      state_dir: 3, artifacts: { plans: ['x'] },
      todo: { catalog: '  ', top_n: 0, gh: { max_age_hours: '24' }, inject_context: 'yes', snapshots: 'x' },
    })
    expect(readConfig(text)).toEqual(DEFAULTS)
    expect(readConfig(JSON.stringify({ todo: { top_n: 2.5 } })).topN).toBe(DEFAULT_TOP_N)
    expect(readConfig(JSON.stringify({ todo: [] })).catalog).toBeNull()
  })

  test('null keeps a nullable key off', async () => {
    expect(readConfig(JSON.stringify({ todo: { catalog: null, snapshots: { dir: null } } }))).toEqual(DEFAULTS)
  })
})

describe('paths', () => {
  test('relative paths join the root; absolute ones are kept', async () => {
    expect(under('/repo', 'docs/a.json')).toBe('/repo/docs/a.json')
    expect(under('C:/repo', 'docs/a.json')).toBe('C:/repo/docs/a.json')
    expect(under('/repo', '/abs/a.json')).toBe('/abs/a.json')
    expect(under('/repo', 'D:/abs/a.json')).toBe('D:/abs/a.json')
    expect(under('/repo', '//host/share/a.json')).toBe('//host/share/a.json')
  })

  test('the sync folder sits under state_dir', async () => {
    expect(syncDirOf(readConfig('{}'))).toBe('.claude/state/harness/todo-sync')
  })
})
