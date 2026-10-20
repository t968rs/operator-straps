/** Which skill dispatched a run. */
export type Skill = 'pr-team' | 'pr-review'

/**
 * Where a run stands: from its latest dispatch or closeout, refined for pr-review by the `phase` its
 * current run's `plan.json` records.
 */
export type Phase = 'plan' | 'review' | 'consolidate' | 'fix-plan' | 'fix' | 'closeout' | 'done'

/** A reviewer-style COUNTS line. */
export type Counts = { findings: number; critical: number; important: number; minor: number }

/** One tracked subagent of a run. */
export type AgentRec = {
  /** Slot id from the dispatch plan, or `orchestrator_plan` / `orchestrator_consolidate` / `fixer_plan` / `closer`. */
  id: string
  /** `reviewer`, `fixer`, `orchestrator`, `planner` or `closer`. */
  role: string
  /** Model as requested or resolved; null when neither is known. */
  model: string | null
  effort: string | null
  tokens: number
  toolUses: number
  durationMs: number
  /** True once engine-measured usage was folded in. */
  isMeasured: boolean
  /** Return-block SIGNAL; `NO_BLOCK` when the agent returned without one; null while running. */
  signal: string | null
  counts: Counts | null
  /** Epoch ms of the matrix-row attempt; null before it. */
  loggedAt: number | null
  /** The dispatch's `subagent_type`; null when the call named none or the agent was rebuilt from disk. */
  subagentType: string | null
  /** Epoch ms of the usage-row attempt; null before it. */
  usageLoggedAt: number | null
  /**
   * The model the engine resolved at a background launch; null otherwise. Read by usage rows only, so a
   * background agent whose loop reports no usage still logs the model that ran, not the requested alias.
   */
  launchModel: string | null
}

/** One pr-team or pr-review invocation, keyed by its RUN_ID. */
export type Run = {
  runId: string
  skill: Skill
  pr: number | null
  phase: Phase
  /** Repo-relative pr-team runtime dir; null for pr-review. */
  runtimeDir: string | null
  agents: Record<string, AgentRec>
  bubbled: string[]
  /**
   * `review_json` (pr-review): the review's `bubbles[]` plus ids bubbled in the run's `fixes/*.json`
   * that no RESOLVED / CLOSED_NO_ACTION resolution closes.
   */
  bubbledFrom: 'closer' | 'bubble_ups' | 'review_json' | 'none'
  verdict: string | null
  /** Epoch ms of the first tracked dispatch; 0 for a run recovered from disk. */
  startedAt: number
}

/**
 * A matrix or usage-log row that failed validation or could not be written. `cell` is the matrix cell, or
 * `<run_id>/<agent_id>` for a usage row.
 */
export type LogFailure = { cell: string; reason: string; at: number }

declare module 'claude-code' {
  interface PluginState {
    'pr-review-watch': {
      runs: Record<string, Run>
      /** RUN_ID of the run dispatched most recently. */
      active: string | null
      /** Engine loop id of a background subagent -> [runId, agentId]. */
      loops: Record<string, [string, string]>
      failures: LogFailure[]
      /** PR ids of hot Phase 5 sentinels. */
      phase5: string[]
      /** Tracked bubbled ids the active run's review JSON does not disposition. */
      missing: string[]
    }
  }
}
