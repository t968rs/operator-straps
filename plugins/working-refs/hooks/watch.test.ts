import type { FsEntry, On, ProcessRunResult } from 'claude-code'
import type { Engine, MockClock } from 'claude-code/testing'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { WorkingLine } from '../types'
import { statusText } from './line'
import { branchOfSnapshot, configPathOf, isSnapshotMove, pairedPlans, rootCandidates, signatureOf } from './watch'

/**
 * The scans seen through the hooks, over a mocked world: files by path, git answered from a small repository
 * model, and git-status's snapshot held in state. The plugin test sandbox reads no repository file, so every
 * `$` call the mod makes is answered here (todo-watch testWorld.ts pattern).
 */

const NOW = 1_800_000_000_000
const ROOT = '/repo'
const PLANS = `${ROOT}/docs/PLANS`
const LINE_FILE = `${ROOT}/.claude/state/harness/working-refs/line.txt`
const OVERRIDES_FILE = `${ROOT}/.claude/state/harness/working-refs/overrides.json`
const LINE_JSON_FILE = `${ROOT}/.claude/state/harness/working-refs/line.json`
const ISSUES_FILE = `${ROOT}/.claude/state/harness/working-refs/issues.json`
const OPEN_ISSUES_FILE = `${ROOT}/.claude/state/harness/todo-sync/open_issues.json`
const CATALOG_FILE = `${ROOT}/docs/TODO/RepoToDo.json`
const TODO_CONFIG = JSON.stringify({ todo: { folder: 'docs/TODO' } })
const HOUR = 3_600_000
/** A second checkout (a worktree session's cwd) beside CLAUDE_PROJECT_DIR. */
const WT = '/wt'
const WT_LINE_FILE = `${WT}/.claude/state/harness/working-refs/line.txt`
const BASE = 'a'.repeat(40)
const OLD_BASE = 'b'.repeat(40)
const NEW_BASE = 'c'.repeat(40)
const HEAD = 'd'.repeat(40)
const ARCHIVE_TAG = 'archive/plan/2025-banner-refs/r1'

/** A file: its text, its mtime and its path as first written (a listing gives names in their own case). */
type Rec = { text: string; mtimeMs: number; path: string }

type GitSnapshot = {
  branch: string; upstream: string | null; ahead: number; behind: number
  staged: number; unstaged: number; untracked: number
}

const snapshot = (branch: string): GitSnapshot => ({
  branch, upstream: null, ahead: 0, behind: 0, staged: 0, unstaged: 0, untracked: 0,
})

/** The repository git answers for. */
type Repo = {
  head: string
  /** Whether `origin/main` exists. */
  hasRemote: boolean
  /** Whether local `main` contains `origin/main` (`merge-base --is-ancestor`). */
  isLocalAhead: boolean
  /** `git merge-base <tip> HEAD`, by tip. */
  mergeBase: Record<string, string>
  tags: string[]
  /** Every git call is refused. */
  isBroken: boolean
}

type World = {
  files: Map<string, Rec>
  repo: Repo
  git: GitSnapshot | null
  gitVersion: number
  /** Every git argv after `git -C <root>`. */
  gits: string[][]
  /** Every `$.process.run` timeout, index for index with `gits`. */
  timeouts: Array<number | undefined>
  /** Every `$.fs.write` path. */
  writes: string[]
  /** Every gh argv, with the cwd and timeout it ran with. */
  ghs: Array<{ argv: string[]; cwd: string | undefined; timeoutMs: number | undefined }>
  /** What `gh issue view <n>` answers: a state, or 'fail' (a non-zero exit); absent numbers fail. */
  gh: Record<number, string>
  /** The last value written to the `line` atom; undefined before one. */
  line: WorkingLine | null | undefined
  clock: MockClock
  setFile: (path: string, text: string, mtimeMs?: number) => void
}

/** A path's host-independent key: forward slashes, case-folded, a drive letter (and what precedes it) dropped. */
const keyOf = (p: string): string =>
  p.replace(/\\/g, '/').replace(/^(?:[^]*?\/)?[A-Za-z]:(?=\/|$)/, '').toLowerCase()

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

