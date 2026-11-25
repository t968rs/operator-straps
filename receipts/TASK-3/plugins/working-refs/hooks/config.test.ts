import { describe, expect, test } from 'claude-code/testing'

import {
  catalogFileOf,
  issuesCacheFileOf,
  lineFileOf,
  lineJsonFileOf,
  openIssuesFileOf,
  overridesFileOf,
  plansFolderOf,
  readConfig,
  under,
} from './config'
import {
  DEFAULT_GH_MAX_AGE_HOURS,
  DEFAULT_GH_REPO,
  DEFAULT_MAX_CHARS,
  DEFAULT_PLANS,
  DEFAULT_STATE_DIR,
  DEFAULT_TODO_CATALOG,
  DEFAULT_TODO_FOLDER,
  ISSUES_CACHE_PATH,
  LINE_JSON_PATH,
  LINE_PATH,
  OPEN_ISSUES_PATH,
  OVERRIDES_PATH,
} from './mirror'

const DEFAULTS = {
  stateDir: DEFAULT_STATE_DIR,
  plansDir: DEFAULT_PLANS,
  todoFolder: DEFAULT_TODO_FOLDER,
  todoCatalog: DEFAULT_TODO_CATALOG,
  ghRepo: DEFAULT_GH_REPO,
  ghMaxAgeHours: DEFAULT_GH_MAX_AGE_HOURS,
  maxChars: DEFAULT_MAX_CHARS,
}

describe('readConfig', () => {
  test('the defaults for absent, malformed or empty text', async () => {
    for (const text of [undefined, '', '{not json', '[]', '{}']) {
      expect(readConfig(text)).toEqual(DEFAULTS)
    }
  })

  test('state_dir and artifacts.plans, cleaned', async () => {
    const text = JSON.stringify({ state_dir: ' var\\state/ ', artifacts: { plans: 'docs/plans/', research: 'x' } })
    expect(readConfig(text)).toEqual({ ...DEFAULTS, stateDir: 'var/state', plansDir: 'docs/plans' })
  })

  test('blank or wrong-typed values keep the defaults', async () => {
    const text = JSON.stringify({ state_dir: '  ', artifacts: { plans: 3 } })
    expect(readConfig(text)).toEqual(DEFAULTS)
    expect(readConfig(JSON.stringify({ artifacts: 'docs' })).plansDir).toBe(DEFAULT_PLANS)
  })

  test('the todo keys and working_refs.max_chars', async () => {
    const text = JSON.stringify({
      todo: { folder: 'docs\\TODO/', catalog: 'Cat.json', gh: { repo: ' o/r ', max_age_hours: 6 } },
      working_refs: { max_chars: 80 },
    })
    expect(readConfig(text)).toEqual({
      ...DEFAULTS,
      todoFolder: 'docs/TODO',
      todoCatalog: 'Cat.json',
      ghRepo: 'o/r',
      ghMaxAgeHours: 6,
      maxChars: 80,
    })
  })

  test('wrong-typed todo and cap values keep the defaults', async () => {
    const bad = [
      { todo: { folder: '  ', catalog: 4, gh: { repo: '', max_age_hours: 0 } }, working_refs: { max_chars: 0 } },
      { todo: { folder: 3, gh: { repo: 5, max_age_hours: '24' } }, working_refs: { max_chars: 1.5 } },
      { todo: 'x', working_refs: { max_chars: true } },
      { todo: { gh: 'x' }, working_refs: 'x' },
    ]
    for (const data of bad) expect(readConfig(JSON.stringify(data))).toEqual(DEFAULTS)
  })
})

describe('the store paths', () => {
  const c = readConfig(undefined)

  test('joined under the project root', async () => {
    expect(overridesFileOf('/repo', c)).toBe(`/repo/${DEFAULT_STATE_DIR}/${OVERRIDES_PATH}`)
    expect(lineFileOf('C:\\repo\\', c)).toBe(`C:/repo/${DEFAULT_STATE_DIR}/${LINE_PATH}`)
    expect(plansFolderOf('/repo', c)).toBe(`/repo/${DEFAULT_PLANS}`)
  })

  test('the line json, open-issue list and issue cache under state_dir', async () => {
    expect(lineJsonFileOf('/repo', c)).toBe(`/repo/${DEFAULT_STATE_DIR}/${LINE_JSON_PATH}`)
    expect(openIssuesFileOf('/repo', c)).toBe(`/repo/${DEFAULT_STATE_DIR}/${OPEN_ISSUES_PATH}`)
    expect(issuesCacheFileOf('/repo', c)).toBe(`/repo/${DEFAULT_STATE_DIR}/${ISSUES_CACHE_PATH}`)
  })

  test('the catalog under todo.folder, null while the folder is unset', async () => {
    expect(catalogFileOf('/repo', c)).toBeNull()
    expect(catalogFileOf('/repo', { ...c, todoFolder: 'docs/TODO' })).toBe(`/repo/docs/TODO/${DEFAULT_TODO_CATALOG}`)
    expect(catalogFileOf('/repo', { ...c, todoFolder: 'D:/todo', todoCatalog: 'x.json' })).toBe('D:/todo/x.json')
  })

  test('an absolute configured path is kept', async () => {
    expect(under('/repo', 'D:/state')).toBe('D:/state')
    expect(lineFileOf('/repo', { ...c, stateDir: '/data/state' })).toBe(`/data/state/${LINE_PATH}`)
  })
})
