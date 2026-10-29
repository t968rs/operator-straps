import { describe, expect, test } from 'claude-code/testing'

import {
  DECISION_OPEN, DECISION_PREFIX, ENTRY_ID_PATTERN, ENTRY_PREFIX, INDEX_HEADER, STATUS_DECIDED, STATUS_OPEN, openIds, parseMemo, stampMemo,
} from './memo'
import type { Resolution } from './memo'

const entry = (id: string, decision = DECISION_OPEN): string => [
  `${ENTRY_PREFIX}${id}. Title of ${id}`,
  '',
  '- **Class:** architectural_ambiguity',
  '- **Description:** brief',
  '- **References:** `src/a.py:1-2`',
  '- **Expected behavior per fix:**',
  '    - (a) fix one -> effect one',
  '- **Recommendation:** do (a)',
  decision,
].join('\n')

const row = (id: string, status = STATUS_OPEN, decision = '-', tracked = '-'): string =>
  `| ${id} | architectural_ambiguity | ${status} | ${decision} | ${tracked} |`

const memo = (rows: string[], entries: string[], extra = ''): string => [
  '# PR #7 Bubbles: Title', '', '- **Scope:** s', '', '## Index', '', INDEX_HEADER,
  '|----|-------|--------|----------|------------|', ...rows, '', '## Entries', '', entries.join('\n\n'), extra, '',
].join('\n')

const resolved = (id: string, evidence = 'fixed', over: Partial<Resolution> = {}): Resolution =>
  ({ id, status: 'RESOLVED', date: '2026-10-29', evidence, ...over })

describe('anchors', () => {
  test('the exported anchors read as the library writes them', async () => {
    expect(STATUS_OPEN).toBe('Open')
    expect(STATUS_DECIDED).toBe('Decided')
    expect(DECISION_OPEN).toBe('- **Decision:** open')
    expect(DECISION_PREFIX).toBe('- **Decision:** ')
    expect(ENTRY_PREFIX).toBe('### ')
    expect(ENTRY_ID_PATTERN).toBe('[A-Z]+[0-9]+')
    expect(INDEX_HEADER).toBe('| ID | Class | Status | Decision | Tracked in |')
  })
})

describe('parseMemo', () => {
  test('index rows and entry boundaries', async () => {
    const text = memo([row('I1'), row('M2', STATUS_DECIDED, 'RESOLVED 2026-10-01: x', '#4')], [entry('I1'), entry('M2')])
    const parsed = parseMemo(text)!
    expect(parsed.rows.map(r => [r.id, r.status, r.decision, r.tracked])).toEqual([
      ['I1', 'Open', '-', '-'], ['M2', 'Decided', 'RESOLVED 2026-10-01: x', '#4'],
    ])
    expect(parsed.rows[0]!.cls).toBe('architectural_ambiguity')
    const lines = text.split('\n')
    const i1 = parsed.entries.get('I1')!
    expect(lines[i1.start]).toBe('### I1. Title of I1')
    expect(lines[i1.end - 1]).toBe(DECISION_OPEN)
    expect(parsed.entries.get('M2')!.start).toBeGreaterThan(i1.end - 1)
  })

  test('undefined when the index header is missing, for junk and for empty text', async () => {
    expect(parseMemo('# Title\n\n## Entries\n\n### I1. T\n')).toBeUndefined()
    expect(parseMemo('')).toBeUndefined()
    expect(parseMemo('{"json": true}')).toBeUndefined()
  })

  test('a header with no rows or entries parses empty', async () => {
    const parsed = parseMemo(memo([], []))!
    expect(parsed.rows).toEqual([])
    expect(parsed.entries.size).toBe(0)
  })

  test('malformed rows (not five cells) and the rule row are skipped', async () => {
    const text = memo(['| I1 | c | Open |', row('I2'), '|---|---|---|---|---|'], [])
    expect(parseMemo(text)!.rows.map(r => r.id)).toEqual(['I2'])
  })

  test('an escaped pipe stays inside its cell', async () => {
    const text = memo(['| I1 | a\\|b | Open | - | - |'], [])
    expect(parseMemo(text)!.rows[0]!.cls).toBe('a\\|b')
  })

  test('an entry ends at the next ### or ## line or an unindented --- but not at an indented ---', async () => {
    const body = [
      '### I1. One', 'text', '  ---', 'more', DECISION_OPEN, '', '---', 'trailer',
      '### I2. Two', DECISION_OPEN, '## Appendix', 'prose',
      '### Not an id', 'prose', '### M3. Three', DECISION_OPEN,
    ].join('\n')
    const text = memo([row('I1')], [body])
    const lines = text.split('\n')
    const span = (id: string): string[] => {
      const s = parseMemo(text)!.entries.get(id)!
      return lines.slice(s.start, s.end)
    }
    expect(span('I1')).toEqual(['### I1. One', 'text', '  ---', 'more', DECISION_OPEN])
    expect(span('I2')).toEqual(['### I2. Two', DECISION_OPEN])
    expect(span('M3')).toEqual(['### M3. Three', DECISION_OPEN])
    expect(parseMemo(text)!.entries.has('Not')).toBe(false)
  })

  test('the first entry for a duplicate id wins', async () => {
    const text = memo([], [entry('I1'), entry('I1', '- **Decision:** other')])
    const lines = text.split('\n')
    const s = parseMemo(text)!.entries.get('I1')!
    expect(lines[s.end - 1]).toBe(DECISION_OPEN)
  })

  test('CRLF text parses like LF text', async () => {
    const text = memo([row('I1')], [entry('I1')]).replace(/\n/g, '\r\n')
    const parsed = parseMemo(text)!
    expect(parsed.rows.map(r => r.id)).toEqual(['I1'])
    expect(parsed.entries.has('I1')).toBe(true)
  })
})

