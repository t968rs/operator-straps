import { describe, expect, test } from 'claude-code/testing'

import {
  DEFINED_AGENTS, identify, identifyStandalone, idList, isDefinedAgent, modelFamily, parseCounts, parseHeader,
  keyOfRunId, parseReturnBlock, standaloneRunId, startedAtOfRunId,
} from './contract'

const RUN = 'pr1526_20261009T120000Z'
const LOCAL_RUN = 'local-fix-band_20261102T080910Z'
const BASE = 'state/pr-team/_runtime'

const reviewerPrompt = [
  'You are a pr-team reviewer.',
  'AGENT_ID: r1_config',
  'AGENT_ROLE: reviewer',
  'PROMPT_FILE: .claude/state/harness/pr-team/_runtime/pr1526_20261009T120000Z/prompts/r1_config.md',
  'OUTPUT_FILE: .claude/state/harness/pr-team/_runtime/pr1526_20261009T120000Z/outputs/r1_config.json',
  `RUN_ID: ${RUN}`,
].join('\n')

describe('parseHeader', () => {
  test('reads KEY=value and KEY: value lines; first occurrence wins', async () => {
    const h = parseHeader('MODE=PLAN\nPR_NUMBER=12\nAGENT_ID: a\nAGENT_ID: b\n  INDENTED: x\nprose: y')
    expect(h).toEqual({ MODE: 'PLAN', PR_NUMBER: '12', AGENT_ID: 'a' })
  })
})

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

describe('identify', () => {
  test('pr-team reviewer slot dispatch', async () => {
    expect(identify('superpowers:code-reviewer', reviewerPrompt, BASE)).toEqual({
      runId: RUN, skill: 'pr-team', agentId: 'r1_config', role: 'reviewer', pr: 1526,
      runtimeDir: '.claude/state/harness/pr-team/_runtime/pr1526_20261009T120000Z', phase: 'review',
    })
  })

  test('pr-team slot without OUTPUT_FILE: the runtime dir sits under the given base', async () => {
    const d = identify('x', `AGENT_ID: r2\nAGENT_ROLE: fixer\nRUN_ID: ${RUN}`, BASE)
    expect(d?.runtimeDir).toBe(`${BASE}/${RUN}`)
  })

  test('pr-review reviewer: PR line, no runtime dir', async () => {
    const d = identify('superpowers:code-reviewer', `AGENT_ID: runtime\nAGENT_ROLE: reviewer\nRUN_ID: ${RUN}\nPR: 1526`, BASE)
    expect(d?.skill).toBe('pr-review')
    expect(d?.runtimeDir).toBeNull()
    expect(d?.pr).toBe(1526)
  })

  test('pr-review slot with a local key on its PR line: the key is the run key', async () => {
    const prompt = `AGENT_ID: overall\nAGENT_ROLE: reviewer\nRUN_ID: ${LOCAL_RUN}\nPR: local-fix-band`
    expect(identify('harness:pr-reviewer', prompt, BASE)).toEqual({
      runId: LOCAL_RUN, skill: 'pr-review', agentId: 'overall', role: 'reviewer', pr: 'local-fix-band',
      runtimeDir: null, phase: 'review',
    })
    const fixer = identify('harness:pr-fixer', `AGENT_ID: f1\nAGENT_ROLE: fixer\nRUN_ID: ${LOCAL_RUN}\nPR: junk`, BASE)
    expect(fixer?.pr).toBe('local-fix-band')
    const bad = identify('harness:pr-fixer', 'AGENT_ID: f1\nAGENT_ROLE: fixer\nRUN_ID: r\nPR: local-Bad', BASE)
    expect(bad?.pr).toBeNull()
  })

  test('orchestrator and fixer mode dispatches', async () => {
    const dir = `.claude/state/harness/pr-team/_runtime/${RUN}`
    const plan = identify('pr-team-orchestrator', `MODE=PLAN\nPR_NUMBER=1526\nRUN_ID=${RUN}\nRUNTIME_DIR=${dir}`, BASE)
    expect(plan).toEqual({
      runId: RUN, skill: 'pr-team', agentId: 'orchestrator_plan', role: 'orchestrator', pr: 1526, runtimeDir: dir,
      phase: 'plan',
    })
    expect(identify('pr-team-orchestrator', `MODE=CONSOLIDATE\nRUN_ID=${RUN}`, BASE)?.phase).toBe('consolidate')
    expect(identify('pr-team-fixer', `MODE=PLAN\nRUN_ID=${RUN}`, BASE)?.agentId).toBe('fixer_plan')
    const closer = identify('pr-team-fixer', `MODE=CLOSEOUT\nRUN_ID=${RUN}`, BASE)
    expect([closer?.agentId, closer?.role, closer?.phase]).toEqual(['closer', 'closer', 'closeout'])
  })

  test('untracked dispatches: no RUN_ID, unknown role, unknown mode, unknown agent', async () => {
    expect(identify('Explore', 'find the files', BASE)).toBeUndefined()
    expect(identify('x', `AGENT_ID: a\nAGENT_ROLE: poet\nRUN_ID: ${RUN}`, BASE)).toBeUndefined()
    expect(identify('pr-team-orchestrator', `MODE=DANCE\nRUN_ID=${RUN}`, BASE)).toBeUndefined()
    expect(identify('general-purpose', `MODE=PLAN\nRUN_ID=${RUN}`, BASE)).toBeUndefined()
  })
})

