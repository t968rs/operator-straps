import { describe, expect, test } from 'claude-code/testing'

import type { AgentRec } from '../../types'
import { MODEL_FAMILIES, parseReturnBlock } from './contract'
import {
  blockCounts, buildUsageRow, capValue, logFields, NO_COUNTS, preferCounts, unclaimedDispatch,
  USAGE_MODEL_FAMILIES, validateUsageRow, type FixerCounts, type UsageInput,
} from './usageRow'

const agent = (over: Partial<AgentRec> = {}): AgentRec => ({
  id: 'runtime', role: 'reviewer', model: 'claude-opus-5-5', effort: null, tokens: 1000, toolUses: 7,
  durationMs: 2500, isMeasured: true, signal: 'DONE', counts: null, loggedAt: null,
  subagentType: 'harness:pr-reviewer', usageLoggedAt: null, launchModel: null, ...over,
})
const input = (over: Partial<UsageInput> = {}): UsageInput => ({
  runId: 'pr35_20261020T210000Z', skill: 'pr-review', pr: 35, agent: agent(), ending: 'ok', isMeasured: true,
  loggedAt: Date.UTC(2026, 9, 20, 21, 0, 0), counts: NO_COUNTS, ...over,
})
const COUNTS: FixerCounts = { issues_assigned: 2, issues_fixed: 1, issues_bubbled: 1, files_touched: 3 }
const COUNT_KEYS = ['issues_assigned', 'issues_fixed', 'issues_bubbled', 'files_touched']

describe('buildUsageRow', () => {
  test('a measured reviewer row', async () => {
    const row = buildUsageRow(input())
    expect(row).toEqual({
      logged_at: '2026-10-20T21:00:00.000Z', run_id: 'pr35_20261020T210000Z', pr: 35, skill: 'pr-review',
      role: 'reviewer', agent_id: 'runtime', subagent_type: 'harness:pr-reviewer', model: 'claude-opus-5-5',
      model_family: 'opus', effort: 'default', tokens: 1000, tool_uses: 7, duration_s: 2.5, signal: 'DONE',
      notes: 'agent-watcher auto row; reviewer DONE',
    })
    expect(validateUsageRow(row)).toEqual([])
  })

  test('fixer and closer rows carry the counts; other roles never do', async () => {
    const fixer = buildUsageRow(input({ agent: agent({ role: 'fixer', id: 'w1_fix_1' }), counts: COUNTS }))
    expect(fixer).toMatchObject(COUNTS)
    expect(validateUsageRow(fixer)).toEqual([])
    const closer = buildUsageRow(input({ agent: agent({ role: 'closer', id: 'closer' }), counts: NO_COUNTS }))
    expect(closer).toMatchObject(NO_COUNTS)
    expect(validateUsageRow(closer)).toEqual([])
    const reviewer = buildUsageRow(input({ counts: COUNTS })) as Record<string, unknown>
    expect(COUNT_KEYS.filter(k => k in reviewer)).toEqual([])
  })

  test('unmeasured and errored notes', async () => {
    expect(buildUsageRow(input({ isMeasured: false })).notes).toBe(
      'agent-watcher auto row; reviewer DONE; usage not measured',
    )
    const errored = buildUsageRow(input({ agent: agent({ role: 'fixer', signal: 'NO_BLOCK' }), ending: 'errored', isMeasured: false }))
    expect(errored.signal).toBe('ERROR')
    expect(errored.notes).toBe('agent-watcher auto row; fixer ERROR; usage not measured; agent errored')
  })

  test('no family token logs unknown with the full id', async () => {
    const fable = buildUsageRow(input({ agent: agent({ model: 'claude-fable-5-1' }) }))
    expect([fable.model, fable.model_family]).toEqual(['claude-fable-5-1', 'unknown'])
    expect(validateUsageRow(fable)).toEqual([])
    const none = buildUsageRow(input({ agent: agent({ model: null }) }))
    expect([none.model, none.model_family]).toEqual([null, 'unknown'])
  })

  test('null signal logs NO_BLOCK', async () => {
    expect(buildUsageRow(input({ agent: agent({ signal: null }) })).signal).toBe('NO_BLOCK')
  })

  test('a SIGNAL holding a path logs UNRECOGNIZED, and notes stay free of it; a long one is capped', async () => {
    for (const raw of ['wrote E:/x/report.md', 'saved C:\\w\\out.txt', 'a/b']) {
      const row = buildUsageRow(input({ skill: 'standalone', agent: agent({ role: 'other', signal: raw }) }))
      expect([row.signal, row.notes]).toEqual(['UNRECOGNIZED', 'agent-watcher auto row; other UNRECOGNIZED'])
      expect(validateUsageRow(row)).toEqual([])
    }
    const long = buildUsageRow(input({ agent: agent({ signal: 'S'.repeat(250) }) }))
    expect(long.signal).toBe(`${'S'.repeat(197)}...`)
    expect(validateUsageRow(long)).toEqual([])
  })

  test('a standalone agent row validates and carries no counts', async () => {
    const row = buildUsageRow(input({
      runId: 'standalone_20261020T210000Z_1', skill: 'standalone', pr: null, counts: COUNTS,
      agent: agent({ id: 'messenger', role: 'other', signal: null, subagentType: 'harness:messenger' }),
    })) as Record<string, unknown>
    expect(row).toMatchObject({ skill: 'standalone', role: 'other', pr: null, signal: 'NO_BLOCK' })
    expect(COUNT_KEYS.filter(k => k in row)).toEqual([])
    expect(validateUsageRow(row)).toEqual([])
  })

  test('an other row with a count field is rejected', async () => {
    const row = buildUsageRow(input({ skill: 'standalone', agent: agent({ role: 'other' }) }))
    expect(validateUsageRow({ ...row, issues_fixed: 1 })).toEqual(['issues_fixed: only on fixer and closer rows'])
  })
})

