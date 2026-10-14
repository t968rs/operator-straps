# Commit Message Format (single commit)

Canonical anatomy of ONE Conventional Commit message as the harness commit skills write it. Shared source of
truth for the `harness:c-msg` (single commit) and `harness:branch-commit-msg` (whole-branch breakdown) skills.
When either skill drafts a commit message it conforms to this file — do not re-inline or fork these rules in a
skill body.

## Template

```
<type>(<scope>): <subject> [— <secondary qualifier>]

What changed, and why it had to when behavior differed before — 1 sentence.
  - filename: what changed in this file
  - filename: what changed in this file
  [Optional conclusion: status or result, e.g. "99/99 PASS" or "FCC-0 → COMPLETE"]

Branch: `<branch-name>`
```

The `Branch:` footer is the final-block footer of the build container; it is not part of a standalone
single-commit message. Both skills save through the plugin's `scripts/branch_commit_msg.py build`, which renders
the container in `skills/branch-commit-msg/txt_format.md` (`c-msg` as a one-block file): the footer appears on
the final commit block only, and the file header carries the branch.

## Commit types

| Type       | Use for                                                    |
|------------|------------------------------------------------------------|
| `Feature`  | New capability or extension of existing behavior           |
| `Fix`      | Corrects wrong behavior or a regression                    |
| `Refactor` | Behavior-preserving internal change                        |
| `Test`     | Test-only changes                                          |
| `Build`    | CICD / build / test-infrastructure changes                 |
| `Docs`     | Documentation                                              |
| `Chore`    | Agent config, artifacts, and other non-source housekeeping |

`Plan` is NOT a valid type. Plan documents (`ActionPlan.json`, `PIP.md`) are `Docs(plans)` or `Chore(plans)`;
plan step IDs (`FCC-1`) belong in the body or a `Refs:` footer, never the subject prefix.

**Feature vs Fix**: default to `Feature` for new or extended behavior, `Fix` for corrections. When the files alone
do not make it clear, default to `Feature` and note the ambiguity in the body.

### Bucket to type

| Bucket        | Type                                                                                                       |
|---------------|------------------------------------------------------------------------------------------------------------|
| Runtime+Test  | `Feature` or `Fix` (by the diff)                                                                           |
| Runtime       | `Refactor` (or `Feature` or `Fix` when the diff says so)                                                   |
| Test          | `Test`                                                                                                     |
| Cicd          | `Build`                                                                                                    |
| Docs          | `Docs`                                                                                                     |
| Agent or Other| `Chore` for config and housekeeping, `Feature` for a new module or tool, `Refactor` for a behavior-preserving source change |
| Artifact      | Subject only (the script adds the footer)                                                                  |

## Subject

- Lowercase after `:`, imperative or noun phrase. Aim for <=72 chars including any em-dash extension.
- Use an em dash `—` to append a secondary qualifier when the primary subject needs a framing addendum
  (e.g. `coordination gate updates — cleanup pass`).
- **Scope**: the shared parent module or directory (`billing`, `io`, `cli`). Omit when files span multiple unrelated
  modules or for a whole-project change.
- No PR numbers, issue refs, or internal class names. Move PR/issue refs to a `Refs:` body line; class names go in
  bullets.

## Body

- Prose paragraph first: what changed, and why it had to change when the previous behavior differed, in 1
  sentence (never more than 3).
- Then `  - ` bullets (2-space indent) of `filename: what changed`.
- **State facts, not qualities.** Name the concrete change (`return [] for an empty file`, `split reader into
  parse and validate`), never its virtue. Filler such as "enhance", "improve", "streamline", "robust",
  "reliability", "maintainability", "readability", "seamless", "comprehensive", "leverage" or "various" says
  nothing a reader can check; `build` rejects it.
- **Read the diff before writing.** A message drafted from filenames alone ("modify converter") is filler too.
- Optional final line: a status or result when it adds information (`→ COMPLETE`, `99/99 PASS`). Use `→` for state
  transitions.
- **Artifact / trivial chore commits**: subject + `Branch:` footer only — no body, no bullets.

### Status-aware bullets

Match the bullet verb to the file's `git diff --name-status` letter:

| Status | Bullet phrasing                                                                                    |
|--------|----------------------------------------------------------------------------------------------------|
| `A`    | What the file does and why it exists (`add`, `new`, `register`).                                  |
| `M`    | What changed; why, when the previous behavior differed.                                            |
| `D`    | A **removal** naming its replacement, no why (`oldname.py: remove; replaced by io/writer.py`). Never "add"/"new"/"register". |
| `R###` | A **relocate** with `old → new` (`smooth_simp.py: relocate geo/... → generalize/...`).            |

## Prohibitions

- **No brand or tool names** in subject/body prose or bullet descriptions (Copilot, Claude, ChatGPT, etc.). Use
  generic terms: "review", "agent", "skill", "analysis". The ban does not apply inside verbatim strings (file
  paths, verbatim PR titles).
- **No sign-offs or authoring credits**: omit `Co-authored-by:`, `Signed-off-by:`, and any author-attribution line.

## File list (when the commit block is saved to a file)

When a commit block is written to a `.txt` (so the saved paths can drive `git add`), list every file in the commit
as a PowerShell-array-friendly literal — one path per line, double-quoted, trailing comma on every line (including
the last):

```
"src/billing/config.py",
"tests/billing/test_config.py",
```

- Column 0, no leading whitespace (leading spaces break `git add` and `$files = @(...)` when pasted).
- No elision — every path, never "… N more".
- For a renamed (`R###`) file, list BOTH the old and new path so `git add $files` stages the deletion side.
- **Artifact-bucket exception** (`branch-commit-msg` only): the final `artifact` commit may use glob patterns
  (`docs/PR_REVIEWS/*.json`) in place of literal paths for machine-generated file families — see the plugin's
  `skills/branch-commit-msg/txt_format.md` "Artifact glob patterns". Every other bucket stays literal-path-only.

## Example

```
Fix(billing): add null-safety check to rate resolution

No guard existed for None values returned by the rate resolver, causing a TypeError on any run with an
unresolved rate config key.
  - config.py: add Optional handling in resolve_rate
  - test_config.py: cover None-input edge cases

Branch: `0015-billing-rates`
```
