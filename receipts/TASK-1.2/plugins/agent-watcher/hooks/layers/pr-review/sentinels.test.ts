import { describe, expect, test } from 'claude-code/testing'

import { blocksSession, isHot, isSentinelName, MAX_AGE_SECONDS, parseSentinel } from './sentinels'

describe('sentinels (the harness check_phase5_sentinel.py rule)', () => {
  test('parse line 1 PR, line 2 unix time, line 3 arming session', async () => {
    expect(parseSentinel('1526\r\n1700000000\r\nsess-a\r\n'))
      .toEqual({ pr: '1526', writtenAt: 1700000000, sessionId: 'sess-a' })
    expect(parseSentinel('1526\r\n1700000000\r\n')).toEqual({ pr: '1526', writtenAt: 1700000000, sessionId: null })
    expect(parseSentinel('1526\nlater\n  ')).toEqual({ pr: '1526', writtenAt: null, sessionId: null })
    expect(parseSentinel('')).toEqual({ pr: null, writtenAt: null, sessionId: null })
  })

  test('a sentinel spares a session only when both ids are known and differ', async () => {
    expect(blocksSession('sess-a', 'sess-a')).toBe(true)
    expect(blocksSession('sess-a', 'sess-b')).toBe(false)
    expect(blocksSession(null, 'sess-b')).toBe(true)
    expect(blocksSession('sess-a', undefined)).toBe(true)
    expect(blocksSession('sess-a', '')).toBe(true)
    expect(blocksSession('sess-a', '  ')).toBe(true)
  })

  test('hot strictly under 24 h', async () => {
    expect(isHot(0, MAX_AGE_SECONDS - 1)).toBe(true)
    expect(isHot(0, MAX_AGE_SECONDS)).toBe(false)
  })

  test('sentinel names', async () => {
    expect(isSentinelName('.phase5_pending_1526')).toBe(true)
    expect(isSentinelName('.phase5_pending_')).toBe(false)
    expect(isSentinelName('SKILL.md')).toBe(false)
  })
})
