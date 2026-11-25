/**
 * The git-status snapshot this mod draws, as git-status's contract declares it; the `git-status.git` state
 * key itself is typed by that contract (plugin.json `dependencies`).
 */
export type GitSnapshot = {
  /** `# branch.head`: the branch name, or `(detached)`. */
  branch: string
  /** `# branch.upstream`; null when the branch tracks none. */
  upstream: string | null
  ahead: number
  behind: number
  /** Entries with an index (X) change. */
  staged: number
  /** Entries with a worktree (Y) change, plus unmerged entries. */
  unstaged: number
  untracked: number
}

/** What the banner shows of the session: the main loop's model and its context window. */
export type SessionFigures = {
  /** `$.session.model()`; null until the engine answers. */
  model: string | null
  /** Input tokens of the last response; null until the live window has one (a fresh or just compacted session). */
  ctxTokens: number | null
  /** `ctxTokens` against the model's window, a whole percentage; null when unknown. */
  ctxPercent: number | null
}

/** One other-branch segment of the working line, drawn `[ <branch> <refs> ]`. */
export type OtherSegment = {
  branch: string
  /** The refs, already formatted by working-refs. */
  refs: string
}

/**
 * The parts of working-refs's working line this mod reads. A local copy of the shape, so band-line does not
 * depend on working-refs. A line from an older working-refs holds `text` alone.
 */
export type WorkingLine = {
  /** The full plain form (`plan 2025 · todo-k69m (301) · [ other todo-zz99 ] +1`). */
  text: string
  /** The plans part and own refs, plain; empty when both are. */
  head?: string
  /** The drawn other-branch segments, most recent first. Absent from an older working-refs. */
  others?: OtherSegment[]
  /** Segments left out by the cap; 0 when all fit. */
  more?: number
}

declare module 'claude-code' {
  interface PluginState {
    'working-refs': {
      /** The checkout's working line; null or unset while working-refs is absent or has nothing to show. */
      line: WorkingLine | null
    }
    'band-line': {
      /** The session figures the banner shows; all null before the first reading. */
      session: SessionFigures
    }
  }
}