describe('validateUsageRow', () => {
  test('names each break', async () => {
    const ok = buildUsageRow(input()) as Record<string, unknown>
    const problems = (over: Record<string, unknown>): string => validateUsageRow({ ...ok, ...over }).join('; ')
    expect(problems({ cell: 'x' })).toContain('cell')
    expect(problems({ tokens: -1 })).toContain('tokens')
    expect(problems({ role: 'Roaster' })).toContain('role')
    expect(problems({ skill: 'Strap Skills' })).toContain('skill')
    expect(problems({ role: 'runner', skill: 'strap-skills' })).toBe('')
    expect(problems({ logged_at: 'x' })).toContain('logged_at')
    expect(problems({ issues_fixed: 0 })).toContain('issues_fixed')
    expect(problems({ pr: 0 })).toContain('pr')
    expect(problems({ model_family: 'fable' })).toContain('model_family')
    const fixer = buildUsageRow(input({ agent: agent({ role: 'fixer' }), counts: COUNTS })) as Record<string, unknown>
    const { files_touched: _, ...missing } = fixer
    expect(validateUsageRow(missing)).toContain('files_touched: missing')
    expect(validateUsageRow({ ...fixer, issues_fixed: -1 }).join('; ')).toContain('issues_fixed')
  })

  test('USAGE_MODEL_FAMILIES is MODEL_FAMILIES plus unknown', async () => {
    expect([...USAGE_MODEL_FAMILIES]).toEqual([...MODEL_FAMILIES, 'unknown'])
  })

  test('fields: uppercase keys, string values, at most 200 characters, no path separator', async () => {
    const ok = buildUsageRow(input()) as Record<string, unknown>
    const problems = (fields: unknown): string => validateUsageRow({ ...ok, fields }).join('; ')
    expect(problems({ RUN: 'R-3', TARGET: 'retry-policy' })).toBe('')
    expect(problems({ CONTEXT: 'x'.repeat(200) })).toBe('')
    expect(problems({ CONTEXT: 'x'.repeat(201) })).toContain('fields.CONTEXT')
    expect(problems({ run: 'R-3' })).toContain('fields.run')
    expect(problems({ RUN: 3 })).toContain('fields.RUN')
    expect(problems({ TREE: 'a/b' })).toContain('path separator')
    expect(problems({ TREE: 'C:\\w' })).toContain('path separator')
    expect(problems(['x'])).toContain('fields: not an object')
  })

  test('run_id, agent_id, signal and notes never hold a path separator; signal is at most 200', async () => {
    const ok = buildUsageRow(input()) as Record<string, unknown>
    const problems = (over: Record<string, unknown>): string => validateUsageRow({ ...ok, ...over }).join('; ')
    expect(problems({ run_id: 'a/b' })).toContain('run_id: holds a path separator')
    expect(problems({ agent_id: 'docs\\x' })).toContain('agent_id: holds a path separator')
    expect(problems({ signal: 'wrote E:/x' })).toContain('signal: holds a path separator')
    expect(problems({ notes: 'x C:\\w' })).toContain('notes: holds a path separator')
    expect(problems({ signal: 'S'.repeat(201) })).toContain('signal: over 200 characters')
  })
})

