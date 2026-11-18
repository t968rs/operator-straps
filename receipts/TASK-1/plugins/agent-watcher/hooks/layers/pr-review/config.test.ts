import { describe, expect, test } from 'claude-code/testing'

import { parseHarness, readConfig } from '../../core/config'
import {
  DEFAULT_BASE_BRANCH, DEFAULT_MATRIX_PATH, DEFAULT_REVIEWS, DEFAULT_SCRATCH, prReviewConfigOf, runtimeBaseOf,
  sentinelDirOf,
} from './config'

const DEFAULTS = {
  matrixPath: DEFAULT_MATRIX_PATH, reviewsDir: DEFAULT_REVIEWS, scratchDir: DEFAULT_SCRATCH,
  baseBranch: DEFAULT_BASE_BRANCH,
}
const configOf = (text: string) => prReviewConfigOf(parseHarness(text))

describe('prReviewConfigOf (harness.json over the mirrored pr-review defaults)', () => {
  test('an empty object, malformed JSON or a non-object keeps every default', async () => {
    expect(configOf('{}')).toEqual(DEFAULTS)
    expect(configOf('{ not json')).toEqual(DEFAULTS)
    expect(configOf('[1, 2]')).toEqual(DEFAULTS)
    expect(configOf('null')).toEqual(DEFAULTS)
  })

  test('the keys it reads replace the defaults; artifacts merge key by key', async () => {
    const text = JSON.stringify({
      state_dir: '.state\\harness\\', matrix_path: 'meta/matrix.jsonl', agent_usage_path: 'meta/u.jsonl',
      base_branch: 'dev', artifacts: { reviews: 'reviews/' }, tests: { roots: ['t/'] },
    })
    expect(configOf(text)).toEqual({
      matrixPath: 'meta/matrix.jsonl', reviewsDir: 'reviews', scratchDir: DEFAULT_SCRATCH, baseBranch: 'dev',
    })
  })

  test('wrong types and blanks fall back to the defaults', async () => {
    expect(configOf(JSON.stringify({ matrix_path: '  ', base_branch: '', artifacts: 'x' }))).toEqual(DEFAULTS)
    const typed = { matrix_path: 3, base_branch: 7, artifacts: { scratch: ' ' } }
    expect(configOf(JSON.stringify(typed))).toEqual(DEFAULTS)
  })

  test('sentinel and pr-team runtime folders sit under state_dir', async () => {
    const cfg = readConfig(JSON.stringify({ state_dir: 's' }))
    expect(sentinelDirOf(cfg)).toBe('s/pr-review')
    expect(runtimeBaseOf(cfg)).toBe('s/pr-team/_runtime')
  })
})
