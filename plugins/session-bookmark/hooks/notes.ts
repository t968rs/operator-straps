/**
 * The session notes the `harness:add-bookmark` skill stores and the bookmark prints.
 *
 * The skill's script (`plugins/harness/skills/add-bookmark/commands/add_note.py`) writes
 * `<state_dir>/session-bookmark/notes.json` under the project root: `{ "version": 1, "notes": [{ "added",
 * "branch", "text" }] }`, where a note without a usable `branch` applies on every branch. An installed mod sits
 * in its own plugin cache folder and cannot read the harness plugin, so the names, limits and the printed line
 * format (the script's `note_line`) are copied here; `tests/mods/test_session_bookmark_notes_contract.py` pins
 * them. Pure: no `$`.
 */

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const NOTES_PATH = 'session-bookmark/notes.json'
export const NOTES_SCHEMA_VERSION = 1
/** The most notes printed; the script refuses a note past this many. */
export const MAX_NOTES = 20
/** The longest note printed, in characters; the script refuses a longer one. */
export const MAX_NOTE_CHARS = 300
/** The entry key naming the branch a note was added on. */
export const NOTE_BRANCH_KEY = 'branch'
/** The words between a note's branch and the current one when the two differ: `[dev; now on main]`. */
export const OTHER_BRANCH_MARK = 'now on'

/** One stored note: its text, and the branch it was added on (null: a standing note). */
export type StoredNote = { text: string; branch: string | null }

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const parse = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/** Forward slashes, no surrounding blanks, no trailing slash. */
const cleanPath = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** `state_dir` from a `harness.json` text; the default when the text is absent, malformed or holds none. */
export const stateDirOf = (configText: string | undefined): string => {
  const data = configText === undefined ? undefined : parse(configText)
  const named = isObject(data) && typeof data.state_dir === 'string' ? cleanPath(data.state_dir) : ''
  return named === '' ? DEFAULT_STATE_DIR : named
}

/** Whether a path is absolute: POSIX, drive or UNC. */
const isAbsolute = (path: string): boolean => /^([A-Za-z]:)?[\\/]/.test(path)

/** The notes file under `root`; an absolute `stateDir` is kept as it is. */
export const notesFileOf = (root: string, stateDir: string): string => {
  const base = isAbsolute(stateDir) ? stateDir : `${cleanPath(root)}/${stateDir}`
  return `${base}/${NOTES_PATH}`
}

/** A note's text cut to the limit and trimmed; blank and non-text entries read as null. */
const noteText = (entry: unknown): string | null => {
  const text = isObject(entry) && typeof entry.text === 'string' ? entry.text.trim() : ''
  return text === '' ? null : text.slice(0, MAX_NOTE_CHARS)
}

/** A note's branch, trimmed; absent, non-text and blank values read as null (a standing note). */
const noteBranch = (entry: Json): string | null => {
  const value = entry[NOTE_BRANCH_KEY]
  const branch = typeof value === 'string' ? value.trim() : ''
  return branch === '' ? null : branch
}

/** An entry as a stored note; null for one without a usable text. */
const storedNote = (entry: unknown): StoredNote | null => {
  const text = noteText(entry)
  return text === null || !isObject(entry) ? null : { text, branch: noteBranch(entry) }
}

/**
 * The notes in a file's text as `parseNotes` reads them, or null for a file the script refuses (its
 * `read_notes`): malformed JSON, another version or a missing `notes` array.
 */
export const parseNotesOrNull = (text: string): StoredNote[] | null => {
  const data = parse(text)
  if (!isObject(data) || data.version !== NOTES_SCHEMA_VERSION || !Array.isArray(data.notes)) return null
  const kept = data.notes.map(storedNote).filter((n): n is StoredNote => n !== null)
  return kept.slice(-MAX_NOTES)
}

/**
 * The notes in a file's text, oldest first, at most `MAX_NOTES` (the newest when more are stored). Malformed
 * JSON, another version or a missing `notes` array hold none.
 */
export const parseNotes = (text: string): StoredNote[] => parseNotesOrNull(text) ?? []

/** The name `git rev-parse --abbrev-ref HEAD` prints on a detached HEAD. */
const DETACHED_HEAD = 'HEAD'

/** The branch notes are marked against: null on a detached HEAD, as the script's `current_branch` answers. */
export const markingBranch = (branch: string | null): string | null => (branch === DETACHED_HEAD ? null : branch)

/** Whether a note was added on a branch other than `current`; never when either is unknown. */
export const isOtherBranch = (note: StoredNote, current: string | null): boolean =>
  note.branch !== null && current !== null && note.branch !== current

/** The note as printed (the script's `note_body`): bare when standing, branch-tagged, marked when elsewhere. */
export const noteBody = (note: StoredNote, current: string | null): string => {
  if (note.branch === null) return note.text
  if (!isOtherBranch(note, current)) return `[${note.branch}] ${note.text}`
  return `[${note.branch}; ${OTHER_BRANCH_MARK} ${current}] ${note.text}`
}

/** One numbered note line (the script's `note_line`): `N. text`, `N. [b] text` or `N. [b; now on c] text`. */
export const noteLine = (i: number, note: StoredNote, current: string | null): string =>
  `${i}. ${noteBody(note, current)}`
