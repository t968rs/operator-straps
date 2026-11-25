/** The TODO ids and issue numbers a branch works on: an override entry or an ActionPlan's `refs`. */
export type Refs = {
  /** Canonical TODO ids (`todo-k69m`), in first-seen order. */
  todoIds: string[]
  /** GitHub issue numbers, in first-seen order. */
  issues: number[]
}

/** One qualifying plan's link: its number, its page and its done share (plan 2030). */
export type PlanLink = {
  /** The 4-digit `plan_id`. */
  id: string
  /** The absolute path of the plan's `<prefix>_PIP.html`, forward slashes. */
  page: string
  /** How many of the plan's items are done (plan 2030). */
  done: number
  /** The plan's item count. */
  total: number
}

/** The working line of one branch, as the mod renders it. */
export type WorkingLine = {
  /** The branch the line was built for: the branch name, or `(detached)`. */
  branch: string
  /** The qualifying plans, by id. */
  plans: PlanLink[]
  /**
   * The own TODO ids: the branch's override entry's ids that are not retired when it has one, else the union of
   * the plans' ids (plan refs never hide).
   */
  todoIds: string[]
  /** The own issues: the override entry's issues not reported closed when it has one, else the plans' union. */
  issues: number[]
  /** The own TODO ids with their catalog keywords, in `todoIds` order (plan 2028). */
  labels: TodoLabel[]
  /** The own refs formatted plain, each id labelled (`todo-k69m banner (301)`); '' when there are none. */
  refs: string
  /** The plans part and the own refs, plain (`plan 2025 · todo-k69m banner (301)`); '' when both are empty. */
  head: string
  /** The other branches' override segments drawn, most recently set first; each `refs` is the formatted text. */
  others: OtherSegment[]
  /** How many other-branch segments did not fit within `working_refs.max_chars`; 0 when all fit. */
  more: number
  /**
   * The full plain form (`head · [ b1 refs ] [ b2 refs ] +N`); band-line draws its characters from head, others and
   * more, and draws it verbatim only from an older working-refs.
   */
  text: string
}

/** One other branch's override, drawn as `[ <branch> <refs> ]`. */
export type OtherSegment = {
  /** The branch name, or `(detached)`. */
  branch: string
  /** Its visible refs, formatted plain, each id labelled (`todo-k69m banner (301)`). */
  refs: string
  /** Its visible TODO ids with their catalog keywords, in override order (plan 2028). */
  labels: TodoLabel[]
  /** Its visible issues, in override order. */
  issues: number[]
}

/** What a folder listing gives of one entry. */
export type Listed = { name: string; kind: string; size: number; mtimeMs: number }

/** One TODO id as the line labels it (plan 2028 D1): `todo-x7ty stop_gates`, or the id alone. */
export type TodoLabel = {
  /** The canonical TODO id. */
  id: string
  /** The catalog item's `keyword`; null when the item has none or the catalog does not list the id. */
  keyword: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'working-refs': {
      /** The checkout's working line; null before the first scan and while nothing qualifies or overrides. */
      line: WorkingLine | null
    }
  }
}