const planJson = (over: Record<string, unknown> = {}): string => JSON.stringify({
  plan_id: '2025',
  documentation: 'docs/PLANS/2025_banner_refs_PIP.html',
  branch: 'feat',
  base_branch: 'main',
  base_commit: BASE,
  refs: { todo_ids: ['todo-k69m'], issues: [301] },
  ...over,
})

const overridesJson = (branch: string, todoIds: string[], issues: number[]): string => JSON.stringify({
  version: 1, branches: { [branch]: { todo_ids: todoIds, issues, set_at: '2026-11-18T00:00:00Z' } },
})

/** Entries directly under `dir`: its files, and its subfolders. */
const listing = (files: Map<string, Rec>, dir: string): FsEntry[] => {
  const prefix = `${keyOf(dir)}/`
  const out = new Map<string, FsEntry>()
  for (const [key, rec] of files) {
    if (!key.startsWith(prefix)) continue
    const rest = rec.path.replace(/\\/g, '/').slice(-(key.length - prefix.length))
    const name = rest.split('/')[0] ?? rest
    const isFile = !rest.includes('/')
    out.set(name, {
      name, kind: isFile ? 'file' : 'dir', size: isFile ? rec.text.length : 0, mtimeMs: isFile ? rec.mtimeMs : 0,
      isLink: false,
    })
  }
  return [...out.values()]
}

const isDir = (files: Map<string, Rec>, path: string): boolean =>
  [...files.keys()].some(k => k.startsWith(`${keyOf(path)}/`))

function fsHooks(on: On, w: World): void {
  on('fs.read', (_$, e) => {
    const rec = w.files.get(keyOf(e.path))
    return rec === undefined ? { deny: 'ENOENT' } : { value: rec.text }
  })
  on('fs.stat', (_$, e) => {
    const rec = w.files.get(keyOf(e.path))
    if (rec !== undefined) return { value: { kind: 'file', size: rec.text.length, mtimeMs: rec.mtimeMs, isLink: false } }
    // a folder's own mtime never moves, as a plan rewritten in place leaves it
    if (isDir(w.files, e.path)) return { value: { kind: 'dir', size: 0, mtimeMs: NOW - 3_600_000, isLink: false } }
    return { deny: 'ENOENT' }
  })
  on('fs.exists', (_$, e) => ({ value: w.files.has(keyOf(e.path)) || isDir(w.files, e.path) }))
  on('fs.list', (_$, e) => (isDir(w.files, e.path) ? { value: listing(w.files, e.path) } : { deny: 'ENOENT' }))
  on('fs.write', (_$, e) => {
    w.writes.push(e.path)
    w.setFile(e.path, e.text)
    return { value: undefined }
  })
}

/** git as the repository model answers it; refused while `isBroken`. */
function answerGit(repo: Repo, args: readonly string[]): ProcessRunResult {
  const [verb, ...rest] = args
  if (verb === 'rev-parse' && rest[0] === 'HEAD') return ran(`${repo.head}\n`)
  if (verb === 'rev-parse' && rest.includes('--verify')) return repo.hasRemote ? ran(`${BASE}\n`) : ran('', 1)
  if (verb === 'merge-base' && rest[0] === '--is-ancestor') return ran('', repo.isLocalAhead ? 0 : 1)
  if (verb === 'merge-base') {
    const sha = repo.mergeBase[rest[0] ?? '']
    return sha === undefined ? ran('', 1) : ran(`${sha}\n`)
  }
  if (verb === 'for-each-ref') return ran(repo.tags.map(t => `${t}\n`).join(''))
  return ran('', 128)
}

/** gh as the world answers it: `issue view <n> --json state`. */
function answerGh(w: World, argv: readonly string[]): ProcessRunResult {
  const answer = w.gh[Number(argv[3])]
  return answer === undefined || answer === 'fail' ? ran('', 1) : ran(JSON.stringify({ state: answer }))
}

