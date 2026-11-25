import { describe, expect, test } from 'claude-code/testing'

import { ancestorsOf, configPathOf, MAX_DEPTH, normalDir, parentOf, rootCandidates } from './root'

describe('parentOf and ancestorsOf', () => {
  test('POSIX: up to /', async () => {
    expect(ancestorsOf('/repo/sub/dir')).toEqual(['/repo/sub/dir', '/repo/sub', '/repo', '/'])
    expect(parentOf('/')).toBeUndefined()
  })

  test('a drive: up to C:', async () => {
    expect(ancestorsOf('C:/repo/sub')).toEqual(['C:/repo/sub', 'C:/repo', 'C:'])
    expect(parentOf('C:')).toBeUndefined()
  })

  test('UNC: up to the share', async () => {
    expect(ancestorsOf('//host/share/repo')).toEqual(['//host/share/repo', '//host/share'])
  })

  test('the walk is bounded', async () => {
    const deep = `/${Array.from({ length: 60 }, (_, i) => `d${i}`).join('/')}`
    expect(ancestorsOf(deep).length).toBe(MAX_DEPTH + 1)
  })
})

describe('rootCandidates', () => {
  test('the cwd and its ancestors, then CLAUDE_PROJECT_DIR; repeats dropped case-insensitively', async () => {
    expect(rootCandidates('/other', '/repo/sub')).toEqual(['/repo/sub', '/repo', '/', '/other'])
    expect(rootCandidates('C:\\Repo\\', 'c:\\repo')).toEqual(['c:/repo', 'c:'])
  })

  test('blank values are skipped', async () => {
    expect(rootCandidates(undefined, undefined)).toEqual([])
    expect(rootCandidates(' ', '')).toEqual([])
    expect(rootCandidates('/repo', '  ')).toEqual(['/repo'])
  })

  test('normalDir keeps / and strips trailing slashes', async () => {
    expect(normalDir('/')).toBe('/')
    expect(normalDir(' C:\\a\\b\\ ')).toBe('C:/a/b')
    expect(normalDir('')).toBeUndefined()
  })
})

describe('configPathOf', () => {
  test('no doubled slash at /', async () => {
    expect(configPathOf('/')).toBe('/.claude/harness.json')
    expect(configPathOf('/repo')).toBe('/repo/.claude/harness.json')
    expect(configPathOf('C:')).toBe('C:/.claude/harness.json')
  })
})
