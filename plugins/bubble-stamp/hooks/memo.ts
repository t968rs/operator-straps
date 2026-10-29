/**
 * Bubble memo parsing and stamping. The anchors below mirror `harness_lib/bubble_memo.py`;
 * `tests/mods/test_bubble_stamp_anchors_contract.py` pins them. Pure: text in, text out, no `$`.
 *
 * Entry boundary (as in the library): an entry runs from its `### <ID>.` heading to the next line that starts
 * with `### ` or `## `, or that is exactly `---` with no indentation (trailing blanks allowed); trailing blank
 * lines are not part of it. An entry heading id has the review-id shape (`[A-Z]+[0-9]+`).
 */

export const MEMO_SUFFIX = '_Bubbles.md'
export const INDEX_HEADER = '| ID | Class | Status | Decision | Tracked in |'
export const STATUS_OPEN = 'Open'
export const STATUS_DECIDED = 'Decided'
export const DECISION_OPEN = '- **Decision:** open'
export const DECISION_PREFIX = '- **Decision:** '
export const ENTRY_PREFIX = '### '
export const ENTRY_ID_PATTERN = '[A-Z]+[0-9]+'

/** One post-review resolution, as `review.ts` reads it. */
export type Resolution = { id: string; status: string; date: string; evidence: string }

/** One index data row; `line` is its index in `Memo.lines`. */
export type IndexRow = { id: string; cls: string; status: string; decision: string; tracked: string; line: number }

/** Lines `[start, end)` of one entry, the heading first. */
export type EntrySpan = { id: string; start: number; end: number }

/** `lines` carry no line endings; `ends[i]` is the ending that followed `lines[i]` (`''` for the last line). */
export type Memo = {
  lines: string[]
  ends: string[]
  rows: IndexRow[]
  entries: Map<string, EntrySpan>
}

export type StampResult = { text: string; stamped: string[] }

const STAMPING: readonly string[] = ['RESOLVED', 'CLOSED_NO_ACTION']
const HEADING = new RegExp(`^${ENTRY_PREFIX}(${ENTRY_ID_PATTERN})\\.(?:\\s|$)`)
const RULE_CELLS = /^[-: ]*$/
const UNESCAPED_PIPE = /(?<!\\)\|/
const UNESCAPED_PIPES = /(?<!\\)\|/g
const ISSUE_REF = /#\d+/
// A 7-40 hex token with a digit (so a word such as "defaced" is not a SHA), not inside a path.
const SHA = /(?<![\w/.-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w/-]|\.\w)/g
// The harness leads its evidence with the working-tree snapshot SHA, a commit that does not exist yet.
const SNAPSHOT_AFTER_SHA = ' (working-tree snapshot'

const cellsOf = (line: string): string[] => line.trim().split(UNESCAPED_PIPE).slice(1, -1).map(c => c.trim())

const isBoundary = (line: string): boolean =>
  line.startsWith(ENTRY_PREFIX) || line.startsWith('## ') || line.trimEnd() === '---'

/** Data rows after the index header: five cells each; the rule row and malformed rows are skipped. */
const indexRows = (lines: readonly string[], header: number): IndexRow[] => {
  const rows: IndexRow[] = []
  for (let i = header + 1; i < lines.length && (lines[i] ?? '').startsWith('|'); i++) {
    const cells = cellsOf(lines[i] ?? '')
    if (RULE_CELLS.test(cells.join('')) || cells.length !== 5) continue
    const [id = '', cls = '', status = '', decision = '', tracked = ''] = cells
    rows.push({ id, cls, status, decision, tracked, line: i })
  }
  return rows
}

const entrySpans = (lines: readonly string[]): Map<string, EntrySpan> => {
  const spans = new Map<string, EntrySpan>()
  let current: { id: string; start: number } | undefined
  for (let i = 0; i <= lines.length; i++) {
    const line = i < lines.length ? (lines[i] ?? '') : '---'
    if (current !== undefined && isBoundary(line)) {
      let end = i
      while (end > current.start + 1 && (lines[end - 1] ?? '').trim() === '') end--
      if (!spans.has(current.id)) spans.set(current.id, { id: current.id, start: current.start, end })
      current = undefined
    }
    const id = HEADING.exec(line)?.[1]
    if (id !== undefined) current = { id, start: i }
  }
  return spans
}

