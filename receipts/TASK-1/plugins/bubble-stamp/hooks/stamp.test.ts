import type { Engine } from 'claude-code/testing'
import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import { INDEX_HEADER } from './memo'
import { memoPrOf } from './stamp'

/**
 * Engine-level behavior of the stamp glue: which triggers stat and read a review JSON, what the memo ends up
 * holding, and every way a host call can fail. Files, git, env and tools sit beneath the plugin, answered from
 * memory.
 */

const ROOT = '/repo'
const REVIEWS = `${ROOT}/docs/PR_REVIEWS`
const HARNESS = `${ROOT}/.claude/harness.json`
const MEMO = `${REVIEWS}/PR_7_Bubbles.md`
const REVIEW = `${REVIEWS}/0007_title.json`
const STAMPED_ROW = '| I1 | architectural_ambiguity | Decided | RESOLVED 2026-10-29: fixed in #12 | #12 |'
const STAMPED_LINE = '- **Decision:** RESOLVED, 2026-10-29. fixed in #12'

const TOOL_RESULT = { stdout: '', stderr: '', interrupted: false }

type Files = Map<string, { text: string; mtimeMs: number }>
type Seen = {
  files: Files
  /** Paths that exist but whose read is refused. */
  unreadable: Set<string>
  /** Paths whose write is refused. */
  unwritable: Set<string>
  /** Paths that exist but whose stat is refused. */
  unstattable: Set<string>
  /** Folder listings are refused while true. */
  refuseList: boolean
  /** Toasts are refused while true. */
  refuseToast: boolean
  toasts: string[]
  writes: string[]
  reads: string[]
  lists: string[]
  stats: string[]
  /** Reads the world refused, by path. */
  denied: string[]
  /** Every stat and read in call order, as `stat <path>` and `read <path>`. */
  order: string[]
  /** Called before a read is answered (the read is already in `order`). */
  onRead?: (path: string) => void
  /** Every process.run argv, in call order. */
  runs: string[][]
  tick: number
}

/** Where the session runs: CLAUDE_PROJECT_DIR, the session cwd, and git's top level of that cwd (unset: git fails). */
type Place = { projectDir?: string; cwd?: string; toplevel?: string }

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** A host path as the test keys it: Windows hosts hand the hooks `C:\repo\...` for `/repo/...`. */
const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')

const listed = (files: Files, dir: string) => {
  const prefix = `${dir}/`
  return [...files]
    .filter(([p]) => p.startsWith(prefix) && !p.slice(prefix.length).includes('/'))
    .map(([p, f]) => ({ name: p.slice(prefix.length), kind: 'file' as const, size: 1, mtimeMs: f.mtimeMs, isLink: false }))
}

