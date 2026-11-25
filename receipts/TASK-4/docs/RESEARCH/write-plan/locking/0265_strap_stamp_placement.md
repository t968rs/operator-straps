# Strap freeze stamp: in the ledger, or in SkillSpec.json

Issue #265 (todo-w3ck), design `docs/superpowers/specs/2026-11-11-freeze-tags-design.md`. Decided
2026-11-11 on branch `1151-commit-tagging`: **asymmetric** (the strap stamp stays in `SkillSpec.json`).

## The question

The freeze-tags design moves the plan's freeze stamp out of the plan JSON into an append-only ledger under
`<artifacts.plans>/freezes/`. It has to: the plan JSON is in the plan's freeze tree, and a tree cannot
contain the file that records the tree's own SHA.

The strap spec has no such constraint. `SkillSpec.json` is in no freeze tree, because green runs, grades and
`add_part` / `remove_part` write it after a freeze by design. It is in the lock tree, but the lock entry
lives in the ledger, not in the spec, so there is no circularity either way. The choice was therefore
between symmetry with plans and leaving the strap model alone.

## Options

| | Symmetric (both stamps in the ledger) | Asymmetric (strap stamp stays in `SkillSpec.json`) |
|---|---|---|
| `SkillSpec` model | Drops `frozen` and `rounds`, adds a top-level `authored` seal. The schema is regenerated; `driver_digest` and the byte-for-byte dump rule for old specs change. | Unchanged |
| Strap readers | About 16 sites in `strap.py` and `strap_api.py` that test `spec.frozen` move to the ledger, as does the `Round.behaviors` lock (`strap_api.py:205`). | Unchanged; only the new Locked check reads the ledger |
| Existing specs | Every frozen spec (write-plan with two earlier rounds, c-msg, merge-commit-msg, writing-docstrings and others) has its stamp and round history rebuilt into the ledger on its next pass. | No strap stamp migration; the ledger starts with history entries copied from the spec |
| Source of truth | One rule for both drivers: state lives in the ledger. | Plans read the ledger. Strap reads the spec for Frozen and the ledger for Locked. The ledger repeats `skill_hash`, so two places must agree, though the driver writes both in one command and `check` reports a mismatch. |
| Tags, trees, Lock guard | Identical | Identical |

## Why asymmetric

Symmetry buys one rule for reading state. It costs the riskiest part of the change: reshaping a model whose
dump compatibility was tuned recently for `rounds[]` (the strap reopen design,
`docs/superpowers/specs/2026-11-10-strap-reopen-design.md`), and migrating every frozen spec. The protection
and browsing goals (tags, trees, Lock) come out the same either way.

## Revisit when

- A third driver gains Frozen/Locked states and a shared "state lives in the ledger" reader would pay for
  itself.
- `SkillSpec` is reshaped for another reason, which would make the migration cost incidental.
