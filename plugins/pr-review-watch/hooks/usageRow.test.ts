import { describe, expect, test } from 'claude-code/testing'

import type { AgentRec } from '../types'
import { MODEL_FAMILIES, parseReturnBlock } from './contract'
import {
  blockCounts, buildUsageRow, NO_COUNTS, preferCounts, reportCounts, USAGE_MODEL_FAMILIES, validateUsageRow,
  type FixerCounts, type UsageInput,
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
      notes: 'pr-review-watch auto row; reviewer DONE',
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
      'pr-review-watch auto row; reviewer DONE; usage not measured',
    )
    const errored = buildUsageRow(input({ agent: agent({ role: 'fixer', signal: 'NO_BLOCK' }), ending: 'errored', isMeasured: false }))
    expect(errored.signal).toBe('ERROR')
    expect(errored.notes).toBe('pr-review-watch auto row; fixer ERROR; usage not measured; agent errored')
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
})

describe('validateUsageRow', () => {
  test('names each break', async () => {
    const ok = buildUsageRow(input()) as Record<string, unknown>
    const problems = (over: Record<string, unknown>): string => validateUsageRow({ ...ok, ...over }).join('; ')
    expect(problems({ cell: 'x' })).toContain('cell')
    expect(problems({ tokens: -1 })).toContain('tokens')
    expect(problems({ role: 'roaster' })).toContain('role')
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
})

describe('fixer counts', () => {
  test('blockCounts', async () => {
    expect(blockCounts(undefined)).toEqual(NO_COUNTS)
    const block = parseReturnBlock('---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: C1,I3\nBUBBLED: M2\nEDITED: 4\n---')
    expect(blockCounts(block)).toEqual({ issues_assigned: null, issues_fixed: 2, issues_bubbled: 1, files_touched: 4 })
    expect(blockCounts(parseReturnBlock('---\nSIGNAL: FAIL\n---'))).toEqual(NO_COUNTS)
  })

  test('reportCounts reads waves.json and fixes/<id>.json', async () => {
    const waves = JSON.stringify({
      waves: [[{ id: 'w1_fix_1', issue_ids: ['M1', 'I2'] }], [{ id: 'w2_fix_1', issue_ids: ['C1'] }]],
    })
    const report = JSON.stringify({
      fixer: 'w1_fix_1',
      fixed: [{ id: 'M1', what: 'w', files: ['a.py', 'b.py'] }, { id: 'I2', what: 'w', files: ['b.py'], no_change: ['c.py'] }],
      bubbled: [],
    })
    expect(reportCounts(waves, report, 'w1_fix_1')).toEqual(
      { issues_assigned: 2, issues_fixed: 2, issues_bubbled: 0, files_touched: 2 },
    )
    expect(reportCounts(waves, undefined, 'w2_fix_1')).toEqual(
      { issues_assigned: 1, issues_fixed: null, issues_bubbled: null, files_touched: null },
    )
    expect(reportCounts('not json', 'not json', 'w1_fix_1')).toEqual(NO_COUNTS)
    expect(reportCounts(waves, report, 'w9_fix_9').issues_assigned).toBeNull()
  })

  test('preferCounts fills nulls from the fallback, field by field', async () => {
    const primary: FixerCounts = { issues_assigned: 3, issues_fixed: null, issues_bubbled: 0, files_touched: null }
    const fallback: FixerCounts = { issues_assigned: 9, issues_fixed: 1, issues_bubbled: 9, files_touched: null }
    expect(preferCounts(primary, fallback)).toEqual(
      { issues_assigned: 3, issues_fixed: 1, issues_bubbled: 0, files_touched: null },
    )
  })
})
