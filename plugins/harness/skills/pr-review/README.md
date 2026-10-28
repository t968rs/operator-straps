# pr-review

Agent-driven code review from capture to closeout. Reviewers read a PR through one lens each, the driver merges
their findings into one review file, and fixers work the issues in waves on the PR's branch. Fixes are planned in 
reverse-severity order, which tends to aid parallelism, but also ensures all mechanical or unambiguous issues are 
resolved by the time the `bubble` issues are presented.
- `SKILL.md` is the procedure the agent follows
- `operating_rules.md` holds the standing rules
- this file explains the shape of the fix waves, the part of Phase 5 that decides who edits what and when.

## The five phases

| Phase           | Driver command                | Result                                                                            |
|-----------------|-------------------------------|-----------------------------------------------------------------------------------|
| 1 Capture       | `capture`                     | PR metadata, structural guards, review buckets, slot plan, one brief per reviewer |
| 2 Review        | none (agent dispatch)         | One `findings/<slot>.json` per reviewer, written through `record`                 |
| 3 Consolidate   | `merge`, `amend`, `build`     | One `<reviews>/<NNNN>_<slug>.json` with a derived verdict                         |
| 4 Branch safety | `phase4_branch_safety.py`     | First run inside `build`, second run before any fix                               |
| 5 Fix           | `waves`, `bubble`, `closeout` | Fixer briefs, dispatch rows, resolutions, verdict recomputed                      |

The driver is `../../scripts/pr_review.py`; each subcommand lists its options under `--help`.

## Fix waves

`waves` turns the undispositioned issues into units, links the units that cannot run side by side, and lays them
out as waves of file-disjoint fixers. Fixers of one wave run in parallel; a wave starts only after the one before
it returns.

### From findings to fixers

```
findings ──► units ──► keys ──► groups ──► cut ──► waves ──► fixers

issue          mechanical multi-file: one unit per file; judgment: one unit over primary + also
unit           files minus tracking paths, plus widened tests and named docs
keys           owned file, widened file, serial-test lock
groups         units linked by a shared key (_components)
cut            group over 6 units: defer the most connected unit until every group fits (_cut)
wave           groups that fit; deferred units re-enter the pool (_schedule)
fixer          up to 4 per wave, then the smallest with room (_place_free)
```

### Grouping and the cut

Units that share an owned file, a widened file or a serial-test lock must be edited by one fixer, so they form a
group. A group of 6 units or fewer runs whole. A larger group loses its hub first.

```
link units sharing a file, a widened file or a serial-test lock
     │
     ▼
group of 6 or fewer? ──yes──► runs whole in one fixer of the wave
     │no
     ▼
defer the most connected unit (ties: the least severe)
     │
     ▼
units that shared a key only through it fall apart; the rest stay linked
     │
     ▼
every remaining group fits 6? ──no──► defer the next most connected unit
     │yes
     ▼
remaining groups run in this wave, in parallel
deferred units re-enter the pool and are planned the same way in the next wave
```

### Placing groups on fixers

Groups of a wave share no file and no lock. A wave opens up to 4 fixers before any fixer takes a second,
unrelated group.

```
place a group in a wave
     │
     ▼
a fixer with room holds another part of one of its issues? ──yes──► joins that fixer
     │no
     ▼
wave holds fewer than 4 fixers? ──yes──► new fixer
     │no
     ▼
some fixer has room? ──yes──► smallest fixer, one of the group's own fix kind first
     │no
     ▼
new fixer
```

Wall time follows the slowest fixer of each wave, so the plan spreads work over fixers instead of filling one to
the cap of 6 units.

### Worked example

Nine issues: a judgment issue `I1` over seven files, one mechanical minor `M1` to `M7` per file
(`mod_a.py` to `mod_g.py`), a judgment critical `C1` in `cli.py` and a mechanical minor `M8` in `docs_x.py`.

`I1` links the seven leaves into one group of 8 units, over the cap of 6. `I1` has seven links against one for
each leaf, so it is deferred; the leaves then share nothing with each other. `C1` and `M8` are separate groups.

```
wave 1   fixer 1  [C1        ]                       opus: judgment
         fixer 2  [M1][M4][M7]                       haiku: mechanical
         fixer 3  [M2][M5][M8]
         fixer 4  [M3][M6]
                  ──────── all four fixers return ────────
wave 2   fixer 1  [I1: mod_a.py .. mod_g.py]         opus: judgment

critical path: 3 + 1 = 4 ids
```

`C1`, `M1`, `M2` and `M3` open the four fixers. `M4` to `M8` join the smallest fixer with room, one of their own
fix kind first, which is why `M7` and `M8` do not land on the opus fixer holding `C1`.

### Tracking paths

A path matching `review.tracking_paths` (plans, trackers) belongs to no fixer.

```
wave reads the findings
     │
     ▼
every file of the issue is a tracking path? ──yes──► no fixer; `tracking:` row
     │no                                                   │
     ▼                                                     ▼
tracking files dropped, other files planned       main session edits them, then
     │                                            closeout --resolved <id>="what changed"
     ▼
fixer brief lists the tracking files as not its own
     │
     ▼
`tracking (after its fixer):` row ──► main session edits after that fixer's wave returns;
                                      the fixer's entry resolves the id at closeout
```

### Serial tests

A registered test that is `true` at a `tests.serial_flags` path and is not deferred holds that flag as a lock.

```
wave reads the registry
     │
     ▼
test is true at a tests.serial_flags path and not deferred? ──no──► holds no lock
     │yes
     ▼
units owning the test (file or widened file) hold the lock
     │
     ▼
two groups hold the same lock? ──yes──► linked: one fixer takes both, or different waves
     │no
     ▼
groups share a wave; the fixer record in waves.json lists its locks
```

### What the shape trades

- **Order.** A hub issue, often a judgment one spanning many files, can land in a later wave than the minors
  around it. Every issue still gets worked.
- **Links.** Units link only through shared files and locks. Two fixes that depend on each other through behavior
  alone are not linked.
- **Cap.** Six units per fixer bounds one fixer's load; the units the cut defers wait for a later wave.

## Config keys

The README table at the repository root documents each key.

| Key                        | Effect on `waves`                                 |
|----------------------------|---------------------------------------------------|
| `review.tracking_paths`    | globs of tracking documents no fixer owns         |
| `tests.serial_flags`       | registry flags whose tests never run side by side |
| `tests.defer_flags`        | registry flags whose tests no fixer runs          |
| `tests.fixer_test_seconds` | runtime ceiling above which a test is deferred    |

## Related

- `SKILL.md`: the procedure.
- `operating_rules.md`: standing rules for review JSON fields, folding, Phase 5 flow and branch checks.
- `../../lib/harness_lib/review_merge.py`: the planner (`plan_waves`).
- `../../scripts/pr_review.py`: the driver.
- `../fold-in-review/README.md`: folding outside findings into a run.
