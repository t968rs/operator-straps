/**
 * One stored session note: its text and the branch it was added on (null: a standing note). Mirrors
 * `StoredNote` in `hooks/notes.ts`; the type contract stays self-contained, so it is declared here too.
 */
export type StoredNote = { text: string; branch: string | null }

/** Session state captured as the main conversation compacts; stands in for a bookmark file. */
export type Bookmark = {
  /** Epoch ms when the compaction finished. */
  savedAt: number
  /**
   * The compaction's trigger; `detected` for a bookmark built at the next prompt after a main-loop compaction
   * row reached `session.append` while this mod's `session.compact` hook did not run.
   */
  trigger: 'manual' | 'auto' | 'plugin' | 'detected'
  /** The folder git answered from (session cwd, else CLAUDE_PROJECT_DIR); null when neither is a repo. */
  root: string | null
  /** `git rev-parse --abbrev-ref HEAD`, else `git symbolic-ref --short HEAD` (no commits yet); null when git was unavailable. */
  branch: string | null
  /** `git log --oneline -5`; null when git was unavailable or the repository has no commits. */
  log: string | null
  /** `git status --porcelain`, capped at MAX_STATUS_LINES entries plus a count line; null when git was unavailable, '' when clean. */
  status: string | null
  /** The last user prompts before the compaction, newest last; a previous compaction's summary can be one. */
  lastMessages: string[]
  /**
   * Session notes added with the `harness:add-bookmark` skill, oldest first, each with the branch it was added
   * on (null: standing); [] when none are stored. A bookmark an earlier mod version stored holds plain strings,
   * which `formatBookmark` reads as standing notes.
   */
  notes: StoredNote[]
  /** The compaction's instructions (the text after `/compact`); null when none. */
  instructions: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'session-bookmark': {
      /** The latest compaction bookmark of this session; null before the first. */
      bookmark: Bookmark | null
    }
  }
}
