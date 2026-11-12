import { describe, expect, test } from 'claude-code/testing'

import type { AgentRec } from '../../../types'
import { appendRows } from '../../core/jsonl'
import { buildRow, buildWorkflowRow, DISPATCH_SHAPES, MATRIX_REQUIRED, validateRow, workflowPlan } from './matrixRow'

const SHA = '0123456789abcdef0123456789abcdef01234567'
const agent = (over: Partial<AgentRec> = {}): AgentRec => ({
  id: 'r1_config', role: 'reviewer', model: 'claude-opus-5-5', effort: null, tokens: 144385, toolUses: 33,
  durationMs: 321294.4, isMeasured: true, signal: 'DONE',
  counts: { findings: 3, critical: 0, important: 1, minor: 2 }, loggedAt: null, subagentType: null,
  usageLoggedAt: null, launchModel: null, ...over,
})
const row = (over: Partial<AgentRec> = {}) =>
  buildRow({
    pr: 1526, agent: agent(over), verdictPrefix: 'NOT READY TO MERGE',
    devCommit: `${SHA} -- dev (agent-watcher auto)`,
  })

describe('buildRow', () => {
  test('a measured reviewer becomes a valid row', async () => {
    const r = row()
    expect(r).toMatchObject({
      cell: 'pr1526_r1_config', pr: 1526, model_family: 'opus', effort: 'default', dispatch_shape: 'parallel',
      tokens: 144385, tool_uses: 33, duration_s: 321.294, phase4_script: null,
      findings_count: 3, C_count: 0, I_count: 1, M_count: 2, other_count: 0, verdict_prefix: 'NOT READY TO MERGE',
    })
    expect(r.notes).toContain('agent-watcher')
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

describe('Workflow rows', () => {
  const RUN_ID = 'pr1526_20261009T120000Z'
  const entry = (id: string, model = 'opus') => ({ id, agentType: 'x', model, prompt: `AGENT_ID: ${id}` })
  const ARGS = {
    run_key: '1526', run_id: RUN_ID, guidance: null,
    reviewers: [entry('runtime'), entry('docs', 'sonnet')],
    code: [entry('adv_code')],
    refute: [{ ...entry('adv_refute_runtime'), target: 'runtime' }, { ...entry('adv_refute_adv_code'), target: 'adv_code' }],
  }

  test('workflowPlan lists reviewers, code refuters and findings refuters, from an object or JSON text', async () => {
    const plan = workflowPlan(ARGS)
    expect(plan).toEqual({
      runKey: 1526, runId: RUN_ID,
      slots: [
        { id: 'runtime', role: 'reviewer', model: 'opus' }, { id: 'docs', role: 'reviewer', model: 'sonnet' },
        { id: 'adv_code', role: 'code_refuter', model: 'opus' },
        { id: 'adv_refute_runtime', role: 'refuter', model: 'opus' },
        { id: 'adv_refute_adv_code', role: 'refuter', model: 'opus' },
      ],
    })
    expect(workflowPlan(JSON.stringify(ARGS))).toEqual(plan)
    const local = { ...ARGS, run_key: 'local-fix-band', run_id: 'local-fix-band_20261009T120000Z', code: undefined }
    expect(workflowPlan(local)?.slots.map(s => s.id)).toEqual([
      'runtime', 'docs', 'adv_refute_runtime', 'adv_refute_adv_code',
    ])
  })

  test('a numeric run_key reads as the PR number', async () => {
    expect(workflowPlan({ ...ARGS, run_key: 1526 })).toMatchObject({ runKey: 1526, runId: RUN_ID })
  })

  test('args that are not pr-review adversarial args give no plan', async () => {
    expect(workflowPlan(undefined)).toBeUndefined()
    expect(workflowPlan('not json')).toBeUndefined()
    expect(workflowPlan({ draftDir: 'x' })).toBeUndefined()
    expect(workflowPlan({ ...ARGS, run_key: 'feature-x' })).toBeUndefined()
    expect(workflowPlan({ ...ARGS, reviewers: 'runtime' })).toBeUndefined()
  })

  test('a run_id missing, malformed or naming another key gives no plan', async () => {
    const { run_id: _dropped, ...noRunId } = ARGS
    expect(workflowPlan(noRunId)).toBeUndefined()
    expect(workflowPlan({ ...ARGS, run_id: 'pr1526' })).toBeUndefined()
    expect(workflowPlan({ ...ARGS, run_id: 'pr1527_20261009T120000Z' })).toBeUndefined()
    expect(workflowPlan({ ...ARGS, run_key: 'local-fix-band' })).toBeUndefined()
  })

  test('a slot row carries dispatch shape workflow, zero counts and the unobserved note', async () => {
    const r = buildWorkflowRow({
      pr: 1526, slot: { id: 'adv_code', role: 'code_refuter', model: 'opus' },
      devCommit: `${SHA} -- dev (agent-watcher auto)`,
    })
    expect(r).toEqual({
      cell: 'pr1526_adv_code', pr: 1526, model_family: 'opus', effort: 'default',
      dev_commit: `${SHA} -- dev (agent-watcher auto)`, dispatch_shape: 'workflow', tokens: 0, tool_uses: 0,
      duration_s: 0, phase4_script: null, findings_count: 0, C_count: 0, I_count: 0, M_count: 0, other_count: 0,
      verdict_prefix: 'N/A (unobserved)', notes: 'agent-watcher auto row; code_refuter; unobserved: workflow agent',
    })
    expect(validateRow(r)).toEqual([])
    expect(DISPATCH_SHAPES).toContain('workflow')
  })

  test('a slot with no model fails validation instead of guessing (R4)', async () => {
    const r = buildWorkflowRow({ pr: 1526, slot: { id: 'runtime', role: 'reviewer', model: null }, devCommit: SHA })
    expect(r.model_family).toBe('unknown')
    expect(validateRow(r)).toEqual(["model_family: 'unknown' is not one of haiku/sonnet/opus"])
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
