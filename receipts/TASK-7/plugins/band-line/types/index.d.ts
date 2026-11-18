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

declare module 'claude-code' {
  interface PluginState {
    'band-line': {
      /** The session figures the banner shows; all null before the first reading. */
      session: SessionFigures
    }
  }
}
