import type { FsEntry, On, ProcessRunResult, SessionMessage } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import { MAX_AGE_SECONDS } from './sentinels'
import { phase5Context } from './phase5Scan'

/**
 * The Phase 5 scan (line-2 stamp, else listed mtime, else stat mtime) and the per-prompt
 * `PHASE5_PENDING=` context line, observed through `prompt.submit`.
 */

const ROOT = '/repo'
const NOW_MS = 1_800_000_000_000
const NOW_S = NOW_MS / 1000
const DEFAULT_DIR = '.claude/state/harness/pr-review'

type Sentinel = { text?: string; mtimeMs?: number }
type World = {
  sentinels?: Record<string, Sentinel>
  /** `.claude/harness.json` text; null: no file (the watch is inactive). */
  config?: string | null
  /** What `$.fs.stat` answers as a file's mtime; refused when unset. */
  statMtimeMs?: number
  /** Core refuses the prompt while this answers true. */
  isDropping?: () => boolean
  /** Session cwd (default ROOT). */
  cwd?: string
  /** CLAUDE_PROJECT_DIR (default ROOT). */
  projectDir?: string
  /** What `git rev-parse --show-toplevel` answers; git fails when unset. */
  toplevel?: string
  /** What `git rev-parse --git-common-dir` answers; git fails when unset. */
  commonDir?: string
  /** Folders holding a `.claude/harness.json` (default: ROOT only). */
  harnessRoots?: readonly string[]
}
type Seen = { lists: string[] }

