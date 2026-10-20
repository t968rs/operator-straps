import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_GH_MAX_AGE_HOURS, DEFAULT_INJECT_CONTEXT, DEFAULT_NOTICE_ITEMS, DEFAULT_NOTICE_STYLE, DEFAULT_PLANS,
  DEFAULT_RESEARCH,
  DEFAULT_STATE_DIR, DEFAULT_TOAST_SECONDS, DEFAULT_TOP_N, inFolder, isActive, readConfig, syncDirOf, under,
} from './config'

const DEFAULTS = {
  stateDir: DEFAULT_STATE_DIR, researchDir: DEFAULT_RESEARCH, plansDir: DEFAULT_PLANS, folder: null,
  catalog: null, catalogSchema: null, topN: DEFAULT_TOP_N, snapshotsDir: null, researchCatalog: null,
  ghMaxAgeHours: DEFAULT_GH_MAX_AGE_HOURS, injectContext: DEFAULT_INJECT_CONTEXT,
  noticeStyle: DEFAULT_NOTICE_STYLE, toastMs: DEFAULT_TOAST_SECONDS * 1000, noticeItems: DEFAULT_NOTICE_ITEMS,
}

const F = 'docs/RESEARCH/_TODO'

/** The paths a bare `{"folder": F}` block resolves to. */
const FOLDER_ONLY = {
  ...DEFAULTS, folder: F, catalog: `${F}/RepoToDo.json`, catalogSchema: `${F}/RepoToDo.schema.json`,
  snapshotsDir: `${F}/Snapshots`, researchCatalog: `${F}/ResearchImplementationCatalog.json`,
}

describe('readConfig', () => {
  test('an empty or malformed file is the defaults, inactive', async () => {
    expect(readConfig('{}')).toEqual(DEFAULTS)
    expect(readConfig('{')).toEqual(DEFAULTS)
    expect(readConfig('[1]')).toEqual(DEFAULTS)
    expect(isActive(readConfig('{}'))).toBe(false)
  })

  test('the folder alone derives every TODO path and turns the watch on', async () => {
    const config = readConfig(JSON.stringify({ todo: { folder: `${F}/` } }))
    expect(config).toEqual(FOLDER_ONLY)
    expect(isActive(config)).toBe(true)
    expect(readConfig(JSON.stringify({ todo: { folder: F.replace(/\//g, '\\') } }))).toEqual(FOLDER_ONLY)
  })

  test('every key read, names resolved under the folder, objects merged key by key', async () => {
    const text = JSON.stringify({
      state_dir: '.claude\\state\\h\\',
      artifacts: { research: 'docs/R/', reviews: 'x' },
      todo: {
        folder: 'docs/R/T', catalog: 'todo.json', catalog_schema: '../schemas/todo.schema.json', top_n: 5,
        snapshots: { dir: '../TODO', name_pattern: 'x' }, research: { catalog: 'cat.json' },
        gh: { max_age_hours: 6.5 }, inject_context: false, notice: { style: 'banner', toast_seconds: 12.5 },
      },
    })
    expect(readConfig(text)).toEqual({
      ...DEFAULTS, stateDir: '.claude/state/h', researchDir: 'docs/R', folder: 'docs/R/T',
      catalog: 'docs/R/T/todo.json', catalogSchema: 'docs/R/schemas/todo.schema.json', topN: 5,
      snapshotsDir: 'docs/R/TODO', researchCatalog: 'docs/R/T/cat.json', ghMaxAgeHours: 6.5, injectContext: false,
      noticeStyle: 'banner', toastMs: 12_500,
    })
  })

  test('without a folder no other key turns the watch on', async () => {
    const config = readConfig(JSON.stringify({ todo: { catalog: 'docs/R/todo.json' } }))
    expect(config).toEqual(DEFAULTS)
    expect(isActive(config)).toBe(false)
  })

  test('a wrong-typed value keeps its default; blank strings count as unset', async () => {
    const text = JSON.stringify({
      state_dir: 3, artifacts: { plans: ['x'] },
      todo: { folder: '  ', top_n: 0, gh: { max_age_hours: '24' }, inject_context: 'yes', snapshots: 'x' },
    })
    expect(readConfig(text)).toEqual(DEFAULTS)
    expect(readConfig(JSON.stringify({ todo: { top_n: 2.5 } })).topN).toBe(DEFAULT_TOP_N)
    expect(readConfig(JSON.stringify({ todo: [] })).catalog).toBeNull()
    expect(readConfig(JSON.stringify({ todo: { folder: F, catalog: 7 } }))).toEqual(FOLDER_ONLY)
  })

  test('the toast defaults to the engine ceiling; an unknown style or an out-of-range time keeps the default', async () => {
    expect([DEFAULT_NOTICE_STYLE, DEFAULT_TOAST_SECONDS]).toEqual(['banner', 60])
    for (const notice of [{ style: 'popup' }, { style: 'BANNER' }, { toast_seconds: 0 }, { toast_seconds: 61 },
      { toast_seconds: '30' }, { toast_seconds: -5 }, 'banner']) {
      expect(readConfig(JSON.stringify({ todo: { notice } }))).toEqual(DEFAULTS)
    }
    expect(readConfig(JSON.stringify({ todo: { notice: { toast_seconds: 0.25 } } })).toastMs).toBe(250)
  })

  test('the notice defaults to a banner listing 3 items', async () => {
    const config = readConfig('{}')
    expect([config.noticeStyle, config.noticeItems]).toEqual(['banner', 3])
  })

  test('notice items: an integer from 1 to 10, else the default', async () => {
    for (const items of [1, 5, 10]) {
      expect(readConfig(JSON.stringify({ todo: { notice: { items } } })).noticeItems).toBe(items)
    }
    for (const items of [0, 11, 2.5, '5']) {
      expect(readConfig(JSON.stringify({ todo: { notice: { items } } })).noticeItems).toBe(3)
    }
  })

  test('null turns a nullable path off', async () => {
    const text = JSON.stringify({
      todo: { folder: F, catalog_schema: null, snapshots: { dir: null }, research: { catalog: null } },
    })
    expect(readConfig(text)).toEqual({ ...FOLDER_ONLY, catalogSchema: null, snapshotsDir: null, researchCatalog: null })
  })

  test('a rooted, drive-prefixed or climbing folder leaves the watch inactive', async () => {
    for (const folder of ['/abs/_TODO', 'C:/repo/_TODO', 'C:\\repo\\_TODO', '../_TODO', 'docs/../..']) {
      const config = readConfig(JSON.stringify({ todo: { folder } }))
      expect(config).toEqual(DEFAULTS)
      expect(isActive(config)).toBe(false)
    }
  })
})

describe('inFolder', () => {
  test('joins and folds dot segments like posixpath.normpath', async () => {
    expect(inFolder('docs/T', 'a.json')).toBe('docs/T/a.json')
    expect(inFolder('docs/T', './x/../a.json')).toBe('docs/T/a.json')
    expect(inFolder('docs/T', '../../..')).toBe('..')
    expect(inFolder('docs/T', '..\\U\\b.json')).toBe('docs/U/b.json')
    expect(inFolder('/abs/T', '../a.json')).toBe('/abs/a.json')
  })

  test('null on either side is null', async () => {
    expect(inFolder(null, 'a.json')).toBeNull()
    expect(inFolder('docs/T', null)).toBeNull()
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
