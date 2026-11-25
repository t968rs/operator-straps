import { describe, expect, test } from 'claude-code/testing'

import { DETACHED_KEY } from './mirror'
import type { PlanInfo } from './plans'
import { archivedIdsOf, itemsOf, pageOf, parsePlan, qualifies, refsOf } from './plans'

const SHA = 'a'.repeat(40)
const OTHER = 'b'.repeat(40)
const PLAN = 'E:/repo/docs/PLANS/2025_banner_refs_ActionPlan.json'
const PAGE = 'E:/repo/docs/PLANS/2025_banner_refs_PIP.html'

const planJson = (over: Record<string, unknown> = {}): string => JSON.stringify({
  plan_id: '2025',
  documentation: 'docs/PLANS/2025_banner_refs_PIP.html',
  branch: '1168-todo-banner',
  base_branch: 'main',
  base_commit: SHA,
  refs: { todo_ids: ['todo-k69m'], issues: [301, 315] },
  items: [{ id: 'TASK-1', status: 'COMPLETE' }, { id: 'TASK-2', status: 'PENDING' }],
  ...over,
})

const ITEMS = [{ id: 'TASK-1', status: 'COMPLETE' }, { id: 'TASK-2', status: 'PENDING' }]

const info = (over: Partial<PlanInfo> = {}): PlanInfo => ({
  id: '2025', branch: '1168-todo-banner', baseBranch: 'main', baseCommit: SHA,
  refs: { todoIds: [], issues: [] }, page: PAGE, items: ITEMS, ...over,
})

const NONE: ReadonlySet<string> = new Set()
const baseIs = (sha: string | null) => (_base: string) => sha

describe('pageOf', () => {
  test('the sibling page of a plan file, forward slashes', async () => {
    expect(pageOf(PLAN)).toBe(PAGE)
    expect(pageOf('E:\\repo\\docs\\PLANS\\2025_x_ActionPlan.json')).toBe('E:/repo/docs/PLANS/2025_x_PIP.html')
  })

  test('any other name has no page', async () => {
    expect(pageOf('E:/repo/docs/PLANS/2025_x_PIP.html')).toBeNull()
  })
})

describe('refsOf', () => {
  test('the ids and issues, duplicates dropped in first order', async () => {
    expect(refsOf({ todo_ids: ['todo-a', 'todo-b', 'todo-a'], issues: [3, 1, 3] }))
      .toEqual({ todoIds: ['todo-a', 'todo-b'], issues: [3, 1] })
  })

  test('wrong-typed members and fields are dropped; a non-object is no refs', async () => {
    expect(refsOf({ todo_ids: ['todo-a', 5, ''], issues: ['7', 0, -2, 1.5, 9] }))
      .toEqual({ todoIds: ['todo-a'], issues: [9] })
    for (const v of [null, undefined, [], 'x', { todo_ids: 'todo-a' }]) {
      expect(refsOf(v)).toEqual({ todoIds: [], issues: [] })
    }
  })
})

describe('itemsOf', () => {
  test('each item id and status, in file order', async () => {
    expect(itemsOf([{ id: 'TASK-2', status: 'PENDING', title: 't' }, { id: 'TASK-1', status: 'COMPLETE' }]))
      .toEqual([{ id: 'TASK-2', status: 'PENDING' }, { id: 'TASK-1', status: 'COMPLETE' }])
  })

  test('non-objects and entries without a string id are dropped; a non-string status is null', async () => {
    const raw = [null, 'TASK-1', ['TASK-1'], { status: 'COMPLETE' }, { id: 7 }, { id: 'TASK-3', status: 1 },
      { id: 'TASK-4' }]
    expect(itemsOf(raw)).toEqual([{ id: 'TASK-3', status: null }, { id: 'TASK-4', status: null }])
  })

  test('an empty id is dropped', async () => {
    expect(itemsOf([{ id: '', status: 'COMPLETE' }, { id: 'TASK-1' }])).toEqual([{ id: 'TASK-1', status: null }])
  })

  test('a repeated id keeps only its first entry', async () => {
    expect(itemsOf([{ id: 'TASK-1', status: 'PENDING' }, { id: 'TASK-2' }, { id: 'TASK-1', status: 'COMPLETE' }]))
      .toEqual([{ id: 'TASK-1', status: 'PENDING' }, { id: 'TASK-2', status: null }])
  })

  test('a non-array is no items', async () => {
    for (const v of [null, undefined, {}, 'TASK-1']) expect(itemsOf(v)).toEqual([])
  })
})

