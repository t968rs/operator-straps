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
  NOTES_ARG,
  NOTES_STALE_HINT,
  NOTES_UNREADABLE_TEXT,
  NOTES_USAGE,
} from './bookmark'
import type { StoredNote } from './notes'
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

const NOTES_FILE = `${ROOT}/${DEFAULT_STATE_DIR}/${NOTES_PATH}`

/** A notes file of standing notes; `branches` gives the note at the same index a branch. */
const notesJson = (texts: string[], branches: (string | undefined)[] = []): string => {
  const notes = texts.map((text, i) => {
    const branch = branches[i]
    return branch === undefined ? { added: '2026-10-22T00:00:00Z', text } : { added: '2026-10-22T00:00:00Z', branch, text }
  })
  return JSON.stringify({ version: NOTES_SCHEMA_VERSION, notes })
}

const standing = (text: string): StoredNote => ({ text, branch: null })

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
  /** The top level `rev-parse --show-toplevel` prints for a folder; a folder not listed is its own. */
  tops?: Record<string, string>
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
  /** What `rev-parse --abbrev-ref HEAD` prints; `HEAD` on a detached HEAD. Defaults to GIT_OUT's. */
  branch?: string
  /** Read at each prompt: a set reason makes core drop the prompt with it. */
  promptDrop?: { reason?: string }
}
type Seen = {
  reads: string[]
  runs: (readonly string[])[]
  inits: (ProcessRunInit | undefined)[]
  state: Map<string, unknown>
  commands: string[]
  descriptions: string[]
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
  if (args === 'rev-parse --show-toplevel') return ran(`${w.tops?.[root] ?? root}\n`)
  if (w.unborn && (args === 'rev-parse --abbrev-ref HEAD' || args.startsWith('log'))) return ran('', 128)
  if (args === 'rev-parse --abbrev-ref HEAD' && w.branch !== undefined) return ran(`${w.branch}\n`)
  if (args === 'status --porcelain' && w.status !== undefined) return ran(w.status)
  return ran(GIT_OUT[args] ?? '')
}

/** Answers env, cwd, git, state writes and core's compaction from memory. */
const world = (on: On, w: World = {}): Seen => {
  const seen: Seen = { reads: [], runs: [], inits: [], state: new Map(), commands: [], descriptions: [] }
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
    seen.descriptions.push(e.description)
    return { value: { command: e.name } }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('prompt.submit', (_$, e) =>
    w.promptDrop?.reason !== undefined ? { drop: w.promptDrop.reason } : { text: e.text, context: e.context },
  )
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
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

const runCommand = async ($: Engine, command: string, args = ''): Promise<string> => {
  const r = await $.command.run({
    command,
    args,
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 100 },
  })
  return r.text ?? ''
}

/** A prompt from the composer; answers the context it entered with. */
const promptContext = async ($: Engine): Promise<readonly string[]> => {
  const out = await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'composer' } })
  return 'context' in out ? (out.context ?? []) : []
}

