import type { Engine } from 'claude-code/testing'
import type { On, ProcessRunInit, ProcessRunResult, SessionCompactResult, SessionMessage } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { Bookmark } from '../types'
import {
  BOOKMARK_HEADER,
  formatBookmark,
  lastUserTexts,
  MAX_MESSAGE_CHARS,
  MAX_STATUS_LINES,
  NO_BOOKMARK_TEXT,
} from './bookmark'
import { DEFAULT_STATE_DIR, NOTES_PATH, NOTES_SCHEMA_VERSION } from './notes'

const ROOT = '/repo'
const NOW_MS = 1_800_000_000_000
const SUMMARY: SessionMessage = { role: 'user', text: 'summary of the conversation', toolUses: [] }

const user = (text: string): SessionMessage => ({ role: 'user', text, toolUses: [] })
const assistant = (text: string): SessionMessage => ({ role: 'assistant', text, toolUses: [] })
const toolResult: SessionMessage = {
  role: 'user',
  text: '',
  toolUses: [],
  toolResults: [{ tool_use_id: 't1', text: 'ok', isError: false, result: 'ok' }],
} as unknown as SessionMessage

const HISTORY: SessionMessage[] = [
  user('first ask'),
  assistant('on it'),
  user('second ask'),
  toolResult,
  user('third ask'),
  assistant('done'),
  user('fourth ask'),
]

/**
 * A path as the mocked files key it: forward slashes, drive and host prefix dropped, lower case. On Windows the
 * engine resolves a drive-less path (`/repo`) onto the current drive, so a read arrives as `E:\repo\...`.
 */
const keyOf = (p: string): string =>
  p.replace(/\\/g, '/').replace(/^(?:[^]*?\/)?[A-Za-z]:(?=\/|$)/, '').toLowerCase()

const NOTES_FILE =`${ROOT}/${DEFAULT_STATE_DIR}/${NOTES_PATH}`

const notesJson = (texts: string[]): string =>
  JSON.stringify({ version: NOTES_SCHEMA_VERSION, notes: texts.map(text => ({ added: '2026-10-22T00:00:00Z', text })) })

const bookmark = (over: Partial<Bookmark> = {}): Bookmark => ({
  savedAt: NOW_MS,
  trigger: 'manual',
  root: ROOT,
  branch: 'dev',
  log: 'abc1234 Fix it',
  status: ' M a.py',
  lastMessages: ['do the thing'],
  notes: [],
  instructions: null,
  ...over,
})

// ---------------------------------------------------------------------------
// The world beneath the plugin

type Git = 'ok' | 'missing' | { exitCode: number }
type World = {
  git?: Git
  env?: Record<string, string>
  /** The session cwd; blank when unset. */
  cwd?: string
  /** Folders git answers in; others exit 128 (not a repository). Defaults to ROOT. */
  repos?: string[]
  skip?: string
  /** A repository with no commits yet: HEAD names no commit, so rev-parse HEAD and log fail. */
  unborn?: boolean
  /** Porcelain status git prints; defaults to GIT_OUT's. */
  status?: string
  /** Every bookmark state write is refused. */
  stateFails?: boolean
  /** The clock is refused, so building the bookmark throws. */
  clockFails?: boolean
  /** Extra fields core's compaction answers with. */
  core?: { tokensBefore?: number; tokensAfter?: number }
  /** Files `$.fs.read` answers with, by path; any other read is refused. */
  files?: Record<string, string>
}
type Seen = {
  reads: string[]
  runs: (readonly string[])[]
  inits: (ProcessRunInit | undefined)[]
  state: Map<string, unknown>
  commands: string[]
}

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

const GIT_OUT: Record<string, string> = {
  'rev-parse --show-toplevel': `${ROOT}\n`,
  'rev-parse --abbrev-ref HEAD': 'dev\n',
  'symbolic-ref --short HEAD': 'main\n',
  'status --porcelain': ' M a.py\n?? b.py\n',
  'log --oneline -5': 'abc1234 Fix it\ndef5678 Add it\n',
}

