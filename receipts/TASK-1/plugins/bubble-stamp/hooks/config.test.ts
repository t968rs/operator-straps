import { describe, expect, test } from 'claude-code/testing'

import { DEFAULT_REVIEWS, readConfig, under } from './config'

describe('readConfig (harness.json over the mirrored default)', () => {
  test('an empty object, malformed JSON or a non-object keeps the default', async () => {
    const defaults = { reviewsDir: DEFAULT_REVIEWS }
    expect(DEFAULT_REVIEWS).toBe('docs/PR_REVIEWS')
    expect(readConfig('{}')).toEqual(defaults)
    expect(readConfig('{ not json')).toEqual(defaults)
    expect(readConfig('[1, 2]')).toEqual(defaults)
    expect(readConfig('null')).toEqual(defaults)
    expect(readConfig('')).toEqual(defaults)
  })

  test('artifacts.reviews replaces the default; backslashes and trailing slashes are cleaned', async () => {
    expect(readConfig(JSON.stringify({ artifacts: { reviews: 'reviews/' } }))).toEqual({ reviewsDir: 'reviews' })
    expect(readConfig(JSON.stringify({ artifacts: { reviews: ' out\\prs\\ ' } }))).toEqual({ reviewsDir: 'out/prs' })
  })

  test('other keys are ignored', async () => {
    const text = JSON.stringify({ state_dir: 's', base_branch: 'dev', artifacts: { scratch: 'x', reviews: 'r' } })
    expect(readConfig(text)).toEqual({ reviewsDir: 'r' })
  })

  test('wrong types and blanks fall back to the default', async () => {
    expect(readConfig(JSON.stringify({ artifacts: 'x' }))).toEqual({ reviewsDir: DEFAULT_REVIEWS })
    expect(readConfig(JSON.stringify({ artifacts: { reviews: 3 } }))).toEqual({ reviewsDir: DEFAULT_REVIEWS })
    expect(readConfig(JSON.stringify({ artifacts: { reviews: '  ' } }))).toEqual({ reviewsDir: DEFAULT_REVIEWS })
    expect(readConfig(JSON.stringify({ artifacts: [1] }))).toEqual({ reviewsDir: DEFAULT_REVIEWS })
  })
})

describe('under', () => {
  test('a relative path joins the root; an absolute one (POSIX, drive or UNC) is kept', async () => {
    expect(under('/repo', 'docs/PR_REVIEWS')).toBe('/repo/docs/PR_REVIEWS')
    expect(under('/repo', '/abs/r')).toBe('/abs/r')
    expect(under('C:/repo', 'C:/abs/r')).toBe('C:/abs/r')
    expect(under('C:/repo', 'D:\\abs\\r')).toBe('D:\\abs\\r')
    expect(under('C:/repo', '//host/share')).toBe('//host/share')
  })
})