/** A row reaching `session.append`: the main loop's unless `agentId`, by the compaction door unless `door`. */
const appendRow = ($: Engine, agentId?: string, door: 'compaction' | 'note' = 'compaction') =>
  $.session.append({
    message: { type: 'user', role: 'user', content: [{ type: 'text', text: 'summary' }] },
    door,
    origin: { kind: 'engine' },
    uuid: `u-${agentId ?? 'main'}-${door}`,
    ...(agentId === undefined ? {} : { agentId }),
  } as Parameters<Engine['session']['append']>[0])

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
    const notes = [standing('keep the API frozen'), standing('no new deps')]
    const text = formatBookmark(bookmark({ notes, instructions: 'focus on X' }))
    expect(text).toContain('## Session Notes')
    expect(text).toContain('1. keep the API frozen')
    expect(text).toContain('2. no new deps')
    expect(text.indexOf('## Last User Messages')).toBeLessThan(text.indexOf('## Session Notes'))
    expect(text.indexOf('## Session Notes')).toBeLessThan(text.indexOf('## Compaction Instructions'))
  })

  test('no notes, no notes section', async () => {
    expect(formatBookmark(bookmark())).not.toContain('Session Notes')
  })

  test('a note on the bookmark branch prints its branch and no hint', async () => {
    const text = formatBookmark(bookmark({ notes: [{ text: 'keep it', branch: 'dev' }, standing('always')] }))
    expect(text).toContain('1. [dev] keep it')
    expect(text).toContain('2. always')
    expect(text).not.toContain(NOTES_STALE_HINT)
  })

  test('a note from another branch is marked, with one hint line under the heading', async () => {
    const notes = [{ text: 'old work', branch: 'feature' }, { text: 'more old', branch: 'other' }]
    const text = formatBookmark(bookmark({ notes }))
    expect(text).toContain('1. [feature; now on dev] old work')
    expect(text).toContain('2. [other; now on dev] more old')
    expect(text).toContain(`## Session Notes\n\n${NOTES_STALE_HINT}\n\n1. `)
    expect(text.split(NOTES_STALE_HINT).length).toBe(2)
  })

  test('the hint says the note is confirmed with the developer, never dropped silently', async () => {
    expect(NOTES_STALE_HINT).toContain('another branch')
    expect(NOTES_STALE_HINT).toContain('developer')
    expect(NOTES_STALE_HINT).toContain('never drop')
  })

  test('an unknown bookmark branch marks no note and prints no hint', async () => {
    const text = formatBookmark(bookmark({ branch: null, notes: [{ text: 'keep it', branch: 'feature' }] }))
    expect(text).toContain('1. [feature] keep it')
    expect(text).not.toContain(NOTES_STALE_HINT)
  })

  test('a bookmark an earlier load stored with string notes prints them as standing notes', async () => {
    const old = bookmark({ notes: ['keep the API frozen', 'no new deps'] as unknown as StoredNote[] })
    const text = formatBookmark(old)
    expect(text).toContain('1. keep the API frozen')
    expect(text).toContain('2. no new deps')
    expect(text).not.toContain(NOTES_STALE_HINT)
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
    const counts = out as { tokensBefore?: number; tokensAfter?: number }
    expect(counts.tokensBefore).toBe(90_000)
    expect(counts.tokensAfter).toBe(4_000)
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
    expect(saved(seen)?.notes).toEqual([standing('keep the API frozen'), standing('no new deps')])
    expect(lastText(out)).toContain('1. keep the API frozen')
    expect(lastText(out).indexOf('Session Notes')).toBeLessThan(lastText(out).indexOf('Compaction Instructions'))
  })

  test('branch-scoped notes are marked against the branch git reports', async ($, on) => {
    const files = { [NOTES_FILE]: notesJson(['here', 'there', 'always'], ['dev', 'feature']) }
    const seen = world(on, { files })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.notes).toEqual([{ text: 'here', branch: 'dev' }, { text: 'there', branch: 'feature' }, standing('always')])
    expect(lastText(out)).toContain('1. [dev] here')
    expect(lastText(out)).toContain('2. [feature; now on dev] there')
    expect(lastText(out)).toContain('3. always')
    expect(lastText(out)).toContain(NOTES_STALE_HINT)
  })

  test('on a detached HEAD no note is marked and no hint prints; the branch line still says HEAD', async ($, on) => {
    const seen = world(on, { branch: 'HEAD', files: { [NOTES_FILE]: notesJson(['x'], ['feature']) } })
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.branch).toBe('HEAD')
    expect(lastText(out)).toContain('- Branch: `HEAD`')
    expect(lastText(out)).toContain('1. [feature] x')
    expect(lastText(out)).not.toContain('now on')
    expect(lastText(out)).not.toContain(NOTES_STALE_HINT)
  })

  test('state_dir from the project harness.json locates the notes', async ($, on) => {
    const files = {
      [`${ROOT}/.claude/harness.json`]: JSON.stringify({ state_dir: 'var/state' }),
      [`${ROOT}/var/state/${NOTES_PATH}`]: notesJson(['from the configured dir']),
      [NOTES_FILE]: notesJson(['from the default dir']),
    }
    const seen = world(on, { files })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.notes).toEqual([standing('from the configured dir')])
  })

  test('notes are read from the git top level, so a worktree reads its own', async ($, on) => {
    const wt = '/wt/feature'
    const sub = `${wt}/sub`
    const files = {
      [`${wt}/${DEFAULT_STATE_DIR}/${NOTES_PATH}`]: notesJson(['wt note']),
      [NOTES_FILE]: notesJson(['root note']),
    }
    const seen = world(on, { cwd: sub, repos: [ROOT, sub], tops: { [sub]: wt }, files })
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(saved(seen)?.root).toBe(sub)
    expect(saved(seen)?.notes).toEqual([standing('wt note')])
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
    expect(saved(seen)?.notes).toEqual([standing('no git note')])
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
  test('session start registers the command, its description naming the notes argument', async ($, on) => {
    const seen = world(on)
    await $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
    expect(seen.commands).toContain('session-bookmark')
    expect(seen.descriptions.some(d => d.includes(NOTES_ARG))).toBe(true)
  })

  test('says so before any compaction, then shows the bookmark', async ($, on) => {
    world(on)
    expect(await runCommand($, 'session-bookmark')).toBe(NO_BOOKMARK_TEXT)
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    const text = await runCommand($, 'session-bookmark')
    expect(text.startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(text).toContain('fourth ask')
  })

  test('blank arguments print the saved bookmark as the bare command does', async ($, on) => {
    world(on)
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect((await runCommand($, 'session-bookmark', '   ')).startsWith(BOOKMARK_HEADER)).toBe(true)
  })
})

describe('/session-bookmark notes', () => {
  test('the argument is notes', async () => {
    expect(NOTES_ARG).toBe('notes')
  })

  test('reads the notes live and numbers them against the current branch', async ($, on) => {
    world(on, { files: { [NOTES_FILE]: notesJson(['always', 'here'], [undefined, 'dev']) } })
    expect(await runCommand($, 'session-bookmark', NOTES_ARG)).toBe('1. always\n2. [dev] here')
  })

  test('surrounding blanks around the argument are ignored', async ($, on) => {
    world(on, { files: { [NOTES_FILE]: notesJson(['always']) } })
    expect(await runCommand($, 'session-bookmark', `  ${NOTES_ARG} `)).toBe('1. always')
  })

  test('needs no compaction: no bookmark is read or stored', async ($, on) => {
    const seen = world(on, { files: { [NOTES_FILE]: notesJson(['always']) } })
    await runCommand($, 'session-bookmark', NOTES_ARG)
    expect(saved(seen)).toBeUndefined()
    expect(seen.reads.some(p => keyOf(p) === keyOf(NOTES_FILE))).toBe(true)
  })

  test('a note from another branch is marked, with the hint first', async ($, on) => {
    world(on, { files: { [NOTES_FILE]: notesJson(['old work', 'here'], ['feature', 'dev']) } })
    const text = await runCommand($, 'session-bookmark', NOTES_ARG)
    expect(text).toBe(`${NOTES_STALE_HINT}\n\n1. [feature; now on dev] old work\n2. [dev] here`)
  })

  test('on a detached HEAD no note is marked and no hint prints', async ($, on) => {
    world(on, { branch: 'HEAD', files: { [NOTES_FILE]: notesJson(['x'], ['feature']) } })
    expect(await runCommand($, 'session-bookmark', NOTES_ARG)).toBe('1. [feature] x')
  })

  const NONE: Array<[string, Record<string, string>]> = [
    ['no notes file', {}],
    ['an empty notes list', { [NOTES_FILE]: notesJson([]) }],
  ]
  for (const [name, files] of NONE) {
    test(`${name}: no notes`, async ($, on) => {
      world(on, { files })
      expect(await runCommand($, 'session-bookmark', NOTES_ARG)).toBe('no notes')
    })
  }

  const UNREADABLE: Array<[string, string]> = [
    ['not JSON', '{not json'],
    ['another version', '{"version":2,"notes":[{"text":"x"}]}'],
    ['no notes list', '{"version":1}'],
  ]
  for (const [name, text] of UNREADABLE) {
    test(`a notes file holding ${name} is reported unreadable, not empty`, async ($, on) => {
      world(on, { files: { [NOTES_FILE]: text } })
      expect(await runCommand($, 'session-bookmark', NOTES_ARG)).toBe(NOTES_UNREADABLE_TEXT)
      expect(NOTES_UNREADABLE_TEXT).toBe('notes file unreadable; /harness:add-bookmark --clear resets it')
    })
  }

  test('without git the notes are read from the root candidates, none marked', async ($, on) => {
    world(on, { git: 'missing', files: { [NOTES_FILE]: notesJson(['there'], ['feature']) } })
    expect(await runCommand($, 'session-bookmark', NOTES_ARG)).toBe('1. [feature] there')
  })

  test('any other argument prints the usage', async ($, on) => {
    world(on)
    expect(await runCommand($, 'session-bookmark', 'list')).toBe(NOTES_USAGE)
    expect(NOTES_USAGE).toBe('usage: /session-bookmark [notes]')
  })
})

describe('compaction fallback', () => {
  test('a compaction row the session.compact hook never saw puts the bookmark on the next prompt once', async ($, on) => {
    const seen = world(on, { files: { [NOTES_FILE]: notesJson(['here'], ['dev']) } })
    expect(await promptContext($)).toEqual([])
    await appendRow($)
    const context = await promptContext($)
    expect(context.length).toBe(1)
    expect(context[0]?.startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(context[0]).toContain('- Trigger: detected')
    expect(context[0]).toContain('- Branch: `dev`')
    expect(context[0]).toContain('(no user messages recovered)')
    expect(context[0]).toContain('1. [dev] here')
    expect(saved(seen)?.trigger).toBe('detected')
    expect(saved(seen)?.lastMessages).toEqual([])
    expect(saved(seen)?.instructions).toBeNull()
    expect(await promptContext($)).toEqual([])
  })

  test('the fallback bookmark is what /session-bookmark shows after', async ($, on) => {
    world(on)
    await promptContext($)
    await appendRow($)
    await promptContext($)
    expect(await runCommand($, 'session-bookmark')).toContain('- Trigger: detected')
  })

  test('a compaction the hook answered, then its row and a prompt, adds no context', async ($, on) => {
    world(on)
    await promptContext($)
    const out = await $.session.compact({ trigger: 'manual', messages: HISTORY })
    expect(lastText(out).startsWith(BOOKMARK_HEADER)).toBe(true)
    await appendRow($)
    expect(await promptContext($)).toEqual([])
  })

  test('the installed mark lasts one prompt: a later unseen compaction is still owed', async ($, on) => {
    world(on)
    await $.session.compact({ trigger: 'manual', messages: HISTORY })
    await appendRow($)
    expect(await promptContext($)).toEqual([])
    await appendRow($)
    expect((await promptContext($)).length).toBe(1)
  })

  test("a subagent's compaction row owes nothing", async ($, on) => {
    world(on)
    await promptContext($)
    await appendRow($, 'sub-1')
    expect(await promptContext($)).toEqual([])
  })

  test('a main-loop row through another door owes nothing', async ($, on) => {
    world(on)
    await promptContext($)
    await appendRow($, undefined, 'note')
    expect(await promptContext($)).toEqual([])
  })

  test('a slash-command submission leaves the bookmark owed; the next plain prompt carries it once', async ($, on) => {
    world(on)
    await promptContext($)
    await appendRow($)
    for (const name of ['compact', 'clear', 'session-bookmark']) {
      const out = await $.prompt.submit({
        text: `/${name}`, wait: false, origin: { kind: 'composer' }, command: { name, args: '' },
      } as Parameters<Engine['prompt']['submit']>[0])
      expect('context' in out ? (out.context ?? []) : []).toEqual([])
    }
    expect((await promptContext($)).length).toBe(1)
    expect(await promptContext($)).toEqual([])
  })

  test('a slash-command submission clears the installed mark: a later unseen compaction is owed', async ($, on) => {
    world(on)
    await promptContext($)
    await $.session.compact({ trigger: 'auto', messages: HISTORY })
    await appendRow($)
    await $.prompt.submit({
      text: '/compact', wait: false, origin: { kind: 'composer' }, command: { name: 'compact', args: '' },
    } as Parameters<Engine['prompt']['submit']>[0])
    await appendRow($)
    const context = await promptContext($)
    expect(context.length).toBe(1)
    expect(context[0]?.startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(await promptContext($)).toEqual([])
  })

  test('a dropped prompt leaves the bookmark owed; the next prompt carries it once', async ($, on) => {
    const promptDrop: { reason?: string } = {}
    world(on, { promptDrop })
    await promptContext($)
    await appendRow($)
    promptDrop.reason = 'held'
    const dropped = await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'composer' } })
    expect(dropped.drop).toBe('held')
    promptDrop.reason = undefined
    const context = await promptContext($)
    expect(context.length).toBe(1)
    expect(context[0]?.startsWith(BOOKMARK_HEADER)).toBe(true)
    expect(await promptContext($)).toEqual([])
  })

  for (const reason of ['clear', 'resume'] as const) {
    test(`an owed bookmark is forgotten when the session ends for ${reason}`, async ($, on) => {
      world(on)
      await promptContext($)
      await appendRow($)
      await $.session.end({ reason, sessionId: 's1', resume: { id: 's1' } } as Parameters<Engine['session']['end']>[0])
      expect(await promptContext($)).toEqual([])
    })
  }

  test('a failure building the fallback bookmark lets the prompt through unchanged', async ($, on) => {
    world(on, { clockFails: true })
    await promptContext($)
    await appendRow($)
    const out = await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'composer' } })
    expect('text' in out ? out.text : undefined).toBe('hello')
    expect('context' in out ? (out.context ?? []) : []).toEqual([])
  })
})
