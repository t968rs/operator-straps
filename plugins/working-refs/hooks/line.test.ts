import { describe, expect, test } from 'claude-code/testing'

import type { Refs, WorkingLine } from '../types'
import {
  buildLine, DARK, fileUrl, fnv1a32, formatRefs, type LineView, osc8, plainText, RESET_FG, statusText, todoColor,
  TODO_PALETTE,
} from './line'
import type { Overrides } from './overrides'
import type { PlanInfo } from './plans'

const ESC = '\x1b'
/** A TODO label as the ccstatusline form draws it: in the id's color, then the default foreground. */
const painted = (id: string, label: string = id): string => `${ESC}[38;5;${todoColor(id)}m${label}${RESET_FG}`
/** Every OSC 8 link escape and SGR color escape dropped. */
const strip = (s: string): string => s.replace(/\x1b\]8;;[^\x1b]*\x1b\\/g, '').replace(/\x1b\[[0-9;]*m/g, '')
const KEYWORDS: ReadonlyMap<string, string> = new Map([['todo-x7ty', 'stop_gates'], ['todo-k69m', 'banner']])
const page = (id: string): string => `E:/repo/docs/PLANS/${id}_x_PIP.html`

const plan = (id: string, refs: Partial<Refs> = {}): PlanInfo => ({
  id, branch: 'topic', baseBranch: 'main', baseCommit: 'a'.repeat(40),
  refs: { todoIds: [], issues: [], ...refs }, page: page(id),
})

const NONE: Overrides = new Map()
const SET_AT = '2026-11-18T00:00:00Z'
const override = (branch: string, refs: Refs): Overrides => new Map([[branch, { refs, setAt: SET_AT }]])
/** Several overrides: `[branch, todoIds, issues, setAt]` each. */
const overridesOf = (...rows: Array<[string, string[], number[], string?]>): Overrides =>
  new Map(rows.map(([b, todoIds, issues, setAt]) => [b, { refs: { todoIds, issues }, setAt: setAt ?? SET_AT }]))
const view = (over: Partial<LineView> = {}): LineView => ({
  retired: new Set(), isClosed: () => false, keywords: new Map(), maxChars: 1000, ...over,
})

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

  test('each id is labelled with its keyword; an id without one prints alone (plan 2028 D1)', async () => {
    expect(formatRefs({ todoIds: ['todo-x7ty'], issues: [] }, KEYWORDS)).toBe('todo-x7ty stop_gates')
    expect(formatRefs({ todoIds: ['todo-x7ty', 'todo-zz99', 'todo-k69m'], issues: [301] }, KEYWORDS))
      .toBe('todo-x7ty stop_gates, todo-zz99, todo-k69m banner (301)')
    expect(formatRefs({ todoIds: [], issues: [301] }, KEYWORDS)).toBe('#301')
  })
})

describe('todoColor (plan 2028 V5, V6)', () => {
  test('FNV-1a 32-bit matches the reference vectors', async () => {
    expect(fnv1a32('')).toBe(0x811c9dc5)
    expect(fnv1a32('a')).toBe(0xe40c292c)
    expect(fnv1a32('foobar')).toBe(0xbf9cf968)
  })

  test('the palette is the eight V5 colors, never DARK\'s 240', async () => {
    expect([...TODO_PALETTE]).toEqual([39, 170, 36, 214, 141, 72, 203, 178])
    expect(TODO_PALETTE).not.toContain(240)
  })

  test('the color is the palette entry at the hash modulo eight', async () => {
    // 0xe40c292c % 8 = 4, 0xbf9cf968 % 8 = 0, 0x811c9dc5 % 8 = 5
    expect(todoColor('a')).toBe(141)
    expect(todoColor('foobar')).toBe(39)
    expect(todoColor('')).toBe(72)
    for (const id of ['todo-x7ty', 'todo-k69m', 'todo-zz99']) {
      expect(todoColor(id)).toBe(TODO_PALETTE[fnv1a32(id) % 8])
      expect(todoColor(id)).toBe(todoColor(id))
    }
  })
})