function gitHooks(on: On, w: World): void {
  on('process.run', (_$, e) => {
    const argv = [...e.argv]
    if (argv[0] === 'gh') {
      w.ghs.push({ argv, cwd: e.init?.cwd, timeoutMs: e.init?.timeoutMs })
      return { value: answerGh(w, argv) }
    }
    if (argv[0] !== 'git' || argv[1] !== '-C') return { value: ran('', 127) }
    w.gits.push(argv.slice(3))
    w.timeouts.push(e.init?.timeoutMs)
    return w.repo.isBroken ? { deny: 'process timed out after 10000 ms' } : { value: answerGit(w.repo, argv.slice(3)) }
  })
  on('state.get', (_$, e, next) =>
    e.plugin === 'git-status' && e.key === 'git' ? { value: { value: w.git, version: w.gitVersion } } : next(e),
  )
  on('state.set', { plugin: 'working-refs', key: 'line' }, (_$, e, next) => {
    w.line = e.value
    return next(e)
  })
}

/** Core's echo for the session events the hooks pass on, and the tools beneath. */
function bottoms(on: On): void {
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('tool.call', { tool: /^(Bash|PowerShell)$/ }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never)
  // the file tools refuse beneath (git-status status.test.ts pattern); a test moves the file itself
  on('tool.call', { tool: /^(Edit|MultiEdit|Write)$/ }, () => ({ deny: 'beneath' }))
}

/** `cwd` is the session's folder (default ROOT); CLAUDE_PROJECT_DIR stays ROOT. */
type WorldOpts = { branch?: string | null; repo?: Partial<Repo>; config?: boolean | string; cwd?: string }

function world(on: On, opts: WorldOpts = {}): World {
  const files = new Map<string, Rec>()
  const w: World = {
    files,
    repo: {
      head: HEAD, hasRemote: false, isLocalAhead: true, mergeBase: { main: BASE }, tags: [], isBroken: false,
      ...opts.repo,
    },
    git: opts.branch === null ? null : snapshot(opts.branch ?? 'feat'),
    gitVersion: 1, gits: [], timeouts: [], writes: [], ghs: [], gh: {}, line: undefined,
    clock: mock.clock(on, { now: NOW }),
    setFile: (path, text, mtimeMs) => files.set(keyOf(path), {
      text, mtimeMs: mtimeMs ?? w.clock.now(), path: files.get(keyOf(path))?.path ?? path,
    }),
  }
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  on('session.cwd', () => ({ value: opts.cwd ?? ROOT }))
  fsHooks(on, w)
  gitHooks(on, w)
  bottoms(on)
  if (opts.config !== false) w.setFile(configPathOf(ROOT), typeof opts.config === 'string' ? opts.config : '{}', 1)
  return w
}

/** A plan and its page in the plans folder. */
const addPlan = (w: World, stem: string, text: string, mtimeMs = NOW - 60_000, folder = PLANS): void => {
  w.setFile(`${folder}/${stem}_ActionPlan.json`, text, mtimeMs)
  w.setFile(`${folder}/${stem}_PIP.html`, '<html></html>', mtimeMs)
}

const lineText = (w: World): string | undefined => w.files.get(keyOf(LINE_FILE))?.text
const fileJson = (w: World, path: string): any => {
  const text = w.files.get(keyOf(path))?.text
  return text === undefined ? undefined : JSON.parse(text)
}
const iso = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z')
/** An issue cache file: `[n, state, checkedAt]` each. */
const cacheJson = (...rows: Array<[number, string, number]>): string => JSON.stringify({
  version: 1, issues: Object.fromEntries(rows.map(([n, state, at]) => [n, { state, checked_at: iso(at) }])),
})
const openJson = (fetchedAt: number, open: number[]): string =>
  JSON.stringify({ version: 1, fetched_at: iso(fetchedAt), open })
const ghIssues = (w: World): number[] => w.ghs.map(g => Number(g.argv[3]))

