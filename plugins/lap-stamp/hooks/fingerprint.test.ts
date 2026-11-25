import { describe, expect, test } from 'claude-code/testing'

import { fingerprintOf, fnv1a64Hex, normalizeAnswer } from './fingerprint'

describe('normalizeAnswer', () => {
  test('context spans are dropped, whole span and any attributes', async () => {
    expect(normalizeAnswer('before<context>hidden\nlines</context>after')).toBe('beforeafter')
    expect(normalizeAnswer('a <context kind="x">one</context> b <context>two</context> c')).toBe('a  b  c')
  })

  test('line endings are unified to LF and the ends trimmed', async () => {
    expect(normalizeAnswer('  one\r\ntwo\r\n\r\n')).toBe('one\ntwo')
    expect(normalizeAnswer('x\ry')).toBe('x\ny')
  })

  test('text with only a context span normalizes to empty', async () => {
    expect(normalizeAnswer('<context>only</context>\n')).toBe('')
  })
})

describe('fnv1a64Hex', () => {
  test('known FNV-1a 64 vectors', async () => {
    expect(fnv1a64Hex('')).toBe('cbf29ce484222325')
    expect(fnv1a64Hex('a')).toBe('af63dc4c8601ec8c')
    expect(fnv1a64Hex('foobar')).toBe('85944171f73967e8')
  })

  test('multi-byte text hashes its UTF-8 bytes (C3 A9 for the e-acute)', async () => {
    expect(fnv1a64Hex('é')).toBe('0ac21707b7181e01')
  })
})

describe('fingerprintOf', () => {
  test('hash and normalized length', async () => {
    expect(fingerprintOf('a')).toEqual({ hash: 'af63dc4c8601ec8c', len: 1 })
  })

  test('copies that differ only by context span and line endings share a fingerprint', async () => {
    expect(fingerprintOf('hi\r\nthere')).toEqual(fingerprintOf('<context>x</context>hi\nthere\n'))
  })

  test('empty normalized text has no fingerprint', async () => {
    expect(fingerprintOf('')).toBeNull()
    expect(fingerprintOf('  \r\n ')).toBeNull()
    expect(fingerprintOf('<context>x</context>')).toBeNull()
  })
})
