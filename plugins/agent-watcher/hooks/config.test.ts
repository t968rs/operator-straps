import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_AGENT_USAGE_PATH, DEFAULT_BASE_BRANCH, DEFAULT_MATRIX_PATH, DEFAULT_REVIEWS, DEFAULT_SCRATCH,
  DEFAULT_STATE_DIR, readConfig, runtimeBaseOf, sentinelDirOf, under,
} from './config'
import { HARNESS_CONFIG_REL, rootCandidates } from './root'

const DEFAULTS = {
  stateDir: DEFAULT_STATE_DIR, matrixPath: DEFAULT_MATRIX_PATH, agentUsagePath: DEFAULT_AGENT_USAGE_PATH,
  reviewsDir: DEFAULT_REVIEWS, scratchDir: DEFAULT_SCRATCH, baseBranch: DEFAULT_BASE_BRANCH,
}

describe('readConfig (harness.json over the mirrored defaults)', () => {
  test('an empty object, malformed JSON or a non-object keeps every default', async () => {
    expect(readConfig('{}')).toEqual(DEFAULTS)
    expect(readConfig('{ not json')).toEqual(DEFAULTS)
    expect(readConfig('[1, 2]')).toEqual(DEFAULTS)
    expect(readConfig('null')).toEqual(DEFAULTS)
  })

  test('the keys it reads replace the defaults; artifacts merge key by key', async () => {
    const text = JSON.stringify({
      state_dir: '.state\\harness\\', matrix_path: 'meta/matrix.jsonl', agent_usage_path: 'meta/u.jsonl',
      base_branch: 'dev', artifacts: { reviews: 'reviews/' }, tests: { roots: ['t/'] },
    })
    expect(readConfig(text)).toEqual({
      stateDir: '.state/harness', matrixPath: 'meta/matrix.jsonl', agentUsagePath: 'meta/u.jsonl',
      reviewsDir: 'reviews', scratchDir: DEFAULT_SCRATCH, baseBranch: 'dev',
    })
  })

  test('wrong types and blanks fall back to the defaults', async () => {
    const text = JSON.stringify({
      state_dir: 3, matrix_path: '  ', agent_usage_path: '  ', base_branch: '', artifacts: 'x',
    })
    expect(readConfig(text)).toEqual(DEFAULTS)
  })

  test('sentinel and pr-team runtime folders sit under state_dir', async () => {
    const cfg = readConfig(JSON.stringify({ state_dir: 's' }))
    expect(sentinelDirOf(cfg)).toBe('s/pr-review')
    expect(runtimeBaseOf(cfg)).toBe('s/pr-team/_runtime')
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