async function start($: Engine, w: World): Promise<void> {
  await $.session.start({ cwd: ROOT, surface: null, isInteractive: false })
  await w.clock.settle()
}

async function prompt($: Engine, w: World): Promise<void> {
  await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'composer' } })
  await w.clock.settle()
}

async function bash($: Engine, w: World): Promise<void> {
  await $.tool.call({ tool: 'Bash', command: 'true' } as never)
  await w.clock.settle()
}

/** One tool call of any watched tool, then the deferred work. */
async function callTool($: Engine, w: World, input: Record<string, unknown>): Promise<void> {
  await $.tool.call(input as never)
  await w.clock.settle()
}

const mergeBaseRuns = (w: World): string[][] =>
  w.gits.filter(a => a[0] === 'merge-base' && a[1] !== '--is-ancestor')

// ---------------------------------------------------------------------------
// Pure helpers

describe('rootCandidates', () => {
  test('the cwd and the folders above it, then CLAUDE_PROJECT_DIR, no repeats', async () => {
    expect(rootCandidates('C:\\repo\\', 'C:/repo/sub')).toEqual(['C:/repo/sub', 'C:/repo', 'C:'])
    expect(rootCandidates('/env', '/a/b')).toEqual(['/a/b', '/a', '/', '/env'])
  })
})

describe('git-status snapshot trigger', () => {
  test('the snapshot\'s branch, or null for no snapshot or no string branch', async () => {
    expect(branchOfSnapshot(snapshot('feat'))).toBe('feat')
    expect(branchOfSnapshot(null)).toBeNull()
    expect(branchOfSnapshot(undefined)).toBeNull()
    expect(branchOfSnapshot({ branch: 7 })).toBeNull()
  })

  test('a scan follows another branch, a first snapshot or an unscanned session; the same branch waits', async () => {
    expect(isSnapshotMove({ isScanned: true, branch: 'feat' }, 'feat')).toBe(false)
    expect(isSnapshotMove({ isScanned: true, branch: 'feat' }, 'elsewhere')).toBe(true)
    expect(isSnapshotMove({ isScanned: true, branch: null }, null)).toBe(false)
    expect(isSnapshotMove({ isScanned: true, branch: null }, 'feat')).toBe(true)
    expect(isSnapshotMove({ isScanned: true, branch: 'feat' }, null)).toBe(true)
    expect(isSnapshotMove({ isScanned: false, branch: null }, null)).toBe(true)
    expect(isSnapshotMove({ isScanned: false, branch: 'feat' }, 'feat')).toBe(true)
  })
})

describe('signatureOf and pairedPlans', () => {
  const entry = (name: string, mtimeMs = 1, size = 2) => ({ name, kind: 'file', size, mtimeMs })

  test('a plan rewritten in place changes the signature; other files do not count', async () => {
    const before = [entry('2025_x_ActionPlan.json'), entry('2025_x_PIP.html'), entry('notes.md')]
    const after = [entry('2025_x_ActionPlan.json', 5), entry('2025_x_PIP.html'), entry('notes.md', 9)]
    expect(signatureOf(before)).not.toBe(signatureOf(after))
    expect(signatureOf(before)).toBe(signatureOf([...before.slice(0, 2), entry('notes.md', 9)]))
  })

  test('only a plan with its page beside it is read', async () => {
    const entries = [entry('2025_x_ActionPlan.json'), entry('2025_x_PIP.html'), entry('2026_y_ActionPlan.json')]
    expect(pairedPlans(entries)).toEqual(['2025_x_ActionPlan.json'])
  })
})

// ---------------------------------------------------------------------------
// Scans

