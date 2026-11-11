# Freeze tags: Frozen and Locked states, a freeze ledger and driver-made tags

Issue #265 (todo-w3ck). Branch `1151-commit-tagging`, cut after PR 261 (2150-plan-refreeze) merged.

## Intent

Plans (`plan.py`) and strap specs (`strap.py`) name commits the drivers read later: a plan's `base_commit`
(anchors and sweeps are read there once an item is done) and a strap spec's `base` (the baseline arm reads
the SKILL.md there, runs start there, `reopen` refuses a base that does not descend from it). A squash or
rebase can orphan those commits; garbage collection then drops them and the drivers fail on a SHA that no
longer exists. The developer has been tagging such commits by hand, with no consistent names, and kept
`9368d9e` alive for PR 266 only through a "merge, never squash" rule.

The developer wants a tag protocol that does both:

1. **Protects** every commit a driver reads from a history rewrite.
2. **Makes the history browsable**: where a plan or skill was frozen or locked, exactly what was frozen,
   and how it has drifted since.

Tags are created by the drivers, never printed as suggestions or left to memory.

Two further goals came out of the design:

- A freeze **identifies exactly the files it froze**, as a git tree object, instead of naming the whole
  repository's HEAD (today's plan `frozen.commit` / `frozen.tree`) or a sha256 git cannot tag (today's strap
  `skill_hash`).
- A plan or skill has **two states**: **Frozen** (pinned, but the drivers still write their sanctioned
  records) and **Locked** (final; its planning artifacts are write-protected).

## Goals

- `plan.py` and `strap.py` build a git tree from a scoped set of **tracked** files at freeze and at lock,
  and tag it at once.
- A **freeze ledger** under `<artifacts.plans>/freezes/`, one file per plan or skill, append-only, records
  every freeze, lock, unlock and reopen with its tree. The plan stamp moves out of the plan JSON into it;
  the strap stamp stays in `SkillSpec.json` (asymmetric, see Approaches).
- New `plan.py lock` and `strap.py lock` commands, gated and run only on the developer's explicit ask.
- A Locked plan or spec's planning artifacts are denied to the agent's file tools and refused by the library
  writers; `check` reports drift from any other writer.
- Every driver run tags the commit that first holds a committed ledger entry, and adds a second tag when a
  rewrite moved that entry to a new commit.
- `plan.py new` and `strap.py new --edit` / `reopen` tag the base commit.
- `check` warns when a necessary SHA is untagged or unreachable.
- Existing plans and specs keep their in-file stamp until their next pass (see Migration).

## Non-goals

- No pushing. Tags are local; the drivers print the push command and the developer runs it.
- No git `pre-commit` hook. The developer's own edits (IDE, shell) are not blocked; `check` reports them.
- No lock on strap **parts** (SKILL.md, scripts, agents): they are product code anywhere in the repo. They
  sit in the trees, go stale as today, and a refreeze settles it.
- No gitignored file in any tree. Planned tests (`docs/plans/**/*.py`, `.gitignore:241`) stay uncommitted
  and unpublished.
- No tags for red or green points of a strap round, and no retagging of existing hand-made tags.
- No change to what a receipt seals.

## Approaches and decisions

| Question | Options | Picked |
|---|---|---|
| Where the stamp lives | (a) stays in the frozen file, which the tree leaves out; (b) moves to a ledger | **(b) for plans**: the plan JSON is in the freeze tree, so its stamp must leave it |
| Strap stamp: symmetric with plans, or stays in `SkillSpec.json` | symmetric (ledger only); asymmetric (spec keeps `frozen` and `rounds[]`, ledger records trees and Lock) | **asymmetric** (developer, after weighing the cost: `docs/RESEARCH/write-plan/locking/0265_strap_stamp_placement.md`). `SkillSpec.json` is in no freeze tree, so its stamp causes no circularity; the lock tree holds it, but the lock entry lives in the ledger |
| How a freeze's commit gets tagged | driver-side reconcile; git `post-commit` hook; the driver commits the stamp itself | **driver-side reconcile**: no change to how the developer works; the hook is per-clone and unversioned; a driver commit breaks "the developer commits" |
| Protection against the developer's own writes | `pre-commit` hook; detect only | **detect only** (developer: "Claude and the drivers are blocked, check reports anything else") |
| Rewrite moved a freeze to a new commit | move the commit tag; add a second | **add a second**: the old tag keeps the original commit alive |
| One freeze state or two | one; Frozen plus Locked | **Frozen plus Locked** (developer) |
| When Lock happens | automatically when the gate first holds; explicit | **explicit**, on the developer's "ready to lock" |
| Planned tests in trees | include them; tracked files only | **tracked files only** |
| Existing plans and specs | migrate now; on the next pass | **on the next pass** |

