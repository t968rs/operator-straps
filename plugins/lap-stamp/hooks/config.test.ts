import { describe, expect, test } from 'claude-code/testing'

import { DEFAULT_STATE_DIR, LAPS_PATH, lapsPathOf, readConfig } from './config'
import { HARNESS_CONFIG_REL, rootCandidates } from './root'

describe('readConfig (harness.json over the mirrored state_dir)', () => {
  test('an empty object, malformed JSON, a non-object or blank text keeps the default', async () => {
    const defaults = { stateDir: DEFAULT_STATE_DIR }
    expect(DEFAULT_STATE_DIR).toBe('.claude/state/harness')
    expect(readConfig('{}')).toEqual(defaults)
    expect(readConfig('{ not json')).toEqual(defaults)
    expect(readConfig('[1, 2]')).toEqual(defaults)
    expect(readConfig('null')).toEqual(defaults)
    expect(readConfig('')).toEqual(defaults)
  })

  test('state_dir replaces the default; backslashes and trailing slashes are cleaned', async () => {
    expect(readConfig(JSON.stringify({ state_dir: 'out/state/' }))).toEqual({ stateDir: 'out/state' })
    expect(readConfig(JSON.stringify({ state_dir: ' out\\state\\ ' }))).toEqual({ stateDir: 'out/state' })
  })

  test('other keys are ignored', async () => {
    const text = JSON.stringify({ artifacts: { reviews: 'r' }, base_branch: 'dev', state_dir: 's' })
    expect(readConfig(text)).toEqual({ stateDir: 's' })
  })

  test('a non-string or blank state_dir falls back to the default', async () => {
    expect(readConfig(JSON.stringify({ state_dir: 3 }))).toEqual({ stateDir: DEFAULT_STATE_DIR })
    expect(readConfig(JSON.stringify({ state_dir: null }))).toEqual({ stateDir: DEFAULT_STATE_DIR })
    expect(readConfig(JSON.stringify({ state_dir: ['s'] }))).toEqual({ stateDir: DEFAULT_STATE_DIR })
    expect(readConfig(JSON.stringify({ state_dir: '  ' }))).toEqual({ stateDir: DEFAULT_STATE_DIR })
  })
})

describe('lapsPathOf (the laps file under state_dir)', () => {
  test('the laps file is the mod folder and its file under state_dir', async () => {
    expect(LAPS_PATH).toBe('lap-stamp/laps.jsonl')
  })

  test('the default state_dir joins the project root', async () => {
    expect(lapsPathOf('/repo', readConfig('{}'))).toBe('/repo/.claude/state/harness/lap-stamp/laps.jsonl')
  })

  test('a relative state_dir joins the root; an absolute one (POSIX, drive or UNC) is kept', async () => {
    expect(lapsPathOf('/repo', { stateDir: 'out/state' })).toBe('/repo/out/state/lap-stamp/laps.jsonl')
    expect(lapsPathOf('C:/repo', { stateDir: 'C:/abs/s' })).toBe('C:/abs/s/lap-stamp/laps.jsonl')
    expect(lapsPathOf('C:/repo', { stateDir: '/abs/s' })).toBe('/abs/s/lap-stamp/laps.jsonl')
    expect(lapsPathOf('C:/repo', { stateDir: '//host/share' })).toBe('//host/share/lap-stamp/laps.jsonl')
  })
})

describe('root (harness_lib.project.project_root order)', () => {
  test('the config file the mod needs is .claude/harness.json', async () => {
    expect(HARNESS_CONFIG_REL).toBe('.claude/harness.json')
  })

  test('git top level of the cwd, then CLAUDE_PROJECT_DIR, then the cwd; repeats and blanks dropped', async () => {
    expect(rootCandidates('C:\\repo\\', undefined)).toEqual(['C:/repo'])
    expect(rootCandidates(undefined, '/w')).toEqual(['/w'])
    expect(rootCandidates('/repo', '/REPO')).toEqual(['/repo'])
    expect(rootCandidates('/repo', '/wt')).toEqual(['/repo', '/wt'])
    expect(rootCandidates('/repo', '/wt/sub', '/wt\n')).toEqual(['/wt', '/repo', '/wt/sub'])
    expect(rootCandidates('/repo', '/repo/sub', '/repo')).toEqual(['/repo', '/repo/sub'])
    expect(rootCandidates(' ', '', ' ')).toEqual([])
  })
})