describe('row fields (Decision D8)', () => {
  test('a value holding a path separator is dropped with its key; others are capped at 200', async () => {
    const long = 'y'.repeat(250)
    const fields = logFields({ TREE: '/w/tree', INIT: 'C:\\w\\init.sh', FILES: 'a.py, b/c.py', RUN: 'R-1', CONTEXT: long })
    expect(fields).toEqual({ RUN: 'R-1', CONTEXT: `${'y'.repeat(197)}...` })
    expect(capValue('z'.repeat(200))).toBe('z'.repeat(200))
    expect(logFields({ TREE: './x' })).toBeUndefined()
    expect(logFields({})).toBeUndefined()
  })

  test('buildUsageRow logs fields only when some survive', async () => {
    const row = buildUsageRow(input({ fields: { TARGET: 'retry-policy', SPEC: 'docs/s.json' } }))
    expect(row.fields).toEqual({ TARGET: 'retry-policy' })
    expect(validateUsageRow(row)).toEqual([])
    expect('fields' in buildUsageRow(input({ fields: { SPEC: 'docs/s.json' } }))).toBe(false)
    expect('fields' in buildUsageRow(input())).toBe(false)
  })
})

describe('unclaimedDispatch (Decision D11)', () => {
  const ID = 'standalone_20261104T060000Z_1'

  test('no header: standalone, other, the generated id, the type name, null pr, no fields', async () => {
    expect(unclaimedDispatch('Explore', {}, ID)).toEqual({
      runId: ID, skill: 'standalone', agentId: 'Explore', role: 'other', pr: null, runtimeDir: null, phase: 'done',
    })
    expect(unclaimedDispatch(undefined, {}, ID).agentId).toBe('general-purpose')
  })

  test('accepted values fill the row; unconsumed keys become fields', async () => {
    const h = {
      SKILL: 'harness:strap-skills', RUN_ID: 'R-7', AGENT_ID: 'runner_1', AGENT_ROLE: 'runner', PR: '208',
      TARGET: 'retry-policy',
    }
    expect(unclaimedDispatch('harness:strap-scenario-runner', h, ID)).toEqual({
      runId: ID, skill: 'strap-skills', agentId: 'runner_1', role: 'runner', pr: 208, runtimeDir: null,
      phase: 'done', logRunId: 'R-7', fields: { TARGET: 'retry-policy' },
    })
  })

  test('a value that fails its rule falls back and stays in fields, unless it holds a path', async () => {
    const d = unclaimedDispatch('x:agent', {
      SKILL: 'Strap Skills', AGENT_ROLE: 'closer', RUN_ID: 'a/b', AGENT_ID: 'docs\\x', PR: 'local-x',
    }, ID)
    expect(d).toMatchObject({ skill: 'standalone', role: 'other', agentId: 'agent', pr: null, runId: ID })
    expect('logRunId' in d).toBe(false)
    expect(d.fields).toEqual({ SKILL: 'Strap Skills', AGENT_ROLE: 'closer', PR: 'local-x' })
    expect(unclaimedDispatch('x', { AGENT_ROLE: 'fixer', PR: '0' }, ID)).toMatchObject({
      role: 'other', pr: null, fields: { AGENT_ROLE: 'fixer', PR: '0' },
    })
  })

  test('a PR too large for an exact JSON number falls back to null and stays in fields', async () => {
    const big = '9'.repeat(400)
    const d = unclaimedDispatch('x', { PR: big }, ID)
    expect(d.pr).toBeNull()
    expect(d.fields).toEqual({ PR: `${'9'.repeat(197)}...` })
    expect(unclaimedDispatch('x', { PR: '9007199254740993' }, ID).pr).toBeNull()
    expect(unclaimedDispatch('x', { PR: '9007199254740991' }, ID).pr).toBe(9007199254740991)
  })
})

describe('fixer counts', () => {
  test('blockCounts', async () => {
    expect(blockCounts(undefined)).toEqual(NO_COUNTS)
    const block = parseReturnBlock('---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: C1,I3\nBUBBLED: M2\nEDITED: 4\n---')
    expect(blockCounts(block)).toEqual({ issues_assigned: null, issues_fixed: 2, issues_bubbled: 1, files_touched: 4 })
    expect(blockCounts(parseReturnBlock('---\nSIGNAL: FAIL\n---'))).toEqual(NO_COUNTS)
  })

  test('preferCounts fills nulls from the fallback, field by field', async () => {
    const primary: FixerCounts = { issues_assigned: 3, issues_fixed: null, issues_bubbled: 0, files_touched: null }
    const fallback: FixerCounts = { issues_assigned: 9, issues_fixed: 1, issues_bubbled: 9, files_touched: null }
    expect(preferCounts(primary, fallback)).toEqual(
      { issues_assigned: 3, issues_fixed: 1, issues_bubbled: 0, files_touched: null },
    )
  })
})
