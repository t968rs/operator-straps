import type { On, ProcessRunResult, SessionMessage } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { GitSnapshot } from '../types'
import {
  cleanPath,
  delegateExecutable,
  executableCandidates,
  formatContext,
  formatStatus,
  MIN_GAP_MS,
  parsePorcelain,
  rootStarts,
  TAIL_WAIT_MS,
  TICK_MS,
} from './status'

const ROOT = '/repo'
const NOW_MS = 1_800_000_000_000

const CLEAN = [
  '# branch.oid 0123456789abcdef0123456789abcdef01234567',
  '# branch.head dev',
  '# branch.upstream origin/dev',
  '# branch.ab +0 -0',
].join('\n')

const DIRTY = [
  '# branch.oid 0123456789abcdef0123456789abcdef01234567',
  '# branch.head feature/x',
  '# branch.upstream origin/feature/x',
  '# branch.ab +2 -1',
  '1 M. N... 100644 100644 100644 aaa bbb staged.py',
  '1 .M N... 100644 100644 100644 aaa bbb unstaged.py',
  '1 MM N... 100644 100644 100644 aaa bbb both.py',
  '2 R. N... 100644 100644 100644 aaa bbb R100 new.py\told.py',
  'u UU N... 100644 100644 100644 100644 aaa bbb ccc conflict.py',
  '? new_a.py',
  '? new_b.py',
  '! ignored.pyc',
].join('\n')

const snapshot = (over: Partial<GitSnapshot> = {}): GitSnapshot => ({
  branch: 'dev', upstream: 'origin/dev', ahead: 0, behind: 0,
  staged: 0, unstaged: 0, untracked: 0, ...over,
})

// ---------------------------------------------------------------------------
// The world beneath the plugin

type Git = { stdout: string } | { exitCode: number } | 'missing'
type World = {
  env?: Record<string, string>
  cwd?: string
  /** `git status`'s answer; `missing` and an exit code apply to `rev-parse` too. */
  git?: Git
  /** `rev-parse --show-toplevel` per start folder: a top level, or null (not a repo); unset echoes the start. */
  toplevels?: Record<string, string | null>
  /** `$.env.get` and `$.session.cwd` throw. */
  isEnvBroken?: boolean
  /** `$.ui.status` is refused. */
  isStatusRefused?: boolean
  /** Held before git status answers, when set: the test releases it. */
  gate?: Promise<void>
  /** Core refuses the prompt while this answers true. */
  isDropping?: () => boolean
  /** The merged settings `$.settings.read` answers; `throw` makes the read reject. */
  settings?: Record<string, unknown> | 'throw'
  /** Paths `$.fs.exists` answers true for. */
  files?: string[]
}
/**
 * `runs`: the git status runs; `starts`: the folders `rev-parse --show-toplevel` was asked from;
 * `probes`: the paths `$.fs.exists` was asked about.
 */
type Seen = { statuses: (string | undefined)[]; runs: (readonly string[])[]; starts: string[]; probes: string[] }

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** Whether two paths name one file once the engine resolved them: separators and a Windows drive ignored. */
const samePath = (a: string, b: string): boolean => {
  const norm = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')
  return norm(a) === norm(b)
}

/** git's answer to `rev-parse --show-toplevel` from `start`. */
const toplevelAnswer = (w: World, start: string): ProcessRunResult => {
  const git = w.git ?? { stdout: '' }
  if (git !== 'missing' && 'exitCode' in git) return ran('', git.exitCode)
  const top = w.toplevels?.[start]
  return top === null ? ran('', 128) : ran(`${top ?? start}\n`)
}

