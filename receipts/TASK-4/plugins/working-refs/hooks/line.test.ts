import { describe, expect, test } from 'claude-code/testing'

import type { Refs, WorkingLine } from '../types'
import { buildLine, fileUrl, formatRefs, osc8, plainText, statusText } from './line'
import type { Overrides } from './overrides'
import type { PlanInfo } from './plans'

const ESC = '\x1b'
const page = (id: string): string => `E:/repo/docs/PLANS/${id}_x_PIP.html`

const plan = (id: string, refs: Partial<Refs> = {}): PlanInfo => ({
  id, branch: 'topic', baseBranch: 'main', baseCommit: 'a'.repeat(40),
  refs: { todoIds: [], issues: [], ...refs }, page: page(id),
})

const NONE: Overrides = new Map()
const override = (branch: string, refs: Refs): Overrides => new Map([[branch, refs]])

describe('formatRefs', () => {
  test('ids, then issues in parentheses', async () => {
    expect(formatRefs({ todoIds: ['todo-k69m'], issues: [301] })).toBe('todo-k69m (301)')
    expect(formatRefs({ todoIds: ['todo-a', 'todo-b'], issues: [1, 2] })).toBe('todo-a, todo-b (1, 2)')
  })

  test('ids alone, issues alone, or nothing', async () => {
    expect(formatRefs({ todoIds: ['todo-k69m'], issues: [] })).toBe('todo-k69m')
    expect(formatRefs({ todoIds: [], issues: [301, 315] })).toBe('#301, #315')
    expect(formatRefs({ todoIds: [], issues: [] })).toBe('')
  })
})

describe('buildLine', () => {
  test('one plan: its link, then its refs', async () => {
    const line = buildLine('topic', [plan('2025', { todoIds: ['todo-k69m'], issues: [301] })], NONE)
    expect(line).toEqual({
      branch: 'topic', plans: [{ id: '2025', page: page('2025') }], todoIds: ['todo-k69m'], issues: [301],
      text: 'plan 2025 · todo-k69m (301)',
    })
  })

  test('several plans: sorted by id, refs the union in plan order', async () => {
    const a = plan('2025', { todoIds: ['todo-b', 'todo-a'], issues: [3] })
    const b = plan('2024', { todoIds: ['todo-a'], issues: [1, 3] })
    const line = buildLine('topic', [a, b], NONE)
    expect(line?.plans.map(p => p.id)).toEqual(['2024', '2025'])
    expect(line?.text).toBe('plans 2024, 2025 · todo-a, todo-b (1, 3)')
  })

  test('a plan with no refs shows its link alone', async () => {
    expect(buildLine('topic', [plan('2025')], NONE)?.text).toBe('plan 2025')
  })

  test('the branch\'s override replaces the plans\' refs; the links stay', async () => {
    const plans = [plan('2025', { todoIds: ['todo-k69m'], issues: [301] })]
    const line = buildLine('topic', plans, override('topic', { todoIds: ['todo-zz99'], issues: [] }))
    expect(line?.plans).toEqual([{ id: '2025', page: page('2025') }])
    expect(line?.text).toBe('plan 2025 · todo-zz99')
  })

  test('another branch\'s override does not apply', async () => {
    const line = buildLine('topic', [plan('2025', { issues: [7] })], override('other', { todoIds: [], issues: [9] }))
    expect(line?.text).toBe('plan 2025 · #7')
  })

  test('an override with no plan shows the refs alone', async () => {
    const line = buildLine('(detached)', [], override('(detached)', { todoIds: ['todo-k69m'], issues: [301] }))
    expect(line).toEqual({ branch: '(detached)', plans: [], todoIds: ['todo-k69m'], issues: [301], text: 'todo-k69m (301)' })
  })

  test('nothing qualifies and no override: no line', async () => {
    expect(buildLine('topic', [], NONE)).toBeNull()
    expect(buildLine('topic', [], override('topic', { todoIds: [], issues: [] }))).toBeNull()
  })
})

describe('fileUrl', () => {
  test('a drive path gets three slashes, backslashes become slashes', async () => {
    expect(fileUrl('E:/x/y.html')).toBe('file:///E:/x/y.html')
    expect(fileUrl('E:\\x\\y.html')).toBe('file:///E:/x/y.html')
  })

  test('a POSIX path and a UNC path', async () => {
    expect(fileUrl('/home/u/y.html')).toBe('file:///home/u/y.html')
    expect(fileUrl('//host/share/y.html')).toBe('file://host/share/y.html')
  })

  test('spaces, # and ? are percent-encoded', async () => {
    expect(fileUrl('E:/my plans/#1?.html')).toBe('file:///E:/my%20plans/%231%3F.html')
  })
})

describe('the rendered forms', () => {
  const line = (over: Partial<WorkingLine> = {}): WorkingLine => ({
    branch: 'topic', plans: [{ id: '2025', page: 'E:/r/2025_x_PIP.html' }], todoIds: ['todo-k69m'], issues: [301],
    text: 'plan 2025 · todo-k69m (301)', ...over,
  })

  test('osc8 wraps the text in the hyperlink escapes', async () => {
    expect(osc8('file:///E:/a.html', '2025')).toBe(`${ESC}]8;;file:///E:/a.html${ESC}\\2025${ESC}]8;;${ESC}\\`)
  })

  test('the plain form is the line text', async () => {
    expect(plainText(line())).toBe('plan 2025 · todo-k69m (301)')
    expect(plainText(null)).toBe('')
  })

  test('the ccstatusline form links each plan number to its page', async () => {
    expect(statusText(line())).toBe(`plan ${osc8('file:///E:/r/2025_x_PIP.html', '2025')} · todo-k69m (301)`)
    const two = line({ plans: [{ id: '2024', page: '/r/a.html' }, { id: '2025', page: '/r/b.html' }] })
    expect(statusText(two)).toBe(
      `plans ${osc8('file:///r/a.html', '2024')}, ${osc8('file:///r/b.html', '2025')} · todo-k69m (301)`,
    )
  })

  test('the ccstatusline form, escapes stripped, is the plain form', async () => {
    const built = buildLine('topic', [plan('2024'), plan('2025', { issues: [5] })], NONE)
    const stripped = statusText(built).replace(/\x1b\]8;;[^\x1b]*\x1b\\/g, '')
    expect(stripped).toBe(plainText(built))
  })

  test('no line, no text', async () => {
    expect(statusText(null)).toBe('')
    expect(statusText(line({ plans: [], todoIds: [], issues: [] }))).toBe('')
  })
})
