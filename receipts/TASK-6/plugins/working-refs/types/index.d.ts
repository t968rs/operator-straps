/** The TODO ids and issue numbers a branch works on: an override entry or an ActionPlan's `refs`. */
export type Refs = {
  /** Canonical TODO ids (`todo-k69m`), in first-seen order. */
  todoIds: string[]
  /** GitHub issue numbers, in first-seen order. */
  issues: number[]
}

/** One qualifying plan's link: its number and its page. */
export type PlanLink = {
  /** The 4-digit `plan_id`. */
  id: string
  /** The absolute path of the plan's `<prefix>_PIP.html`, forward slashes. */
  page: string
}

/** The working line of one branch, as the mod renders it. */
export type WorkingLine = {
  /** The branch the line was built for: the branch name, or `(detached)`. */
  branch: string
  /** The qualifying plans, by id. */
  plans: PlanLink[]
  /** The override's TODO ids when one is set, else the union of the plans' ids. */
  todoIds: string[]
  /** The override's issues when one is set, else the union of the plans' issues. */
  issues: number[]
  /** The plain form (`plan 2025 · todo-k69m (301)`), drawn verbatim by band-line. */
  text: string
}

declare module 'claude-code' {
  interface PluginState {
    'working-refs': {
      /** The checkout's working line; null before the first scan and while nothing qualifies or overrides. */
      line: WorkingLine | null
    }
  }
}
