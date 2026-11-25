import { describe, expect, test } from 'claude-code/testing'

import { TODO_PALETTE } from './line'
import type { PlanItem } from './plans'
import {
  outcomeKindOf, PLAN_RAMP, planColor, planStep, progressOf, receiptsDirOf, receiptsSignatureOf,
} from './progress'
import type { Listed } from './watch'

const receiptJson = (kind: unknown): string => JSON.stringify({
  plan_id: '2028', item: 'TASK-1', outcome: { kind, provenance: 'x' }, evidence: 'e', date: '2026-11-24',
})

const items = (...statuses: (string | null)[]): PlanItem[] =>
  statuses.map((status, i) => ({ id: `TASK-${i + 1}`, status }))

const NO_RECEIPTS: ReadonlyMap<string, string | null> = new Map()

const file = (name: string, mtimeMs = 1, size = 10): Listed => ({ name, kind: 'file', size, mtimeMs })

describe('outcomeKindOf', () => {
  test('the outcome kind of a receipt', async () => {
    expect(outcomeKindOf(receiptJson('complete'))).toBe('complete')
    expect(outcomeKindOf(receiptJson('started'))).toBe('started')
  })

  test('absent or malformed text, or no string kind, is no kind', async () => {
    expect(outcomeKindOf(undefined)).toBeNull()
    expect(outcomeKindOf('{not json')).toBeNull()
    expect(outcomeKindOf('[]')).toBeNull()
    expect(outcomeKindOf(JSON.stringify({ outcome: 'complete' }))).toBeNull()
    expect(outcomeKindOf(receiptJson(3))).toBeNull()
  })

  test('given an item id, only a receipt naming that item counts', async () => {
    expect(outcomeKindOf(receiptJson('complete'), 'TASK-2')).toBeNull()
    expect(outcomeKindOf(receiptJson('complete'), 'TASK-1')).toBe('complete')
    expect(outcomeKindOf(receiptJson('complete'))).toBe('complete')
  })
})

describe('progressOf', () => {
  test('complete and closed receipts count as done; started and blocked do not', async () => {
    const kinds = new Map([['TASK-1', 'complete'], ['TASK-2', 'closed'], ['TASK-3', 'started'], ['TASK-4', 'blocked']])
    expect(progressOf(items('PENDING', 'PENDING', 'PENDING', 'PENDING'), kinds)).toEqual({ done: 2, total: 4 })
  })

  test('a receipt outranks the item status', async () => {
    const kinds = new Map([['TASK-1', 'started']])
    expect(progressOf(items('COMPLETE'), kinds)).toEqual({ done: 0, total: 1 })
  })

  test('no receipt falls back to the status: COMPLETE and CLOSED_NO_ACTION count', async () => {
    const plan = items('COMPLETE', 'CLOSED_NO_ACTION', 'IN_PROGRESS', 'BLOCKED', 'PENDING', null)
    expect(progressOf(plan, NO_RECEIPTS)).toEqual({ done: 2, total: 6 })
  })

  test('a malformed receipt counts as none, so the status decides', async () => {
    const kinds = new Map([['TASK-1', outcomeKindOf('{not json')], ['TASK-2', outcomeKindOf('{not json')]])
    expect(progressOf(items('COMPLETE', 'PENDING'), kinds)).toEqual({ done: 1, total: 2 })
  })

  test('a plan with no items has none done of none', async () => {
    expect(progressOf([], NO_RECEIPTS)).toEqual({ done: 0, total: 0 })
  })
})

describe('planStep and planColor', () => {
  test('every step boundary of four items', async () => {
    expect([0, 1, 2, 3, 4].map(done => planStep({ done, total: 4 }))).toEqual([0, 1, 2, 3, 4])
  })

  test('exact thirds step up', async () => {
    expect(planStep({ done: 1, total: 3 })).toBe(2)
    expect(planStep({ done: 2, total: 3 })).toBe(3)
  })

  test('the ramp is the five V1 colors', async () => {
    expect(PLAN_RAMP).toEqual([51, 45, 74, 67, 243])
  })

  test('a plan with no items takes step 0', async () => {
    expect(planStep({ done: 0, total: 0 })).toBe(0)
  })

  test('steps 0 and 4 are only exactly none and exactly all', async () => {
    expect(planStep({ done: 1, total: 100 })).toBe(1)
    expect(planStep({ done: 99, total: 100 })).toBe(3)
  })

  test('the color is the ramp entry of the step', async () => {
    expect(planColor({ done: 0, total: 4 })).toBe(51)
    expect(planColor({ done: 2, total: 4 })).toBe(74)
    expect(planColor({ done: 4, total: 4 })).toBe(243)
  })

  test('no ramp color is a TODO label color or the punctuation 240', async () => {
    for (const c of PLAN_RAMP) {
      expect(TODO_PALETTE.includes(c)).toBe(false)
      expect(c).not.toBe(240)
    }
  })
})

describe('receiptsDirOf', () => {
  test('the receipts folder under the plan id, forward slashes', async () => {
    expect(receiptsDirOf('E:/repo/docs/plans', '2030')).toBe('E:/repo/docs/plans/2030/receipts')
    expect(receiptsDirOf('E:\\repo\\docs\\plans\\', '2030')).toBe('E:/repo/docs/plans/2030/receipts')
  })
})

describe('receiptsSignatureOf', () => {
  test('moves with a receipt mtime', async () => {
    const before = receiptsSignatureOf(new Map([['2030', [file('TASK-1.json', 1)]]]))
    const after = receiptsSignatureOf(new Map([['2030', [file('TASK-1.json', 2)]]]))
    expect(after).not.toBe(before)
  })

  test('moves with a new receipt and with another plan on the line', async () => {
    const one = receiptsSignatureOf(new Map([['2030', [file('TASK-1.json')]]]))
    expect(receiptsSignatureOf(new Map([['2030', [file('TASK-1.json'), file('TASK-2.json')]]]))).not.toBe(one)
    expect(receiptsSignatureOf(new Map([['2030', [file('TASK-1.json')]], ['2031', []]]))).not.toBe(one)
  })

  test('ignores other files and folders, and the listing order', async () => {
    const plain = receiptsSignatureOf(new Map([['2030', [file('TASK-1.json'), file('TASK-2.json')]]]))
    const noisy = receiptsSignatureOf(new Map([['2030', [
      file('TASK-2.json'), file('notes.txt'), { name: 'old.json', kind: 'dir', size: 0, mtimeMs: 5 }, file('TASK-1.json'),
    ]]]))
    expect(noisy).toBe(plain)
  })
})
