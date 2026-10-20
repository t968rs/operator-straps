import { describe, expect, test } from 'claude-code/testing'

import type { SyncFinding, SyncReport, TodoSummary } from '../types'
import {
  CLEAN_TOAST, contextLineFor, driftToast, formatContextLine, formatFinding, formatSummary, formatSyncSection,
  formatTable, formatTodoBody, ghAgeText, parseCatalog, ruleCounts, UNAVAILABLE_CONTEXT,
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

describe('context line and drift toasts', () => {
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

  test('a rise above the last toasted drift toasts with the delta', async () => {
    expect(driftToast({ drift: 4, byRule: { P1: 2, S5: 2 } }, null, null)).toEqual({
      text: 'TODO sync drift 4 (+4): P1=2 S5=2', toasted: 4,
    })
    expect(driftToast({ drift: 4, byRule: { P1: 4 } }, 2, 2)?.text).toBe('TODO sync drift 4 (+2): P1=4')
  })

  test('no toast at or below the last toasted drift', async () => {
    expect(driftToast({ drift: 4, byRule: { P1: 4 } }, 4, 4)).toBeUndefined()
    expect(driftToast({ drift: 2, byRule: { P1: 2 } }, 4, 4)).toBeUndefined()
    expect(driftToast({ drift: 3, byRule: { P1: 3 } }, 4, 2)).toBeUndefined()
  })

  test('zero from non-zero toasts clean once; zero from zero or from nothing does not', async () => {
    expect(driftToast({ drift: 0, byRule: {} }, 4, 2)).toEqual({ text: CLEAN_TOAST, toasted: 0 })
    expect(driftToast({ drift: 0, byRule: {} }, 0, 0)).toBeUndefined()
    expect(driftToast({ drift: 0, byRule: {} }, null, null)).toBeUndefined()
  })

  test('a long rise toast is clipped', async () => {
    const byRule = Object.fromEntries(Array.from({ length: 40 }, (_, i) => [`T${i + 1}`, 1]))
    const text = driftToast({ drift: 40, byRule }, null, null)?.text ?? ''
    expect(text.length).toBeLessThanOrEqual(160)
    expect(text.endsWith('…')).toBe(true)
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
