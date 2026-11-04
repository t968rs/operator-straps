/** One lane of a parallel2 run state file (`<state_dir>/parallel2/<target>.json`), the fields the mod reads. */
export type LaneState = {
  id: string
  kind: string
  model: string
  wave: number | null
  status: string
  /** The lane's worktree (forward slashes); null for a read-only lane or one not set up. */
  worktree: string | null
}

/** A parallel2 run state file as the mod reads it. */
export type RunState = { target: string; lanes: LaneState[] }

/** Where a lane's brief and its run state live, read from a `Brief: <path>` line. */
export type LaneRef = {
  /** The run state file: `<folder>/parallel2/<target slug>.json`. */
  stateFile: string
  laneId: string
}

/** What the session's lane agent is doing: started, or its run handed back. */
export type AgentPhase = 'running' | 'returned'

/** One lane as the band draws it. */
export type LaneView = {
  id: string
  wave: number | null
  status: string
  agent: AgentPhase | null
}

/** One run as the band draws it. */
export type RunView = { stateFile: string; target: string; lanes: LaneView[] }

declare module 'claude-code' {
  interface PluginState {
    'parallel2-lanes': {
      /** The lane each spawned lane agent runs, by agent id. */
      spawned: Record<string, LaneRef>
      /** Each spawned lane's agent phase, by `<stateFile>#<laneId>`. */
      agents: Record<string, AgentPhase>
      /** The runs seen this session, reread from their state files; a run whose file is gone is dropped. */
      runs: RunView[]
    }
  }
}
