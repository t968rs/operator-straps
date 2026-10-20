import { describe, expect, test } from 'claude-code/testing'

import type { NoticeView, SyncFinding, SyncReport, TodoRow, TodoSummary } from '../types'
import {
  contextLineFor, formatContextLine, formatFinding, formatNotice, formatSummary, formatSyncSection, formatTable,
  formatTodoBody, ghAgeText, IN_SYNC_TEXT, isEmptyView, MAX_NOTICE_TITLE, noticeText, parseCatalog, ruleCounts,
  UNAVAILABLE_CONTEXT,
} from './summary'

const HOUR = 3_600_000
const NOW = Date.parse('2026-10-19T12:00:00Z')

/** An item; a null score leaves `priority` out. */
const item = (rank: number, status = 'OPEN', score: number | null = 90 - rank) => ({
  id: `TODO-${String(rank).padStart(3, '0')}`, rank, title: `Item ${rank}`, status,
  ...(score === null ? {} : { priority: { score, components: {} } }),
})

const catalogText = (over: Record<string, unknown> = {}): string =>
  JSON.stringify({
    counts: {
      items: 89, needs_decision: 12,
      by_status: { OPEN: 68, PARTIAL: 12, NEEDS_DECISION: 8, BLOCKED: 1 },
    },
    // out of rank order on purpose: the summary sorts by rank
    items: [item(3), item(1), item(2, 'PARTIAL')],
    ...over,
  })

const summary = (over: Partial<TodoSummary> = {}): TodoSummary => ({
  items: 89, open: 68, partial: 12, blocked: 1, needsDecision: 12,
  top: [{ id: 'TODO-001', rank: 1, title: 'First', status: 'OPEN', score: 88.5 }], mtimeMs: 1, ...over,
})

const finding = (over: Partial<SyncFinding> = {}): SyncFinding => ({
  rule: 'P1', severity: 'error', counted: true, file: 'docs/plans/a_PIP.md', line: 12, subject: 'BFX-3',
  message: 'item COMPLETE but a box is open', fix: 'check the box', ...over,
})

const report = (over: Partial<SyncReport> = {}): SyncReport => ({
  generatedAt: '2026-10-19T12:00:00Z', drift: 4, byRule: { T2: 1, P1: 1, S5: 1, G2: 1 }, errors: 4, warns: 0,
  ghFetchedAt: null, findings: [finding()], mtimeMs: 1, ...over,
})

describe('parseCatalog', () => {
  test('counts and the top rows by rank', async () => {
    const s = parseCatalog(catalogText(), 2, 7)
    expect(s?.items).toBe(89)
    expect([s?.open, s?.partial, s?.blocked, s?.needsDecision]).toEqual([68, 12, 1, 12])
    expect(s?.top.map(r => r.id)).toEqual(['TODO-001', 'TODO-002'])
    expect(s?.top[0]).toEqual({ id: 'TODO-001', rank: 1, title: 'Item 1', status: 'OPEN', score: 89 })
    expect(s?.mtimeMs).toBe(7)
  })

  test('a missing score is null; malformed items are skipped', async () => {
    const s = parseCatalog(catalogText({ items: [item(1, 'OPEN', null), { id: 3 }, 'x'] }), 10, 0)
    expect(s?.top).toEqual([{ id: 'TODO-001', rank: 1, title: 'Item 1', status: 'OPEN', score: null }])
  })

  test('malformed catalogs answer undefined', async () => {
    expect(parseCatalog('{', 10, 0)).toBeUndefined()
    expect(parseCatalog('[]', 10, 0)).toBeUndefined()
    expect(parseCatalog(JSON.stringify({ counts: {}, items: [] }), 10, 0)).toBeUndefined()
    expect(parseCatalog(JSON.stringify({ counts: { items: 1 } }), 10, 0)).toBeUndefined()
  })

  test('missing status counts read as zero', async () => {
    const s = parseCatalog(JSON.stringify({ counts: { items: 2 }, items: [] }), 10, 0)
    expect([s?.open, s?.partial, s?.blocked, s?.needsDecision]).toEqual([0, 0, 0, 0])
  })
})