## Design

### States

| | Frozen | Locked |
|---|---|---|
| **Plan** | while the plan is reviewed (`freeze`, `freeze --refreeze`) | once the frozen plan is committed; execution runs under the lock |
| **Strap spec** | while it is tested and stress-tested (`freeze`, `freeze --refreeze`) | at branch end or merge, after freeze, nothing stale and the developer's agreement |
| **Who writes** | the drivers, through what each scheme already allows (plan: `write` plus `--refreeze`, receipts, `live.js`, DesignEvolution; strap: green runs, grades, `add_part`/`remove_part`, refreeze) | plan: receipts, `live.js`, DesignEvolution only (the execution record); strap: nothing until `reopen` |
| **Write guard** | today's seals only (plan freeze digest, strap `authored` seal) | the Lock guard below |

### Tree scope

Built with a temporary index (`GIT_INDEX_FILE` pointing at a scratch file) and `git write-tree`. Paths keep
their repo-relative place, so `git diff <tree-tag> HEAD -- <paths>` works. Blobs go through git's clean
filters, so a `core.autocrlf` checkout hashes as committed content. **Only tracked files go in**: a path
that `git ls-files` does not list, or that `.gitignore` excludes, is left out.

| Entry | Tree holds (tracked files only) |
|---|---|
| Plan freeze | the plan JSON; tracked files under `<artifacts.plans>/<id>/tests/` |
| Plan lock | the same set as the plan freeze: the lock confirms the frozen design is committed |
| Strap freeze | every part at its repo path; tracked files under the spec folder's `tests/` and `fixtures/` |
| Strap lock | the strap freeze set plus `SkillSpec.json`: the whole record of the round |

Left out of every plan tree: `receipts/`, `live.js`, `DesignEvolution.json` (the execution record, still
written under Lock) and the rendered PIP page.

**Untracked planned tests** are not in the tree. The ledger entry records each one's path and sha256 (CRLF
read as LF, as `strap_runs.content_hash` does). The Lock guard covers them, and `check` compares them when
present and skips them when absent (a fresh worktree has none).

The plan's `frozen.commit` and `frozen.tree` (HEAD and the whole repository's tree) are dropped.

### Freeze ledger

`<artifacts.plans>/freezes/plan-<id>.json` and `<artifacts.plans>/freezes/strap-<name>.json`: a list of
entries, appended by the drivers and never rewritten. A pydantic model in `harness_lib` defines it, with a
JSON Schema generated like the others.

Entry kinds: `freeze`, `lock`, `unlock` (plans) and `reopen` (strap). Fields (the builder may refine names):

