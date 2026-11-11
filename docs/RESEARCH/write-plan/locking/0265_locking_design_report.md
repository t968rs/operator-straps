# Locking and freeze tags: design report

Issue #265 (todo-w3ck): "Driver-created local tags for every necessary, plan-referenced and base-to-freeze
commit". Design session on 2026-11-11, branch `1151-commit-tagging` (cut after PR 261 merged). The design is
in `docs/superpowers/specs/2026-11-11-freeze-tags-design.md`; the strap stamp trade-off is in
`0265_strap_stamp_placement.md` beside this report.

## Starting point

- **Commits the drivers read later:**
  - a plan's `base_commit`, where anchors and sweeps are read once an item is done
    (`plugins/harness/scripts/plan.py:281`);
  - a strap spec's `base`, where the baseline arm reads the SKILL.md (`plugins/harness/scripts/strap.py:640`),
    runs start (`strap.py:391`), and `reopen` checks that the new base descends from it (`strap.py:911-912`).
- **Commits recorded for display only:**
  - the plan's `frozen.commit` and `frozen.tree`, which are HEAD and `HEAD^{tree}` at freeze, the whole
    repository (`plan.py:433-437`);
  - strap `rounds[].base`.
- **What the stamps hash today:**
  - plan: a sha256 freeze digest over the plan JSON (`pd.frozen_digest`);
  - strap: a sha256 over the part files (`plugins/harness/lib/harness_lib/strap_runs.py:24`).
  - Neither is a git object, so neither can be tagged.
- **Hand-made tags existed without a scheme:**
  - names such as `plan-1014-base`, `write-plan-skill-spec-base`, `strap/writing-docstrings-0004-base` and
    `commit-msg-red/green/freeze`;
  - a mix of annotated and lightweight;
  - `plan-1014-base` already corrected to `5a8ef39`.
- The developer asked that past hand-tagging not set the direction.

## How the design moved

1. **Purpose.** The developer wants both rewrite protection and browsable history, with names in the shape
   `freeze/commit-msg`.
2. **Why a freeze tag cannot sit on the commit holding the freeze.** Freezing writes the stamp to the working
   tree, and the developer commits afterwards. At freeze time HEAD is the commit before the freeze.
3. **The developer's turn:** a freeze should hash its own scoped files, not the repository.
   - Building a git tree (temporary index, `git write-tree`) makes the stamp a git object.
   - Git can tag a tree, so the freeze is tagged at once, with no commit.
   - The commit that later holds the freeze gets its own tag, by practice.
4. **Circularity.** A tree cannot contain the file recording its own SHA. Options: (a) leave the stamp file
   out of the tree, or (b) move the stamp to a ledger. The developer picked (b).
5. **Lock enforcement.** The developer asked for a mechanical block on writes to frozen files. The design
   blocks the agent's file tools (a PreToolUse guard) and the library writers, and `check` detects any
   other writer. A git `pre-commit` hook was offered and declined.
6. **Two states.**
   - The developer split the freeze into **Frozen** and **Locked**.
   - Frozen: during strap testing and plan review; driver-sanctioned writes continue.
   - Locked: final.
   - This removed the conflict that green runs and grades write `SkillSpec.json` after a freeze.
7. **When Lock happens.** It is explicit:
   - **plans** lock once the frozen plan is committed, and execution runs under the lock;
   - **skills** lock at branch end or merge, after freeze, nothing stale and the developer's agreement.
8. **Reviewer findings** (a fresh-context design read), settled below.
9. **Stamp placement.**
   - The developer first chose symmetry (both stamps in the ledger).
   - After seeing the cost, the developer switched to asymmetric: the strap stamp stays in `SkillSpec.json`.

## Decisions

| Topic | Decision | By |
|---|---|---|
| Purpose | Rewrite protection and browsable history | developer |
| Freeze identity | A git tree of scoped, **tracked** files, tagged at once | developer (scope by the session) |
| Plan stamp | Moves to the ledger under `<artifacts.plans>/freezes/` | developer |
| Strap stamp | Stays in `SkillSpec.json`; the ledger records trees and Lock | developer |
| States | Frozen, then Locked | developer |
| Lock trigger | Explicit command; plans after the frozen plan is committed, skills at branch end with agreement | developer |
| Who is blocked under Lock | The agent's file tools and the drivers; `check` reports the rest | developer |
| Commit tags | Driver-side reconcile on every run, `check` included | session |
| Rewrite policy | A second commit tag; the old one stays | developer |
| Planned tests | Not in trees (gitignored, never committed); the ledger keeps a sha256 for drift and lock | developer (tracked only), session (sha256) |
| Existing plans and specs | Keep the in-file stamp; migrate at their next pass | developer |
| Design change after a plan Lock | `freeze --refreeze --unlock` writes `unlock`, then a new `freeze`; relock after commit | session |
| Tag names | `base/<name>/r<N>`, `freeze/<name>/r<N>.<k>-tree` and `-commit`, `lock/...` likewise, `-commit.2` after a rewrite; plans named `plan-<id>` | developer (shape), session (suffixes) |

## Reviewer findings and how each was settled

