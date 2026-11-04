import { describe, expect, test } from 'claude-code/testing'

import {
  coreConfigOf, DEFAULT_AGENT_USAGE_PATH, DEFAULT_STATE_DIR, parseHarness, readConfig, under,
} from './config'
import { HARNESS_CONFIG_REL, rootCandidates } from './root'

const DEFAULTS = { stateDir: DEFAULT_STATE_DIR, agentUsagePath: DEFAULT_AGENT_USAGE_PATH }

describe('readConfig (harness.json over the mirrored core defaults)', () => {
  test('an empty object, malformed JSON or a non-object keeps every default', async () => {
    expect(readConfig('{}')).toEqual(DEFAULTS)
    expect(readConfig('{ not json')).toEqual(DEFAULTS)
    expect(readConfig('[1, 2]')).toEqual(DEFAULTS)
    expect(readConfig('null')).toEqual(DEFAULTS)
  })

  test('the keys it reads replace the defaults; other keys are left to the layers', async () => {
    const text = JSON.stringify({
      state_dir: '.state\\harness\\', matrix_path: 'meta/matrix.jsonl', agent_usage_path: 'meta/u.jsonl',
      base_branch: 'dev', artifacts: { reviews: 'reviews/' }, tests: { roots: ['t/'] },
    })
    expect(readConfig(text)).toEqual({ stateDir: '.state/harness', agentUsagePath: 'meta/u.jsonl' })
  })

  test('wrong types and blanks fall back to the defaults', async () => {
    expect(readConfig(JSON.stringify({ state_dir: 3, agent_usage_path: '  ' }))).toEqual(DEFAULTS)
  })
})

describe('parseHarness (the whole file, kept for the layers)', () => {
  test('a JSON object as parsed; anything else is empty', async () => {
    const data = { state_dir: 's', artifacts: { reviews: 'r' } }
    expect(parseHarness(JSON.stringify(data))).toEqual(data)
    expect(coreConfigOf(parseHarness(JSON.stringify(data)))).toEqual(readConfig(JSON.stringify(data)))
    for (const text of ['{ not json', '[1, 2]', 'null', '"x"']) expect(parseHarness(text)).toEqual({})
  })
})

describe('under', () => {
  test('a relative path joins the root; an absolute one (POSIX, drive or UNC) is kept', async () => {
    expect(under('/repo', 's/pr-review')).toBe('/repo/s/pr-review')
    expect(under('/repo', '/abs/s')).toBe('/abs/s')
    expect(under('C:/repo', 'C:/abs/s')).toBe('C:/abs/s')
    expect(under('C:/repo', 'D:\\abs\\s')).toBe('D:\\abs\\s')
    expect(under('C:/repo', '//host/share')).toBe('//host/share')
  })
})

describe('rootCandidates (harness_lib.project.project_root order)', () => {
  test('git top level of the cwd, then CLAUDE_PROJECT_DIR, then the cwd; repeats and blanks dropped', async () => {
    expect(HARNESS_CONFIG_REL).toBe('.claude/harness.json')
    expect(rootCandidates('C:\\repo\\', undefined)).toEqual(['C:/repo'])
    expect(rootCandidates(undefined, '/w')).toEqual(['/w'])
    expect(rootCandidates('/repo', '/REPO')).toEqual(['/repo'])
    expect(rootCandidates('/repo', '/wt')).toEqual(['/repo', '/wt'])
    expect(rootCandidates('/repo', '/wt/sub', '/wt\n')).toEqual(['/wt', '/repo', '/wt/sub'])
    expect(rootCandidates('/repo', '/repo/sub', '/repo')).toEqual(['/repo', '/repo/sub'])
    expect(rootCandidates(' ', '', ' ')).toEqual([])
  })
})
