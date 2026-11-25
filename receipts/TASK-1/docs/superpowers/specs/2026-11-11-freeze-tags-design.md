# Freeze tags: Frozen and Locked states, a freeze ledger and driver-made tags

Issue #265 (todo-w3ck). Branch `1151-commit-tagging`, cut after PR 261 (2150-plan-refreeze) merged. Amended
after the design review of `5beb6e0` (41 confirmed findings, 8 from the completeness critic); the review
dispositions are in `docs/RESEARCH/write-plan/locking/0265_locking_design_report.md`.

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

- `plan.py` and `strap.py` build a git tree from a scoped set of **not-gitignored** files at freeze and at
  lock, and tag it at once.
- A **freeze ledger** of append-only entry files records every freeze, lock, unlock, arm, reopen and
  relink. The plan stamp moves out of the plan JSON into it; the strap stamp stays in `SkillSpec.json`
  (asymmetric, see Approaches).
- New `lock`, `unlock` (plans) and `relink` commands; `lock` is gated and run only on the developer's
  explicit ask.
- A Locked plan or spec's planning artifacts are denied to the agent's file tools and refused by the library
  writers; `check` reports drift from any other writer.
- Every driver run tags the commit that added each committed ledger entry, and adds a second tag when a
  rewrite moved that entry to a new commit.
- `plan.py new` and `strap.py new --edit` / `reopen` / `relink` tag the base commit.
- Plan numbers are unique and ascending across every branch and tag the clone can see.
- `check` warns when a necessary SHA is untagged or not on HEAD's history.
- Existing plans keep their in-file stamp until their next refreeze; existing strap specs gain a ledger at
  their next stamp-writing command (see Migration).

## Non-goals

- No pushing. Tags are local; the drivers print the push command and the developer runs it.
- No git `pre-commit` hook. The developer's own edits (IDE, shell) are not blocked; `check` reports them.
- No lock on strap **parts** (SKILL.md, scripts, agents): they are product code anywhere in the repo. They
  sit in the trees and go stale as today; on a Frozen spec a refreeze settles it, on a Locked spec `reopen`.
- No gitignored file in any tree. Planned tests, strap contract tests and `.py` fixtures
  (`docs/plans/**/*.py`, `.gitignore:241`) stay uncommitted and unpublished; their sha256 goes in the ledger.
- No tags for red or green points of a strap round, and no retagging of existing hand-made tags.
- No change to what a receipt seals. Receipt tags (below) are added beside the receipt; the receipt and its
  seal stay as they are.
- No private ref namespace: tags live in `refs/tags`.

## Approaches and decisions

