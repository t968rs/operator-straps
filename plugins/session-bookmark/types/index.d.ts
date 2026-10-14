/** Session state captured as the main conversation compacts; stands in for a bookmark file. */
export type Bookmark = {
  /** Epoch ms when the compaction finished. */
  savedAt: number
  trigger: 'manual' | 'auto' | 'plugin'
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