/** The memo's index rows and entry spans, or undefined when the index header anchor is missing. */
export const parseMemo = (text: string): Memo | undefined => {
  const parts = text.split(/(\r?\n)/)
  const lines = parts.filter((_, i) => i % 2 === 0)
  const ends = lines.map((_, i) => parts[2 * i + 1] ?? '')
  const header = lines.findIndex(line => line.trim() === INDEX_HEADER)
  if (header < 0) return undefined
  return { lines, ends, rows: indexRows(lines, header), entries: entrySpans(lines) }
}

/** Ids of the index rows whose Status is `Open`, in order; none for text without the anchors. */
export const openIds = (text: string): string[] =>
  (parseMemo(text)?.rows ?? []).filter(r => r.status === STATUS_OPEN).map(r => r.id)

const oneLine = (value: string): string => value.split(/\s+/).filter(Boolean).join(' ')

const joinNonEmpty = (parts: readonly string[], sep: string): string => parts.filter(p => p !== '').join(sep)

/** The first 7-40 hex SHA that is not the working-tree snapshot SHA the harness leads its evidence with. */
const firstSha = (evidence: string): string | undefined =>
  [...evidence.matchAll(SHA)].find(m => !evidence.startsWith(SNAPSHOT_AFTER_SHA, (m.index ?? 0) + m[0].length))?.[0]

/**
 * The Tracked in cell: the first `#<n>` in the evidence; else the cell the developer already filled; else
 * the first usable SHA; else `-`.
 */
const trackedIn = (evidence: string, current: string): string => {
  const issue = ISSUE_REF.exec(evidence)?.[0]
  if (issue !== undefined) return issue
  return current !== '' && current !== '-' ? current : (firstSha(evidence) ?? '-')
}

/** `<STATUS> <date>: <evidence>` with `|` escaped. */
const decisionCell = (status: string, date: string, evidence: string): string => {
  const head = joinNonEmpty([status, date], ' ')
  return (evidence === '' ? head : `${head}: ${evidence}`).replace(UNESCAPED_PIPES, '\\|')
}

/** `- **Decision:** <STATUS>, <date>. <evidence>` */
const decisionLine = (status: string, date: string, evidence: string): string => {
  const head = joinNonEmpty([status, date], ', ')
  return `${DECISION_PREFIX}${evidence === '' ? `${head}.` : `${head}. ${evidence}`}`
}

const stampedRow = (row: IndexRow, status: string, date: string, evidence: string): string => {
  const cells = [row.id, row.cls, STATUS_DECIDED, decisionCell(status, date, evidence), trackedIn(evidence, row.tracked)]
  return `| ${cells.join(' | ')} |`
}

/** Line index of the entry's `- **Decision:** open` line in `lines`, or -1. */
const openDecisionAt = (memo: Memo, lines: readonly string[], id: string): number => {
  const span = memo.entries.get(id)
  if (span === undefined) return -1
  for (let i = span.start; i < span.end; i++) if ((lines[i] ?? '').trimEnd() === DECISION_OPEN) return i
  return -1
}

/**
 * Stamp each `Open` index row whose latest resolution (the last one given per id) is `RESOLVED` or
 * `CLOSED_NO_ACTION`: Status to `Decided`, the Decision and Tracked in cells, and the entry's open Decision
 * line. Nothing else changes, and every line keeps its own ending; a `Decided` row is never touched, so a
 * second run changes nothing. A Tracked in cell the developer filled stays unless the evidence names a `#<n>`.
 * The text is returned as given when nothing stamps or the memo lacks the anchors.
 */
export const stampMemo = (text: string, resolutions: readonly Resolution[]): StampResult => {
  const memo = parseMemo(text)
  if (memo === undefined) return { text, stamped: [] }
  const latest = new Map<string, Resolution>()
  for (const r of resolutions) latest.set(r.id, r)
  const lines = [...memo.lines]
  const stamped: string[] = []
  for (const row of memo.rows) {
    const r = latest.get(row.id)
    if (row.status !== STATUS_OPEN || r === undefined || !STAMPING.includes(r.status)) continue
    const date = oneLine(r.date)
    const evidence = oneLine(r.evidence)
    lines[row.line] = stampedRow(row, r.status, date, evidence)
    const at = openDecisionAt(memo, lines, row.id)
    if (at >= 0) lines[at] = decisionLine(r.status, date, evidence)
    if (!stamped.includes(row.id)) stamped.push(row.id)
  }
  if (stamped.length === 0) return { text, stamped }
  return { text: lines.map((l, i) => l + (memo.ends[i] ?? '')).join(''), stamped }
}
