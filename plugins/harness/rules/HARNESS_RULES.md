# Harness rules

Project-independent working rules from the `harness` plugin. Every path named below as a config key resolves
against the project's `.claude/harness.json` (merged over the plugin defaults); the project's own CLAUDE.md wins
wherever it is more specific.

## Bash discipline

- **One command per Bash call.** No `&&` or `;` chaining; the `bash_discipline` hook denies both (heredoc
  bodies, quoted text and `for` / `while` / `if` / `case` constructs are exempt).
- Absolute paths everywhere. Shell state does not persist between calls, so never rely on `cd`.
- Git runs as `git -C "<absolute-path>" <subcommand>`, never `cd <path> && git ...`.
- Interactive flags (`git rebase -i`, `git add -i`) are unavailable.
- Harness scripts run through the launcher in the Bash tool only:
  `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/<script>.py" ...`.

## Saving vs committing

- **The agent saves files; the developer commits and pushes.** No `git push`, no force-push, no commits on the
  target branch unless the current user message asks for exactly that.
- **Worktree exception:** commits inside a dedicated worktree are allowed. Only the main session moves a
  `harness:d-w` worktree back, with `harness:a-w`: staged and uncommitted by default, `--committed`
  (fast-forwarding the target to the worktree's commits) only when the current user message asks for it. a-w
  removes the worktree itself. Subagents never move or merge a worktree.
- **History rewrites belong to the developer, everywhere:** no `rebase`, `cherry-pick`, `commit --amend`,
  `reset` to drop commits, or `push`. Recommend the operation instead; subagent prompts never contain one.
- Commit messages only on explicit ask (`harness:c-msg`, `harness:branch-commit-msg`, or in words). A finished
  unit of work otherwise ends with the list of changed files.
- `harness:amend-commit-msg` rewrites only the drafted commit-message TXT file; it never runs `git commit --amend`.
- **A drafted commit message is final as saved.** When `harness:c-msg`, `harness:branch-commit-msg` or
  `harness:amend-commit-msg` returns, relay its receipt (and the TXT's text when asked) unchanged: no new
  subject, type, body or bullets, in chat or on disk, a canned message included. That saved text, quoted
  unchanged, is the proposed commit message wherever an instruction asks for one. A message changes only on the
  developer's ask: `harness:amend-commit-msg [--base <sha7>] -- <change>` for a branch TXT (the `--base` its
  draft used), `harness:c-msg <change>` for a pending TXT. `harness:c-msg` runs without arguments unless the
  developer asked for a specific change. A merge TXT follows the same rule: `harness:merge-commit-msg` `build`
  with `PR<N>_merge.txt`, changed as asked, on stdin is its change route.
- Multi-stage plans run continuously: no pause for commits between stages; save, record evidence, continue.

### Pre-merge recommendation

At PR creation, after review fixes, and on any "ready to merge?" prompt, recommend ONE strategy tied to the
branch's actual commit history, with a one-sentence rationale:

- **Squash-merge**: exploratory or WIP commits; the PR is one logical unit.
- **Merge as-is**: every commit is bisect-friendly and the narrative adds value.
- **Restructure** (`rebase -i` / `reset`, run by the developer): right content, wrong shape; say what to fold,
  drop or reorder.

## Branch and worktree flow

- **Never assume branch or PR state.** Verify merge status (`gh pr view <N> --json state,mergedAt`), tree
  cleanliness (`git -C <path> status --porcelain`) and ancestry (`git -C <path> log <base>..HEAD`) before
  stating anything about them. "Committed and pushed" describes the developer's action, not the PR's state.
- **Session start (issue-tied work):** search the issue body and comments for `BASE_BRANCH_REQUIRED`. When
  present, verify the current branch matches or abort and report; no silent checkout. Otherwise the base is the
  project's configured `base_branch` (else the branch `origin/HEAD` points at). Ask when ambiguous.
- Never branch from an integration branch unless told to; the working branch descends from the validated base.
- First status update names the lineage: `[base]-->[parent]-->[child]`.
- **Session end:** report **Branch**, **What was done**, **What's left to do**, **Issues or questions**.
- **Worktrees** live outside the project directory (an IDE indexing the workspace holds file locks on Windows).
  `harness:d-w` creates a detached worktree and prints its path. Work there with absolute paths only, commit
  coherent slices, and stage results onto the target branch only after validation and review, once the target
  branch is confirmed checked out: `harness:a-w <target>` stages them (or, on the developer's explicit ask,
  `--committed` fast-forwards the commits) and drops the worktree.

## Agent accountability

Schemas, templates and worked examples ship with the plugin (`schemas/`); a project may pin its own copies under
the configured `schemas_dir`. Work that is not tracked explicitly is work going rogue.

- Every review writes `<artifacts.reviews>/{PR}_{Title}.json` with an explicit verdict.
- Every plan not produced by a plan-writing skill that owns its own plan/spec format writes
  `<artifacts.plans>/{PR}_ActionPlan.json` **and**
  `<artifacts.plans>/{PR}_PIP.md`, updated as a pair: both written before work begins; after each task the JSON
  status and evidence update and the PIP steps are checked off atomically.
- **Status is never a claim:** `COMPLETE` requires a commit SHA; `CLOSED_NO_ACTION` requires a rationale.
- Anchor plan-state verification on the tree SHA (`git rev-parse HEAD^{tree}`), which survives rebase; fall back
  to the commit SHA for older plans.
- **File touch list:** before changing code, list the files to touch with a rationale mapped to plan items.
- **Refactoring preservation:** ordered structures stay ordered, validation stays validated, indices stay
  indexed. Audit what the original did beyond the obvious before simplifying.

## Verification

- Evidence before assertions: run the command that proves a claim and read its output before stating it.
  State ambiguity plainly instead of letting an assumption stand. This applies to docs, code comments and chat.
- After `Write` creates or fully rewrites a file, confirm it landed (a `Read` of the path, or a size and
  head/tail check) before calling it saved.
- **Test runs name files or node ids, never a directory.** A directory is not "scoped" because it is smaller
  than the whole suite. This binds subagent prompts too: every test command in a prompt names its files and the
  claim each proves. Prefer one agent owning a guard run over many re-running it.
- Full-suite runs belong to the developer. When correctness genuinely depends on one, say so and hand it over.
- Memory and earlier notes are point-in-time observations; re-check them against the current code first.

## Skill invocation at development stages

Skills outside this plugin apply when installed.

- **Writing code:** test-driven development; write or adapt the test, watch it fail, then fix.
- **Troubleshooting:** systematic debugging (`superpowers-lt:systematic-debugging`, else the bundled
  `harness:strap-debugging`); finish the diagnosis before proposing a fix.
- **Creating plans:** a written plan for any multi-task work.
- **Parallel subagent dispatch:** `harness:parallel2` first (vets the dispatch plan, prevents overlapping file
  sets), then dispatch.
- **Making claims:** verification before completion; non-negotiable.
- **Reviewing code:** `harness:pr-review` (single session) or `harness:pr-team` (parallel fan-out for PRs
  spanning several path buckets). Execute every phase of the chosen skill before stopping.
- **CI or test-infrastructure changes:** run the project's configured guard suite by file before handing off.

## Plans and specs

- Planning documents live under the configured `artifacts.planning_prefixes`; research notes under
  `artifacts.research`.
- Spec or plan changes that alter the design are catalogued in a `DesignEvolution.json` beside the plan's
  research notes, conforming to `catalogs/DesignEvolutionCatalog.schema.json` (resolved through the pinned
  schemas first, then the plugin's). Lint, guard, helper-extraction and rename changes stay out.

## Writing conventions

- No first- or second-person voice in code comments or docstrings.
- No AI vendor names in developer-facing artifacts (commits, PR bodies, PR summaries, changelogs, shipped
  docstrings).
- Skill and agent docs state what to do and why, directly: no comparisons with other skills, no postmortem
  citations.

## Red flags: stop

- "Let me just fix this quickly" -> finish the diagnosis, then document.
- "The fix is obvious, no need to discuss" -> explicit agreement required.
- "Tests pass, we're done" -> record the evidence and verify the plan docs.
- "I'll update the docs later" -> the docs update is atomic with task completion.
- "It's a one-line change to a CI script" -> run the configured guard files anyway; small CI changes regress.
- "The subagent says its tests pass" -> per-file subagent loops do not run guard suites; run them by name.