/** Files, env, git, clock and the terminal handlers beneath the plugin; the harness file holds `config`. */
const world = (on: On, config: string | null = '{}', place: Place = {}): Seen => {
  const seen: Seen = {
    files: new Map(), unreadable: new Set(), unwritable: new Set(), unstattable: new Set(), refuseList: false,
    refuseToast: false, toasts: [], writes: [], reads: [], lists: [], stats: [], denied: [], order: [], runs: [],
    tick: 1000,
  }
  if (config !== null) seen.files.set(HARNESS, { text: config, mtimeMs: 1 })
  mock.env(on, { CLAUDE_PROJECT_DIR: place.projectDir ?? ROOT })
  mock.clock(on, { now: 1_800_000_000_000 })
  on('session.cwd', () => ({ value: place.cwd ?? ROOT }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('process.run', (_$, e) => {
    seen.runs.push([...e.argv])
    const top = place.toplevel
    return { value: top === undefined || e.argv[3] !== 'rev-parse' ? ran('', 128) : ran(`${top}\n`) }
  })
  on('fs.read', (_$, e) => {
    const path = slash(e.path)
    seen.reads.push(path)
    seen.order.push(`read ${path}`)
    seen.onRead?.(path)
    if (seen.unreadable.has(path)) {
      seen.denied.push(path)
      return { deny: `EBUSY ${e.path}` }
    }
    const f = seen.files.get(path)
    return f === undefined ? { deny: `ENOENT ${e.path}` } : { value: f.text }
  })
  on('fs.write', (_$, e) => {
    const path = slash(e.path)
    if (seen.unwritable.has(path)) return { deny: `EACCES ${e.path}` }
    seen.writes.push(path)
    seen.files.set(path, { text: e.text, mtimeMs: ++seen.tick })
    return { value: undefined }
  })
  on('fs.stat', (_$, e) => {
    const path = slash(e.path)
    seen.stats.push(path)
    seen.order.push(`stat ${path}`)
    if (seen.unstattable.has(path)) return { deny: `EBUSY ${e.path}` }
    const f = seen.files.get(path)
    return f === undefined ? { deny: `ENOENT ${e.path}` } : { value: { kind: 'file', size: 1, mtimeMs: f.mtimeMs, isLink: false } }
  })
  on('fs.list', (_$, e) => {
    seen.lists.push(slash(e.path))
    if (seen.refuseList) return { deny: `EACCES ${e.path}` }
    return { value: listed(seen.files, slash(e.path)) }
  })
  on('ui.toast', (_$, e) => {
    if (seen.refuseToast) return { deny: 'no surface' }
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  const okTool = () => ({ result: TOOL_RESULT }) as never
  on('tool.call', { tool: 'Bash' }, okTool)
  on('tool.call', { tool: 'PowerShell' }, okTool)
  on('tool.call', { tool: 'Edit' }, okTool)
  on('tool.call', { tool: 'Write' }, okTool)
  return seen
}

const put = (seen: Seen, path: string, text: string): void => {
  seen.files.set(path, { text, mtimeMs: ++seen.tick })
}

const entry = (id: string): string => [
  `### ${id}. Title of ${id}`, '', '- **Class:** architectural_ambiguity', '- **Decision:** open',
].join('\n')

const row = (id: string, status: string): string => `| ${id} | architectural_ambiguity | ${status} | - | - |`

/** A memo whose index holds one row per `[id, status]`. */
const memoOf = (rows: ReadonlyArray<readonly [string, string]>): string => [
  '# PR #7 Bubbles: Title', '', '## Index', '', INDEX_HEADER, '|----|-------|--------|----------|------------|',
  ...rows.map(([id, status]) => row(id, status)), '', '## Entries', '', rows.map(([id]) => entry(id)).join('\n\n'), '',
].join('\n')

const resolution = (id: string, status = 'RESOLVED', evidence = 'fixed in #12') =>
  ({ id, status, date: '2026-10-29', evidence })

const reviewOf = (...resolutions: object[]): string => JSON.stringify({ post_review_resolutions: resolutions })

/** One open memo for PR 7 and its review JSON holding `resolutions`. */
const seeded = (seen: Seen, ...resolutions: object[]): void => {
  put(seen, MEMO, memoOf([['I1', 'Open']]))
  put(seen, REVIEW, reviewOf(...resolutions))
}

const text = (seen: Seen, path = MEMO): string => seen.files.get(path)?.text ?? ''

/**
 * How many reads of the memo came since the review JSON was first statted: the stamping phase, whatever the
 * listing read before it. The current read counts.
 */
const memoReadsSinceReviewStat = (seen: Seen): number => {
  const at = seen.order.indexOf(`stat ${REVIEW}`)
  return at < 0 ? 0 : seen.order.slice(at).filter(x => x === `read ${MEMO}`).length
}

const start = ($: Engine) => $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
const shell = ($: Engine, tool: 'Bash' | 'PowerShell', command: string) =>
  $.tool.call({ tool, command, description: 'd' } as never)
const endTurn = ($: Engine) =>
  $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
const subagentTurn = ($: Engine) =>
  $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer', agentId: 'loop-1' } as never)
const fileTool = ($: Engine, tool: 'Edit' | 'Write', path: string) =>
  $.tool.call({ tool, file_path: path, old_string: 'a', new_string: 'b', content: 'x' } as never)

const REVIEW_SCRIPT = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" closeout 7'
const EDIT_SCRIPT = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/review_edit.py" add 7'
const SCAFFOLD_SCRIPT = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py" scaffold --pr 7'

describe('memoPrOf', () => {
  test('reads N from PR_<N>_Bubbles.md and nothing else', () => {
    expect(memoPrOf('PR_12_Bubbles.md')).toBe(12)
    expect(memoPrOf('PR_007_Bubbles.md')).toBe(7)
    for (const name of ['PR__Bubbles.md', 'PR_x_Bubbles.md', 'PR_12_Bubbles.md.bak', 'xPR_12_Bubbles.md', 'Notes.md']) {
      expect(memoPrOf(name)).toBeUndefined()
    }
  })
})

describe('activation', () => {
  test('a project without .claude/harness.json is left alone', async ($, on) => {
    const seen = world(on, null)
    seeded(seen, resolution('I1'))
    await start($)
    await endTurn($)
    expect(seen.lists).toEqual([])
    expect(seen.writes).toEqual([])
  })

  test('the reviews folder comes from artifacts.reviews', async ($, on) => {
    const seen = world(on, JSON.stringify({ artifacts: { reviews: 'notes/reviews' } }))
    put(seen, `${ROOT}/notes/reviews/PR_7_Bubbles.md`, memoOf([['I1', 'Open']]))
    put(seen, `${ROOT}/notes/reviews/0007_title.json`, reviewOf(resolution('I1')))
    await start($)
    expect(seen.lists).toContain(`${ROOT}/notes/reviews`)
    expect(text(seen, `${ROOT}/notes/reviews/PR_7_Bubbles.md`)).toContain(STAMPED_ROW)
  })

  test('the git top level of the cwd (a linked worktree) is probed before CLAUDE_PROJECT_DIR', async ($, on) => {
    // Both /repo (CLAUDE_PROJECT_DIR) and /wt hold the harness file; only /wt holds the memo.
    const seen = world(on, '{}', { cwd: '/wt/sub', toplevel: '/wt' })
    put(seen, '/wt/.claude/harness.json', '{}')
    put(seen, '/wt/docs/PR_REVIEWS/PR_7_Bubbles.md', memoOf([['I1', 'Open']]))
    put(seen, '/wt/docs/PR_REVIEWS/0007_title.json', reviewOf(resolution('I1')))
    await start($)
    expect(seen.runs).toEqual([['git', '-C', '/wt/sub', 'rev-parse', '--show-toplevel']])
    expect(seen.lists).toEqual(['/wt/docs/PR_REVIEWS'])
    expect(text(seen, '/wt/docs/PR_REVIEWS/PR_7_Bubbles.md')).toContain(STAMPED_ROW)
  })

  test('git failing and CLAUDE_PROJECT_DIR lacking the harness file, the cwd is the root', async ($, on) => {
    const seen = world(on, '{}', { projectDir: '/other' })
    seeded(seen, resolution('I1'))
    await start($)
    expect(seen.runs).toEqual([['git', '-C', ROOT, 'rev-parse', '--show-toplevel']])
    expect(seen.reads.slice(0, 2)).toEqual(['/other/.claude/harness.json', HARNESS])
    expect(seen.lists).toEqual([REVIEWS])
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a known top level is not asked again on a later trigger', async ($, on) => {
    const seen = world(on, '{}', { cwd: '/wt2', toplevel: '/wt2' })
    put(seen, '/wt2/.claude/harness.json', '{}')
    await start($)
    await shell($, 'Bash', REVIEW_SCRIPT)
    expect(seen.lists).toEqual(['/wt2/docs/PR_REVIEWS', '/wt2/docs/PR_REVIEWS'])
    expect(seen.runs).toHaveLength(1)
  })
})

describe('session.start', () => {
  test('stamps a resolved id of an open memo and toasts the ids stamped', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    await start($)
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(text(seen)).toContain(STAMPED_LINE)
    expect(seen.writes).toEqual([MEMO])
    expect(seen.toasts).toHaveLength(1)
    expect(seen.toasts[0]).toContain('I1')
  })

  test('a memo with no Open row is dropped without reading its review JSON', async ($, on) => {
    const seen = world(on)
    put(seen, MEMO, memoOf([['I1', 'Decided']]))
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await start($)
    await endTurn($)
    expect(seen.reads).not.toContain(REVIEW)
    expect(seen.writes).toEqual([])
  })

  test('a file without the memo anchors is not an active memo', async ($, on) => {
    const seen = world(on)
    put(seen, MEMO, '# just notes\n')
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await start($)
    expect(seen.reads).not.toContain(REVIEW)
    expect(seen.writes).toEqual([])
  })

  test('the newest review JSON for the PR decides', async ($, on) => {
    const seen = world(on)
    put(seen, MEMO, memoOf([['I1', 'Open']]))
    put(seen, `${REVIEWS}/0007_old.json`, reviewOf(resolution('I1', 'RESOLVED', 'old #1')))
    put(seen, `${REVIEWS}/0007_new.json`, reviewOf(resolution('I1', 'RESOLVED', 'new #2')))
    put(seen, `${REVIEWS}/0008_other.json`, reviewOf(resolution('I1', 'RESOLVED', 'other #3')))
    await start($)
    expect(text(seen)).toContain('new #2')
    expect(text(seen)).not.toContain('old #1')
    expect(text(seen)).not.toContain('other #3')
  })

  test('a refused listing at the start does nothing and does not throw', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    seen.refuseList = true
    await start($)
    expect(seen.lists).toHaveLength(1)
    expect(seen.writes).toEqual([])
  })

  test('session.start returns the host result unchanged', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    const active = await start($)
    expect(seen.writes).toEqual([MEMO])
    expect(active).toMatchObject({ cwd: ROOT })
    seen.files.delete(HARNESS)
    const inactive = await start($)
    expect(active).toEqual(inactive)
  })
})

describe('listing at a trigger', () => {
  test('a refused listing keeps the active set, so a later turn still stamps', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    seen.refuseList = true
    await shell($, 'Bash', REVIEW_SCRIPT)
    expect(seen.lists).toHaveLength(2)
    expect(seen.writes).toEqual([])
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a memo read the host refuses at a listing stays active', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    seen.unreadable.add(MEMO)
    await shell($, 'Bash', REVIEW_SCRIPT)
    expect(seen.denied).toContain(MEMO)
    seen.unreadable.delete(MEMO)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a memo that parsed with no Open row is dropped at a listing', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, MEMO, memoOf([['I1', 'Decided']]))
    await shell($, 'Bash', REVIEW_SCRIPT)
    const stats = seen.stats.filter(p => p === REVIEW).length
    await endTurn($)
    expect(seen.stats.filter(p => p === REVIEW).length).toBe(stats)
  })
})