const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')
const entry = (name: string, mtimeMs: number): FsEntry => ({ name, kind: 'file', size: 10, mtimeMs, isLink: false })
const gitRan = (stdout: string, exitCode: number): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** Env, cwd, git, the sentinel folder `dir` (absolute), harness.json and core's prompt and session echoes. */
const world = (on: On, w: World = {}, dir = `${ROOT}/${DEFAULT_DIR}`): Seen => {
  const seen: Seen = { lists: [] }
  const config = w.config === undefined ? '{}' : w.config
  const harnessFiles = (w.harnessRoots ?? [ROOT]).map(r => `${r}/.claude/harness.json`)
  mock.env(on, { CLAUDE_PROJECT_DIR: w.projectDir ?? ROOT })
  mock.clock(on, { now: NOW_MS })
  on('session.cwd', () => ({ value: w.cwd ?? ROOT }))
  on('process.run', (_$, e) => {
    const answer = e.argv.includes('--git-common-dir') ? w.commonDir : w.toplevel
    return { value: answer === undefined ? gitRan('', 128) : gitRan(`${answer}\n`, 0) }
  })
  on('prompt.submit', (_$, e) => (w.isDropping?.() ? { drop: 'held' } : { text: e.text, context: e.context }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('session.compact', (_$, e) => ({ messages: e.messages }))
  on('fs.list', (_$, e) => {
    const path = slash(e.path)
    seen.lists.push(path)
    if (path !== dir) return { deny: `ENOENT ${e.path}` }
    return { value: Object.entries(w.sentinels ?? {}).map(([name, s]) => entry(name, s.mtimeMs ?? 0)) }
  })
  on('fs.read', (_$, e) => {
    const path = slash(e.path)
    if (harnessFiles.includes(path)) return config === null ? { deny: 'ENOENT' } : { value: config }
    const text = (w.sentinels ?? {})[path.slice(path.lastIndexOf('/') + 1)]?.text
    return text === undefined ? { deny: `ENOENT ${e.path}` } : { value: text }
  })
  on('fs.stat', (_$, e) =>
    w.statMtimeMs === undefined
      ? { deny: `ENOENT ${e.path}` }
      : { value: { kind: 'file', size: 10, mtimeMs: w.statMtimeMs, isLink: false } },
  )
  return seen
}

const submit = { text: 'hello', wait: false, origin: { kind: 'composer' } } as const
const HISTORY: SessionMessage[] = [{ role: 'user', text: 'hi', toolUses: [] }]

describe('phase5Context', () => {
  test('the PR ids, comma-separated', async () => {
    expect(phase5Context(['1526', '1530'])).toBe('PHASE5_PENDING=1526,1530')
  })
})

describe('the scan', () => {
  test('hot by line 2 or by listed mtime appear, sorted by name; stale ones and other files do not', async ($, on) => {
    world(on, {
      sentinels: {
        '.phase5_pending_1530': { text: '1530\n', mtimeMs: NOW_MS - 3_600_000 },
        '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` },
        '.phase5_pending_1400': { text: `1400\n${NOW_S - MAX_AGE_SECONDS}\n` },
        '.phase5_pending_1200': { text: '1200', mtimeMs: NOW_MS - 2 * MAX_AGE_SECONDS * 1000 },
        'README.md': { text: 'not a sentinel', mtimeMs: NOW_MS },
      },
    })
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526,1530'])
  })

  test('line 2 wins over a fresh mtime; an unreadable file falls back to its name and mtime', async ($, on) => {
    world(on, {
      sentinels: {
        '.phase5_pending_1600': { text: `1600\n${NOW_S - 90_000}`, mtimeMs: NOW_MS },
        '.phase5_pending_1700': { mtimeMs: NOW_MS - 1000 },
      },
    })
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1700'])
  })

  test('no line 2 and no listed mtime: a fresh stat mtime makes it hot, a stale one does not', async ($, on) => {
    world(on, { sentinels: { '.phase5_pending_1800': { text: '1800\n', mtimeMs: 0 } }, statMtimeMs: NOW_MS - 5000 })
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1800'])
  })

  test('a stale stat mtime keeps it out', async ($, on) => {
    world(on, {
      sentinels: { '.phase5_pending_1800': { text: '1800\n', mtimeMs: 0 } },
      statMtimeMs: NOW_MS - 2 * MAX_AGE_SECONDS * 1000,
    })
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
  })

  test('the folder follows state_dir from harness.json', async ($, on) => {
    const seen = world(on, {
      config: JSON.stringify({ state_dir: 'var/h' }),
      sentinels: { '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` } },
    }, `${ROOT}/var/h/pr-review`)
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    expect(seen.lists).toEqual([`${ROOT}/var/h/pr-review`])
  })

  test('an absolute state_dir is scanned as it is, not under the root', async ($, on) => {
    const seen = world(on, {
      config: JSON.stringify({ state_dir: '/elsewhere/h' }),
      sentinels: { '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` } },
    }, '/elsewhere/h/pr-review')
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    expect(seen.lists).toEqual(['/elsewhere/h/pr-review'])
  })

  test('the root is the git top level of the cwd, ahead of CLAUDE_PROJECT_DIR', async ($, on) => {
    const seen = world(on, {
      cwd: '/wt/sub/dir', projectDir: ROOT, toplevel: '/wt', harnessRoots: [ROOT, '/wt'],
      sentinels: { '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` } },
    }, `/wt/${DEFAULT_DIR}`)
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    expect(seen.lists).toEqual([`/wt/${DEFAULT_DIR}`])
  })

  test('a linked worktree scans its main checkout, where every worktree arms sentinels', async ($, on) => {
    const seen = world(on, {
      cwd: '/wt', projectDir: '/wt', toplevel: '/wt', commonDir: `${ROOT}/.git`, harnessRoots: ['/wt'],
      sentinels: { '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` } },
    })
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    expect(seen.lists).toEqual([`${ROOT}/${DEFAULT_DIR}`])
  })

  test('git failing on the cwd falls back to CLAUDE_PROJECT_DIR before the raw cwd', async ($, on) => {
    const seen = world(on, { cwd: '/wt', projectDir: ROOT, harnessRoots: [ROOT, '/wt'] })
    await $.prompt.submit(submit)
    expect(seen.lists).toEqual([`${ROOT}/${DEFAULT_DIR}`])
  })

  test('outside a harness project nothing is scanned or attached', async ($, on) => {
    const seen = world(on, { config: null, sentinels: { '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` } } })
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    expect(seen.lists).toEqual([])
  })
})

describe('the context line', () => {
  const hot = { '.phase5_pending_1526': { text: `1526\n${NOW_S - 60}\n` } }

  test('attached once per change of the set, beneath context already attached', async ($, on) => {
    const w: World = { sentinels: { ...hot } }
    world(on, w)
    expect((await $.prompt.submit({ ...submit, context: ['other'] })).context).toEqual(['other', 'PHASE5_PENDING=1526'])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    w.sentinels = {}
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    w.sentinels = { ...hot }
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
  })

  test('after /clear or a main compaction the unchanged line is attached again', async ($, on) => {
    world(on, { sentinels: hot })
    await $.prompt.submit(submit)
    await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    await $.session.compact({ trigger: 'precompute', messages: HISTORY })
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
  })

  test('a prompt that did not enter records nothing; the next one still gets the line', async ($, on) => {
    let isDropping = true
    world(on, { sentinels: hot, isDropping: () => isDropping })
    const dropped = await $.prompt.submit(submit)
    expect('drop' in dropped && dropped.drop).toBe('held')
    isDropping = false
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
  })
})
