import type {
  EngineInterface,
  Register,
  SessionCompactInput,
  SessionCompactResult,
  SessionMessage,
} from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { Bookmark } from '../types'
import { notesFileOf, parseNotes, stateDirOf } from './notes'

/**
 * Compaction bookmark kept in `$.state` instead of a bookmark file.
 *
 * Stands in for file-based `PreCompact` and `SessionStart` compact|resume bookmark hooks. The bookmark
 * is written to `$.state`, which outlives compaction and
 * module reloads, and is appended to the compacted conversation as its last message, so the model reads it
 * on the very next request, mid-turn auto-compactions included, and a resumed transcript carries it.
 * Every failure path degrades to the compaction as core answered it; the hook never throws past `next`.
 */

type Dollar = EngineInterface

const bookmarkState = atom({ plugin: 'session-bookmark', key: 'bookmark' } as const, null)

/** Opening line of every bookmark message; also how a later compaction recognises one. */
export const BOOKMARK_HEADER = 'POST-COMPACT BOOKMARK (session-bookmark)'
/** Longest stored prompt or instruction text, in characters. */
export const MAX_MESSAGE_CHARS = 2000
/** Most porcelain status entries kept; the rest are counted, not listed. */
export const MAX_STATUS_LINES = 40
/** The `/session-bookmark` reply when this session's state holds no bookmark. */
export const NO_BOOKMARK_TEXT =
  "No compaction bookmark in this session's state. A resumed session's transcript may still carry one."
const MESSAGE_COUNT = 3
const GIT_TIMEOUT_MS = 5000
const COMMAND = 'session-bookmark'
/** Triggers that install a compaction (precompute installs nothing). */
const INSTALLING = { trigger: ['manual', 'auto', 'plugin'] } as const

const RESUME_HINT =
  'The content below is the authoritative resume point. Read the LAST user message recorded here and ' +
  'continue from there, not from tool-result replays rehydrated above it. Run `git status` and ' +
  '`git log -3` before acting: commits may have landed during compaction.'

// ---------------------------------------------------------------------------
// Pure

/**
 * Whether a message counts as a prompt: a user message with text, no tool results, not a bookmark. A
 * previous compaction's summary is a user message too, so it counts.
 */
const isPrompt = (m: SessionMessage): boolean =>
  m.role === 'user' &&
  (m.toolResults ?? []).length === 0 &&
  m.text.trim() !== '' &&
  !m.text.startsWith(BOOKMARK_HEADER)

/** The last `n` prompts (an earlier summary included), newest last. */
export const lastUserTexts = (messages: readonly SessionMessage[], n = MESSAGE_COUNT): string[] =>
  messages.filter(isPrompt).slice(-n).map(m => m.text.trim())

/** Cuts text past MAX_MESSAGE_CHARS, keeping the start. */
const truncate = (text: string): string =>
  text.length <= MAX_MESSAGE_CHARS ? text : `${text.slice(0, MAX_MESSAGE_CHARS)}\n...(truncated)`

/** Keeps the first MAX_STATUS_LINES porcelain entries and counts the rest. */
const capStatus = (status: string): string => {
  const lines = status.split('\n')
  if (lines.length <= MAX_STATUS_LINES) return status
  const rest = lines.length - MAX_STATUS_LINES
  return [...lines.slice(0, MAX_STATUS_LINES), `... (${rest} more entries)`].join('\n')
}

/** A fenced block; four backticks so a prompt holding a triple fence stays inside. */
const fence = (body: string): string[] => ['````', body, '````', '']

/** The prompt section's lines. */
const messageLines = (messages: readonly string[]): string[] => {
  if (messages.length === 0) return ['(no user messages recovered)', '']
  return messages.flatMap((m, i) => [`### Message ${i + 1}`, '', ...fence(truncate(m))])
}

/** The session notes' lines: one numbered line per note. */
const noteLines = (notes: readonly string[]): string[] => [
  '## Session Notes',
  '',
  ...notes.map((n, i) => `${i + 1}. ${n}`),
  '',
]

