import { describe, expect, test } from 'claude-code/testing'

import {
  DEFINED_AGENTS, holdsPath, idList, isDefinedAgent, leadingHeader, modelFamily, parseCounts, parseHeader,
  parseReturnBlock, standaloneRunId, typeName,
} from './contract'

describe('parseHeader', () => {
  test('reads KEY=value and KEY: value lines; first occurrence wins', async () => {
    const h = parseHeader('MODE=PLAN\nPR_NUMBER=12\nAGENT_ID: a\nAGENT_ID: b\n  INDENTED: x\nprose: y')
    expect(h).toEqual({ MODE: 'PLAN', PR_NUMBER: '12', AGENT_ID: 'a' })
  })
})

describe('leadingHeader (Decision D3)', () => {
  test('the block ends at the first line that is not a header line', async () => {
    const prompt = 'SKILL: bubble-memo\nRUN_ID=r1\nISSUE: I2\n\nInvestigate.\nSIGNAL: DONE\nNOTES: x'
    expect(leadingHeader(prompt)).toEqual({ SKILL: 'bubble-memo', RUN_ID: 'r1', ISSUE: 'I2' })
  })

  test('leading blank lines are skipped; a prose first line means no block; CRLF; first key wins', async () => {
    expect(leadingHeader('\r\n\r\nSKILL: a\r\nSKILL: b\r\nMemo: m\r\nRUN: R-1')).toEqual({ SKILL: 'a' })
    expect(leadingHeader('Write the commit message.\nSKILL: x')).toEqual({})
    expect(leadingHeader('')).toEqual({})
  })
})

describe('unclaimed dispatch helpers', () => {
  test('every defined agent is recognized; built-in and foreign types are not', async () => {
    expect(DEFINED_AGENTS.every(t => isDefinedAgent(t))).toBe(true)
    for (const type of ['Explore', 'general-purpose', 'superpowers:code-reviewer', 'messenger', 'harness:', undefined]) {
      expect(isDefinedAgent(type)).toBe(false)
    }
  })

  test('the run id carries the UTC second and a sequence number', async () => {
    expect(standaloneRunId(Date.UTC(2026, 9, 22, 15, 53, 29, 350), 3)).toBe('standalone_20261022T155329Z_3')
  })

  test('typeName drops the plugin prefix; no type is general-purpose', async () => {
    expect(typeName('harness:messenger')).toBe('messenger')
    expect(typeName('Explore')).toBe('Explore')
    expect(typeName(undefined)).toBe('general-purpose')
    expect(typeName('harness:')).toBe('general-purpose')
  })

  test('holdsPath sees either separator', async () => {
    expect(['a/b', 'C:\\w', './x', '/abs'].every(holdsPath)).toBe(true)
    expect(holdsPath('retry-policy R-1')).toBe(false)
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
