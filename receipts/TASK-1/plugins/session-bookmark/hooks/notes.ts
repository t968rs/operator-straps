/**
 * The session notes the `harness:add-bookmark` skill stores and the bookmark prints.
 *
 * The skill's script (`plugins/harness/skills/add-bookmark/commands/add_note.py`) writes
 * `<state_dir>/session-bookmark/notes.json` under the project root: `{ "version": 1, "notes": [{ "added",
 * "text" }] }`. An installed mod sits in its own plugin cache folder and cannot read the harness plugin, so the
 * names and limits are copied here; `tests/mods/test_session_bookmark_notes_contract.py` pins them. Pure: no `$`.
 */

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const NOTES_PATH = 'session-bookmark/notes.json'
export const NOTES_SCHEMA_VERSION = 1
/** The most notes printed; the script refuses a note past this many. */
export const MAX_NOTES = 20
/** The longest note printed, in characters; the script refuses a longer one. */
export const MAX_NOTE_CHARS = 300

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

/**
 * The notes in a file's text, oldest first, at most `MAX_NOTES` (the newest when more are stored). Malformed
 * JSON, another version or a missing `notes` array hold none.
 */
export const parseNotes = (text: string): string[] => {
  const data = parse(text)
  if (!isObject(data) || data.version !== NOTES_SCHEMA_VERSION || !Array.isArray(data.notes)) return []
  const kept = data.notes.map(noteText).filter((t): t is string => t !== null)
  return kept.slice(-MAX_NOTES)
}