| Finding | Settled by |
|---|---|
| Q1: a frozen plan could never be edited before a refreeze | The Frozen/Locked split: only Locked denies writes |
| Q2: whether strap parts lock | Only paths under `<artifacts.plans>` lock; parts never do. The guard returns early on any other path |
| Q3: plan ids collide across branches, so tags would too | `plan.py new` and the renumber rule skip ids any tag already holds |
| Q4: the shape of a migrated `SkillSpec` | Moot after the asymmetric decision: `SkillSpec` does not change |
| Q5: `check`, `lanes` and `verify` are documented as read-only | Reconcile writes refs, never files; the docstrings say so |
| Q6: planned tests are gitignored | Trees hold tracked files only; the ledger keeps a sha256 per planned test |
| Q7: reconcile could keep adding tags across worktrees, and a same-tree refreeze clashes | Key on the entry (its unique `at`), not the tree; add a tag only when no existing commit tag is an ancestor of HEAD |
| Q8a: plans with an unset record scheme also write records into the plan JSON | Treated like `sealed` plans: the plan JSON stays writable by `record` |
| Q8b: no PowerShell write guard | A best-effort guard joins the PowerShell PreToolUse command |
| C1: the reader count missed modules | Added `plan_api.py`, `plan_doc.py` and `todo_sync/rules_plans.py:65-66` |
| C2: a skill could be named `plan-NNNN` | `strap.py new` refuses names matching `plan-[0-9]{4}` |
| C3: `plan.py` and `strap.py` are not strap-spec parts | Corrected: the SKILL.md edits are what stale the specs |
| C4: strap-skills is not frozen | Its next freeze is a first freeze straight into the ledger. write-plan migrates at its refreeze, taking seq `r3.2` |

## Work this design owes

- **write-plan:** its strap spec goes stale through SKILL.md, so it owes greens and a refreeze, which also
  migrates it to the ledger.
- **strap-skills:** its next freeze is a first freeze.
- **Release:** a harness minor version bump, with release notes.
- **Existing hand-made tags:** left as they are.

## Design review of 5beb6e0 (workflow `review-freeze-tags-spec`)

Four lens reviewers (git mechanics, plan side, strap side, lock guard and doc consistency), one adversarial
verifier per lens, and a completeness critic: 41 findings confirmed, 10 refuted, 8 more from the critic.
Full output: workflow run `wf_c9ebe190-3c1`. The spec was amended for every confirmed finding.

| Finding | Amendment | By |
|---|---|---|
| GIT-1, PLAN-1, STRAP-1 (critical): "tracked only" leaves first-freeze trees empty | Membership is "not gitignored"; an empty tree is refused | developer ("not gitignored" was the intent) |
| GIT-2, STRAP-8, GUARD-12: strap tests and `.py` fixtures are ignored and unrecorded | The `ignored` sha256 map covers every ignored file of any set | session |
| GIT-3, PLAN-11, GUARD-7, STRAP-13, CRIT-1: tag names collide across branches, renumbers, archives | Stems `plan/<no>-<slug>` and `skill/<name>`; refuse on collision before writing; plan numbers unique across branches and tags; `k` counted past existing tags | developer (skill stem: session) |
| CRIT-2: one JSON list per subject conflicts on merge | One file per ledger entry | developer |
| PLAN-3, GUARD-4, CRIT-5: no way to change a Locked plan | `plan.py unlock --arm` on the developer's permission, then `unlock` by the session when needed | developer |
| CRIT-6: driver tags pollute `git describe` | Keep `refs/tags`; document `--match 'v*'` | developer |
| CRIT-4: a rebased base cannot be re-pointed | Session-run `relink` (patch-id match or `--to`) on the developer's request | developer |
| GIT-4, STRAP-4/5, GUARD-6, PLAN-5/13: migration history entries | `history: true`, no tags or warnings, original date; `lock` refuses a legacy plan or spec until a refreeze | session |
| PLAN-4/6/8/9: state readers, sealed plans, a lost ledger, the `frozen` field | Readers mean frozen-or-locked; sealed plan JSON unlocked; a static `ledger` field in the plan JSON; `ActionPlan.frozen` stays (D1 hydrate) | session |
| CRIT-3, GIT-10, STRAP-10: gates need the tree object; working tree vs HEAD; "contract tests" | Entries store blob SHAs; gates check HEAD and a clean working tree; contract tests are the mechanical nodes plus `contract_test` parts | session |
| STRAP-2/3/6/11: strap writers, parts after Lock, write-plan parts | Every SkillSpec writer listed; `reopen` after Lock; write-plan's parts include `plan.py` and the plan library | session |
| STRAP-7: tags created inside scenario trees | Drivers skip tagging where strap's tree marker file sits | session |
| GUARD-1/2/3/8/10, CRIT-8: guard resolution, precedence, paths, wording | Folder early return, cwd resolution, deny first, POSIX paths, wording fixed | session |
| GIT-5/7/8/9, CRIT-7, PLAN-7/12: tag failure, autocrlf, follow-tags, "unreachable", `at` uniqueness, scheme pin, ledger location | Refuse-before-write and `warn:` after; wording fixed; `off-history:`; reconcile keys on the entry file; `committed_scheme` reads HEAD's ledger; ledger beside the plan file's folder | session |