describe('triggers', () => {
  test('a Bash command naming pr_review.py stamps after the review JSON moves', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    expect(seen.writes).toEqual([])
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await shell($, 'Bash', REVIEW_SCRIPT)
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(seen.toasts).toHaveLength(1)
  })

  test('a PowerShell command naming review_edit.py stamps', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await shell($, 'PowerShell', `& ${EDIT_SCRIPT}`)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('other commands neither stat nor read anything', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    const before = { reads: seen.reads.length, stats: seen.stats.length, lists: seen.lists.length }
    await shell($, 'Bash', 'git status')
    await shell($, 'PowerShell', 'Get-ChildItem')
    expect(seen.reads.length).toBe(before.reads)
    expect(seen.stats.length).toBe(before.stats)
    expect(seen.lists.length).toBe(before.lists)
    expect(text(seen)).not.toContain(STAMPED_ROW)
  })

  test('a shell trigger finds a memo created after the session started', async ($, on) => {
    const seen = world(on)
    await start($)
    seeded(seen, resolution('I1'))
    await shell($, 'Bash', REVIEW_SCRIPT)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a memo scaffolded mid-session stamps when its review JSON is then edited', async ($, on) => {
    const seen = world(on)
    await start($)
    seeded(seen)
    await shell($, 'Bash', SCAFFOLD_SCRIPT)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await fileTool($, 'Edit', REVIEW)
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(seen.writes).toEqual([MEMO])
  })

  test('Edit and Write of an active review JSON stamp; other paths do not', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await fileTool($, 'Edit', `${ROOT}/src/other.py`)
    expect(seen.writes).toEqual([])
    await fileTool($, 'Edit', REVIEW)
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(seen.writes).toEqual([MEMO])
  })

  test('Write of an active review JSON stamps, backslashes and case notwithstanding', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await fileTool($, 'Write', REVIEW.replace(/\//g, '\\').toUpperCase())
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('turn.complete stamps after the review JSON moves', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('an unchanged mtime costs a stat and no read of the review JSON', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    const reads = seen.reads.filter(p => p === REVIEW).length
    expect(reads).toBe(1)
    await endTurn($)
    await endTurn($)
    expect(seen.reads.filter(p => p === REVIEW).length).toBe(reads)
    expect(seen.stats.filter(p => p === REVIEW).length).toBeGreaterThanOrEqual(2)
  })

  test('a trigger returns the tool result untouched', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    const plain = await shell($, 'Bash', 'git status')
    expect(seen.writes).toEqual([])
    const r = await shell($, 'Bash', REVIEW_SCRIPT)
    expect(seen.writes).toEqual([MEMO])
    expect(r).toEqual(plain)
    expect(r).toMatchObject({ result: TOOL_RESULT })
  })

  test('a subagent turn end is not a trigger; the main turn end is', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    const stats = seen.stats.length
    await subagentTurn($)
    expect(seen.stats.length).toBe(stats)
    expect(seen.writes).toEqual([])
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('triggers fired together stamp once and toast once', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await Promise.all([shell($, 'Bash', REVIEW_SCRIPT), fileTool($, 'Edit', REVIEW), endTurn($)])
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(seen.writes).toEqual([MEMO])
    expect(seen.toasts).toHaveLength(1)
  })
})