describe('formatSummary', () => {
  test('the full catalog-only line', async () => {
    expect(formatSummary(summary())).toBe(
      'TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: First',
    )
  })

  test('a long or multi-line top title is flattened and clipped', async () => {
    const title = `line one\nline two ${'x'.repeat(80)}`
    const top = [{ id: 'TODO-001', rank: 1, title, status: 'OPEN', score: null }]
    const shown = formatSummary(summary({ top })).split('top: ')[1]
    expect(shown.startsWith('line one line two x')).toBe(true)
    expect(shown.length).toBe(60)
    expect(shown.endsWith('…')).toBe(true)
  })

  test('zero segments are left out, the total never is', async () => {
    expect(formatSummary(summary({ open: 0, partial: 0, blocked: 0, needsDecision: 0, items: 0, top: [] }))).toBe(
      'TODO 0',
    )
    expect(formatSummary(summary({ partial: 0, blocked: 0 }))).toBe(
      'TODO 89 · 68 open · 12 need a decision · top: First',
    )
  })

  test('drift, clean and the issue cache age', async () => {
    expect(formatSummary(summary(), { drift: 4 })).toMatch(/top: First · 4 out of sync$/)
    expect(formatSummary(summary(), { drift: 0 })).toMatch(/top: First · sync clean$/)
    expect(formatSummary(summary(), { drift: 4, ghAge: '3d' })).toMatch(/· 4 out of sync · gh 3d old$/)
  })
})

describe('ghAgeText', () => {
  test('null or fresh shows nothing; past the limit shows hours, then days', async () => {
    expect(ghAgeText(null, NOW, 24)).toBeUndefined()
    expect(ghAgeText(new Date(NOW - 23 * HOUR).toISOString(), NOW, 24)).toBeUndefined()
    expect(ghAgeText(new Date(NOW - 8 * HOUR).toISOString(), NOW, 6)).toBe('8h')
    expect(ghAgeText(new Date(NOW - 75 * HOUR).toISOString(), NOW, 24)).toBe('3d')
    expect(ghAgeText('not a time', NOW, 24)).toBeUndefined()
  })
})

describe('context line', () => {
  test('rules sorted by id: letter, then number', async () => {
    expect(ruleCounts({ T2: 1, S10: 2, S5: 1, P1: 1, G2: 3 })).toBe('G2=3 P1=1 S5=1 S10=2 T2=1')
    expect(formatContextLine({ drift: 3, byRule: { T2: 1, P1: 1, S5: 1 } })).toBe('TODO_SYNC drift=3 P1=1 S5=1 T2=1')
    expect(formatContextLine({ drift: 0, byRule: {} })).toBe('TODO_SYNC drift=0')
  })

  test('contextLineFor: a report, unavailable, or nothing while pending', async () => {
    expect(contextLineFor(report(), 'found')).toBe('TODO_SYNC drift=4 G2=1 P1=1 S5=1 T2=1')
    expect(contextLineFor(null, 'unavailable')).toBe(UNAVAILABLE_CONTEXT)
    expect(contextLineFor(null, 'pending')).toBeUndefined()
    expect(contextLineFor(null, 'found')).toBeUndefined()
  })
})

/** Rows ranked 1..n, titled `Item <k>`. */
const rows = (n: number): TodoRow[] =>
  Array.from({ length: n }, (_, i) => ({
    id: `TODO-${i + 1}`, rank: i + 1, title: `Item ${i + 1}`, status: 'OPEN', score: null,
  }))

