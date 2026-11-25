# Working-refs line colors (issue #343)

Short design. Scope: the ccstatusline form of the working-refs line (`plugins/working-refs/hooks/line.ts`,
`statusText`), plus what the mod reads to color it.

## Intent

The developer wants more contrast on the third banner line "because it's nice", and one piece of meaning: each
plan number shows how far along its plan is. A plan is bright while active and fades as its tasks finish, so a
plan nearing its archive recedes.

## Goals

- Every kind of piece on the line has its own look: plan numbers, TODO labels, issue numbers, other branch
  names, and the punctuation between them.
- Each plan number's color steps from bright to dim by the share of its tasks that are done.
- The color follows a newly recorded task without waiting for an unrelated file change.

## Non-goals

- band-line's form stays one color (`subtle`, other branches dim); the plain `text` and the cap are unchanged.
- The widget's stale-branch stamp (the dark prefix the ccstatusline command adds when `line.json` names another
  branch) keeps its look.
- The TODO label colors (plan 2028 palette and hash) stay as they are.
- No new config key: the colors are fixed in the mod.

## Anti-goals

- A gradient that reads wrong on a fresh clone (a derived file missing means no progress shown).
- A plan color that collides with a TODO label color, so the two read as the same thing.

## Approaches

| | Source of "how far along" | Trade-off |
|---|---|---|
| **A (picked)** | The mod reads `<plans>/<id>/receipts/*.json` itself and counts done outcomes over the plan's items | One rule (which outcomes are done) is mirrored from the harness into the mod, pinned by the existing contract test |
| B | The mod reads the plan page's generated `<id>/live.js` | One file to read, but it is git-ignored and absent on a fresh clone until the page is rebuilt |
| C | The harness writes a progress file per plan | No counting in the mod, but three writers (`plan.py record`, `render`, the a-w rebuild) and the same absence problem as B |

The developer picked A: receipts are committed and write-once, so the color is right on every checkout.

## Decided

- **Done counting.** A plan with a `receipts/` folder counts an item done when its receipt's `outcome.kind` is
  `complete` or `closed` (`harness_lib.plan_enums.OutcomeKind`); `started` and `blocked` count as not done. A
  plan without the folder counts its items' `status` of `COMPLETE` or `CLOSED_NO_ACTION` (`plan_enums.DONE`). The total is the
  plan's item count. (The closed-counts-as-done rule was proposed in conversation and not corrected.)
- **Gradient direction.** Bright at 0 done, dim at all done (developer's answer).
- **Palette depth.** ANSI 256 steps, matching the TODO palette and the ccstatusline `colorLevel` 2; no
  24-bit color.
- **Scope.** ccstatusline form only (proposed in conversation, not corrected).

## Builder's calls (proposed values, tunable)

- **Plan ramp, five steps:** `51` (none done), then `45`, `74`, `67` for a done share in the first, second and
  last third of the way, then `243` (all done). Step 0 and step 4 are reserved for exactly none and exactly
  all, so both ends read at a glance. None of the five is in the TODO palette (39, 170, 36, 214, 141, 72, 203,
  178). A plan with no items, or one whose file cannot be read, takes step 0.
- **Issue numbers:** `180`, steady, outside the TODO palette and the plan ramp.
- **Other branch names:** `246` in place of today's `240`, readable on dark and light themes.
- **Punctuation** (`[ ]`, ` · `, `,`, `( )` around issues, ` +N`): `240`, so the colored pieces stand out.
- **Watching receipts.** The change check also takes the name, size and mtime of each receipt file of the plans
  on the current line (the qualifying plans of the last scan), so `plan.py record` moves the color at the
  next tool call. Plans not on the line are not listed.
- **Mirror and contract.** `hooks/mirror.ts` gains the receipts folder name, the done outcome kinds and the
  done legacy statuses; `tests/mods/test_working_refs_contract.py` pins them against `harness_lib`.
- **State atom.** Each `PlanLink` in `line.plans` gains `done` and `total` (`types/index.d.ts`); additive, so
  band-line and other readers keep working.

## Left to the builder

- The exact module split inside the mod (a `progress.ts` beside `plans.ts` is the likely shape).
- Test layout in the mod's `*.test.ts` files and the contract test additions.
- The working-refs version bump and the release-notes line.
