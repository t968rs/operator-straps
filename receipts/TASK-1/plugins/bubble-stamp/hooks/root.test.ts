import { describe, expect, test } from 'claude-code/testing'

import { HARNESS_CONFIG_REL, rootCandidates } from './root'

describe('rootCandidates (harness_lib.project.project_root order)', () => {
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