describe('the notice view', () => {
  test('items by rank, at most count', async () => {
    expect(formatNotice(summary({ top: rows(5) }), { drift: 0 }, 'found', 3).items).toEqual([
      '1  Item 1', '2  Item 2', '3  Item 3',
    ])
  })

  test('a short or missing catalog gives fewer lines', async () => {
    expect(formatNotice(summary({ top: rows(2) }), { drift: 0 }, 'found', 3).items.length).toBe(2)
    expect(formatNotice(null, { drift: 0 }, 'found', 3)).toEqual({
      items: [], status: { text: '✓ in sync', tone: 'ok' },
    })
  })

  test('a messy title folds to one clipped line', async () => {
    const top = [{ id: 'TODO-001', rank: 1, title: `a\n\tb ${'x'.repeat(200)}`, status: 'OPEN', score: null }]
    const [line] = formatNotice(summary({ top }), null, 'found', 3).items
    expect(line.startsWith('1  a b x')).toBe(true)
    expect(/[\n\t]/.test(line)).toBe(false)
    expect(line.endsWith('…')).toBe(true)
    expect(line.length).toBeLessThanOrEqual(3 + MAX_NOTICE_TITLE)
  })

  test('status by report and checks state', async () => {
    expect(formatNotice(null, { drift: 5 }, 'found', 3).status).toEqual({ text: '5 out of sync', tone: 'warn' })
    expect(formatNotice(null, null, 'found', 3).status).toBeNull()
    expect(formatNotice(null, null, 'unavailable', 3).status).toEqual({ text: 'sync checks unavailable', tone: 'dim' })
  })

  test('toast text joins items then status', async () => {
    const view: NoticeView = { items: ['1  A', '2  B'], status: { text: IN_SYNC_TEXT, tone: 'ok' } }
    expect(noticeText(view)).toBe('1  A\n2  B\n✓ in sync')
  })

  test('ten long items still end with the whole status', async () => {
    const top = rows(10).map(r => ({ ...r, title: 'y'.repeat(80) }))
    const text = noticeText(formatNotice(summary({ top }), { drift: 12 }, 'found', 10))
    expect(text.endsWith('\n12 out of sync')).toBe(true)
  })

  test('an empty view', async () => {
    expect(isEmptyView(formatNotice(null, null, 'found', 3))).toBe(true)
    expect(isEmptyView(formatNotice(null, null, 'unavailable', 3))).toBe(false)
  })
})

describe('the /todo body', () => {
  test('table rows: rank, id, status, score, title (pipes escaped)', async () => {
    const rows = [
      { id: 'TODO-001', rank: 1, title: 'a | b', status: 'OPEN', score: 88.456 },
      { id: 'TODO-002', rank: 2, title: 'c', status: 'BLOCKED', score: null },
    ]
    expect(formatTable(rows)).toBe(
      [
        '| Rank | Id | Status | Score | Title |',
        '|---:|---|---|---:|---|',
        '| 1 | TODO-001 | OPEN | 88.46 | a \\| b |',
        '| 2 | TODO-002 | BLOCKED | - | c |',
      ].join('\n'),
    )
    expect(formatTable([])).toBe('')
  })

  test('a finding: rule severity file:line subject: message (fix), null parts left out', async () => {
    expect(formatFinding(finding())).toBe(
      'P1 error docs/plans/a_PIP.md:12 BFX-3: item COMPLETE but a box is open (check the box)',
    )
    expect(formatFinding(finding({ line: null, subject: null, fix: null }))).toBe(
      'P1 error docs/plans/a_PIP.md: item COMPLETE but a box is open',
    )
    expect(formatFinding(finding({ file: null, rule: 'T6', severity: 'warn' }))).toBe(
      'T6 warn BFX-3: item COMPLETE but a box is open (check the box)',
    )
  })

  test('sync section: no report yet, unavailable, clean, findings', async () => {
    expect(formatSyncSection(null, 'pending')).toBe('no report yet')
    expect(formatSyncSection(null, 'found')).toBe('no report yet')
    expect(formatSyncSection(null, 'unavailable')).toBe('sync checks unavailable')
    expect(formatSyncSection(report({ drift: 0, byRule: {}, findings: [] }), 'found')).toBe('sync clean')
    expect(formatSyncSection(report(), 'found').split('\n')).toEqual([
      'sync drift 4: G2=1 P1=1 S5=1 T2=1',
      'P1 error docs/plans/a_PIP.md:12 BFX-3: item COMPLETE but a box is open (check the box)',
    ])
  })

  test('the whole body; an unreadable catalog says so', async () => {
    const body = formatTodoBody(summary(), report(), 'found', { drift: 4 })
    expect(body.split('\n\n')[0]).toBe(
      'TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: First · 4 out of sync',
    )
    expect(body).toContain('| 1 | TODO-001 | OPEN | 88.5 | First |')
    expect(formatTodoBody(null, null, 'unavailable', {})).toBe('TODO catalog unreadable\n\nsync checks unavailable')
  })
})
