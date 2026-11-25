import { describe, expect, test } from 'claude-code/testing'

import {
  isLocalKey, keyOfRunId, LABEL_MAX, LABEL_PATTERN, LOCAL_PREFIX, reviewPrefix, RUN_ID_PATTERN, runDirName, runName,
  startedAtOfRunId, toRunKey,
} from './runKey'

const STAMP = '20261102T080910Z'
const RUN = 'pr1526_20261009T120000Z'
const LOCAL_RUN = 'local-fix-band_20261102T080910Z'

describe('keyOfRunId', () => {
  test('pr number from a run id, null otherwise', async () => {
    expect(keyOfRunId(RUN)).toBe(1526)
    expect(keyOfRunId('run-1')).toBeNull()
  })

  test('the local key from a review-local run id', async () => {
    expect(keyOfRunId(LOCAL_RUN)).toBe('local-fix-band')
    expect(keyOfRunId('local-x_20261102T080910Z')).toBe('local-x')
    expect(keyOfRunId('local-Bad_20261102T080910Z')).toBeNull()
    expect(keyOfRunId('local-a--b_20261102T080910Z')).toBeNull()
    expect(keyOfRunId('local-_20261102T080910Z')).toBeNull()
  })
})

describe('startedAtOfRunId', () => {
  test('epoch ms of the UTC stamp in a run id, null otherwise', async () => {
    expect(startedAtOfRunId(RUN)).toBe(Date.UTC(2026, 9, 9, 12, 0, 0))
    expect(startedAtOfRunId('run-1')).toBeNull()
    expect(startedAtOfRunId('pr1526_20261309T120000Z')).toBeNull()
  })

  test('a review-local run id carries the same stamp', async () => {
    expect(startedAtOfRunId(LOCAL_RUN)).toBe(Date.UTC(2026, 10, 2, 8, 9, 10))
    expect(startedAtOfRunId('local-x_20261302T080910Z')).toBeNull()
  })
})

describe('isLocalKey', () => {
  test('local-<label>: lower-case letters, digits and single hyphens, at most LABEL_MAX', async () => {
    expect(isLocalKey('local-x')).toBe(true)
    expect(isLocalKey('local-fix-band-2')).toBe(true)
    expect(isLocalKey(`local-${'a'.repeat(LABEL_MAX)}`)).toBe(true)
    expect(isLocalKey(`local-${'a'.repeat(LABEL_MAX + 1)}`)).toBe(false)
    for (const bad of ['local-', 'local-X', 'local-a--b', 'local--a', 'local-a-', 'local-a_b', 'pr-1', '1526', 7]) {
      expect(isLocalKey(bad)).toBe(false)
    }
  })
})

describe('toRunKey', () => {
  test('a PR number, a local key, else null', async () => {
    expect(toRunKey('1526')).toBe(1526)
    expect(toRunKey('local-x')).toBe('local-x')
    expect(toRunKey('0')).toBeNull()
    expect(toRunKey('local-X')).toBeNull()
    expect(toRunKey('')).toBeNull()
    expect(toRunKey(undefined)).toBeNull()
  })
})

describe('RUN_ID_PATTERN', () => {
  test('built from the mirrored constants', async () => {
    expect(RUN_ID_PATTERN).toContain(`${LOCAL_PREFIX}(?=[^_]{1,${LABEL_MAX}}_)`)
    expect(RUN_ID_PATTERN).toContain(LABEL_PATTERN.slice(1, -1).replace('(-', '(?:-'))
  })

  test('the local label is bounded by LABEL_MAX', async () => {
    expect(keyOfRunId(`local-${'a'.repeat(LABEL_MAX)}_${STAMP}`)).toBe(`local-${'a'.repeat(LABEL_MAX)}`)
    expect(keyOfRunId(`local-${'a'.repeat(LABEL_MAX + 1)}_${STAMP}`)).toBeNull()
    expect(keyOfRunId(`pr12345678_${STAMP}`)).toBeNull()
  })
})

describe('names built from a key', () => {
  test('run directory: zero-padded PR number, or the local key itself', async () => {
    expect(runDirName(42)).toBe('0042')
    expect(runDirName(12345)).toBe('12345')
    expect(runDirName('local-x')).toBe('local-x')
  })

  test('review prefix: <NNNN>_, or LOCAL_<label>_', async () => {
    expect(reviewPrefix(916)).toBe('0916_')
    expect(reviewPrefix('local-fix-band')).toBe('LOCAL_fix-band_')
  })

  test('run name: PR #<N>, local review <key>, PR #? for none', async () => {
    expect(runName(1526)).toBe('PR #1526')
    expect(runName('1526')).toBe('PR #1526')
    expect(runName('local-x')).toBe('local review local-x')
    expect(runName(null)).toBe('PR #?')
  })
})