| Question | Options | Picked |
|---|---|---|
| Where the stamp lives | (a) stays in the frozen file, which the tree leaves out; (b) moves to a ledger | **(b) for plans**: the plan JSON is in the freeze tree |
| Strap stamp: symmetric or kept in `SkillSpec.json` | symmetric; asymmetric | **asymmetric** (developer, after weighing the cost: `0265_strap_stamp_placement.md`) |
| How a freeze's commit gets tagged | driver-side reconcile; git `post-commit` hook; the driver commits | **driver-side reconcile** |
| Protection against the developer's own writes | `pre-commit` hook; detect only | **detect only** (developer) |
| Rewrite moved an entry to a new commit | move the commit tag; add a second | **add a second** (developer) |
| States | one; Frozen plus Locked | **Frozen plus Locked** (developer) |
| When Lock happens | automatic; explicit | **explicit** (developer) |
| Tree membership | tracked only; not gitignored | **not gitignored** (developer, after review GIT-1: "tracked" left first-freeze trees empty) |
| Existing plans and specs | migrate now; on the next pass | **on the next pass** (developer) |
| Tag names | plain `plan-<id>`; namespaced with a slug; random stem suffix | **`<kind>/plan/<no>-<slug>/...` and `<kind>/skill/<name>/...`, refuse on collision**; plan numbers made unique (developer; the skill form is the session's proposal) |
| Ledger layout | one JSON list per plan or skill; one file per entry | **one file per entry** (developer): appends from two branches never conflict |
| Design change under Lock | `--refreeze --unlock`; a standalone `unlock` | **`plan.py unlock` in two steps**: `--arm` on the developer's permission, then a plain `unlock` by the session when needed (developer) |
| Tag namespace | `refs/tags`; `refs/freeze/...` | **`refs/tags`**, with `git describe --match 'v*'` documented (developer) |
| Base lost to a rebase | nothing; a developer-run re-point; a session-run relink | **session-run `relink` on the developer's request** after the developer rebases (developer) |
| Receipt evidence lost to a rewrite | nothing (issue #265 assumed a tree cannot be tagged); tag the tested tree or commit | **`record` tags it, local only** (developer) |

## Design

### States

| | Frozen | Locked |
|---|---|---|
| **Plan** | while the plan is reviewed (`freeze`, `freeze --refreeze`) | once the frozen plan is committed (`lock`); execution runs under the lock |
| **Strap spec** | while it is tested and stress-tested (`freeze`, `freeze --refreeze`) | at branch end or merge, after freeze, nothing stale and the developer's agreement (`lock`) |
| **Who writes** | the drivers, through what each scheme already allows (plan: `write` plus `--refreeze`, receipts, `live.js`, DesignEvolution; strap: green runs, grades, `add_part`/`remove_part`, refreeze) | plan: receipts, `live.js`, DesignEvolution only (the execution record); strap: nothing until `reopen` |
| **Write guard** | today's seals only (plan freeze digest, strap `authored` seal) | the Lock guard below |

Every current reader of "is the plan frozen" (`plan.frozen is not None`, `uses_receipts`, the record gate)
means **frozen or locked**: `record`, `verify`, `lanes` and `check` treat both alike. Only `write`, the
refreeze and the guard tell them apart.

### Tree scope

Built with a temporary index (`GIT_INDEX_FILE` pointing at a scratch file) and `git write-tree`. Paths keep
their repo-relative place, so `git diff <tree-tag> HEAD -- <paths>` works. Blobs are stored as `git add`
would store them from the working tree (clean filters and `core.autocrlf` apply; a file committed with
CRLF under `text=auto` hashes as git stores it, not as LF).

**Membership is "not gitignored"**: the set's paths that `git ls-files --cached --others --exclude-standard`
lists, so a new plan JSON or a new skill's parts are in the tree before the developer commits them. Every
gitignored file of the set is left out of the tree and recorded in the entry's `ignored` map (path to sha256,
CRLF read as LF, as `strap_runs.content_hash` does). A set whose tree would be empty is refused.

| Entry | Set |
|---|---|
| Plan freeze | the plan JSON; everything under `<plan folder>/<id>/tests/` |
| Plan lock | the same set as the plan freeze |
| Strap freeze | every part at its repo path; everything under the spec folder's `tests/` and `fixtures/` |
| Strap lock | the strap freeze set plus `SkillSpec.json` |

Left out of every plan set: `receipts/`, `live.js`, `DesignEvolution.json` (the execution record, still
written under Lock) and the rendered PIP page. Planned tests, strap contract tests and `.py` fixtures are
gitignored, so they always land in `ignored`.

### Freeze ledger

One JSON file per entry, written once by a driver and never rewritten:

```
<plans>/freezes/plan/0015-freeze-tags-and-locking/r1.1-freeze.json
<plans>/freezes/plan/0015-freeze-tags-and-locking/r1.1-lock.json
<plans>/freezes/skill/write-plan/r3.2-freeze.json
```

`<plans>` is the plan file's folder (as receipts are read beside the plan file); for strap it is
`<artifacts.plans>`. The folder under `freezes/` is the subject's **stem**, which also names its tags:
`plan/<no>-<slug>` (the plan file's id and title slug, underscores as hyphens) or `skill/<name>`. A pydantic model in `harness_lib`
defines an entry; a JSON Schema is generated like the others.

Entry kinds: `freeze`, `lock`, `unlock`, `arm`, `reopen`, `relink`. Fields (names may be refined):

- `kind`; `round` (plans are always 1); `seq` (see Tags);
- `tree` (40-hex; null on `unlock`, `arm`, `reopen`, `relink` and on history entries);
- `files` (repo path to blob SHA of every tree member, so the lock gate and drift need no tree object and work
  in a clone without the tags); `ignored` (repo path to sha256);
- `at` (ISO date-time), `base` (the round's base commit, or null for a new strap skill);
- `history` (true on entries migration copies from an old stamp);
- plan: `digest` (today's freeze digest over the plan JSON) and `records` (the record scheme);
- strap: `skill_hash` and `grader`, copied from the stamp the same command writes to `SkillSpec.json`;
- `arm`: `reason`; `relink`: `old_base`, `new_base`, `match` (`patch-id` or `ref`).

**Where state is read.**

- **Plans read the ledger only.** The current state comes from the highest `r<N>.<k>` entry: `freeze` is
  Frozen, `lock` is Locked, `arm` keeps Locked and marks it armed, `unlock` is Unlocked (editable as a
  never-locked Frozen plan; its stamp is the last `freeze`). The plan JSON drops `frozen` and carries a static
  `ledger` field (the stem), set by the first ledger freeze before its tree is built: a plan whose ledger
  folder is missing then fails `check` instead of reading as never frozen. `ActionPlan.frozen` stays in the
  model (decision D1, hydrate: `load_plan` fills it from the ledger, `save_plan` omits it), so the `Mutable`
  markers, `MUTABLE_TOP` and every legacy digest stay as they are.
- **Strap specs keep their stamp.** `SkillSpec.frozen`, `rounds[]` and the `authored` seal stay as they are,
  and Frozen still means `spec.frozen is not None`. Locked is read from the ledger alone (the highest entry
  of the spec's current round, `len(rounds) + 1`, is a `lock`). The driver writes the spec stamp and the
  ledger entry in the same command; `check` reports a ledger whose last freeze `skill_hash` disagrees with
  `spec.frozen.skill_hash`.

### Commands

- `plan.py freeze` / `--refreeze`: as today, plus write a `freeze` entry, build and tag the tree. Refused on
  a Locked plan (unlock first).
- `plan.py lock <id>`: refuses unless the plan is Frozen with a ledger (a legacy plan refreezes first,
  which migrates it), its freeze digest holds, every `files` entry of the last freeze is committed at HEAD
  with the same blob and unchanged in the working tree, and every `ignored` file still has its sha256.
  Appends `lock`, tags the tree.
- `plan.py unlock <id> --arm REASON` and `plan.py unlock <id>`: two steps, so an unlock always rests on the
  developer's permission. `--arm` is run on the developer's explicit OK (given ahead of time, or when asked)
  and appends an `arm` entry; the plan stays Locked. Plain `unlock`, run by the session when a design change
  is needed, refuses without a live arm; with one it appends `unlock`, which uses up the arm, and the plan is
  editable again: `write`, `freeze --refreeze`, then `lock` after the developer commits. Hand edits stay
  denied throughout.
- `strap.py freeze` / `--refreeze`: as today, plus a `freeze` entry and tree tag. Refused on a Locked spec.
- `strap.py lock <name>`: refuses unless the spec is Frozen and not stale, its mechanical behaviors' planned
  nodes and its `contract_test` parts' nodes pass, and the last freeze's `files` and `ignored` match HEAD and
  the working tree. Appends `lock`, builds the lock tree, tags it. The skill text says the session runs it
  only on the developer's explicit ask ("agreement / post-review").
- Locked strap spec: every SkillSpec writer refuses with `<name> is locked; reopen to change it`:
  `load(writable)`, `run` (any arm), `record-run`, `retest`, `draw`, `scaffold`, every `strap.py api` call
  that saves (grades, `add_part`, `remove_part`, behaviors, scenarios) and `freeze --refreeze`.
- `strap.py reopen`: allowed on a Frozen or Locked spec. As today it moves the stamp into `rounds[]` and
  `base` to the new start; it also appends `reopen` and tags the new base.
- `plan.py relink <id> [--to REF]` and `strap.py relink <name> [--to REF]`: run by the session when the
  developer asks, after the developer rebased. The base (plan `base_commit`, strap `base`) that is no longer
  on HEAD's history is matched to its rewritten counterpart by `git patch-id` among HEAD's ancestors, or
  taken from `--to`. The driver re-points the field (plan: through the plan model, a sanctioned write on a
  Frozen or Locked plan; strap: a driver-owned field), appends `relink` and tags the new base; the old tags
  stay.
- `plan.py new`, `strap.py new --edit`: tag the base.

### Plan numbers

`plan.py new` takes one past the highest plan number it can see: the local plans folder, the plans folder
on every local and remote-tracking branch (`git for-each-ref` plus `git ls-tree`), and every
`*/plan/<no>-*` tag. A collision is then possible only with unfetched work, and the tag refusal below
surfaces it before anything is written. A plan with a ledger is never renumbered.

### Tags

Annotated tags (`git tag -a`), created locally by the drivers, in `refs/tags`. A ref cannot be both a name
and a directory (`refs/tags/a/b` and `refs/tags/a/b/c`), so suffixes use `-`:

| Tag | Points at |
|---|---|
| `base/<stem>/r<N>` | the round's base commit (plans: `r1` is `base_commit`; strap: only when `base` is set) |
| `base/<stem>/r<N>-<m>` | the m-th relinked base of round N (m from 2) |
| `freeze/<stem>/r<N>.<k>-tree` | the tree of entry `r<N>.<k>` |
| `freeze/<stem>/r<N>.<k>-commit` | the commit that added that entry's file |
| `lock/<stem>/r<N>.<k>-tree` / `-commit` | the same for a lock entry |
| `...-commit.2`, `.3` | the same entry, on a commit a rewrite produced |

`<stem>` is `plan/<no>-<slug>` or `skill/<name>`, e.g. `freeze/plan/0015-freeze-tags-and-locking/r1.2-tree`
and `freeze/skill/write-plan/r3.2-tree`.

**Sequence.** `k` counts entries of a round across kinds: one past the highest `k` in the ledger folder and
in the existing tags of that stem and round. Two branches that refreeze the same skill therefore get
`r3.2` and `r3.3`, not one name twice.

**Collision.** A command works out every tag name it will create before it writes anything. A name that
already exists on another object refuses the command with a `problem:` naming both objects; the same name on
the same object is a no-op. A git failure after the entry is written (a lock file, a full disk) prints
`warn:` and leaves the entry; `check` then reports the tag as missing and reconcile creates it.

Each command that creates tags prints one `tag: <name> -> <sha7>` line and a `push: git push origin <tags>`
line. Commit tags travel with `push --follow-tags` once their commit is pushed; tree tags never do, so the
push line names every new tag. The docs say to use `git describe --match 'v*'` where a release version is
read, since driver tags sit on main-line commits.

### Receipt tags

A receipt records the tested code only as SHA text: `record --sha` the commit and its tree, `record --staged`
the index tree (tested on a snapshot commit no ref keeps). After a reset, squash or rebase nothing references
them, and gc deletes them while the seal still checks. `record` therefore tags the tested code beside each
receipt it writes:

| `record` mode | Tag |
|---|---|
| `--sha` | `receipt/<stem>/<ITEM>-commit` on the tested commit |
| `--staged` | `receipt/<stem>/<ITEM>-tree` on the tested tree |

A second `record` of the item adds `.2`, `.3` (earlier evidence is never retargeted). Receipt tags are
**local only**: `record` prints their `tag:` lines, but no `push:` line names them, since a `--staged` tree
may hold work that is never committed. A clone that needs the evidence pushes them by hand
(`git push origin 'refs/tags/receipt/*'`). The receipt files themselves stay tracked: gitignoring them would
make plan status local to one clone (`verify`, `lanes` and `check` read them), a separate decision.

### Reconcile

Every `plan.py` and `strap.py` command reconciles the ledger folders it loads (at minimum the named plan or
spec). `check` reconciles too: it writes refs, never files, and its docstring says so (as do those of
`lanes` and `verify`).

1. For each committed, non-history entry without a `-commit` tag: the commit that added its file
   (`git log --diff-filter=A --format=%H -- <entry file>`, the oldest on HEAD's history) gets the tag.
2. For each non-history entry where **no** existing `-commit` tag is an ancestor of HEAD, but a commit on
   HEAD's history added its file, that commit gets the next `.N` suffix.
3. An uncommitted entry is skipped silently; a history entry is never tagged.

Reconcile never fails a command; a failure prints a `warn:` line.

**Scenario trees.** Strap scenario and red runs build linked worktrees of the developer's repository, and a
driver run inside one would tag the developer's refs. `strap.py`'s tree builder writes an ignored marker
file at the tree root, and the drivers skip tag creation and reconcile when the project root holds it.

### Lock guard

It covers only paths under the plans folders (`<artifacts.plans>` and its `freezes/`). Each guard resolves
the project from the payload `cwd` (`load_config(project_root(cwd))`, as the other hooks do), normalizes the
target to a repo-relative POSIX path, and returns early when it is outside. That folder test is new code; it
is not the name check `guard_commit_txt.py` uses.

- **Locked set:**
  - plan: the plan JSON (except on `sealed` and unset-scheme plans, where `record` still writes it) and its
    planned tests;
  - strap: `SkillSpec.json` and the spec folder's `tests/` and `fixtures/`;
  - always: every file under `freezes/`.
- **Write/Edit:** a new `write_pretool.py` dispatcher (decision D2) runs `guard_locked` first, then
  `guard_commit_txt`.
- **Bash:** `bash_pretool.py` runs `guard_locked` before its other hooks, since its first non-None output
  wins and two of them emit allow. The match is best-effort (`sed -i`, `>`/`>>`, `tee`, `cp`/`mv` onto a
  locked path).
- **PowerShell:** a new `powershell_pretool.py` dispatcher runs `guard_locked`, then
  `powershell_allow_shapes` (`Set-Content`, `Out-File`, `Add-Content`, `Copy-Item`/`Move-Item` onto a
  locked path).
- **Library writers:** `plan_api.write` refuses a Locked plan (armed or not: the session runs `unlock`
  first); the strap writers refuse as
  listed under Commands. `unlock`, `reopen` and `relink` are the driver ways in.
- **Detection:** `check` compares each Locked file with the last lock entry and prints
  `drift: <path> differs from <tag>`: `files` by blob SHA, `ignored` by sha256 when present, skipped when
  absent (a fresh worktree has no ignored files).
- **Exceptions the deny message names:** the plan-load repair (a plan JSON that fails to load), which on a
  Locked plan becomes the developer's hand edit, not the session's.

### check warnings

- `untagged: <sha7> (<role>)` for the base commit and each committed, non-history entry's tree and commit.
- `off-history: <sha7> (<role>)` for a base that is not an ancestor of HEAD (the cue to ask for `relink`).
- `drift:` lines as above.
- `ledger:` on a strap ledger and spec stamp that disagree.
- `legacy: plan <id> keeps an in-file stamp; migrates at its next refreeze`, and for a frozen strap spec
  without a ledger, `legacy: <name> has no ledger; one starts at its next freeze, refreeze or reopen`, with no
  tag warnings for either.

### Migration ("on the next pass")

- **Plans:** the next `freeze --refreeze` of a plan with an in-file stamp and no ledger writes a history
  `freeze` entry (`history: true`, `tree` null, `at` from the old `Frozen.date`, its `digest` and `records`),
  removes `frozen` from the JSON, sets `ledger`, then writes its own entry as `r1.2`. `lock` refuses a legacy
  plan with the refreeze it needs.
- **Strap specs:** the next `freeze --refreeze` or `reopen` writes one history `freeze` entry per `rounds[]`
  entry and one for the current stamp, each with its `base`, then its own entry. The spec's fields do not
  change. write-plan, frozen once in round 3, takes `r3.2`. `lock` refuses a spec without a ledger (it needs a
  last freeze entry with `files`) and names the refreeze.
- Base tags for the current round are created at migration; history entries get no tags and no warnings.

## Strap specs this work stales

- **write-plan:** frozen in round 3. Its parts include `plan.py` and the plan library modules this work
  rewrites, plus its SKILL.md, so it goes stale broadly; it needs greens on the new hash and
  `freeze --refreeze`, which is also its migration.
- **strap-skills:** not frozen (edit mode at `697dce2`, no behaviors yet). Its SKILL.md and templates
  change, and its next freeze is a first freeze straight into the ledger.

## Documentation

- write-plan and strap-skills SKILL.md: the two states; `lock`, `unlock` and `--arm`, `relink`; the ledger,
  the tags and the push line; the explicit-ask rule for `strap.py lock`; `git describe --match 'v*'`.
- `plugins/harness/README.md` and `schemas/README.md`: the ledger and its schema, the guard hooks.
- Release notes (`docs/RELEASES/`) and a harness minor version bump.

## Left to the builder

- Exact entry field names and the module layout.
- The temporary-index mechanics (`git add` under `GIT_INDEX_FILE`, or `update-index --cacheinfo` with
  `hash-object -w`).
- How wide reconcile scans, as long as a command stays fast with tens of ledger folders.
- The exact Bash and PowerShell write patterns the best-effort guards match.
- Test layout, following the repo's rules (`make_project`; `cross_os` markers where git paths matter).