describe('buildLine', () => {
  test('one plan: its link, then its refs', async () => {
    const line = buildLine('topic', [plan('2025', { todoIds: ['todo-k69m'], issues: [301] })], NONE)
    expect(line).toEqual({
      branch: 'topic', plans: [{ id: '2025', page: page('2025') }], todoIds: ['todo-k69m'], issues: [301],
      labels: [{ id: 'todo-k69m', keyword: null }], refs: 'todo-k69m (301)',
      head: 'plan 2025 · todo-k69m (301)', others: [], more: 0, text: 'plan 2025 · todo-k69m (301)',
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

  test('another branch\'s override does not replace the own refs; it follows bracketed', async () => {
    const line = buildLine('topic', [plan('2025', { issues: [7] })], override('other', { todoIds: [], issues: [9] }))
    expect(line?.issues).toEqual([7])
    expect(line?.text).toBe('plan 2025 · #7 · [ other #9 ]')
  })

  test('an override with no plan shows the refs alone', async () => {
    const line = buildLine('(detached)', [], override('(detached)', { todoIds: ['todo-k69m'], issues: [301] }))
    expect(line).toEqual({
      branch: '(detached)', plans: [], todoIds: ['todo-k69m'], issues: [301],
      labels: [{ id: 'todo-k69m', keyword: null }], refs: 'todo-k69m (301)', head: 'todo-k69m (301)', others: [],
      more: 0, text: 'todo-k69m (301)',
    })
  })

  test('nothing qualifies and no override: no line', async () => {
    expect(buildLine('topic', [], NONE)).toBeNull()
    expect(buildLine('topic', [], override('topic', { todoIds: [], issues: [] }))).toBeNull()
  })
})

describe('buildLine: hidden refs (plan 2027)', () => {
  const closed301 = view({ isClosed: n => n === 301 })

  test('a retired id hides; its issue stays', async () => {
    const line = buildLine('topic', [], override('topic', { todoIds: ['todo-k69m'], issues: [301] }),
      view({ retired: new Set(['todo-k69m']) }))
    expect(line?.text).toBe('#301')
    expect(line?.todoIds).toEqual([])
  })

  test('a closed issue hides; the id stays', async () => {
    const line = buildLine('topic', [], override('topic', { todoIds: ['todo-k69m'], issues: [301] }), closed301)
    expect(line?.text).toBe('todo-k69m')
    expect(line?.issues).toEqual([])
  })

  test('another branch\'s segment hides refs the same way, and drops when all are hidden', async () => {
    const ov = overridesOf(['a', ['todo-k69m'], [301]], ['b', [], [301]])
    expect(buildLine('topic', [], ov, closed301)?.text).toBe('[ a todo-k69m ]')
  })

  test('an own override with every ref hidden leaves the own refs empty; the plan union does not return', async () => {
    const plans = [plan('2025', { todoIds: ['todo-p1'] })]
    const line = buildLine('topic', plans, override('topic', { todoIds: ['todo-gone'], issues: [] }),
      view({ retired: new Set(['todo-gone']) }))
    expect(line?.text).toBe('plan 2025')
    expect(line?.todoIds).toEqual([])
  })

  test('the plan union applies only without an own override entry, and its refs never hide (D4)', async () => {
    const plans = [plan('2025', { todoIds: ['todo-k69m'], issues: [301] })]
    const hideAll = view({ retired: new Set(['todo-k69m']), isClosed: () => true })
    expect(buildLine('topic', plans, NONE, hideAll)?.text).toBe('plan 2025 · todo-k69m (301)')
  })
})

describe('buildLine: other branches and the cap (plan 2027)', () => {
  test('other branches follow the own part, most recently set first, then by name', async () => {
    const ov = overridesOf(
      ['old', ['todo-o1'], [], '2026-11-01T00:00:00Z'],
      ['new', ['todo-n1'], [], '2026-11-19T00:00:00Z'],
      ['b', [], [2], '2026-11-10T00:00:00Z'],
      ['a', [], [1], '2026-11-10T00:00:00Z'],
      ['topic', ['todo-k69m'], [], '2026-11-02T00:00:00Z'],
    )
    const line = buildLine('topic', [], ov)
    expect(line?.head).toBe('todo-k69m')
    expect(line?.others.map(s => s.branch)).toEqual(['new', 'a', 'b', 'old'])
    expect(line?.text).toBe('todo-k69m · [ new todo-n1 ] [ a #1 ] [ b #2 ] [ old todo-o1 ]')
  })

  test('segments past the cap fold into +N; each drawn line fits', async () => {
    const ov = overridesOf(
      ['b1', ['todo-aaaa'], [], '2026-11-19T00:00:03Z'],
      ['b2', ['todo-bbbb'], [], '2026-11-19T00:00:02Z'],
      ['b3', ['todo-cccc'], [], '2026-11-19T00:00:01Z'],
    )
    const full = 'todo-k69m · [ b1 todo-aaaa ] [ b2 todo-bbbb ] [ b3 todo-cccc ]'
    const own = new Map([...ov, ['topic', { refs: { todoIds: ['todo-k69m'], issues: [] }, setAt: '' }]])
    expect(buildLine('topic', [], own, view({ maxChars: full.length }))?.text).toBe(full)
    const two = 'todo-k69m · [ b1 todo-aaaa ] [ b2 todo-bbbb ] +1'
    const line = buildLine('topic', [], own, view({ maxChars: two.length }))
    expect(line?.text).toBe(two)
    expect(line?.more).toBe(1)
    expect(line?.others.map(s => s.branch)).toEqual(['b1', 'b2'])
    expect(buildLine('topic', [], own, view({ maxChars: two.length - 1 }))?.text)
      .toBe('todo-k69m · [ b1 todo-aaaa ] +2')
  })

  test('when no segment fits the line is head +N, with no separator before +N', async () => {
    const ov = overridesOf(['topic', ['todo-k69m'], []], ['other', ['todo-zz99'], []])
    expect(buildLine('topic', [], ov, view({ maxChars: 14 }))?.text).toBe('todo-k69m +1')
  })

  test('a head longer than the cap is drawn whole, every segment folded', async () => {
    const plans = [plan('2025', { todoIds: ['todo-k69m', 'todo-abcd'], issues: [301, 302] })]
    const ov = overridesOf(['x', ['todo-x1'], []], ['y', ['todo-y1'], []])
    const line = buildLine('topic', plans, ov, view({ maxChars: 10 }))
    expect(line?.text).toBe('plan 2025 · todo-k69m, todo-abcd (301, 302) +2')
    expect(line?.others).toEqual([])
  })

  test('with an empty head the first segment is always drawn, then the cap applies', async () => {
    const ov = overridesOf(
      ['a', ['todo-aaaa'], [], '2026-11-19T00:00:02Z'], ['b', ['todo-bbbb'], [], '2026-11-19T00:00:01Z'],
    )
    expect(buildLine('topic', [], ov, view({ maxChars: 5 }))?.text).toBe('[ a todo-aaaa ] +1')
  })
})

describe('buildLine: keyword labels (plan 2028)', () => {
  const kw = (over: Partial<LineView> = {}): LineView => view({ keywords: KEYWORDS, ...over })

  test('the own refs from the plans are labelled, an id without a keyword alone', async () => {
    const plans = [plan('2025', { todoIds: ['todo-x7ty', 'todo-zz99'], issues: [301] })]
    const line = buildLine('topic', plans, NONE, kw())
    expect(line?.refs).toBe('todo-x7ty stop_gates, todo-zz99 (301)')
    expect(line?.head).toBe('plan 2025 · todo-x7ty stop_gates, todo-zz99 (301)')
    expect(line?.labels).toEqual([{ id: 'todo-x7ty', keyword: 'stop_gates' }, { id: 'todo-zz99', keyword: null }])
    expect(line?.todoIds).toEqual(['todo-x7ty', 'todo-zz99'])
  })

  test('the own override and every other-branch segment are labelled', async () => {
    const ov = overridesOf(
      ['topic', ['todo-k69m'], []], ['a', ['todo-x7ty'], [5], '2026-11-19T00:00:00Z'], ['b', ['todo-zz99'], []],
    )
    const line = buildLine('topic', [], ov, kw())
    expect(line?.text).toBe('todo-k69m banner · [ a todo-x7ty stop_gates (5) ] [ b todo-zz99 ]')
    expect(line?.others[0]).toEqual({
      branch: 'a', refs: 'todo-x7ty stop_gates (5)', labels: [{ id: 'todo-x7ty', keyword: 'stop_gates' }], issues: [5],
    })
  })

  test('a retired id leaves with its label', async () => {
    const ov = overridesOf(['topic', ['todo-x7ty', 'todo-k69m'], []])
    const line = buildLine('topic', [], ov, kw({ retired: new Set(['todo-x7ty']) }))
    expect(line?.text).toBe('todo-k69m banner')
    expect(line?.labels).toEqual([{ id: 'todo-k69m', keyword: 'banner' }])
  })

  test('the cap counts the labelled plain text', async () => {
    const ov = overridesOf(
      ['topic', ['todo-k69m'], []],
      ['a', ['todo-x7ty'], [], '2026-11-19T00:00:02Z'], ['b', ['todo-zz99'], [], '2026-11-19T00:00:01Z'],
    )
    const full = 'todo-k69m banner · [ a todo-x7ty stop_gates ] [ b todo-zz99 ]'
    expect(buildLine('topic', [], ov, kw({ maxChars: full.length }))?.text).toBe(full)
    const one = 'todo-k69m banner · [ a todo-x7ty stop_gates ] +1'
    const line = buildLine('topic', [], ov, kw({ maxChars: one.length }))
    expect(line?.text).toBe(one)
    expect(line?.more).toBe(1)
    // long enough for the whole unlabelled line, too short for any labelled segment
    const unlabelled = 'todo-k69m · [ a todo-x7ty ] [ b todo-zz99 ]'
    expect(buildLine('topic', [], ov, view({ maxChars: unlabelled.length }))?.text).toBe(unlabelled)
    expect(buildLine('topic', [], ov, kw({ maxChars: unlabelled.length }))?.text).toBe('todo-k69m banner +2')
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
    labels: [{ id: 'todo-k69m', keyword: null }], refs: 'todo-k69m (301)',
    head: 'plan 2025 · todo-k69m (301)', others: [], more: 0, text: 'plan 2025 · todo-k69m (301)', ...over,
  })
  const K69M = painted('todo-k69m')

  test('osc8 wraps the text in the hyperlink escapes', async () => {
    expect(osc8('file:///E:/a.html', '2025')).toBe(`${ESC}]8;;file:///E:/a.html${ESC}\\2025${ESC}]8;;${ESC}\\`)
  })

  test('the plain form is the line text', async () => {
    expect(plainText(line())).toBe('plan 2025 · todo-k69m (301)')
    expect(plainText(null)).toBe('')
  })

  test('the ccstatusline form links each plan number to its page', async () => {
    expect(statusText(line())).toBe(`plan ${osc8('file:///E:/r/2025_x_PIP.html', '2025')} · ${K69M} (301)`)
    const two = line({ plans: [{ id: '2024', page: '/r/a.html' }, { id: '2025', page: '/r/b.html' }] })
    expect(statusText(two)).toBe(
      `plans ${osc8('file:///r/a.html', '2024')}, ${osc8('file:///r/b.html', '2025')} · ${K69M} (301)`,
    )
  })

  test('the ccstatusline form, escapes stripped, is the plain form', async () => {
    const built = buildLine('topic', [plan('2024'), plan('2025', { issues: [5] })], NONE)
    const stripped = statusText(built).replace(/\x1b\]8;;[^\x1b]*\x1b\\/g, '')
    expect(stripped).toBe(plainText(built))
  })

  test('other branch names are dark in the ccstatusline form only, +N kept', async () => {
    const ov = overridesOf(['topic', ['todo-k69m'], [301]], ['other', ['todo-zz99'], []], ['third', [], [5]])
    const built = buildLine('topic', [plan('2025')], ov, view({ maxChars: 52 }))
    expect(built?.text).toBe('plan 2025 · todo-k69m (301) · [ other todo-zz99 ] +1')
    expect(statusText(built)).toBe(
      `plan ${osc8(fileUrl(page('2025')), '2025')} · ${K69M} (301) · [ ${DARK}other${RESET_FG} ${painted('todo-zz99')} ] +1`,
    )
    expect(strip(statusText(built))).toBe(plainText(built))
    expect(plainText(built)).not.toContain(DARK)
  })

  test('each TODO label is colored by its id in the own refs and every segment; issues stay plain', async () => {
    const ov = overridesOf(
      ['topic', ['todo-x7ty', 'todo-zz99'], [301]], ['other', ['todo-k69m'], [5], '2026-11-19T00:00:00Z'],
      ['third', [], [7]],
    )
    const built = buildLine('topic', [plan('2025')], ov, view({ keywords: KEYWORDS }))
    expect(built?.text)
      .toBe('plan 2025 · todo-x7ty stop_gates, todo-zz99 (301) · [ other todo-k69m banner (5) ] [ third #7 ]')
    const own = `${painted('todo-x7ty', 'todo-x7ty stop_gates')}, ${painted('todo-zz99')} (301)`
    const other = `[ ${DARK}other${RESET_FG} ${painted('todo-k69m', 'todo-k69m banner')} (5) ]`
    expect(statusText(built)).toBe(
      `plan ${osc8(fileUrl(page('2025')), '2025')} · ${own} · ${other} [ ${DARK}third${RESET_FG} #7 ]`,
    )
    expect(strip(statusText(built))).toBe(plainText(built))
  })

  test('the plain form and the atom\'s texts carry no color', async () => {
    const ov = overridesOf(['topic', ['todo-x7ty'], [301]], ['other', ['todo-k69m'], []])
    const built = buildLine('topic', [plan('2025')], ov, view({ keywords: KEYWORDS }))
    for (const s of [plainText(built), built?.refs ?? '', built?.head ?? '', ...(built?.others ?? []).map(o => o.refs)]) {
      expect(s).not.toContain(ESC)
    }
    expect(built?.refs).toBe('todo-x7ty stop_gates (301)')
  })

  test('the colored form keeps the cap the plain text measured', async () => {
    const ov = overridesOf(
      ['a', ['todo-x7ty'], [], '2026-11-19T00:00:02Z'], ['b', ['todo-k69m'], [], '2026-11-19T00:00:01Z'],
    )
    const built = buildLine('topic', [], ov, view({ keywords: KEYWORDS, maxChars: 30 }))
    expect(built?.text).toBe('[ a todo-x7ty stop_gates ] +1')
    expect(statusText(built)).toBe(`[ ${DARK}a${RESET_FG} ${painted('todo-x7ty', 'todo-x7ty stop_gates')} ] +1`)
  })

  test('no line, no text', async () => {
    expect(statusText(null)).toBe('')
    expect(statusText(line({ plans: [], todoIds: [], issues: [], labels: [] }))).toBe('')
  })
})