/** Core's echo for the session events the hooks pass on; a prompt is refused while `isDropping()`. */
const bottoms = (on: On, isDropping: () => boolean = () => false): void => {
  on('prompt.submit', (_$, e) => (isDropping() ? { drop: 'held' } : { text: e.text, context: e.context }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('session.compact', (_$, e) => ({ messages: e.messages }))
}

/** A promise the test resolves by hand. */
const deferred = (): { promise: Promise<void>; release: () => void } => {
  let release = (): void => undefined
  const promise = new Promise<void>(resolve => {
    release = resolve
  })
  return { promise, release }
}

/** Answers env, session cwd, git and the status line from memory. */
const world = (on: On, w: World = {}): Seen => {
  const seen: Seen = { statuses: [], runs: [], starts: [], probes: [] }
  if (w.isEnvBroken) {
    on('env.get', () => {
      throw new Error('boom')
    })
  } else mock.env(on, w.env ?? { CLAUDE_PROJECT_DIR: ROOT })
  on('session.cwd', () => {
    if (w.isEnvBroken) throw new Error('boom')
    return { value: w.cwd ?? '' }
  })
  on('ui.status', (_$, e) => {
    seen.statuses.push(e.text)
    return w.isStatusRefused ? { deny: 'no surface' } : { value: undefined }
  })
  bottoms(on, w.isDropping)
  on('settings.read', () => {
    if (w.settings === 'throw') throw new Error('boom')
    return { value: w.settings ?? {} }
  })
  on('fs.exists', (_$, e) => {
    seen.probes.push(e.path)
    return { value: (w.files ?? []).some(f => samePath(f, e.path)) }
  })
  on('process.run', async (_$, e) => {
    if (w.git === 'missing') return { deny: 'spawn git ENOENT' }
    if (e.argv[3] === 'rev-parse') {
      seen.starts.push(e.argv[2] ?? '')
      return { value: toplevelAnswer(w, e.argv[2] ?? '') }
    }
    seen.runs.push(e.argv)
    if (w.gate !== undefined) await w.gate
    const git = w.git ?? { stdout: CLEAN }
    if (git === 'missing') return { deny: 'spawn git ENOENT' }
    return { value: 'stdout' in git ? ran(git.stdout) : ran('', git.exitCode) }
  })
  return seen
}

const ORIGIN = { kind: 'composer' } as const
const submit = { text: 'hello', wait: false, origin: ORIGIN }
const lastStatus = (seen: Seen): string | undefined => seen.statuses[seen.statuses.length - 1]

// ---------------------------------------------------------------------------
// Pure: porcelain

describe('parsePorcelain', () => {
  test('clean tree with an upstream', async () => {
    expect(parsePorcelain(CLEAN)).toEqual({
      branch: 'dev', upstream: 'origin/dev', ahead: 0, behind: 0, staged: 0, unstaged: 0, untracked: 0,
    })
  })

  test('dirty mix: XY columns, rename, unmerged and untracked, ignored skipped', async () => {
    expect(parsePorcelain(DIRTY)).toEqual({
      branch: 'feature/x', upstream: 'origin/feature/x', ahead: 2, behind: 1,
      staged: 3, unstaged: 3, untracked: 2,
    })
  })

  test('no upstream: upstream null and zero ahead/behind', async () => {
    const out = parsePorcelain('# branch.oid abc\n# branch.head topic\n? a.py\n')
    expect(out.upstream).toBeNull()
    expect(out.ahead).toBe(0)
    expect(out.behind).toBe(0)
    expect(out.untracked).toBe(1)
  })

  test('detached head', async () => {
    expect(parsePorcelain('# branch.oid abc\n# branch.head (detached)\n').branch).toBe('(detached)')
  })

  test('CRLF output and unmerged-only conflicts', async () => {
    const out = parsePorcelain('# branch.head dev\r\nu AA N... 1 1 1 1 a b c x.py\r\nu DU N... 1 1 1 1 a b c y.py\r\n')
    expect(out.branch).toBe('dev')
    expect(out.unstaged).toBe(2)
    expect(out.staged).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// Pure: root starts

describe('rootStarts and cleanPath', () => {
  test('the session cwd first, then CLAUDE_PROJECT_DIR; blanks and repeats dropped', async () => {
    expect(rootStarts('/repo', '/wt')).toEqual(['/wt', '/repo'])
    expect(rootStarts('/repo', '/REPO/')).toEqual(['/REPO'])
    expect(rootStarts('C:\\repo\\', ' ')).toEqual(['C:/repo'])
    expect(rootStarts(undefined, undefined)).toEqual([])
  })

  test('forward slashes, no trailing slash, blank is undefined', async () => {
    expect(cleanPath(' C:\\a\\b\\ \n')).toBe('C:/a/b')
    expect(cleanPath('/repo\n')).toBe('/repo')
    expect(cleanPath('  ')).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// Pure: formatting

describe('formatStatus', () => {
  test('the full example line', async () => {
    const g = snapshot({ ahead: 1, staged: 2, unstaged: 3, untracked: 1 })
    expect(formatStatus(g)).toBe('⎇ dev ↑1 ↓0 · +2 ~3 ?1 -- commits(R,L):0,1')
  })

  test('clean and in sync omits zero segments but keeps the commit counts', async () => {
    expect(formatStatus(snapshot())).toBe('⎇ dev · clean -- commits(R,L):0,0')
  })

  test('no upstream and partial counts', async () => {
    const g = snapshot({ upstream: null, unstaged: 4 })
    expect(formatStatus(g)).toBe('⎇ dev no upstream · ~4 -- commits(R,L):0,0')
  })

  test('detached head shows as such', async () => {
    const text = formatStatus(snapshot({ branch: '(detached)', upstream: null }))
    expect(text).toBe('⎇ (detached) no upstream · clean -- commits(R,L):0,0')
  })

  test('remote-only commits are R (behind), local-only commits are L (ahead)', async () => {
    expect(formatStatus(snapshot({ ahead: 3, behind: 7 }))).toBe('⎇ dev ↑3 ↓7 · clean -- commits(R,L):7,3')
  })

  test('long branch names are clipped and the line stays within 80 characters', async () => {
    const g = snapshot({
      branch: `feature/${'x'.repeat(90)}`, ahead: 12, behind: 345, staged: 99, unstaged: 99, untracked: 99,
    })
    const text = formatStatus(g)
    expect(text.length).toBeLessThanOrEqual(80)
    expect(text.startsWith(`⎇ feature/${'x'.repeat(23)}… ↑12 ↓345`)).toBe(true)
    expect(text.endsWith('+99 ~99 ?99 -- commits(R,L):345,12')).toBe(true)
  })

  test('an over-long line is clipped before the commit counts, which are never cut', async () => {
    const g = snapshot({
      branch: 'x'.repeat(40), ahead: 123456, behind: 654321, staged: 99999, unstaged: 99999, untracked: 99999,
    })
    const text = formatStatus(g)
    expect(text.length).toBeLessThanOrEqual(80)
    expect(text.endsWith('… -- commits(R,L):654321,123456')).toBe(true)
  })
})

describe('formatContext', () => {
  test('GIT_STATE fields, clean tree', async () => {
    expect(formatContext(snapshot())).toBe(
      'GIT_STATE BRANCH=dev UPSTREAM=origin/dev AHEAD=0 BEHIND=0 STAGED=0 UNSTAGED=0 UNTRACKED=0 DIRTY=false',
    )
  })

  test('no upstream, dirty', async () => {
    const g = snapshot({ upstream: null, untracked: 1 })
    expect(formatContext(g)).toBe(
      'GIT_STATE BRANCH=dev UPSTREAM=none AHEAD=0 BEHIND=0 STAGED=0 UNSTAGED=0 UNTRACKED=1 DIRTY=true',
    )
  })
})

// ---------------------------------------------------------------------------
// Hooks: prompt context

const CLEAN_CONTEXT =
  'GIT_STATE BRANCH=dev UPSTREAM=origin/dev AHEAD=0 BEHIND=0 STAGED=0 UNSTAGED=0 UNTRACKED=0 DIRTY=false'

describe('prompt.submit context', () => {
  test('attached on the first prompt, skipped while unchanged, attached again on change', async ($, on) => {
    const w: World = { git: { stdout: CLEAN } }
    const seen = world(on, w)
    const first = await $.prompt.submit(submit)
    expect(first.text).toBe('hello')
    expect(first.context).toEqual([CLEAN_CONTEXT])
    const second = await $.prompt.submit(submit)
    expect(second.context ?? []).toEqual([])
    w.git = { stdout: `${CLEAN}\n? new.py` }
    const third = await $.prompt.submit(submit)
    expect(third.context).toEqual([CLEAN_CONTEXT.replace('UNTRACKED=0 DIRTY=false', 'UNTRACKED=1 DIRTY=true')])
    expect(seen.runs.length).toBe(3)
    expect(lastStatus(seen)).toBe('⎇ dev · ?1 -- commits(R,L):0,0')
  })

  test('keeps context attached beneath and never rewrites the text', async ($, on) => {
    world(on)
    const out = await $.prompt.submit({ ...submit, text: 'do it', context: ['other'] })
    expect(out.text).toBe('do it')
    expect(out.context).toEqual(['other', CLEAN_CONTEXT])
  })

  test('git runs as git -C <root> status --porcelain=v2 --branch', async ($, on) => {
    const seen = world(on)
    await $.prompt.submit(submit)
    expect(seen.runs[0]).toEqual(['git', '-C', ROOT, 'status', '--porcelain=v2', '--branch'])
  })

  test('a Windows project dir is normalised to forward slashes', async ($, on) => {
    const seen = world(on, { env: { CLAUDE_PROJECT_DIR: 'C:\\Users\\dev\\project\\' } })
    await $.prompt.submit(submit)
    expect(seen.starts).toEqual(['C:/Users/dev/project'])
    expect(seen.runs[0]?.[2]).toBe('C:/Users/dev/project')
  })

  test('without CLAUDE_PROJECT_DIR the session cwd is asked', async ($, on) => {
    const seen = world(on, { env: {}, cwd: '/work/tree' })
    await $.prompt.submit(submit)
    expect(seen.runs[0]?.[2]).toBe('/work/tree')
  })

  test('the root is git\'s top level, not the folder asked from', async ($, on) => {
    const seen = world(on, { env: {}, cwd: '/repo/sub/dir', toplevels: { '/repo/sub/dir': '/repo' } })
    await $.prompt.submit(submit)
    expect(seen.runs[0]).toEqual(['git', '-C', '/repo', 'status', '--porcelain=v2', '--branch'])
  })

  test('the session cwd wins over CLAUDE_PROJECT_DIR (a linked worktree)', async ($, on) => {
    const seen = world(on, { cwd: '/wt' })
    await $.prompt.submit(submit)
    expect(seen.starts).toEqual(['/wt'])
    expect(seen.runs[0]?.[2]).toBe('/wt')
  })

  test('a cwd outside any repo falls back to CLAUDE_PROJECT_DIR', async ($, on) => {
    const seen = world(on, { cwd: '/tmp/x', toplevels: { '/tmp/x': null } })
    await $.prompt.submit(submit)
    expect(seen.starts).toEqual(['/tmp/x', ROOT])
    expect(seen.runs[0]?.[2]).toBe(ROOT)
  })

  test('a known top level is not asked again', async ($, on) => {
    const seen = world(on)
    await $.prompt.submit(submit)
    await $.prompt.submit(submit)
    expect(seen.starts).toEqual([ROOT])
    expect(seen.runs.length).toBe(2)
  })

  test('no repo anywhere: no git status run, status cleared', async ($, on) => {
    const seen = world(on, { toplevels: { [ROOT]: null } })
    const out = await $.prompt.submit(submit)
    expect(seen.runs.length).toBe(0)
    expect(out.context ?? []).toEqual([])
    expect(seen.statuses).toEqual([undefined])
  })

  test('no root at all: no git run, status cleared, prompt passes untouched', async ($, on) => {
    const seen = world(on, { env: {}, cwd: '' })
    const out = await $.prompt.submit(submit)
    expect(seen.runs.length).toBe(0)
    expect(out.context ?? []).toEqual([])
    expect(seen.statuses).toEqual([undefined])
  })
})

// ---------------------------------------------------------------------------
// Hooks: failures degrade

describe('git failures clear the status and never block', () => {
  test('not a repository (exit 128)', async ($, on) => {
    const seen = world(on, { git: { exitCode: 128 } })
    const out = await $.prompt.submit(submit)
    expect(out.text).toBe('hello')
    expect(out.context ?? []).toEqual([])
    expect(seen.statuses).toEqual([undefined])
  })

  test('git missing (the run rejects)', async ($, on) => {
    const seen = world(on, { git: 'missing' })
    const out = await $.prompt.submit(submit)
    expect(out.context ?? []).toEqual([])
    expect(seen.statuses).toEqual([undefined])
  })

  test('a throwing environment still lets the prompt through', async ($, on) => {
    const seen = world(on, { isEnvBroken: true })
    const out = await $.prompt.submit(submit)
    expect(out.text).toBe('hello')
    expect(seen.runs.length).toBe(0)
  })

  test('a status line that refuses is swallowed', async ($, on) => {
    world(on, { isStatusRefused: true })
    const out = await $.prompt.submit(submit)
    expect(out.context).toEqual([CLEAN_CONTEXT])
  })

  test('a later failure clears a status that was set', async ($, on) => {
    const w: World = { git: { stdout: CLEAN } }
    const seen = world(on, w)
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBe('⎇ dev · clean -- commits(R,L):0,0')
    w.git = { exitCode: 128 }
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// Hooks: background refresh

const bash = { tool: 'Bash', command: 'git add -A' } as const

/** The Bash tool beneath the plugins, answering at once. */
const bashTool = (on: On): void => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }))
}

describe('background refresh', () => {
  test('a tool call returns before git runs; the refresh follows', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    bashTool(on)
    const out = await $.tool.call(bash)
    expect(out.deny).toBeUndefined()
    expect(seen.runs.length).toBe(0)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    expect(lastStatus(seen)).toBe('⎇ dev · clean -- commits(R,L):0,0')
  })

  test('bursts coalesce: one run in flight, at most one per 2 s', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    bashTool(on)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    await $.tool.call(bash)
    await $.tool.call(bash)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    await clock.advance(MIN_GAP_MS)
    expect(seen.runs.length).toBe(2)
    await clock.advance(MIN_GAP_MS * 5)
    expect(seen.runs.length).toBe(2)
  })

  test('other tools (Read) do not refresh', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    on('tool.call', { tool: 'Read' }, () => ({ result: { type: 'text', file: { filePath: 'a', content: '', numLines: 0, startLine: 1, totalLines: 0 } } }))
    await $.tool.call({ tool: 'Read', file_path: '/repo/a.py' })
    await clock.advance(MIN_GAP_MS)
    expect(seen.runs.length).toBe(0)
  })

  test('turn.complete refreshes', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    await $.turn.complete({ answer: 'ok', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer' })
    await clock.settle()
    expect(seen.runs.length).toBe(1)
  })

  test('session.start refreshes, then every 60 s', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    await $.session.start({ cwd: ROOT, surface: null, isInteractive: false })
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    await clock.advance(TICK_MS)
    expect(seen.runs.length).toBe(2)
    await clock.advance(TICK_MS)
    expect(seen.runs.length).toBe(3)
  })

  test('a background git failure clears the status without throwing', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on, { git: 'missing' })
    bashTool(on)
    const out = await $.tool.call(bash)
    expect(out.deny).toBeUndefined()
    await clock.settle()
    expect(seen.statuses).toEqual([undefined])
  })
})

// ---------------------------------------------------------------------------
// Review regressions

/** Answers the plugin's `lastContext` key with `line`, as a state that outlived a conversation. */
const lastContextState = (on: On, line: string): void => {
  on('state.get', (_$, e, next) =>
    e.plugin === 'git-status' && e.key === 'lastContext' ? { value: { value: line, version: 1 } } : next(e),
  )
}

const HISTORY: SessionMessage[] = [{ role: 'user', text: 'hi', toolUses: [] }]

const ended = (reason: 'clear' | 'resume' | 'prompt_input_exit') => ({
  reason, sessionId: 's1', resume: { id: 's1' },
})

describe('a new conversation in the same process', () => {
  test('the first prompt attaches even when lastContext already holds the same line', async ($, on) => {
    world(on)
    lastContextState(on, CLEAN_CONTEXT)
    const out = await $.prompt.submit(submit)
    expect(out.context).toEqual([CLEAN_CONTEXT])
  })

  test('after /clear the unchanged line is attached again', async ($, on) => {
    world(on)
    expect((await $.prompt.submit(submit)).context).toEqual([CLEAN_CONTEXT])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.end(ended('clear'))
    expect((await $.prompt.submit(submit)).context).toEqual([CLEAN_CONTEXT])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
  })

  test('after a resume the unchanged line is attached again', async ($, on) => {
    world(on)
    await $.prompt.submit(submit)
    await $.session.end(ended('resume'))
    expect((await $.prompt.submit(submit)).context).toEqual([CLEAN_CONTEXT])
  })

  test('after a compaction of the main conversation the line is attached again', async ($, on) => {
    world(on)
    await $.prompt.submit(submit)
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect((await $.prompt.submit(submit)).context).toEqual([CLEAN_CONTEXT])
  })

  test('a precompute or a subagent compaction does not force the line', async ($, on) => {
    world(on)
    await $.prompt.submit(submit)
    await $.session.compact({ trigger: 'precompute', messages: HISTORY })
    await $.session.compact({ trigger: 'auto', agentId: 'a1', messages: HISTORY })
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
  })
})

describe('refreshing tools', () => {
  /** Calls one tool through a refusing tool beneath and counts the git runs that follow. */
  const runsAfter = async (on: On, call: () => Promise<unknown>): Promise<number> => {
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    on('tool.call', { tool: /^(Edit|Write|NotebookEdit|PowerShell)$/ }, () => ({ deny: 'beneath' }))
    await call()
    await clock.settle()
    return seen.runs.length
  }

  test('Edit refreshes', async ($, on) => {
    const call = () => $.tool.call({ tool: 'Edit', file_path: '/repo/a.py', old_string: 'a', new_string: 'b' })
    expect(await runsAfter(on, call)).toBe(1)
  })

  test('Write refreshes', async ($, on) => {
    expect(await runsAfter(on, () => $.tool.call({ tool: 'Write', file_path: '/repo/a.py', content: 'x' }))).toBe(1)
  })

  test('NotebookEdit refreshes', async ($, on) => {
    const call = () => $.tool.call({ tool: 'NotebookEdit', notebook_path: '/repo/a.ipynb', new_source: 'x' })
    expect(await runsAfter(on, call)).toBe(1)
  })

  test('PowerShell refreshes', async ($, on) => {
    expect(await runsAfter(on, () => $.tool.call({ tool: 'PowerShell', command: 'git add -A' }))).toBe(1)
  })
})

describe('runs while git is in flight', () => {
  test('a tool call during a run is owed one more run after the gap', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const gate = deferred()
    const seen = world(on, { gate: gate.promise })
    bashTool(on)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    gate.release()
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    await clock.advance(MIN_GAP_MS)
    expect(seen.runs.length).toBe(2)
  })

  test('a prompt waits for a background run in flight instead of running git beside it', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const gate = deferred()
    const w: World = { gate: gate.promise }
    const seen = world(on, w)
    bashTool(on)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    const pending = $.prompt.submit(submit)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    w.gate = undefined
    w.git = { stdout: `${CLEAN}\n? new.py` }
    gate.release()
    const out = await pending
    expect(seen.runs.length).toBe(2)
    expect(out.context?.[0]?.endsWith('UNTRACKED=1 DIRTY=true')).toBe(true)
    expect(lastStatus(seen)).toBe('⎇ dev · ?1 -- commits(R,L):0,0')
  })
})

describe('a refused pacing wait', () => {
  test('does not stop later background refreshes', async ($, on) => {
    // above the mocked clock; the paced wait is exactly the gap, as that clock stands still between calls
    on('clock.after', { ms: MIN_GAP_MS }, () => ({ deny: 'no timer' }))
    on('clock.sleep', { ms: MIN_GAP_MS }, () => ({ deny: 'no timer' }))
    const clock = mock.clock(on, { now: NOW_MS })
    const seen = world(on)
    bashTool(on)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    await $.tool.call(bash)
    await clock.settle()
    await clock.advance(MIN_GAP_MS * 2)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(2)
  })
})

describe('round 3: the prompt hook within its budget', () => {
  test('a background run stuck past TAIL_WAIT_MS does not hold the prompt: it runs its own git', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const gate = deferred()
    const w: World = { gate: gate.promise }
    const seen = world(on, w)
    bashTool(on)
    await $.tool.call(bash)
    await clock.settle()
    expect(seen.runs.length).toBe(1)
    // the background run stays held; the prompt's own run answers at once
    w.gate = undefined
    w.git = { stdout: `${CLEAN}\n? new.py` }
    const pending = $.prompt.submit(submit)
    await clock.advance(TAIL_WAIT_MS)
    const out = await pending
    expect(seen.runs.length).toBe(2)
    expect(out.context?.[0]?.endsWith('UNTRACKED=1 DIRTY=true')).toBe(true)
    gate.release()
    await clock.settle()
  })

  test('a prompt that did not enter records nothing; the next one still gets the forced line', async ($, on) => {
    let isDropping = true
    const writes: unknown[] = []
    on('state.set', (_$, e, next) => {
      if (e.plugin === 'git-status' && e.key === 'lastContext') writes.push(e.value)
      return next(e)
    })
    world(on, { isDropping: () => isDropping })
    lastContextState(on, CLEAN_CONTEXT)
    const dropped = await $.prompt.submit(submit)
    expect('drop' in dropped && dropped.drop).toBe('held')
    expect(writes).toEqual([])
    isDropping = false
    const entered = await $.prompt.submit(submit)
    expect(entered.context).toEqual([CLEAN_CONTEXT])
    // the stubbed state answers one fixed version, so the write may be retried: count only its value
    expect(writes.length).toBeGreaterThan(0)
    expect(new Set(writes)).toEqual(new Set([CLEAN_CONTEXT]))
  })
})

// ---------------------------------------------------------------------------
// Fallback: the mod's line gives way to a ccstatusline status line

describe('delegateExecutable', () => {
  test('a statusLine command naming ccstatusline yields its executable', async () => {
    const line = { type: 'command', command: 'ccstatusline --config C:/repo/.claude/ccstatusline.json' }
    expect(delegateExecutable(line)).toBe('ccstatusline')
    expect(delegateExecutable({ command: 'npx -y ccstatusline@latest' })).toBe('npx')
    expect(delegateExecutable({ command: '"C:/Program Files/npm/ccstatusline.cmd" --config x' })).toBe(
      'C:/Program Files/npm/ccstatusline.cmd',
    )
  })

  test('anything else yields nothing', async () => {
    expect(delegateExecutable(undefined)).toBeUndefined()
    expect(delegateExecutable('ccstatusline')).toBeUndefined()
    expect(delegateExecutable({ command: 'bash ~/.claude/statusline.sh' })).toBeUndefined()
    expect(delegateExecutable({ command: 42 })).toBeUndefined()
    expect(delegateExecutable({ command: 'mystatusline-ccstatuslinex' })).toBeUndefined()
  })
})

describe('executableCandidates', () => {
  test('a bare name is looked up under every PATH folder, with the Windows launcher suffixes', async () => {
    expect(executableCandidates('ccstatusline', 'C:\\npm\\;C:\\bin')).toEqual([
      'C:/npm/ccstatusline', 'C:/npm/ccstatusline.cmd', 'C:/npm/ccstatusline.exe',
      'C:/bin/ccstatusline', 'C:/bin/ccstatusline.cmd', 'C:/bin/ccstatusline.exe',
    ])
    expect(executableCandidates('ccstatusline', '/usr/bin:/opt/x/')).toEqual([
      '/usr/bin/ccstatusline', '/usr/bin/ccstatusline.cmd', '/usr/bin/ccstatusline.exe',
      '/opt/x/ccstatusline', '/opt/x/ccstatusline.cmd', '/opt/x/ccstatusline.exe',
    ])
  })

  test('a single Windows folder is not split at its drive colon', async () => {
    expect(executableCandidates('npx', 'C:\\nodejs')).toEqual(['C:/nodejs/npx', 'C:/nodejs/npx.cmd', 'C:/nodejs/npx.exe'])
  })

  test('a path is taken as given; no PATH means no candidates', async () => {
    expect(executableCandidates('C:/npm/ccstatusline.cmd', '/usr/bin')).toEqual([
      'C:/npm/ccstatusline.cmd', 'C:/npm/ccstatusline.cmd.cmd', 'C:/npm/ccstatusline.cmd.exe',
    ])
    expect(executableCandidates('ccstatusline', undefined)).toEqual([])
  })
})

const CC_LINE = { statusLine: { type: 'command', command: 'ccstatusline --config /repo/.claude/ccstatusline.json' } }
const NPM_DIR = '/home/dev/.npm-global/bin'

describe('the mod line gives way to ccstatusline', () => {
  test('ccstatusline configured and found: the line is cleared, the context still attached', async ($, on) => {
    const seen = world(on, {
      env: { CLAUDE_PROJECT_DIR: ROOT, PATH: `/usr/bin:${NPM_DIR}` },
      settings: CC_LINE,
      files: [`${NPM_DIR}/ccstatusline`],
    })
    const out = await $.prompt.submit(submit)
    expect(out.context).toEqual([CLEAN_CONTEXT])
    expect(seen.statuses).toEqual([undefined])
  })

  test('ccstatusline configured but not installed: the mod draws its own line', async ($, on) => {
    const seen = world(on, { env: { CLAUDE_PROJECT_DIR: ROOT, PATH: '/usr/bin' }, settings: CC_LINE })
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBe('⎇ dev · clean -- commits(R,L):0,0')
  })

  test('another status line command: the mod draws, and probes nothing', async ($, on) => {
    const settings = { statusLine: { type: 'command', command: 'bash ~/.claude/statusline.sh' } }
    const seen = world(on, { env: { CLAUDE_PROJECT_DIR: ROOT, PATH: '/usr/bin' }, settings })
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBe('⎇ dev · clean -- commits(R,L):0,0')
    expect(seen.probes).toEqual([])
  })

  test('a settings read that rejects keeps the mod line', async ($, on) => {
    const seen = world(on, { settings: 'throw' })
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBe('⎇ dev · clean -- commits(R,L):0,0')
  })

  test('the lookup is kept: a second refresh probes nothing new', async ($, on) => {
    const seen = world(on, {
      env: { CLAUDE_PROJECT_DIR: ROOT, PATH: NPM_DIR },
      settings: CC_LINE,
      files: [`${NPM_DIR}/ccstatusline`],
    })
    await $.prompt.submit(submit)
    const probed = seen.probes.length
    await $.prompt.submit(submit)
    expect(probed).toBeGreaterThan(0)
    expect(seen.probes.length).toBe(probed)
    expect(seen.statuses).toEqual([undefined, undefined])
  })

  test('removing ccstatusline from the settings brings the line back', async ($, on) => {
    const w: World = {
      env: { CLAUDE_PROJECT_DIR: ROOT, PATH: NPM_DIR },
      settings: CC_LINE,
      files: [`${NPM_DIR}/ccstatusline`],
    }
    const seen = world(on, w)
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBeUndefined()
    w.settings = {}
    await $.prompt.submit(submit)
    expect(lastStatus(seen)).toBe('⎇ dev · clean -- commits(R,L):0,0')
  })
})