describe('standalone dispatches', () => {
  test('a defined agent is identified without any prompt header', async () => {
    expect(identifyStandalone('harness:messenger', 'standalone_20261022T155329Z_1')).toEqual({
      runId: 'standalone_20261022T155329Z_1', skill: 'standalone', agentId: 'messenger', role: 'other', pr: null,
      runtimeDir: null, phase: 'done',
    })
  })

  test('every defined agent is recognized; built-in and foreign types are not', async () => {
    expect(DEFINED_AGENTS.every(t => isDefinedAgent(t))).toBe(true)
    for (const type of ['Explore', 'general-purpose', 'superpowers:code-reviewer', 'messenger', 'harness:', undefined]) {
      expect(isDefinedAgent(type)).toBe(false)
      expect(identifyStandalone(type, 'standalone_x')).toBeUndefined()
    }
  })

  test('the run id carries the UTC second and a sequence number', async () => {
    expect(standaloneRunId(Date.UTC(2026, 9, 22, 15, 53, 29, 350), 3)).toBe('standalone_20261022T155329Z_3')
  })

  test('identify itself still ignores a header-less defined agent', async () => {
    expect(identify('harness:messenger', 'write a commit message', BASE)).toBeUndefined()
  })
})

describe('parseReturnBlock', () => {
  test('reviewer DONE after prose and a markdown rule, harness trailer ignored', async () => {
    const text = [
      'Review prose.', '---', 'more prose', '---',
      'SIGNAL: DONE', 'AGENT_ROLE: reviewer', 'COUNTS: findings=7 critical=0 important=4 minor=3',
      'OUTPUT: .claude/state/harness/pr-team/_runtime/x/outputs/r1.json', '---',
      'agentId: abc (harness trailer)',
    ].join('\n')
    expect(parseReturnBlock(text)).toEqual({
      signal: 'DONE', role: 'reviewer', counts: { findings: 7, critical: 0, important: 4, minor: 3 },
      fixed: null, bubbled: null, edited: null, output: '.claude/state/harness/pr-team/_runtime/x/outputs/r1.json',
      notes: null,
    })
  })

  test('EDITED is read as a count; a missing FIXED line is null, an empty one is []', async () => {
    const fixer = parseReturnBlock('---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: C1,I3\nBUBBLED:\nEDITED: 4\n---')
    expect([fixer?.fixed, fixer?.bubbled, fixer?.edited]).toEqual([['C1', 'I3'], [], 4])
    const odd = parseReturnBlock('---\nSIGNAL: DONE\nFIXED:\nEDITED: x\n---')
    expect([odd?.fixed, odd?.edited]).toEqual([[], null])
    expect(parseReturnBlock('---\nSIGNAL: FAIL\n---')?.fixed).toBeNull()
  })

  test('closer DONE: FIXED, BUBBLED, indented EVIDENCE skipped, CRLF', async () => {
    const text =
      '---\r\nSIGNAL: DONE\r\nAGENT_ROLE: fixer\r\nFIXED: C1,I3\r\nBUBBLED: I4,M2,bogus\r\nEDITED: 1\r\nOUTPUT: o\r\n' +
      'EVIDENCE:\r\n  C1: done\r\nNOTES: TERMINAL: x\r\n---\r\n'
    const b = parseReturnBlock(text)
    expect(b?.fixed).toEqual(['C1', 'I3'])
    expect(b?.bubbled).toEqual(['I4', 'M2'])
    expect(b?.notes).toBe('TERMINAL: x')
  })

  test('empty BUBBLED is an empty list; no block is undefined', async () => {
    expect(parseReturnBlock('---\nSIGNAL: DONE\nBUBBLED:\n---')?.bubbled).toEqual([])
    expect(parseReturnBlock('no block here')).toBeUndefined()
    expect(parseReturnBlock('---\nNOTES: x\n---')).toBeUndefined()
  })
})

describe('small parsers', () => {
  test('parseCounts, idList, modelFamily', async () => {
    expect(parseCounts('findings=1 critical=1 important=0 minor=0')).toEqual({
      findings: 1, critical: 1, important: 0, minor: 0,
    })
    expect(parseCounts('findings=1')).toBeNull()
    expect(idList(' C1 , x, M10')).toEqual(['C1', 'M10'])
    expect(modelFamily('claude-opus-5-5')).toBe('opus')
    expect(modelFamily('Claude-Sonnet-5-5[1m]')).toBe('sonnet')
    expect(modelFamily('claude-fable-5-1')).toBeUndefined()
    expect(modelFamily(null)).toBeUndefined()
  })
})
