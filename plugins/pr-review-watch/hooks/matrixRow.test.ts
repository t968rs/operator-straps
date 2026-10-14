import { describe, expect, test } from 'claude-code/testing'

import type { AgentRec } from '../types'
import { appendRows, buildRow, MATRIX_REQUIRED, validateRow } from './matrixRow'

const SHA = '0123456789abcdef0123456789abcdef01234567'
const agent = (over: Partial<AgentRec> = {}): AgentRec => ({
  id: 'r1_config', role: 'reviewer', model: 'claude-opus-5-5', effort: null, tokens: 144385, toolUses: 33,
  durationMs: 321294.4, isMeasured: true, signal: 'DONE',
  counts: { findings: 3, critical: 0, important: 1, minor: 2 }, loggedAt: null, ...over,
})
const row = (over: Partial<AgentRec> = {}) =>
  buildRow({
    pr: 1526, agent: agent(over), verdictPrefix: 'NOT READY TO MERGE',
    devCommit: `${SHA} -- dev (pr-review-watch auto)`,
  })

describe('buildRow', () => {
  test('a measured reviewer becomes a valid row', async () => {
    const r = row()
    expect(r).toMatchObject({
      cell: 'pr1526_r1_config', pr: 1526, model_family: 'opus', effort: 'default', dispatch_shape: 'parallel',
      tokens: 144385, tool_uses: 33, duration_s: 321.294, phase4_script: null,
      findings_count: 3, C_count: 0, I_count: 1, M_count: 2, other_count: 0, verdict_prefix: 'NOT READY TO MERGE',
    })
    expect(r.notes).toContain('pr-review-watch')
    expect(validateRow(r)).toEqual([])
    expect(Object.keys(r).filter(k => !k.startsWith('phase4')).sort()).toEqual([...MATRIX_REQUIRED].sort())
  })

  test('unmeasured usage is said so in notes; FAIL without counts gives zeros', async () => {
    const r = row({ isMeasured: false, tokens: 0, signal: 'FAIL', counts: null })
    expect(r.notes).toContain('not measured')
    expect(r.notes).toContain('FAIL')
    expect([r.findings_count, r.C_count]).toEqual([0, 0])
    expect(validateRow(r)).toEqual([])
  })

  test('a model with no family token fails validation instead of guessing', async () => {
    expect(validateRow(row({ model: 'claude-fable-5-1' }))).toEqual([
      "model_family: 'claude-fable-5-1' is not one of haiku/sonnet/opus",
    ])
  })
})

describe('validateRow', () => {
  test('missing, extra, wrong types, bad pattern', async () => {
    const bad: Record<string, unknown> = { ...row(), tokens: -1, pr: 0, dev_commit: 'dev', extra: 1 }
    delete bad.notes
    expect(validateRow(bad)).toEqual([
      'extra: not in the schema',
      'notes: missing',
      'tokens: not a non-negative integer',
      'pr: not a positive integer',
      'dev_commit: does not start with a 40-char merge-base SHA',
    ])
  })

  test('legacy rows may carry free-text dev_commit', async () => {
    expect(validateRow({ ...row(), legacy: true, dev_commit: 'dev (pre-#916)' })).toEqual([])
  })
})

describe('appendRows', () => {
  test('adds a newline when the file lacks one; nothing to add keeps the text', async () => {
    const r = row()
    expect(appendRows('{"a":1}', [r])).toBe(`{"a":1}\n${JSON.stringify(r)}\n`)
    expect(appendRows('', [r])).toBe(`${JSON.stringify(r)}\n`)
    expect(appendRows('x\n', [])).toBe('x\n')
  })
})