describe('qualifying plans', () => {
  test('a plan on the branch shows, in the atom and in line.txt', async ($, on) => {
    const w = world(on, { repo: { mergeBase: {} } })
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    expect(w.line?.plans).toEqual([{ id: '2025', page: `${PLANS}/2025_banner_refs_PIP.html` }])
    expect(lineText(w)).toBe(statusText(w.line ?? null))
    expect(lineText(w)).toContain('\x1b]8;;file:///repo/docs/PLANS/2025_banner_refs_PIP.html\x1b\\2025')
    // rule 1 holds, so no merge base is resolved
    expect(mergeBaseRuns(w)).toEqual([])
  })

  test('a sibling plan shows by merge base, one resolution per base branch', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other' }))
    addPlan(w, '2026_next', planJson({
      plan_id: '2026', documentation: 'docs/PLANS/2026_next_PIP.html', branch: 'third', refs: { todo_ids: ['todo-zz11'] },
    }))
    await start($, w)
    expect(w.line?.text).toBe('plans 2025, 2026 · todo-k69m, todo-zz11 (301)')
    expect(mergeBaseRuns(w)).toEqual([['merge-base', 'main', 'HEAD']])
  })

  test('a lagging local main resolves against origin/main', async ($, on) => {
    const w = world(on, {
      branch: 'feat-2',
      repo: { hasRemote: true, isLocalAhead: false, mergeBase: { main: OLD_BASE, 'origin/main': BASE } },
    })
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other' }))
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    expect(mergeBaseRuns(w)).toEqual([['merge-base', 'origin/main', 'HEAD']])
  })

  test('a local main that contains origin/main is the tip', async ($, on) => {
    const w = world(on, {
      branch: 'feat-2', repo: { hasRemote: true, isLocalAhead: true, mergeBase: { main: BASE, 'origin/main': OLD_BASE } },
    })
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other' }))
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
  })

  test('a plan that matches neither rule leaves no line', async ($, on) => {
    const w = world(on, { repo: { mergeBase: { main: OLD_BASE } } })
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other' }))
    await start($, w)
    expect(w.line ?? null).toBeNull()
    expect(lineText(w)).toBeUndefined()
    expect(w.writes).toEqual([])
  })

  test('every git call carries a timeout; refused git still shows a plan on the branch', async ($, on) => {
    const w = world(on, { repo: { isBroken: true } })
    addPlan(w, '2025_banner_refs', planJson())
    addPlan(w, '2026_next', planJson({ plan_id: '2026', documentation: 'docs/PLANS/2026_next_PIP.html', branch: 'x' }))
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    expect(w.gits.length).toBeGreaterThan(0)
    expect(w.timeouts.every(t => t === 10_000)).toBe(true)
  })
})

