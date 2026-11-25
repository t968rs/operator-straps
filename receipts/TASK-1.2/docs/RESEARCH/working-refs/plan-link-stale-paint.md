# working-refs: a plan link that stops qualifying keeps its paint (deferred)

Status: deferred. Plan refs stay as they are; this records the smallest change that would keep a plan link on
the line after it stops qualifying, painted as a warning, instead of dropping it.

## Today

`qualifies` (`plugins/working-refs/hooks/plans.ts`) puts a plan on a branch's line when it is not archived and
either its `branch` is the current one (rule 1) or its `base_commit` is the merge base of HEAD and its
`base_branch` (rule 2). A branch switch, or a rebase that moves the merge base, fails both rules and the link
drops off the line at the next scan.

## The change

A plan drops only when it is archived (`archive/plan/<id>-*` tag), the same rule as a TODO dropping only when
it is in the catalog's `retired_ids`. Until then a link that no longer qualifies stays, painted as a warning.

1. `types/index.d.ts`: `PlanLink` gains `stale: boolean`.
2. `hooks/watch.ts` `runScan`: `line.json` (the branch-stamped line file the cross-branch refs work adds)
   gains a `plans` field, `[{id, page}]`, written beside `text` (a `line.json` version bump; `text` alone holds
   only rendered output). The scan reads the previous file's `plans` and carries over each link that is not
   archived and not qualifying now, as `stale: true`. The plan must still read from the plans folder
   (`readPlans`); a deleted plan or page drops. The carry-over is the only new state, and it lives in the file
   the mod already writes, so it survives a session restart without a new store.
3. `hooks/line.ts` `statusText`: wrap a stale plan number in the warning SGR (yellow, `\x1b[33m` ...
   `\x1b[39m`) outside its OSC 8 link; `buildLine` keeps the plain `text` unchanged so band-line's atom
   readers see the same string.
4. `plugins/band-line/hooks/band.tsx`: draw the stale plan part with `color="warning"`, the rest `subtle`.

No change to `qualifies`, the merge-base resolution or the archive scan. A stale link's refs do not join the
union `buildLine` makes; only the link is kept, so the refs still follow the TODO and issue rules.

## Open when picked up

- Whether a stale link ever ages out without an archive tag (a merged branch whose plan was never archived
  stays painted forever).
- Whether a carried link shows on every branch or only on branches that share the plan's `base_branch`.