/** The bookmark as the message the model reads after the compaction. */
export const formatBookmark = (b: Bookmark): string => {
  const lines = [
    `${BOOKMARK_HEADER}. ${RESUME_HINT}`,
    '',
    `- Saved: ${new Date(b.savedAt).toISOString()}`,
    `- Trigger: ${b.trigger}`,
    `- Branch: ${b.branch === null ? '(unknown)' : `\`${b.branch}\``}`,
    `- Root: ${b.root === null ? '(unknown)' : `\`${b.root}\``}`,
    '',
    '## Recent Commits',
    '',
    ...fence(b.log ?? '(git unavailable)'),
    '## Working Tree (git status --porcelain)',
    '',
    ...fence(b.status === null ? '(git unavailable)' : b.status || '(clean)'),
    '## Last User Messages (verbatim, newest last)',
    '',
    ...messageLines(b.lastMessages),
  ]
  const notes = b.notes ?? []
  if (notes.length > 0) lines.push(...noteLines(notes))
  if (b.instructions !== null) lines.push('## Compaction Instructions', '', ...fence(truncate(b.instructions)))
  return lines.join('\n').trimEnd()
}

// ---------------------------------------------------------------------------
// Host access (kept in this file: `$` is not passed across an import)

/**
 * Folders to read git from, in order: the session cwd (a worktree the session moved into), then
 * CLAUDE_PROJECT_DIR; blanks and repeats dropped. Never throws.
 */
const rootCandidates = async ($: Dollar): Promise<string[]> => {
  const cwd = await $.session.cwd().catch(() => undefined)
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(() => undefined)
  const named = [cwd, env].filter((p): p is string => p !== undefined && p.trim() !== '')
  return [...new Set(named)]
}

/** Stdout of one git command, trailing whitespace cut; null on any failure. */
const gitText = async ($: Dollar, root: string, args: string[]): Promise<string | null> => {
  const ran = await $.process
    .run(['git', '-C', root, ...args], { timeoutMs: GIT_TIMEOUT_MS, env: { GIT_OPTIONAL_LOCKS: '0' } })
    .catch(() => undefined)
  // trimEnd: a porcelain line's leading space is its index column (" M a.py")
  return ran === undefined || ran.exitCode !== 0 ? null : ran.stdout.trimEnd()
}

type GitFields = Pick<Bookmark, 'root' | 'branch' | 'log' | 'status'>

const NO_GIT: GitFields = { root: null, branch: null, log: null, status: null }

/** What git answered, and the repository's top level (where the project's notes live); null without a repository. */
type GitCapture = { git: GitFields; top: string | null }

/** The checked-out branch; in a repository with no commits, HEAD's symbolic name. Null when neither answers. */
const gitBranch = async ($: Dollar, root: string): Promise<string | null> =>
  (await gitText($, root, ['rev-parse', '--abbrev-ref', 'HEAD'])) ??
  (await gitText($, root, ['symbolic-ref', '--short', 'HEAD']))

/**
 * Branch, recent commits and capped porcelain status from the first candidate that is a repository; all
 * null when none is. Never throws.
 */
const captureGit = async ($: Dollar): Promise<GitCapture> => {
  for (const root of await rootCandidates($)) {
    const top = await gitText($, root, ['rev-parse', '--show-toplevel'])
    if (top === null) continue
    const [branch, log, status] = await Promise.all([
      gitBranch($, root),
      gitText($, root, ['log', '--oneline', '-5']),
      gitText($, root, ['status', '--porcelain']),
    ])
    return { git: { root, branch, log, status: status === null ? null : capStatus(status) }, top }
  }
  return { git: NO_GIT, top: null }
}

/** The notes of the first root that holds a notes file: `<state_dir>/session-bookmark/notes.json`. Never throws. */
const captureNotes = async ($: Dollar, top: string | null): Promise<string[]> => {
  try {
    for (const root of top === null ? await rootCandidates($) : [top]) {
      const config = await $.fs.read(`${root.replace(/\\/g, '/')}/.claude/harness.json`).catch(() => undefined)
      const text = await $.fs.read(notesFileOf(root, stateDirOf(config))).catch(() => undefined)
      if (typeof text === 'string') return parseNotes(text)
    }
  } catch {
    // a notes failure leaves the bookmark without notes
  }
  return []
}

type Capture = { git: GitFields; notes: string[] }

/** Git state and session notes, read before the compaction answers. Never throws. */
const capture = async ($: Dollar): Promise<Capture> => {
  const { git, top } = await captureGit($)
  return { git, notes: await captureNotes($, top) }
}

/** Builds and stores the bookmark, and returns the result with the bookmark message appended. */
const bookmarkResult = async (
  $: Dollar,
  e: SessionCompactInput,
  trigger: Bookmark['trigger'],
  { git, notes }: Capture,
  result: SessionCompactResult & { skip?: undefined },
): Promise<SessionCompactResult> => {
  const b: Bookmark = {
    savedAt: await $.clock.now(),
    trigger,
    ...git,
    lastMessages: lastUserTexts(e.messages),
    notes,
    instructions: e.instructions?.trim() || null,
  }
  await update($, bookmarkState, () => b).catch(() => undefined)
  const message: SessionMessage = { role: 'user', text: formatBookmark(b), toolUses: [] }
  return { ...result, messages: [...result.messages, message] }
}

// ---------------------------------------------------------------------------
// Registration

/** Registers the compaction bookmark and the `/session-bookmark` command. */
export const registerBookmark = (on: Parameters<Register>[0]): void => {
  on('session.compact', INSTALLING, async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    // git and the notes overlap the summarizer; when core reuses a precomputed summary, git's own timeouts are the wait
    const captured = capture($)
    const result = await next(e)
    if (result.skip !== undefined) return result
    try {
      return await bookmarkResult($, e, e.trigger, await captured, result)
    } catch {
      return result
    }
  })

  on('session.start', async ($, e, next) => {
    await $.command
      .register({ name: COMMAND, description: 'Show the compaction bookmark saved in this session' })
      .catch(() => undefined)
    return next(e)
  })

  on('command.run', { command: COMMAND }, async $ => {
    const b = await read($, bookmarkState)
    return { text: b === null ? NO_BOOKMARK_TEXT : formatBookmark(b) }
  }).catch(() => ({ text: 'session-bookmark: bookmark state unavailable.' }))
}
