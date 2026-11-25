import type {
  EngineInterface,
  PromptSubmitInput,
  PromptSubmitResult,
  Register,
  SessionCompactInput,
  SessionCompactResult,
  SessionMessage,
} from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { Bookmark } from '../types'
import type { StoredNote } from './notes'
import {
  isOtherBranch,
  markingBranch,
  noteLine,
  notesFileOf,
  parseNotes,
  parseNotesOrNull,
  stateDirOf,
} from './notes'

/**
 * Compaction bookmark kept in `$.state` instead of a bookmark file.
 *
 * Stands in for file-based `PreCompact` and `SessionStart` compact|resume bookmark hooks. The bookmark
 * is written to `$.state`, which outlives compaction and
 * module reloads, and is appended to the compacted conversation as its last message, so the model reads it
 * on the very next request, mid-turn auto-compactions included, and a resumed transcript carries it.
 * Every failure path degrades to the compaction as core answered it; the hook never throws past `next`.
 *
 * When a main-loop compaction row reaches `session.append` while this mod's `session.compact` hook did not
 * append a bookmark (a mod before it ended the chain), the next prompt carries a `detected` bookmark as
 * context instead. Those hooks pass the event through on any failure.
 */

type Dollar = EngineInterface

const bookmarkState = atom({ plugin: 'session-bookmark', key: 'bookmark' } as const, null)

/**
 * Per-load bookkeeping of the main loop's compactions (a reload starts afresh). `installed`: this mod's
 * `session.compact` hook appended a bookmark since the last compaction row or prompt. `owed`: a compaction row reached
 * `session.append` with no bookmark installed, so the next prompt carries one.
 */
const compaction = { installed: false, owed: false }

/** Session-end reasons after which the same process goes on with a fresh conversation: nothing is owed. */
const FRESH_CONVERSATION = new Set<string>(['clear', 'resume'])

/** Clears the owed bookmark once the prompt entered with it and the dispatch did not move on. */
const recordDelivered = (text: string, result: PromptSubmitResult, signal: AbortSignal): void => {
  if (signal.aborted || result.drop !== undefined || !(result.context ?? []).includes(text)) return
  compaction.owed = false
}

/** The prompt as received, for a dispatch already abandoned: `next` is not called after that. */
const asReceived = (e: PromptSubmitInput): PromptSubmitResult => ({ text: e.text, context: e.context, origin: e.origin })

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
/** The `/session-bookmark` argument that prints the stored notes, read live, with no model turn. */
export const NOTES_ARG = 'notes'
/** The reply to any other argument. */
export const NOTES_USAGE = `usage: /${COMMAND} [${NOTES_ARG}]`
/** The notes reply when none are stored (the script's `list` says the same). */
const NO_NOTES_TEXT = 'no notes'
/** The notes reply for a file the script would refuse (not JSON, no notes list, another version). */
export const NOTES_UNREADABLE_TEXT = 'notes file unreadable; /harness:bookmark --clear resets it'
const COMMAND_DESCRIPTION =
  `Show the compaction bookmark saved in this session; \`${NOTES_ARG}\` shows the stored session notes`
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

/** Printed under `## Session Notes` when a note was added on a branch other than the bookmark's. */
export const NOTES_STALE_HINT =
  'A note marked `now on` was added on another branch: confirm with the developer whether it applies here ' +
  'before applying or skipping it, and never drop it silently.'

/** A note as held in state; a bookmark an earlier load stored holds plain strings, read as standing notes. */
const asStoredNote = (n: StoredNote | string): StoredNote =>
  typeof n === 'string' ? { text: n, branch: null } : { text: n.text, branch: n.branch ?? null }

/** The numbered note lines against `current`, and the hint line first when any note is from another branch. */
export const notesListing = (notes: readonly StoredNote[], current: string | null): string[] => {
  const lines = notes.map((n, i) => noteLine(i + 1, n, current))
  return notes.some(n => isOtherBranch(n, current)) ? [NOTES_STALE_HINT, '', ...lines] : lines
}