describe('stamp rule', () => {
  test('a second pass changes nothing and toasts nothing', async ($, on) => {
    const seen = world(on)
    put(seen, MEMO, memoOf([['I1', 'Open'], ['I2', 'Open']]))
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await start($)
    const once = text(seen)
    expect(once).toContain(STAMPED_ROW)
    expect(seen.writes).toEqual([MEMO])
    expect(seen.toasts).toHaveLength(1)
    // I2 stays Open, so the memo is still active: the moved review JSON is read and found to stamp nothing new.
    put(seen, REVIEW, reviewOf(resolution('I1')))
    const reads = seen.reads.filter(p => p === REVIEW).length
    await endTurn($)
    expect(seen.reads.filter(p => p === REVIEW).length).toBe(reads + 1)
    expect(text(seen)).toBe(once)
    expect(seen.writes).toEqual([MEMO])
    expect(seen.toasts).toHaveLength(1)
  })

  test('DOWNGRADED_TO_* does not stamp; a later RESOLVED does', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1', 'DOWNGRADED_TO_MINOR'))
    await start($)
    expect(seen.writes).toEqual([])
    put(seen, REVIEW, reviewOf(resolution('I1', 'DOWNGRADED_TO_MINOR'), resolution('I1', 'CLOSED_NO_ACTION', 'by design')))
    await endTurn($)
    expect(text(seen)).toContain('CLOSED_NO_ACTION 2026-10-29: by design')
  })

  test('one toast names the ids of every memo stamped', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    put(seen, `${REVIEWS}/PR_9_Bubbles.md`, memoOf([['M3', 'Open']]))
    put(seen, `${REVIEWS}/0009_other.json`, reviewOf(resolution('M3')))
    await start($)
    expect(seen.toasts).toHaveLength(1)
    expect(seen.toasts[0]).toContain('I1')
    expect(seen.toasts[0]).toContain('M3')
  })

  test('a memo whose last Open row is stamped leaves the active set', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    await start($)
    const stats = seen.stats.filter(p => p === REVIEW).length
    await endTurn($)
    expect(seen.stats.filter(p => p === REVIEW).length).toBe(stats)
  })
})