describe('rescans', () => {
  test('an archived plan drops on the next prompt', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    w.repo.tags = [ARCHIVE_TAG]
    await prompt($, w)
    expect(w.line).toBeNull()
    expect(lineText(w)).toBe('')
  })

  test('a rebase that moves the merge base rescans at the next prompt', async ($, on) => {
    const w = world(on, { repo: { mergeBase: { main: OLD_BASE } } })
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other', base_commit: NEW_BASE }))
    await start($, w)
    expect(w.line ?? null).toBeNull()
    w.repo.head = 'e'.repeat(40)
    w.repo.mergeBase = { main: NEW_BASE }
    await prompt($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
  })

  test('an unmoved HEAD and tag set runs no rescan at a prompt', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other' }))
    await start($, w)
    const before = mergeBaseRuns(w).length
    await prompt($, w)
    expect(mergeBaseRuns(w).length).toBe(before)
  })

  test('a plan rewritten in place updates the line after a shell call', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    w.setFile(`${PLANS}/2025_banner_refs_ActionPlan.json`, planJson({ refs: { todo_ids: ['todo-k69m'], issues: [301, 315] } }),
      NOW - 1_000)
    await bash($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301, 315)')
  })

  const PLAN_FILE = `${PLANS}/2025_banner_refs_ActionPlan.json`
  const fileCalls: Array<[string, Record<string, unknown>]> = [
    ['Write', { tool: 'Write', file_path: PLAN_FILE, content: '{}' }],
    ['Edit', { tool: 'Edit', file_path: PLAN_FILE, old_string: '301', new_string: '301, 315' }],
    ['MultiEdit', { tool: 'MultiEdit', file_path: PLAN_FILE, edits: [{ old_string: '301', new_string: '315' }] }],
    ['PowerShell', { tool: 'PowerShell', command: 'Set-Content x' }],
  ]
  for (const [name, input] of fileCalls) {
    test(`a plan rewritten in place updates the line after a ${name} call`, async ($, on) => {
      const w = world(on)
      addPlan(w, '2025_banner_refs', planJson())
      await start($, w)
      w.setFile(PLAN_FILE, planJson({ refs: { todo_ids: ['todo-k69m'], issues: [301, 315] } }), NOW - 1_000)
      await callTool($, w, input)
      expect(w.line?.text).toBe('plan 2025 · todo-k69m (301, 315)')
    })
  }

  test('a call of an unwatched tool leaves the line as it was', async ($, on) => {
    const w = world(on)
    on('tool.call', { tool: 'Read' }, () => ({ deny: 'beneath' }))
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    w.setFile(PLAN_FILE, planJson({ refs: { todo_ids: ['todo-k69m'], issues: [301, 315] } }), NOW - 1_000)
    await callTool($, w, { tool: 'Read', file_path: PLAN_FILE })
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
  })

  test('a branch change seen at the next prompt rescans', async ($, on) => {
    const w = world(on, { repo: { mergeBase: {} } })
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    // The test engine refuses a test's $.state.set of git-status's key (the test module is not git-status), so
    // no scan test can emit the snapshot write the mod's `state.set` hook watches: that path (onSnapshot and
    // its `later` deferral) is covered only by the pure helpers branchOfSnapshot and isSnapshotMove above.
    // The snapshot moves beneath instead, and the prompt probe reads it.
    w.git = snapshot('elsewhere')
    await prompt($, w)
    expect(w.line).toBeNull()
    expect(lineText(w)).toBe('')
  })

  test('no snapshot yet: rule 1 waits, no override applies, and the first snapshot rescans', async ($, on) => {
    const w = world(on, { branch: null, repo: { mergeBase: {} } })
    addPlan(w, '2025_banner_refs', planJson())
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], []), NOW - 5_000)
    await start($, w)
    expect(w.line ?? null).toBeNull()
    w.git = snapshot('feat')
    await prompt($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-ab12')
  })
})

describe('overrides', () => {
  test('an override replaces the plan refs; the plan link stays', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], [9]), NOW - 5_000)
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-ab12 (9)')
  })

  test('a newer override file rescans at the next prompt', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], []), NOW - 1_000)
    await prompt($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-ab12')
  })

  test('another branch\'s override is not this branch\'s; it shows bracketed', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('other', ['todo-ab12'], []), NOW - 5_000)
    await start($, w)
    expect(w.line?.todoIds).toEqual([])
    expect(w.line?.text).toBe('[ other todo-ab12 ]')
  })
})

describe('line.txt', () => {
  test('a stale non-empty line.txt is emptied by the session.start scan when nothing qualifies', async ($, on) => {
    const w = world(on)
    w.setFile(LINE_FILE, 'plan 1999 · todo-old1', NOW - 86_400_000)
    await start($, w)
    expect(lineText(w)).toBe('')
    expect(w.writes.map(keyOf)).toEqual([keyOf(LINE_FILE)])
  })

  test('an unchanged line is not written again', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    expect(w.writes.map(keyOf)).toEqual([keyOf(LINE_FILE), keyOf(LINE_JSON_FILE)])
    const gitsBefore = w.gits.length
    // the same plan text at a newer mtime moves the signature, so the shell call rescans to the same line
    w.setFile(`${PLANS}/2025_banner_refs_ActionPlan.json`, planJson(), NOW - 1_000)
    await bash($, w)
    expect(w.gits.length).toBeGreaterThan(gitsBefore)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    expect(w.writes.length).toBe(2)
  })

  test('a project without harness.json still scans the cwd with the default folders', async ($, on) => {
    const w = world(on, { config: false, cwd: WT })
    addPlan(w, '2025_banner_refs', planJson(), NOW - 60_000, `${WT}/docs/PLANS`)
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    expect(w.line?.plans).toEqual([{ id: '2025', page: `${WT}/docs/PLANS/2025_banner_refs_PIP.html` }])
    expect(w.files.get(keyOf(WT_LINE_FILE))?.text).toBe(statusText(w.line ?? null))
    expect(lineText(w)).toBeUndefined()
  })

  test('the cwd\'s harness.json wins over CLAUDE_PROJECT_DIR\'s', async ($, on) => {
    const w = world(on, { cwd: WT })
    w.setFile(configPathOf(WT), '{}', 1)
    addPlan(w, '2025_banner_refs', planJson(), NOW - 60_000, `${WT}/docs/PLANS`)
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-k69m (301)')
    expect(w.files.get(keyOf(WT_LINE_FILE))?.text).toBe(statusText(w.line ?? null))
    expect(lineText(w)).toBeUndefined()
  })
})

