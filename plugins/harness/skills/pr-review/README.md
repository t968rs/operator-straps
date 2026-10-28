# pr-review

Agent-driven code review from capture to closeout. Reviewers read a PR through one lens each, the driver merges
their findings into one review file, and fixers work the issues in waves on the PR's branch. Fix waves are planned
for the shortest estimated wall time rather than in severity order, and every wave returns before the `bubble`
issues are presented, so all mechanical or unambiguous issues are resolved by then.
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
cut            group over 6 units: defer units until every group fits (_cut), by one of two rules
wave           groups that fit; deferred units re-enter the pool (_schedule)
fixer          up to 4 per wave, then the smallest with room (_place_free)
choice         the whole layout is planned once per cut rule; the lower estimated wall time wins (_wall_seconds)
```

A **heavy** unit is a judgment fix of a critical or important issue (`_heavy`). Mechanical parts and minor issues
are light. Heavy units set a fixer's wall time, so the cut and the placement both steer around them.

### Grouping and the cut

Units that share an owned file, a widened file or a serial-test lock must be edited by one fixer, so they form a
group. A group of 6 units or fewer runs whole. A larger group is cut.

```
link units sharing a file, a widened file or a serial-test lock
     │
     ▼
group of 6 or fewer? ──yes──► runs whole in one fixer of the wave
     │no
     ▼
defer one unit:
  most-connected cut   the most connected unit (ties: the least severe)
  light-first cut      the most connected light unit; a heavy one only when no light one is left
     │
     ▼
units that shared a key only through it fall apart; the rest stay linked
     │
     ▼
every remaining group fits 6? ──no──► defer the next unit by the same rule
     │yes
     ▼
remaining groups run in this wave, in parallel
deferred units re-enter the pool and are planned the same way in the next wave
```

The most-connected cut breaks a hub's group apart, so its leaves run in parallel while the hub waits. The
light-first cut keeps heavy work in the first wave, beside the other groups' fixers rather than after them, and
leaves the cheap units for later waves.

### Choosing the layout

`waves` plans the full layout under each cut and keeps the one with the lower estimated wall time; a tie keeps
the most-connected cut. A wave lasts as long as its slowest fixer, and the waves run one after another:

```
haiku fixer    25 s + 7 s per unit
opus fixer     20 s + 65 s per heavy unit + 30 s per minor judgment unit + 10 s per mechanical part
layout         sum over the waves of the slowest fixer
```

The figures are calibrated on recorded fixer runs. Only their ratios steer the choice.

### Placing groups on fixers

Groups of a wave share no file and no lock. A wave opens up to 4 fixers before any fixer takes a second,
unrelated group.

```
place a group in a wave
     │
     ▼
a fixer with room holds another part of one of its issues,
and no heavy unit? ──yes──► joins that fixer
     │no
     ▼
wave holds fewer than 4 fixers? ──yes──► new fixer
     │no
     ▼
some fixer has room? ──yes──► smallest fixer: one of the group's own fix kind first,
     │no                       then one holding no heavy unit
     ▼
new fixer
```

Wall time follows the slowest fixer of each wave, so the plan spreads work over fixers instead of filling one to
the cap of 6 units. A fixer holding a heavy unit is usually that slowest fixer, so it takes no extra group while
another place exists.

### Worked examples

Nine issues: a judgment issue `I1` over seven files, one mechanical minor `M1` to `M7` per file
(`mod_a.py` to `mod_g.py`), and a mechanical minor `M8` in `docs_x.py`.

`I1` links the seven leaves into one group of 8 units, over the cap of 6. The most-connected cut defers `I1`,
which has seven links against one for each leaf; the leaves then share nothing with each other. The light-first
cut defers `M7` and `M6` instead, keeping `I1` and five leaves on one opus fixer (135 s, then 32 s for wave 2:
167 s). The most-connected layout is cheaper:

```
wave 1   fixer 1  [M1][M5]                           haiku: mechanical    39 s
         fixer 2  [M2][M6]                                                39 s
         fixer 3  [M3][M7]                                                39 s
         fixer 4  [M4][M8]                                                39 s
                  ──────── all four fixers return ────────
wave 2   fixer 1  [I1: mod_a.py .. mod_g.py]         opus: judgment       85 s

estimated wall: 39 + 85 = 124 s
```

`M1` to `M4` open the four fixers; `M5` to `M8` join the smallest fixer with room.

Add two judgment criticals, `C1` and `C2`, in `cli.py`. They share a file, so they form one group and one opus
fixer of 150 s. The most-connected cut would now queue `I1` behind that fixer (150 s, then 85 s: 235 s). The
light-first cut runs `I1` beside it and leaves two cheap leaves for wave 2:

```
wave 1   fixer 1  [M1][M2][M3][M4][M5][I1]           opus: judgment      135 s
         fixer 2  [C1][C2]                           opus: judgment      150 s
         fixer 3  [M8        ]                       haiku: mechanical    32 s
                  ──────── all three fixers return ────────
wave 2   fixer 1  [M6        ]                       haiku: mechanical    32 s
         fixer 2  [M7        ]                                            32 s

estimated wall: 150 + 32 = 182 s
```

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

- **Order.** Under the most-connected cut, a hub issue, often a judgment one spanning many files, can land in a
  later wave than the minors around it; under the light-first cut, minors can land after the critical work.
  Every issue still gets worked.
- **Estimate.** The layout choice rests on fixed per-unit seconds, not on the size of each fix. Two layouts
  close in estimate can trade places on real runs.
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