- `kind`; `round` (plans are always 1); `seq` (the k-th entry of its kind in the round);
- `tree` (40-hex; null on `unlock` and `reopen`); `files` (the tracked repo paths in the tree, sorted);
- `untracked` (path to sha256, for planned tests);
- `at` (ISO date-time; it also makes each entry's text unique, which reconcile relies on);
- `base` (the commit the round started from, or null for a new strap skill);
- plan: `digest` (today's freeze digest over the plan JSON) and `records` (the record scheme);
- strap: `skill_hash` and `grader`, copied from the stamp the same call writes to `SkillSpec.json`.

**Where state is read.**

- **Plans read the ledger only.** Frozen means the last entry is a `freeze`, Locked a `lock`. The plan JSON
  drops `frozen`, and every reader of it moves to the ledger. A sweep is required; known readers today:
  `plan.py`, `plan_api.py` (`_OWNERS`, the execution-field gate on `disk["frozen"]`), `plan_doc.py` (digest
  and `MUTABLE_TOP`), `plan_record.py`, `plan_receipts.py`, `plan_render.py`, `plan_render_html.py`, and
  `todo_sync/rules_plans.py:65-66` (reads `frozen.records` from the raw plan JSON; it would otherwise treat a
  receipts plan as non-receipts and raise false P1 findings).
- **Strap specs keep their stamp.** `SkillSpec.frozen`, `rounds[]` and the `authored` seal stay as they are,
  and Frozen still means `spec.frozen is not None`. Locked is read from the ledger alone (the last entry of
  the current round is a `lock`); `SkillSpec` gains no field. The driver writes the spec stamp and the ledger
  entry in the same command; `check` reports a strap ledger whose last `freeze` disagrees with
  `spec.frozen.skill_hash`.

### Commands

- `plan.py freeze` / `--refreeze`: as today, plus write a `freeze` entry, build and tag the tree. On a
  Locked plan, `--refreeze` refuses without `--unlock`. With `--unlock` (a design change after the lock,
  developer's OK, as any refreeze), the driver appends `unlock` and then the new `freeze`. The developer
  locks again after committing.
- `plan.py lock <id>`: refuses unless the plan is Frozen, its freeze digest holds, and the tracked files of
  the last freeze tree match HEAD (the frozen plan is committed). It appends `lock` and tags the tree.
- `strap.py freeze` / `--refreeze`: as today, plus a `freeze` entry and tree tag. Refused on a Locked spec.
- `strap.py lock <name>`: refuses unless the spec is Frozen and not stale, its contract tests pass, and the
  parts at HEAD match the last freeze tree. It appends `lock`, builds the lock tree and tags it. The skill
  text says the session runs it only on the developer's explicit ask ("agreement / post-review").
- `strap.py reopen`: allowed on a Frozen or Locked spec. As today it moves the stamp into `rounds[]` and
  `base` to the new start; it also appends `reopen` and tags the new base. A locked round's tags are permanent history.
- `plan.py new`, `strap.py new --edit`: tag the base.

### Tags

Annotated tags (`git tag -a`), created locally by the drivers. A ref cannot be both a name and a directory
(`refs/tags/a/b` and `refs/tags/a/b/c`), so suffixes use `-`:

| Tag | Points at |
|---|---|
| `base/<name>/r<N>` | the round's base commit (plans: `r1` is `base_commit`; strap: only when `base` is set) |
| `freeze/<name>/r<N>.<k>-tree` | the k-th freeze tree of round N |
| `freeze/<name>/r<N>.<k>-commit` | the first commit holding that ledger entry |
| `lock/<name>/r<N>.<k>-tree` / `-commit` | the same for the k-th lock (plans can unlock and relock) |
| `...-commit.2`, `.3` | the same entry, on a commit a rewrite produced |

`<name>` is the skill name, or `plan-<id>` for a plan. `strap.py new` refuses a skill name matching
`plan-[0-9]{4}`. Plan ids collide across branches by design, so `plan.py new` and the renumber rule also
skip an id that any `*/plan-<id>/*` tag already holds.

An existing tag of the same name on the same object is a no-op; on another object it is a `problem:` that
names both. The tag message names the plan or skill, the round, the entry kind and the ledger file. Each
command that creates tags prints one `tag: <name> -> <sha7>` line and a `push: git push origin <tags>` line.
Tree tags do not travel with `push --follow-tags`, and commit tags are annotated, so `--follow-tags` carries
them.

### Reconcile

Every `plan.py` and `strap.py` command reconciles the ledger files it loads, at minimum the named plan or
spec. The builder may widen it if the cost stays bounded. `check` reconciles too: it writes refs, never
files, and its docstring says so (as do those of `lanes` and `verify`).

1. For each committed entry without a `-commit` tag: find the commit that added the entry's text
   (`git log -S<entry's at> -- <ledger file>`, oldest hit on HEAD's history) and tag it. The entry, not the
   tree, is the key: a refreeze with unchanged parts produces the same tree as the entry before it.
2. For each entry where **no** existing `-commit` tag is an ancestor of HEAD, but a commit on HEAD's history
   holds the entry, tag that commit with the next `.N` suffix. Checking "no tag", rather than "the newest
   tag", stops worktrees on both sides of a rewrite from adding tags back and forth.
3. An uncommitted entry is skipped silently.

Reconcile never fails a command; a failure prints a `warn:` line.

### Lock guard

It covers only paths under `<artifacts.plans>`, so every guard can return early on any other path. That is
the cheap path `guard_commit_txt.py:110` already uses.

- **Locked set:**
  - plan: the plan JSON and its planned tests, tracked or not;
  - strap: `SkillSpec.json` and the spec folder's `tests/` and `fixtures/`;
  - always: the ledger files.
- **Write/Edit:** the guard joins `hooks/guard_commit_txt.py`'s command, which becomes a dispatcher with a
  `COMPOSED` entry (the one-launch-per-event rule).
- **Bash:** a best-effort path match joins `bash_pretool.py` (`sed -i`, `>`/`>>`, `tee`, `cp`/`mv` onto a
  locked path).
- **PowerShell:** a best-effort match joins the PowerShell PreToolUse command (`Set-Content`, `Out-File`,
  `Add-Content`, `Copy-Item`/`Move-Item` onto a locked path). The command becomes a dispatcher if it is not
  one already.
- **Library writers:** `plan_api.write` refuses a Locked plan. The strap API's save refuses a Locked spec.
  `reopen` and `freeze --refreeze --unlock` are the only ways out.
- **Detection:** `check` compares each Locked file with the last lock entry and prints
  `drift: <path> differs from <tag>`. Tracked files are compared with the tree, untracked planned tests with
  their sha256.
- **The plan-load repair exception** (a plan JSON that fails to load) remains the developer's hand edit.
  The guard's denial message says so.

### check warnings

- `untagged: <sha7> (<role>)` or `unreachable: <sha7> (<role>)` for:
  - the plan's `base_commit`;
  - the strap spec's current `base`;
  - each committed freeze or lock entry's tree and commit.
- Earlier rounds' bases are history only and are not checked.
- `drift:` lines as above.
- `legacy: <name> keeps an in-file stamp; migrates at its next pass`, with no tag warnings for that plan or
  spec.

### Migration ("on the next pass")

A plan or spec with an in-file stamp and no ledger works as today until its next stamp-writing command:
`freeze --refreeze`, `lock`, or (strap) `reopen`. That command:

1. writes a ledger whose first entries carry the old stamps as history, with `tree` null:
   - a plan: one `freeze` entry;
   - a strap spec: one `freeze` per entry of `rounds[]`, then the current stamp, each with its `base`;
2. removes the plan's in-file `frozen` (a strap spec keeps its fields; nothing in it changes);
3. carries out its own command as a new entry, with seq continuing after the history in the same round
   (write-plan, today in round 3 with one freeze, takes `r3.2`);
4. tags the current base.

Plans whose record scheme is `sealed`, or unset (both still write records into the plan JSON,
`plan_record.py:66-68`), keep the plan JSON writable by `record` under Lock. Only their planned tests
lock.

### Plan renumbering

A plan moved to the next free id moves its ledger file with it. Its tags keep the old id in their names,
and the tag message records the move. Renumbering stays a manual act. The guard's denial message for a
ledger file names the renumber exception, which the developer performs.

## Strap specs this work stales

- **write-plan:** frozen in round 3. Its SKILL.md part changes (Frozen/Locked, lock, tags, ledger), so it
  goes stale and needs greens on the new hash and `freeze --refreeze`. That refreeze is also its migration
  to the ledger.
- **strap-skills:** not frozen (edit mode at `697dce2`, no behaviors yet). Its SKILL.md and templates
  change, and its next freeze is a first freeze straight into the ledger.
- Today's `plan.py`, `strap.py` and their library modules are not parts of either spec.

## Documentation

- write-plan and strap-skills SKILL.md:
  - the two states and the `lock` commands;
  - the ledger and the tags;
  - the push line;
  - `--unlock`;
  - the explicit-ask rule for `strap.py lock`.
- `plugins/harness/README.md` and `schemas/README.md`: the ledger and its schema.
- Release notes (`docs/RELEASES/`) and a harness minor version bump.

## Left to the builder

- Exact ledger field names and the module layout.
- The temporary-index mechanics (`update-index --cacheinfo` with `hash-object -w`, or `git add` under
  `GIT_INDEX_FILE`).
- How wide reconcile scans, as long as a command stays fast with tens of ledger files.
- The exact Bash and PowerShell write patterns the best-effort guards match.
- Test layout, following the repo's rules (`make_project`; `cross_os` markers where git paths matter).
