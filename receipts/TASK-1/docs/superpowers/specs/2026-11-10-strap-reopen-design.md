# strap reopen: a second round of behaviors on a frozen spec

## Intent

A strap spec freezes once. After the freeze it takes part edits, green runs and a refreeze, and nothing
else: `add_behavior` refuses a frozen spec (`strap_api._load`), and `strap.py new` on an existing spec only
resumes it. A skill that later gains new rules (write-plan gained receipts, a plan-bound DesignEvolution and
the lane deviation stop in plan 1013) has no way to prove them test-first in the spec that already covers
it. `strap.py reopen` opens a new round on a frozen spec: the earlier freeze becomes history, new behaviors
join, and the next freeze gates every live behavior again.

## Goals

- `strap.py reopen <name> [--base REF]` on a frozen spec only.
- The spec keeps every behavior, scenario, draw, run and grade of the earlier rounds; new behaviors take the
  next ids (B9 after B8).
- Each earlier freeze is kept in a new driver-owned `rounds[]` list on `SkillSpec`.
- Specs written before `rounds` existed load, digest and dump byte for byte as before.
- The next `freeze` runs every gate on every live behavior, earlier ones included.

## Non-goals

- No change to the gates themselves, to `retest`, or to how a draw is picked.
- No archive of the old spec in another folder; the history stays in the one spec.
- No re-red of mechanical behaviors proven in an earlier round: their code already exists at the new base, so
  their planned tests cannot fail there.

## Approaches (picked: reopen plus rounds[])

1. **reopen plus `rounds[]`** (picked by the developer). One spec holds the whole history; earlier behaviors
   stay under the gate. Costs a model field and a byte-compatibility rule for old specs.
2. **Archive and start fresh.** `reopen` renames the folder and runs `new --edit`. Less code, but the history
   splits and B1-B8 drop out of the gate.

## Design

### Model (`strap_models.py`)

- `Round`: `base: Optional[str]` (the spec's `base` during that round), `frozen: Frozen` (the stamp it ended
  with), `behaviors: List[str]` (the live behavior ids it froze).
- `SkillSpec.rounds: List[Round]`, default empty, driver-owned (`_DRIVER_OWNED`), declared before `frozen`.
- `_dumped` drops an empty `rounds`, and `driver_digest` reads only the driver-owned names present in the
  dump, so an old spec's text, driver digest and authored digest stay byte for byte.
- `SkillSpec.schema.json` is regenerated with `tools/gen_skillspec_schema.py`.

### Driver (`strap.py`)

- `reopen <name> [--base REF]`:
  - refuses an unfrozen spec: `<name> is not frozen; nothing to reopen`;
  - resolves the base through `_edit_base` (HEAD, or an ancestor REF; the skill's SKILL.md must exist at
    HEAD);
  - appends `Round(base=<old base>, frozen=<stamp>, behaviors=<live ids>)`, clears `frozen`, sets `mode` to
    `edit` and `base` to the new base;
  - prints `reopen [done] | <name> | round <N> | base <sha12> | was <hash12>`, N the round now open
    (`len(rounds) + 1`).
- `red` covers mechanical behaviors not yet `green`: a behavior frozen green in an earlier round keeps its
  state and skips red; the freeze gate still reruns its planned tests on the working tree.
- `freeze` after a reopen prints `| was <hash12>` from the last round's stamp, as a refreeze does.
- Baseline runs of the new round carry the SKILL.md at the new base (edit mode), unchanged code path.

### Docs

- strap-skills SKILL.md step 12 gains a **Reopen for new behaviors** paragraph: when to reopen, how to pick
  the base (the commit whose code the scenarios need but whose SKILL.md lacks the new guidance), and that
  earlier behaviors are gated again.
- The strap.py docstring, the README strap row, the harness version bump (minor: a new command) and the
  release notes line.

## Constraints

- Plugins stay generic; no repo literal.
- Functions under 50 lines; `Optional`/`Union`; no first or second person in comments.
- Tests name files; the strap gate tests build projects with `make_project`.

## Left to the builder

- Wording of the SKILL.md paragraph and the refusal lines beyond those fixed above.

## After the build

Round 2 of write-plan runs inline (runner agents one at a time): `reopen write-plan --base <the commit
before the SKILL.md receipts commit>`, judgment behaviors for the receipts rules, baselines, greens, freeze.