/** The session notes' section: the heading, the hint when due, one numbered line per note. */
const noteLines = (notes: readonly StoredNote[], current: string | null): string[] => [
  '## Session Notes',
  '',
  ...notesListing(notes, current),
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
  const notes = (b.notes ?? []).map(asStoredNote)
  if (notes.length > 0) lines.push(...noteLines(notes, markingBranch(b.branch)))
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

/**
 * The text of the first root's notes file, `<state_dir>/session-bookmark/notes.json`; undefined when no root
 * holds one. Never throws.
 */
const captureNotesText = async ($: Dollar, top: string | null): Promise<string | undefined> => {
  try {
    for (const root of top === null ? await rootCandidates($) : [top]) {
      const config = await $.fs.read(`${root.replace(/\\/g, '/')}/.claude/harness.json`).catch(() => undefined)
      const text = await $.fs.read(notesFileOf(root, stateDirOf(config))).catch(() => undefined)
      if (typeof text === 'string') return text
    }
  } catch {
    // a notes failure leaves the bookmark without notes
  }
  return undefined
}

/** The notes of the first root that holds a notes file; [] for none or an unreadable one. Never throws. */
const captureNotes = async ($: Dollar, top: string | null): Promise<StoredNote[]> => {
  const text = await captureNotesText($, top)
  return text === undefined ? [] : parseNotes(text)
}

type Capture = { git: GitFields; notes: StoredNote[] }

/** Git state and session notes, read before the compaction answers. Never throws. */
const capture = async ($: Dollar): Promise<Capture> => {
  const { git, top } = await captureGit($)
  return { git, notes: await captureNotes($, top) }
}

/**
 * The stored notes as `bookmark --list` numbers them, every usable note with no `MAX_NOTES` cut, against
 * the branch checked out now; a file the script refuses is reported, not shown as empty. Never throws.
 */
const liveNotesText = async ($: Dollar): Promise<string> => {
  const { git, top } = await captureGit($)
  const text = await captureNotesText($, top)
  const notes = text === undefined ? [] : parseNotesOrNull(text)
  if (notes === null) return NOTES_UNREADABLE_TEXT
  return notes.length === 0 ? NO_NOTES_TEXT : notesListing(notes, markingBranch(git.branch)).join('\n')
}

/** The `/session-bookmark` reply: the saved bookmark bare, the live notes for NOTES_ARG, else the usage. */
const commandText = async ($: Dollar, args: string): Promise<string> => {
  const arg = args.trim()
  if (arg === NOTES_ARG) return liveNotesText($)
  if (arg !== '') return NOTES_USAGE
  const b = await read($, bookmarkState)
  return b === null ? NO_BOOKMARK_TEXT : formatBookmark(b)
}

/** The conversation part of a bookmark: its last prompts and the compaction's instructions. */
type Conversation = Pick<Bookmark, 'lastMessages' | 'instructions'>

/** Builds the bookmark and stores it in state (a refused write is ignored). Throws when the clock does. */
const saveBookmark = async (
  $: Dollar,
  trigger: Bookmark['trigger'],
  { git, notes }: Capture,
  conversation: Conversation,
): Promise<Bookmark> => {
  const b: Bookmark = { savedAt: await $.clock.now(), trigger, ...git, notes, ...conversation }
  await update($, bookmarkState, () => b).catch(() => undefined)
  return b
}

/** Builds and stores the bookmark, and returns the result with the bookmark message appended. */
const bookmarkResult = async (
  $: Dollar,
  e: SessionCompactInput,
  trigger: Bookmark['trigger'],
  captured: Capture,
  result: SessionCompactResult & { skip?: undefined },
): Promise<SessionCompactResult> => {
  const conversation = { lastMessages: lastUserTexts(e.messages), instructions: e.instructions?.trim() || null }
  const b = await saveBookmark($, trigger, captured, conversation)
  const message: SessionMessage = { role: 'user', text: formatBookmark(b), toolUses: [] }
  return { ...result, messages: [...result.messages, message] }
}

/**
 * The bookmark for a compaction this mod's `session.compact` hook did not answer, as the text the next prompt
 * carries: git and live notes, no prompts (the compacted ones are gone) and no instructions.
 */
const detectedBookmark = async ($: Dollar): Promise<string> =>
  formatBookmark(await saveBookmark($, 'detected', await capture($), { lastMessages: [], instructions: null }))

// ---------------------------------------------------------------------------
// Registration

/** Registers the compaction bookmark, its next-prompt fallback and the `/session-bookmark` command. */
export const registerBookmark = (on: Parameters<Register>[0]): void => {
  on('session.compact', INSTALLING, async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    // git and the notes overlap the summarizer; when core reuses a precomputed summary, git's own timeouts are the wait
    const captured = capture($)
    const result = await next(e)
    if (result.skip !== undefined) return result
    try {
      const installed = await bookmarkResult($, e, e.trigger, await captured, result)
      compaction.installed = true
      return installed
    } catch {
      return result
    }
  })

  // Fallback for a compaction whose row reaches session.append while the session.compact hook above did not
  // run (for example a mod before it ended the chain): the next prompt carries the bookmark instead.
  on('session.append', { door: 'compaction' }, async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) {
      // each row consumes the mark, so a later compaction in the same turn is judged on its own
      compaction.owed = !compaction.installed
      compaction.installed = false
    }
    return result
  }).catch((_$, e, next) => next(e))

  // Every submission clears the installed mark, a slash command's line included, so a compaction it starts is
  // judged on its own. A command's line (`/compact`, `/clear`, `/session-bookmark`) never carries the owed
  // bookmark; the owed mark clears only once a prompt entered carrying it.
  on('prompt.submit', async ($, e, next) => {
    compaction.installed = false
    if (e.command !== undefined || !compaction.owed) return next(e)
    const text = await detectedBookmark($)
    if (next.signal.aborted) return asReceived(e)
    const result = await next({ ...e, context: [...(e.context ?? []), text] })
    recordDelivered(text, result, next.signal)
    return result
  }).catch((_$, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    if (FRESH_CONVERSATION.has(e.reason)) Object.assign(compaction, { installed: false, owed: false })
    return next(e)
  }).catch((_$, e, next) => next(e))

  on('session.start', async ($, e, next) => {
    await $.command
      .register({ name: COMMAND, description: COMMAND_DESCRIPTION })
      .catch(() => undefined)
    return next(e)
  })

  on('command.run', { command: COMMAND }, async ($, e) => ({ text: await commandText($, e.args) }))
    .catch(() => ({ text: 'session-bookmark: bookmark state unavailable.' }))
}