describe('line.json (plan 2027)', () => {
  test('the line is written stamped with the branch it was built for', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    expect(fileJson(w, LINE_JSON_FILE)).toEqual({ version: 1, branch: 'feat', text: statusText(w.line ?? null) })
  })

  test('no snapshot: line.json is not written', async ($, on) => {
    const w = world(on, { branch: null })
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], []), NOW - 5_000)
    await start($, w)
    expect(fileJson(w, LINE_JSON_FILE)).toBeUndefined()
  })

  test('a line that empties rewrites an existing line.json with empty text', async ($, on) => {
    const w = world(on)
    w.setFile(LINE_JSON_FILE, JSON.stringify({ version: 1, branch: 'old', text: 'plan 1999' }), NOW - HOUR)
    await start($, w)
    expect(fileJson(w, LINE_JSON_FILE)).toEqual({ version: 1, branch: 'feat', text: '' })
  })
})

describe('hidden refs (plan 2027)', () => {
  test('a retire in the checked-out catalog rescans at the next prompt', async ($, on) => {
    const w = world(on, { config: TODO_CONFIG })
    addPlan(w, '2025_banner_refs', planJson())
    w.setFile(CATALOG_FILE, JSON.stringify({ items: [], retired_ids: [] }), NOW - HOUR)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12', 'todo-cd34'], []), NOW - 5_000)
    await start($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-ab12, todo-cd34')
    w.setFile(CATALOG_FILE, JSON.stringify({ items: [], retired_ids: ['todo-ab12'] }), NOW - 1_000)
    await prompt($, w)
    expect(w.line?.text).toBe('plan 2025 · todo-cd34')
  })

  test('an unmoved catalog causes no rescan at a prompt', async ($, on) => {
    const w = world(on, { config: TODO_CONFIG })
    addPlan(w, '2025_banner_refs', planJson({ branch: 'other' }))
    w.setFile(CATALOG_FILE, JSON.stringify({ items: [], retired_ids: [] }), NOW - HOUR)
    await start($, w)
    const before = mergeBaseRuns(w).length
    await prompt($, w)
    expect(mergeBaseRuns(w).length).toBe(before)
  })

  test('a sync whose open list is newer than a cached CLOSED shows the issue again', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], [9]), NOW - 5_000)
    w.setFile(ISSUES_FILE, cacheJson([9, 'CLOSED', NOW - HOUR]), NOW - HOUR)
    await start($, w)
    expect(w.line?.text).toBe('todo-ab12')
    w.setFile(OPEN_ISSUES_FILE, openJson(NOW - 1_000, [9]), NOW - 1_000)
    await prompt($, w)
    expect(w.line?.text).toBe('todo-ab12 (9)')
    expect(w.ghs).toEqual([])
  })

  test('another branch\'s closed issue hides from its segment', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('other', ['todo-ab12'], [9]), NOW - 5_000)
    w.setFile(ISSUES_FILE, cacheJson([9, 'CLOSED', NOW - HOUR]), NOW - HOUR)
    await start($, w)
    expect(w.line?.text).toBe('[ other todo-ab12 ]')
  })
})

