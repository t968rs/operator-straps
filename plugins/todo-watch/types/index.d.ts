/** One ranked TODO item as the summary keeps it. */
export type TodoRow = {
  id: string
  rank: number
  title: string
  status: string
  /** `priority.score`; null when the item has none. */
  score: number | null
}

/** The TODO catalog's counts and its top-N items, read by the mod itself. */
export type TodoSummary = {
  /** `counts.items`. */
  items: number
  /** `counts.by_status.OPEN`. */
  open: number
  /** `counts.by_status.PARTIAL`. */
  partial: number
  /** `counts.by_status.BLOCKED`. */
  blocked: number
  /** `counts.needs_decision`. */
  needsDecision: number
  /** The first `todo.top_n` items by rank. */
  top: TodoRow[]
  /** The catalog's mtime when it was read. */
  mtimeMs: number
}

/** One finding of a sync report (TodoSyncReport `findings[]`). */
export type SyncFinding = {
  rule: string
  severity: 'error' | 'warn'
  counted: boolean
  file: string | null
  line: number | null
  subject: string | null
  message: string
  fix: string | null
}

/** The parts of a sync report the mod reads. */
export type SyncReport = {
  generatedAt: string
  drift: number
  /** Counted findings per rule id. */
  byRule: Record<string, number>
  errors: number
  warns: number
  /** The issue cache's `fetched_at`; null when no cache was read. */
  ghFetchedAt: string | null
  findings: SyncFinding[]
  /** The report file's mtime when it was read. */
  mtimeMs: number
}

declare module 'claude-code' {
  interface PluginState {
    'todo-watch': {
      /** The TODO catalog summary; null before the first read or when the catalog is unreadable. */
      summary: TodoSummary | null
      /** The latest report newer than the session start; null before one lands. */
      report: SyncReport | null
      /** The TODO_SYNC line last attached to a prompt. */
      lastContext: string
      /** The drift count last toasted; null before any drift toast. */
      lastToastDrift: number | null
      /** The band's notices, oldest first; empty once dismissed or at a session start. */
      notices: string[]
    }
  }
}