describe('write safety', () => {
  test('the memo is re-read just before the write and the fresh text is the one stamped', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    // The memo changes under the second read of the stamping phase (after the review JSON was statted).
    let isInjected = false
    seen.onRead = path => {
      if (path !== MEMO || memoReadsSinceReviewStat(seen) !== 2) return
      isInjected = true
      put(seen, MEMO, `${text(seen)}\nHand note.\n`)
    }
    await start($)
    expect(isInjected).toBe(true)
    expect(memoReadsSinceReviewStat(seen)).toBe(2)
    expect(seen.writes).toEqual([MEMO])
    expect(text(seen)).toContain('Hand note.')
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a memo that cannot be read is never overwritten', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    // A lock taken after the listing: the first memo read of the stamping phase is refused, and so is every later one.
    seen.onRead = path => {
      if (path === MEMO && memoReadsSinceReviewStat(seen) === 1) seen.unreadable.add(MEMO)
    }
    await start($)
    expect(seen.denied).toContain(MEMO)
    await endTurn($)
    expect(seen.denied.filter(p => p === MEMO).length).toBeGreaterThanOrEqual(2)
    expect(seen.writes).toEqual([])
    expect(seen.toasts).toEqual([])
    seen.unreadable.delete(MEMO)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a memo deleted while active leaves the set', async ($, on) => {
    const seen = world(on)
    seeded(seen)
    await start($)
    seen.files.delete(MEMO)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await endTurn($)
    expect(seen.writes).toEqual([])
    expect(seen.toasts).toEqual([])
    expect(seen.files.has(MEMO)).toBe(false)
    const stats = seen.stats.filter(p => p === REVIEW).length
    await endTurn($)
    expect(seen.stats.filter(p => p === REVIEW).length).toBe(stats)
  })

  test('a refused write is quiet and retried when the next trigger comes', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    seen.unwritable.add(MEMO)
    await start($)
    expect(seen.toasts).toEqual([])
    expect(text(seen)).not.toContain(STAMPED_ROW)
    seen.unwritable.delete(MEMO)
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(seen.toasts).toHaveLength(1)
  })

  test('a malformed review JSON stamps nothing and is read again at the next trigger', async ($, on) => {
    const seen = world(on)
    put(seen, MEMO, memoOf([['I1', 'Open']]))
    put(seen, REVIEW, '{ not json')
    await start($)
    await endTurn($)
    expect(seen.writes).toEqual([])
    expect(seen.reads.filter(p => p === REVIEW).length).toBe(2)
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a refused read of the review JSON does nothing and is retried', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    seen.unreadable.add(REVIEW)
    await start($)
    expect(seen.denied).toContain(REVIEW)
    expect(seen.writes).toEqual([])
    seen.unreadable.delete(REVIEW)
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a refused stat of the review JSON does nothing and is retried', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    seen.unstattable.add(REVIEW)
    await start($)
    expect(seen.stats).toContain(REVIEW)
    expect(seen.reads).not.toContain(REVIEW)
    expect(seen.writes).toEqual([])
    seen.unstattable.delete(REVIEW)
    await endTurn($)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a memo with no review JSON yet is waited on', async ($, on) => {
    const seen = world(on)
    put(seen, MEMO, memoOf([['I1', 'Open']]))
    await start($)
    await endTurn($)
    expect(seen.writes).toEqual([])
    put(seen, REVIEW, reviewOf(resolution('I1')))
    await shell($, 'Bash', REVIEW_SCRIPT)
    expect(text(seen)).toContain(STAMPED_ROW)
  })

  test('a refused toast does not undo the stamp', async ($, on) => {
    const seen = world(on)
    seeded(seen, resolution('I1'))
    seen.refuseToast = true
    await start($)
    expect(text(seen)).toContain(STAMPED_ROW)
    expect(seen.toasts).toEqual([])
  })
})