describe('openIds', () => {
  test('ids of rows whose Status is Open, in order', async () => {
    const text = memo([row('I1'), row('M2', STATUS_DECIDED), row('C3')], [])
    expect(openIds(text)).toEqual(['I1', 'C3'])
  })

  test('none for a memo without the anchors or with no Open row', async () => {
    expect(openIds('no anchors here')).toEqual([])
    expect(openIds(memo([row('I1', STATUS_DECIDED)], []))).toEqual([])
  })
})

describe('stampMemo', () => {
  const base = memo([row('I1'), row('M2')], [entry('I1'), entry('M2')])

  test('a RESOLVED id: row to Decided with the Decision and Tracked cells, entry Decision line replaced', async () => {
    const out = stampMemo(base, [resolved('I1', 'fixed in abc1234 and #12')])
    expect(out.stamped).toEqual(['I1'])
    expect(out.text).toBe(base
      .replace(row('I1'), row('I1', STATUS_DECIDED, 'RESOLVED 2026-10-29: fixed in abc1234 and #12', '#12'))
      .replace(`### I1. Title of I1\n\n- **Class:** architectural_ambiguity\n- **Description:** brief\n- **References:** \`src/a.py:1-2\`\n- **Expected behavior per fix:**\n    - (a) fix one -> effect one\n- **Recommendation:** do (a)\n${DECISION_OPEN}`,
        `### I1. Title of I1\n\n- **Class:** architectural_ambiguity\n- **Description:** brief\n- **References:** \`src/a.py:1-2\`\n- **Expected behavior per fix:**\n    - (a) fix one -> effect one\n- **Recommendation:** do (a)\n${DECISION_PREFIX}RESOLVED, 2026-10-29. fixed in abc1234 and #12`))
  })

  test('only the stamped row and entry change: every other line is untouched', async () => {
    const out = stampMemo(base, [resolved('M2', 'done')])
    const before = base.split('\n')
    const after = out.text.split('\n')
    expect(after.length).toBe(before.length)
    const changed = before.flatMap((line, i) => (line === after[i] ? [] : [after[i]]))
    expect(changed).toEqual([
      row('M2', STATUS_DECIDED, 'RESOLVED 2026-10-29: done', '-'),
      `${DECISION_PREFIX}RESOLVED, 2026-10-29. done`,
    ])
  })

  test('CLOSED_NO_ACTION stamps with its own status word', async () => {
    const out = stampMemo(base, [{ id: 'I1', status: 'CLOSED_NO_ACTION', date: '2026-10-30', evidence: 'not needed' }])
    expect(out.text).toContain(row('I1', STATUS_DECIDED, 'CLOSED_NO_ACTION 2026-10-30: not needed', '-'))
    expect(out.text).toContain(`${DECISION_PREFIX}CLOSED_NO_ACTION, 2026-10-30. not needed`)
  })

  test('a second run changes nothing', async () => {
    const once = stampMemo(base, [resolved('I1', 'x #3'), resolved('M2', 'y')])
    expect(once.stamped).toEqual(['I1', 'M2'])
    const twice = stampMemo(once.text, [resolved('I1', 'other'), resolved('M2', 'other')])
    expect(twice.stamped).toEqual([])
    expect(twice.text).toBe(once.text)
  })

  test('DOWNGRADED_TO_* and other statuses do not stamp; the text comes back as given', async () => {
    const rs = [resolved('I1', 'e', { status: 'DOWNGRADED_TO_MINOR' }), resolved('M2', 'e', { status: 'UNRESOLVED' })]
    const out = stampMemo(base, rs)
    expect(out.stamped).toEqual([])
    expect(out.text).toBe(base)
  })

  test('a later non-closing entry for an id (the last one given wins) leaves the row Open', async () => {
    const out = stampMemo(base, [resolved('I1'), resolved('I1', 'e', { status: 'UNRESOLVED' })])
    expect(out.text).toBe(base)
  })

  test('a Decided row is final: a changed resolution never re-stamps it', async () => {
    const decided = memo([row('I1', STATUS_DECIDED, 'RESOLVED 2026-10-01: hand', '#9')], [entry('I1', `${DECISION_PREFIX}hand edit`)])
    const out = stampMemo(decided, [resolved('I1', 'new')])
    expect(out.text).toBe(decided)
    expect(out.stamped).toEqual([])
  })

  test('an id without an index row stamps nothing', async () => {
    expect(stampMemo(base, [resolved('C9')]).text).toBe(base)
  })

  test('the Decision cell is one line with every | escaped; the entry line keeps the evidence verbatim', async () => {
    const out = stampMemo(base, [resolved('I1', 'a | b\n  and\tc')])
    expect(out.text).toContain(row('I1', STATUS_DECIDED, 'RESOLVED 2026-10-29: a \\| b and c', '-'))
    expect(parseMemo(out.text)!.rows.find(r => r.id === 'I1')!.decision).toBe('RESOLVED 2026-10-29: a \\| b and c')
    expect(out.text).toContain(`${DECISION_PREFIX}RESOLVED, 2026-10-29. a | b and c`)
  })

  test('an already escaped pipe is not escaped twice', async () => {
    const out = stampMemo(base, [resolved('I1', 'a \\| b')])
    expect(out.text).toContain('RESOLVED 2026-10-29: a \\| b |')
  })

  const tracked = (evidence: string, text = base): string =>
    parseMemo(stampMemo(text, [resolved('I1', evidence)]).text)!.rows[0]!.tracked

  test('Tracked in: the first #<n> anywhere in the evidence, else a 7-40 hex SHA, else a dash', async () => {
    expect(tracked('see #123 then abc1234')).toBe('#123')
    expect(tracked('commit abc1234 closes #5')).toBe('#5')
    expect(tracked('#7 and #8')).toBe('#7')
    expect(tracked(`sha ${'a1'.repeat(20)}`)).toBe('a1'.repeat(20))
    expect(tracked('abc123')).toBe('-')
    expect(tracked(`sha ${'a1'.repeat(21)}`)).toBe('-')
    expect(tracked('defaced and effaced words')).toBe('-')
    expect(tracked('no reference at all')).toBe('-')
    expect(tracked('')).toBe('-')
  })

  test('Tracked in: the SHA of a working-tree snapshot is not a tracker', async () => {
    const snapshot = '1a2b3c4 (working-tree snapshot; developer commits) - closed, no action'
    expect(tracked(`${snapshot}: deferred to #140`)).toBe('#140')
    expect(tracked(snapshot)).toBe('-')
    expect(tracked(`${snapshot}, earlier def5678`)).toBe('def5678')
    expect(tracked('1a2b3c4 (working-tree snapshot) then 9f8e7d6')).toBe('9f8e7d6')
    expect(tracked('1a2b3c4 (working tree) fixed')).toBe('1a2b3c4')
  })

  test('Tracked in: a cell the developer filled is kept unless the evidence names a #<n>', async () => {
    const filled = memo([row('I1', STATUS_OPEN, '-', 'PR-77'), row('M2')], [entry('I1'), entry('M2')])
    expect(tracked('fixed in abc1234', filled)).toBe('PR-77')
    expect(tracked('nothing to cite', filled)).toBe('PR-77')
    expect(tracked('moved to #12', filled)).toBe('#12')
    const out = stampMemo(filled, [resolved('I1', 'fixed in abc1234')]).text
    expect(parseMemo(out)!.rows[0]!.decision).toBe('RESOLVED 2026-10-29: fixed in abc1234')
    expect(parseMemo(out)!.rows[0]!.status).toBe(STATUS_DECIDED)
  })

  test('Tracked in: an empty cell counts as unfilled', async () => {
    const empty = memo([row('I1', STATUS_OPEN, '-', '')], [entry('I1')])
    expect(tracked('abc1234 done', empty)).toBe('abc1234')
  })

  test('a date with a line break stays on one line and the following rows still parse', async () => {
    const out = stampMemo(base, [resolved('I1', 'x', { date: '2026-10-29\n' })])
    expect(out.stamped).toEqual(['I1'])
    const parsed = parseMemo(out.text)!
    expect(parsed.rows.map(r => r.id)).toEqual(['I1', 'M2'])
    expect(parsed.rows[0]!.decision).toBe('RESOLVED 2026-10-29: x')
    expect(parsed.rows[1]!.status).toBe(STATUS_OPEN)
    expect(out.text).toContain(`${DECISION_PREFIX}RESOLVED, 2026-10-29. x`)
    expect(out.text.split('\n')).toHaveLength(base.split('\n').length)
  })

  test('an empty evidence or date leaves no dangling punctuation', async () => {
    const bare = stampMemo(base, [{ id: 'I1', status: 'RESOLVED', date: '', evidence: '' }])
    expect(bare.text).toContain(row('I1', STATUS_DECIDED, 'RESOLVED', '-'))
    expect(bare.text).toContain(`${DECISION_PREFIX}RESOLVED.`)
  })

  test('a row without an entry still stamps; an entry without the open Decision line is left alone', async () => {
    const text = memo([row('I1'), row('M2')], [entry('M2', `${DECISION_PREFIX}open (waiting on QA)`)])
    const out = stampMemo(text, [resolved('I1'), resolved('M2')])
    expect(out.stamped).toEqual(['I1', 'M2'])
    expect(out.text).toContain(`${DECISION_PREFIX}open (waiting on QA)`)
    expect(openIds(out.text)).toEqual([])
  })

  test('an entry without a Decision line is not stamped from, and never borrows, the next entry\'s line', async () => {
    const text = memo([row('I1'), row('M2')], [`${ENTRY_PREFIX}I1. No decision line`, '', entry('M2')])
    const out = stampMemo(text, [resolved('I1', 'ok')])
    expect(out.stamped).toEqual(['I1'])
    const lines = out.text.split('\n')
    const m2 = parseMemo(out.text)!.entries.get('M2')!
    expect(lines[m2.end - 1]).toBe(DECISION_OPEN)
    expect(lines.filter(l => l === DECISION_OPEN)).toHaveLength(1)
    expect(out.text).not.toContain(`${DECISION_PREFIX}RESOLVED`)
    expect(parseMemo(out.text)!.rows.map(r => r.status)).toEqual([STATUS_DECIDED, STATUS_OPEN])
  })

  test('CRLF text keeps its line endings and a trailing newline', async () => {
    const crlf = base.replace(/\n/g, '\r\n')
    const out = stampMemo(crlf, [resolved('I1', 'ok')])
    expect(out.stamped).toEqual(['I1'])
    expect(out.text.replace(/\r\n/g, '')).not.toContain('\n')
    expect(out.text.endsWith('\r\n')).toBe(true)
    expect(out.text).toBe(stampMemo(base, [resolved('I1', 'ok')]).text.replace(/\n/g, '\r\n'))
  })

  test('a mixed-ending memo keeps each line\'s own ending; only the stamped lines change', async () => {
    const mix = (text: string): string => text.split('\n').map((l, i, all) => l + (i === all.length - 1 ? '' : i % 3 === 0 ? '\r\n' : '\n')).join('')
    const out = stampMemo(mix(base), [resolved('I1', 'ok')])
    expect(out.stamped).toEqual(['I1'])
    expect(out.text).toBe(mix(stampMemo(base, [resolved('I1', 'ok')]).text))
    const before = mix(base).split(/(?<=\n)/)
    const after = out.text.split(/(?<=\n)/)
    expect(after).toHaveLength(before.length)
    expect(before.filter((l, i) => l !== after[i])).toHaveLength(2)
  })

  test('nothing to stamp in a mixed-ending memo returns the very same text', async () => {
    const mixed = base.replace('\n\n', '\r\n\n')
    expect(stampMemo(mixed, [])).toEqual({ text: mixed, stamped: [] })
  })

  test('a memo without the anchors comes back as given', async () => {
    const out = stampMemo('not a memo', [resolved('I1')])
    expect(out).toEqual({ text: 'not a memo', stamped: [] })
  })

  test('no resolutions: nothing stamps', async () => {
    expect(stampMemo(base, [])).toEqual({ text: base, stamped: [] })
  })
})