/** Git's answer to one command in a folder it treats as a repository. */
const gitAnswer = (w: World, root: string, args: string): ProcessRunResult => {
  if (args === 'rev-parse --show-toplevel') return ran(`${root}\n`)
  if (w.unborn && (args === 'rev-parse --abbrev-ref HEAD' || args.startsWith('log'))) return ran('', 128)
  if (args === 'status --porcelain' && w.status !== undefined) return ran(w.status)
  return ran(GIT_OUT[args] ?? '')
}

/** Answers env, cwd, git, state writes and core's compaction from memory. */
const world = (on: On, w: World = {}): Seen => {
  const seen: Seen = { reads: [], runs: [], inits: [], state: new Map(), commands: [] }
  mock.env(on, w.env ?? { CLAUDE_PROJECT_DIR: ROOT })
  const files = new Map(Object.entries(w.files ?? {}).map(([path, text]) => [keyOf(path), text]))
  on('fs.read', (_$, e) => {
    seen.reads.push(e.path)
    const text = files.get(keyOf(e.path))
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  if (w.clockFails) on('clock.now', () => ({ deny: 'no clock' }))
  else mock.clock(on, { now: NOW_MS })
  on('session.cwd', () => ({ value: w.cwd ?? '' }))
  on('state.set', (_$, e, next) => {
    if (e.plugin !== 'session-bookmark') return next(e)
    if (w.stateFails) return { deny: 'state store full' }
    seen.state.set(e.key, e.value)
    return next(e)
  })
  on('process.run', (_$, e) => {
    seen.runs.push(e.argv)
    seen.inits.push(e.init)
    const git = w.git ?? 'ok'
    if (git === 'missing') return { deny: 'spawn git ENOENT' }
    if (git !== 'ok') return { value: ran('', git.exitCode) }
    if (!(w.repos ?? [ROOT]).includes(e.argv[2] ?? '')) return { value: ran('', 128) }
    return { value: gitAnswer(w, e.argv[2] ?? '', e.argv.slice(3).join(' ')) }
  })
  on('command.register', (_$, e) => {
    seen.commands.push(e.name)
    return { value: { command: e.name } }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.compact', (): SessionCompactResult =>
    w.skip !== undefined ? { skip: w.skip } : { messages: [SUMMARY], ...w.core },
  )
  return seen
}

const saved = (seen: Seen): Bookmark | null | undefined => seen.state.get('bookmark') as Bookmark | null | undefined

const lastText = (r: SessionCompactResult): string => {
  const msgs = r.messages ?? []
  return msgs[msgs.length - 1]?.text ?? ''
}

const runCommand = async ($: Engine, command: string): Promise<string> => {
  const r = await $.command.run({
    command,
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 100 },
  })
  return r.text ?? ''
}

// ---------------------------------------------------------------------------
// Pure

describe('lastUserTexts', () => {
  test('the last three typed prompts, newest last; tool results and replies skipped', async () => {
    expect(lastUserTexts(HISTORY)).toEqual(['second ask', 'third ask', 'fourth ask'])
  })

  test('blank prompts and earlier bookmarks are not prompts', async () => {
    const msgs = [user('real'), user('   '), user(`${BOOKMARK_HEADER}\n\nold bookmark`)]
    expect(lastUserTexts(msgs)).toEqual(['real'])
  })

  test('fewer than n prompts returns what there is', async () => {
    expect(lastUserTexts([user('only')], 3)).toEqual(['only'])
    expect(lastUserTexts([])).toEqual([])
  })
})

describe('formatBookmark', () => {
  test('opens with the header and carries branch, commits, tree and prompts', async () => {
    const text = formatBookmark(bookmark())
    expect(text.startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(text).toContain('- Branch: `dev`')
    expect(text).toContain('- Root: `/repo`')
    expect(text).toContain(`- Saved: ${new Date(NOW_MS).toISOString()}`)
    expect(text).toContain('- Trigger: manual')
    expect(text).toContain('abc1234 Fix it')
    expect(text).toContain(' M a.py')
    expect(text).toContain('do the thing')
    expect(text).not.toContain('Compaction Instructions')
  })

  test('unknown git fields and an empty prompt list read as such', async () => {
    const text = formatBookmark(bookmark({ branch: null, log: null, status: '', lastMessages: [] }))
    expect(text).toContain('- Branch: (unknown)')
    expect(text).toContain('(git unavailable)')
    expect(text).toContain('(clean)')
    expect(text).toContain('(no user messages recovered)')
  })

  test('instructions get their own section', async () => {
    expect(formatBookmark(bookmark({ instructions: 'keep the plan' }))).toContain('keep the plan')
  })

  test('session notes are listed before the compaction instructions', async () => {
    const text = formatBookmark(bookmark({ notes: ['keep the API frozen', 'no new deps'], instructions: 'focus on X' }))
    expect(text).toContain('## Session Notes')
    expect(text).toContain('1. keep the API frozen')
    expect(text).toContain('2. no new deps')
    expect(text.indexOf('## Last User Messages')).toBeLessThan(text.indexOf('## Session Notes'))
    expect(text.indexOf('## Session Notes')).toBeLessThan(text.indexOf('## Compaction Instructions'))
  })

  test('no notes, no notes section', async () => {
    expect(formatBookmark(bookmark())).not.toContain('Session Notes')
  })

  test('long instructions are cut at MAX_MESSAGE_CHARS', async () => {
    const text = formatBookmark(bookmark({ instructions: 'y'.repeat(MAX_MESSAGE_CHARS + 10) }))
    expect(text).toContain(`${'y'.repeat(MAX_MESSAGE_CHARS)}\n...(truncated)`)
    expect(text).not.toContain('y'.repeat(MAX_MESSAGE_CHARS + 1))
  })

  test('a long prompt is cut at MAX_MESSAGE_CHARS', async () => {
    const text = formatBookmark(bookmark({ lastMessages: ['x'.repeat(MAX_MESSAGE_CHARS + 50)] }))
    expect(text).toContain(`${'x'.repeat(MAX_MESSAGE_CHARS)}\n...(truncated)`)
    expect(text).not.toContain('x'.repeat(MAX_MESSAGE_CHARS + 1))
  })
})

// ---------------------------------------------------------------------------
// Hooks

describe('session.compact bookmark', () => {
  test('a manual compaction stores the bookmark in state', async ($, on) => {
    const seen = world(on)
    await $.session.compact({ trigger: 'manual', messages: HISTORY, instructions: 'focus on X' })
    expect(saved(seen)).toEqual({
      savedAt: NOW_MS,
      trigger: 'manual',
      root: ROOT,
      branch: 'dev',
      log: 'abc1234 Fix it\ndef5678 Add it',
      status: ' M a.py\n?? b.py',
      lastMessages: ['second ask', 'third ask', 'fourth ask'],
      notes: [],
      instructions: 'focus on X',
    })
  })

  test('the compacted conversation ends with the bookmark message', async ($, on) => {
    world(on)
    const out = await $.session.compact({ trigger: 'auto', messages: HISTORY })
    expect(out.messages?.length).toBe(2)
    expect(out.messages?.[0]).toEqual(SUMMARY)
    expect(out.messages?.[1]?.role).toBe('user')
    expect(lastText(out).startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(lastText(out)).toContain('fourth ask')
  })

  test('git runs against the root with optional locks off and a 5 s timeout', async ($, on) => {
    const seen = world(on)
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    const commands = seen.runs.map(r => r.join(' ')).sort()
    expect(commands).toEqual([
      `git -C ${ROOT} log --oneline -5`,
      `git -C ${ROOT} rev-parse --abbrev-ref HEAD`,
      `git -C ${ROOT} rev-parse --show-toplevel`,
      `git -C ${ROOT} status --porcelain`,
    ])
    expect(seen.inits.every(i => i?.env?.GIT_OPTIONAL_LOCKS === '0' && i.timeoutMs === 5000)).toBe(true)
  })

  test('a plugin compaction installs a bookmark too', async ($, on) => {
    const seen = world(on)
    const out = await $.session.compact({ trigger: 'plugin', messages: HISTORY })
    expect(saved(seen)?.trigger).toBe('plugin')
    expect(lastText(out).startsWith(BOOKMARK_HEADER)).toBe(true)
  })

  test('blank compaction instructions are stored as null', async ($, on) => {
    const seen = world(on)
    await $.session.compact({ trigger: 'manual', messages: HISTORY, instructions: '   ' })
    expect(saved(seen)?.instructions).toBeNull()
  })

  test("core's token counts pass through beside the appended bookmark", async ($, on) => {
    world(on, { core: { tokensBefore: 90_000, tokensAfter: 4_000 } })
    const out = await $.session.compact({ trigger: 'auto', messages: HISTORY })
    expect(out.tokensBefore).toBe(90_000)
    expect(out.tokensAfter).toBe(4_000)
    expect(lastText(out).startsWith(BOOKMARK_HEADER)).toBe(true)
  })

  test('a refused state write still appends the bookmark message', async ($, on) => {
    const seen = world(on, { stateFails: true })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)).toBeUndefined()
    expect(lastText(out).startsWith(BOOKMARK_HEADER)).toBe(true)
  })

  test("a failure building the bookmark returns core's compaction unchanged", async ($, on) => {
    world(on, { clockFails: true })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(out.messages).toEqual([SUMMARY])
  })

  test(`a long status keeps its first ${MAX_STATUS_LINES} entries and counts the rest`, async ($, on) => {
    const lines = Array.from({ length: MAX_STATUS_LINES + 60 }, (_, i) => ` M f${i}.py`)
    const seen = world(on, { status: `${lines.join('\n')}\n` })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    const status = saved(seen)?.status ?? ''
    expect(status.split('\n')).toEqual([...lines.slice(0, MAX_STATUS_LINES), '... (60 more entries)'])
    expect(lastText(out)).not.toContain(` M f${MAX_STATUS_LINES}.py`)
  })

  test('a status at the cap is kept whole', async ($, on) => {
    const lines = Array.from({ length: MAX_STATUS_LINES }, (_, i) => ` M f${i}.py`)
    const seen = world(on, { status: `${lines.join('\n')}\n` })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.status).toBe(lines.join('\n'))
  })

  test('a repository with no commits keeps its root, branch and status', async ($, on) => {
    const seen = world(on, { unborn: true })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.root).toBe(ROOT)
    expect(saved(seen)?.branch).toBe('main')
    expect(saved(seen)?.log).toBeNull()
    expect(saved(seen)?.status).toBe(' M a.py\n?? b.py')
  })

  test('a precompute is passed through: no state, no message', async ($, on) => {
    const seen = world(on)
    const out = await $.session.compact({ trigger: 'precompute', messages: HISTORY })
    expect(out.messages).toEqual([SUMMARY])
    expect(saved(seen)).toBeUndefined()
    expect(seen.runs).toEqual([])
  })

  test('a subagent compaction is passed through', async ($, on) => {
    const seen = world(on)
    const out = await $.session.compact({ trigger: 'auto', agentId: 'a1', messages: HISTORY })
    expect(out.messages).toEqual([SUMMARY])
    expect(saved(seen)).toBeUndefined()
  })

  test('a skipped compaction stores nothing and stays skipped', async ($, on) => {
    const seen = world(on, { skip: 'blocked' })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(out.skip).toBe('blocked')
    expect(saved(seen)).toBeUndefined()
  })

  test('git missing still saves the bookmark, with null git fields', async ($, on) => {
    const seen = world(on, { git: 'missing' })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.branch).toBeNull()
    expect(saved(seen)?.log).toBeNull()
    expect(saved(seen)?.lastMessages).toEqual(['second ask', 'third ask', 'fourth ask'])
    expect(lastText(out).startsWith(BOOKMARK_HEADER)).toBe(true)
  })

  test('not a repository (exit 128) reads as unknown', async ($, on) => {
    const seen = world(on, { git: { exitCode: 128 } })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.branch).toBeNull()
    expect(saved(seen)?.root).toBeNull()
  })

  test('no cwd and no CLAUDE_PROJECT_DIR: no git run, bookmark still saved', async ($, on) => {
    const seen = world(on, { env: {} })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(seen.runs).toEqual([])
    expect(saved(seen)?.root).toBeNull()
  })

  test('a session cwd that is a repository wins (a worktree)', async ($, on) => {
    const wt = '/wt/feature'
    const seen = world(on, { cwd: wt, repos: [ROOT, wt] })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.root).toBe(wt)
    expect(seen.runs.every(r => r[2] === wt)).toBe(true)
  })

  test('a session cwd outside any repository falls back to CLAUDE_PROJECT_DIR', async ($, on) => {
    const seen = world(on, { cwd: '/tmp/scratch' })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.root).toBe(ROOT)
    expect(saved(seen)?.branch).toBe('dev')
  })

  test('without CLAUDE_PROJECT_DIR the session cwd alone is tried', async ($, on) => {
    const seen = world(on, { env: {}, cwd: ROOT })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.root).toBe(ROOT)
  })

  test('notes stored under the default state dir enter the bookmark', async ($, on) => {
    const seen = world(on, { files: { [NOTES_FILE]: notesJson(['keep the API frozen', 'no new deps']) } })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY, instructions: 'focus on X' })
    expect(saved(seen)?.notes).toEqual(['keep the API frozen', 'no new deps'])
    expect(lastText(out)).toContain('1. keep the API frozen')
    expect(lastText(out).indexOf('Session Notes')).toBeLessThan(lastText(out).indexOf('Compaction Instructions'))
  })

  test('state_dir from the project harness.json locates the notes', async ($, on) => {
    const files = {
      [`${ROOT}/.claude/harness.json`]: JSON.stringify({ state_dir: 'var/state' }),
      [`${ROOT}/var/state/${NOTES_PATH}`]: notesJson(['from the configured dir']),
      [NOTES_FILE]: notesJson(['from the default dir']),
    }
    const seen = world(on, { files })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.notes).toEqual(['from the configured dir'])
  })

  test('notes are read from the git top level, so a worktree reads its own', async ($, on) => {
    const wt = '/wt/feature'
    const seen = world(on, { cwd: wt, repos: [ROOT, wt], files: { [`${wt}/.claude/state/harness/${NOTES_PATH}`]: notesJson(['wt note']) } })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.notes).toEqual(['wt note'])
  })

  const NO_NOTES: Array<[string, Record<string, string>]> = [
    ['no notes file', {}],
    ['a malformed notes file', { [NOTES_FILE]: '{not json' }],
    ['a notes file of another version', { [NOTES_FILE]: '{"version":2,"notes":[{"text":"x"}]}' }],
  ]
  for (const [name, files] of NO_NOTES) {
    test(`${name}: the bookmark has no notes section`, async ($, on) => {
      const seen = world(on, { files })
      const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
      expect(saved(seen)?.notes).toEqual([])
      expect(lastText(out)).not.toContain('Session Notes')
    })
  }

  test('without git the notes are read from the root candidates', async ($, on) => {
    const seen = world(on, { git: 'missing', files: { [NOTES_FILE]: notesJson(['no git note']) } })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.notes).toEqual(['no git note'])
  })

  test('a precompute reads no notes', async ($, on) => {
    const seen = world(on, { files: { [NOTES_FILE]: notesJson(['x']) } })
    await $.session.compact({ trigger: 'precompute', messages: HISTORY })
    expect(seen.reads).toEqual([])
  })

  test('a second compaction skips the first bookmark; the summary can fill a prompt slot', async ($, on) => {
    const seen = world(on)
    const first = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    const after = [...(first.messages ?? []), user('fifth ask')]
    await $.session.compact({ trigger: 'manual', messages: after })
    expect(saved(seen)?.lastMessages).toEqual(['summary of the conversation', 'fifth ask'])
  })
})

describe('/session-bookmark', () => {
  test('session start registers the command', async ($, on) => {
    const seen = world(on)
    await $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
    expect(seen.commands).toContain('session-bookmark')
  })

  test('says so before any compaction, then shows the bookmark', async ($, on) => {
    world(on)
    expect(await runCommand($, 'session-bookmark')).toBe(NO_BOOKMARK_TEXT)
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    const text = await runCommand($, 'session-bookmark')
    expect(text.startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(text).toContain('fourth ask')
  })
})