describe('gh rechecks (plan 2027)', () => {
  const twoIssues = (w: World): void => {
    w.setFile(OVERRIDES_FILE, JSON.stringify({
      version: 1,
      branches: {
        feat: { todo_ids: [], issues: [9, 10], set_at: '2026-11-18T00:00:00Z' },
        other: { todo_ids: [], issues: [11], set_at: '2026-11-17T00:00:00Z' },
      },
    }), NOW - 5_000)
  }

  test('one gh call per stale override issue, none inside the age, one cache write', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    twoIssues(w)
    w.setFile(ISSUES_FILE, cacheJson([9, 'OPEN', NOW - HOUR]), NOW - HOUR)
    w.gh = { 10: 'OPEN', 11: 'OPEN' }
    await start($, w)
    expect(ghIssues(w).sort()).toEqual([10, 11])
    expect(w.writes.filter(p => keyOf(p) === keyOf(ISSUES_FILE)).length).toBe(1)
    await prompt($, w)
    await bash($, w)
    expect(ghIssues(w).length).toBe(2)
  })

  test('only override issues are checked, never a plan\'s', async ($, on) => {
    const w = world(on)
    addPlan(w, '2025_banner_refs', planJson())
    await start($, w)
    expect(w.ghs).toEqual([])
  })

  test('gh runs in the checkout with the git timeout, and --repo when todo.gh.repo is set', async ($, on) => {
    const w = world(on, { config: JSON.stringify({ todo: { gh: { repo: 'o/r' } } }) })
    w.setFile(OVERRIDES_FILE, overridesJson('feat', [], [9]), NOW - 5_000)
    w.gh = { 9: 'OPEN' }
    await start($, w)
    expect(w.ghs).toEqual([{
      argv: ['gh', 'issue', 'view', '9', '--json', 'state', '--repo', 'o/r'], cwd: ROOT, timeoutMs: 10_000,
    }])
  })

  test('a CLOSED answer rescans and hides the issue', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], [9]), NOW - 5_000)
    w.gh = { 9: 'CLOSED' }
    await start($, w)
    expect(w.line?.text).toBe('todo-ab12')
    expect(fileJson(w, ISSUES_FILE).issues['9'].state).toBe('CLOSED')
  })

  test('a gh failure with nothing known records UNKNOWN and shows the issue', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', [], [9]), NOW - 5_000)
    w.gh = { 9: 'fail' }
    await start($, w)
    expect(w.line?.text).toBe('#9')
    expect(fileJson(w, ISSUES_FILE).issues['9'].state).toBe('UNKNOWN')
  })

  test('a CLOSED issue stays hidden after a gh failure; the retry waits the age from the try', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', ['todo-ab12'], [9]), NOW - 5_000)
    w.setFile(ISSUES_FILE, cacheJson([9, 'CLOSED', NOW - 48 * HOUR]), NOW - 48 * HOUR)
    w.gh = { 9: 'fail' }
    await start($, w)
    expect(w.ghs.length).toBe(1)
    expect(w.line?.text).toBe('todo-ab12')
    const entry = fileJson(w, ISSUES_FILE).issues['9']
    expect(entry).toEqual({ state: 'CLOSED', checked_at: iso(NOW - 48 * HOUR), tried_at: iso(NOW) })
    await prompt($, w)
    expect(w.ghs.length).toBe(1)
  })

  test('an idle session rechecks at a prompt once the age has passed', async ($, on) => {
    const w = world(on)
    w.setFile(OVERRIDES_FILE, overridesJson('feat', [], [9]), NOW - 5_000)
    w.setFile(ISSUES_FILE, cacheJson([9, 'OPEN', NOW - HOUR]), NOW - HOUR)
    w.gh = { 9: 'CLOSED' }
    await start($, w)
    expect(w.ghs).toEqual([])
    await w.clock.advance(24 * HOUR)
    await prompt($, w)
    expect(ghIssues(w)).toEqual([9])
    expect(w.line ?? null).toBeNull()
  })
})
