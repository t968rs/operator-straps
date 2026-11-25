/** One `git status --porcelain=v2 --branch` reading of the project root. */
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

declare module 'claude-code' {
  interface PluginState {
    'git-status': {
      /** The latest snapshot; null before the first or after a failed run. */
      git: GitSnapshot | null
      /** The GIT_STATE line last attached to a prompt. */
      lastContext: string
    }
  }
}