describe('parsePlan', () => {
  test('the branch fields, the refs and the sibling page', async () => {
    expect(parsePlan(PLAN, planJson())).toEqual({
      id: '2025', branch: '1168-todo-banner', baseBranch: 'main', baseCommit: SHA,
      refs: { todoIds: ['todo-k69m'], issues: [301, 315] }, page: PAGE, items: ITEMS,
    })
  })

  test('a plan with no items field parses with no items', async () => {
    expect(parsePlan(PLAN, planJson({ items: undefined }))?.items).toEqual([])
  })

  test('a plan with no branch fields or refs still parses, with nulls and no refs', async () => {
    const text = planJson({ branch: undefined, base_branch: null, base_commit: '', refs: null })
    expect(parsePlan(PLAN, text)).toEqual(info({ branch: null, baseBranch: null, baseCommit: '' }))
  })

  test('the base commit compares in lower case', async () => {
    expect(parsePlan(PLAN, planJson({ base_commit: 'A'.repeat(40) }))?.baseCommit).toBe(SHA)
  })

  test('a markdown PIP, another page or no documentation is skipped', async () => {
    for (const documentation of ['docs/PLANS/2025_banner_refs_PIP.md', 'docs/PLANS/2024_other_PIP.html', null]) {
      expect(parsePlan(PLAN, planJson({ documentation }))).toBeNull()
    }
  })

  test('a documentation path in another folder or with backslashes still names the page', async () => {
    expect(parsePlan(PLAN, planJson({ documentation: 'docs\\plans\\2025_banner_refs_PIP.html' }))?.page).toBe(PAGE)
  })

  test('malformed JSON, a non-object, a bad plan_id or a non-plan file name is skipped', async () => {
    expect(parsePlan(PLAN, '{not json')).toBeNull()
    expect(parsePlan(PLAN, '[]')).toBeNull()
    expect(parsePlan(PLAN, planJson({ plan_id: '25' }))).toBeNull()
    expect(parsePlan(PLAN, planJson({ plan_id: 2025 }))).toBeNull()
    expect(parsePlan(PAGE, planJson())).toBeNull()
  })
})

describe('archivedIdsOf', () => {
  test('the plan ids of archive tags, any round', async () => {
    const names = 'archive/plan/2024-relink-base-validation/r1\r\narchive/plan/2021-tags/r1-2\nv0.7.0\n\n'
    expect([...archivedIdsOf(names)].sort()).toEqual(['2021', '2024'])
  })

  test('driver tags and other kinds are not archives', async () => {
    expect(archivedIdsOf('base/plan/2025-banner-refs/r1\narchive/skill/x/r1\nreceipt/plan/2025-x/TASK-1').size)
      .toBe(0)
  })
})

describe('qualifies', () => {
  test('rule 1: the plan names the current branch', async () => {
    expect(qualifies(info(), '1168-todo-banner', baseIs(null), NONE)).toBe(true)
  })

  test('rule 2: the plan was written against the merge base of HEAD and its base branch', async () => {
    const seen: string[] = []
    const mergeBaseOf = (base: string) => { seen.push(base); return SHA }
    expect(qualifies(info({ branch: 'other' }), 'topic', mergeBaseOf, NONE)).toBe(true)
    expect(seen).toEqual(['main'])
  })

  test('rule 2 compares the merge base trimmed and in lower case', async () => {
    expect(qualifies(info({ branch: null }), 'topic', baseIs(`${'A'.repeat(40)}\n`), NONE)).toBe(true)
  })

  test('neither rule: another branch and another merge base, or none', async () => {
    expect(qualifies(info({ branch: 'other' }), 'topic', baseIs(OTHER), NONE)).toBe(false)
    expect(qualifies(info({ branch: 'other' }), 'topic', baseIs(null), NONE)).toBe(false)
  })

  test('no base branch or no base commit: rule 2 cannot match and git is not asked', async () => {
    const ask = (_base: string): string | null => { throw new Error('asked') }
    expect(qualifies(info({ branch: null, baseBranch: null }), 'topic', ask, NONE)).toBe(false)
    expect(qualifies(info({ branch: null, baseCommit: '' }), 'topic', ask, NONE)).toBe(false)
  })

  test('an archived plan never qualifies', async () => {
    expect(qualifies(info(), '1168-todo-banner', baseIs(SHA), new Set(['2025']))).toBe(false)
  })

  test('a detached checkout matches by merge base only', async () => {
    expect(qualifies(info({ branch: DETACHED_KEY }), DETACHED_KEY, baseIs(null), NONE)).toBe(false)
    expect(qualifies(info({ branch: DETACHED_KEY }), DETACHED_KEY, baseIs(SHA), NONE)).toBe(true)
  })
})
