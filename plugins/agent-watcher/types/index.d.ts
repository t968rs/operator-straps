/**
 * Which skill dispatched a run: `pr-team` or `pr-review` for a layer's run; for any other dispatch its header
 * `SKILL:` (plugin prefix stripped, matching the usage schema's pattern), else `standalone`.
 */
export type Skill = string

/**
 * Where a run stands: from its latest dispatch or closeout, refined for pr-review by the `phase` its
 * current run's `plan.json` records.
 */
export type Phase = 'plan' | 'review' | 'consolidate' | 'fix-plan' | 'fix' | 'closeout' | 'done'

/** A reviewer-style COUNTS line. */
export type Counts = { findings: number; critical: number; important: number; minor: number }

/** One tracked subagent of a run. */
export type AgentRec = {
  /**
   * Slot id from the dispatch plan, or `orchestrator_plan` / `orchestrator_consolidate` / `fixer_plan` / `closer`
   * in a layer's run; an unclaimed dispatch's header `AGENT_ID:`, else the agent type's name.
   */
  id: string
  /**
   * `reviewer`, `fixer`, `orchestrator`, `planner` or `closer` in a layer's run, or for pr-review `-a` a
   * `refuter` or `code_refuter` re-dispatched as an `Agent` call; an unclaimed dispatch's header
   * `AGENT_ROLE:`, else `other`.
   */
  role: string
  /** Model as requested or resolved; null when neither is known. */
  model: string | null
  effort: string | null
  /** Input + output + cache read + cache creation tokens summed over every model request the agent made. */
  tokens: number
  /**
   * The same four counts for the agent's last model request alone (its context size at the end, the figure its
   * completion notification shows); absent while unknown.
   */
  contextTokens?: number
  /** Model requests the agent's loop made (one per `turn.step`), with or without usage; absent while unknown. */
  requests?: number
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

/**
 * One tracked invocation, keyed by its run id: the dispatches a layer claimed under one run (`claimedBy`), or
 * an unclaimed dispatch (no `claimedBy`), a run of one agent under its generated `standalone_<UTC>_<seq>` id
 * whatever its header RUN_ID, dropped once its usage row is attempted.
 * Core (hooks/core) creates the run from a dispatch and folds its agents; `pr`, `phase`, `runtimeDir`,
 * `bubbled`, `bubbledFrom` and `verdict` are set from the claim and kept current by the claiming layer (today
 * only hooks/layers/pr-review).
 */
export type Run = {
  runId: string
  skill: Skill
  /**
   * The run key (`RunKey` in hooks/layers/pr-review/runKey.ts): a PR number, or a `local-<label>` key for a
   * review-local run; null when the run names none. A local run logs no matrix rows and a null `pr` in its
   * usage rows.
   */
  pr: number | string | null
  phase: Phase
  /** Repo-relative pr-team runtime dir; null for pr-review. */
  runtimeDir: string | null
  agents: Record<string, AgentRec>
  bubbled: string[]
  /**
   * `review_json` (pr-review): the review's `bubbles[]` plus ids bubbled in the run's `fixes/*.json`
   * that no RESOLVED / CLOSED_NO_ACTION / REFUTED resolution closes.
   */
  bubbledFrom: 'closer' | 'bubble_ups' | 'review_json' | 'none'
  verdict: string | null
  /**
   * Epoch ms of the first tracked dispatch; for a run recovered from disk, the UTC stamp its run id carries
   * (`startedAtOfRunId`; a run id without a valid stamp is not recovered).
   */
  startedAt: number
  /**
   * The name of the layer that claimed the run (hooks/core/layer.ts); core calls that layer's per-run members
   * only. Unset for an unclaimed run; core tells the two apart by this field alone.
   */
  claimedBy?: string
  /** An unclaimed run's logged `run_id` (its header RUN_ID) when it differs from the state key `runId`. */
  logRunId?: string
  /** An unclaimed run's usage-row `fields` (header keys core did not consume); unset when none. */
  fields?: Readonly<Record<string, string>>
}

/**
 * A matrix or usage-log row that failed validation or could not be written. `cell` is the matrix cell, or
 * `<run_id>/<agent_id>` for a usage row.
 */
export type LogFailure = { cell: string; reason: string; at: number }

declare module 'claude-code' {
  interface PluginState {
    'agent-watcher': {
      runs: Record<string, Run>
      /** Run id of the latest layer-claimed dispatch; an unclaimed dispatch never becomes active; null before any. */
      active: string | null
      /** Engine loop id of a background subagent -> [runId, agentId]. */
      loops: Record<string, [string, string]>
      failures: LogFailure[]
      /** Run keys (PR numbers or `local-<label>` keys) of hot Phase 5 sentinels. */
      phase5: string[]
      /** Tracked bubbled ids the active run's review JSON does not disposition. */
      missing: string[]
    }
  }
}
