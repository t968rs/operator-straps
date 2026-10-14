---
name: post-forcepush
description: Use when a PR's branch has been rebased / force-pushed and a previously-written PR-review JSON in the project's review directory has stale commit SHAs that need refreshing to match the new HEAD
model: haiku
effort: low
---

# Post-Forcepush JSON Metadata Refresh

Refresh commit SHAs in a PR-review JSON after a `git rebase -i` or `git reset --hard` rewrites history. Mechanical — no judgment about the review's substance, only its metadata.

## When to Use

- Branch was rebased / force-pushed; PR HEAD on GitHub is now ahead of the SHAs recorded in `<reviews>/{NNNN}_*.json`
  (`<reviews>` is `artifacts.reviews` in the project's `.claude/harness.json`).
- The body of the JSON (issues, strengths, verdict, post_review_resolutions) is otherwise correct — only SHA references need updating.

**Don't use** when the rebase squashed away a fix or changed which issues exist — that's a re-review, not a refresh; run `harness:pr-review` from scratch instead.

## Dispatch

```text
Agent: general-purpose
model: haiku
description: Post-forcepush JSON SHA refresh for PR #N
```

Hand the agent these inputs:

- PR number `[N]`
- Review JSON path `<reviews>/{NNNN}_{Title}.json` (absolute)
- Plugin root `[plugin-root]`: the absolute path `${CLAUDE_PLUGIN_ROOT}` expands to in this session
- Branch name `[branch]`
- (Optional) bootstrap-hint mapping of OLD→NEW SHAs to speed Step 2; agent verifies hints, does NOT trust them

## Prompt (paste verbatim, fill in the bracketed values)

```markdown
You are a metadata-refresh worker for a single JSON file in the repo
root `<repo-root>` (the dispatcher provides the absolute path).

PR: #[N]
Review JSON: `[review-json-abs-path]`
Plugin root: `[plugin-root]`
Branch (post-rebase): `[branch-name]`

Pre-authorized tools: Read(**), Edit(**), Bash(git -C * log *),
Bash(git -C * rev-parse *), Bash(git -C * cat-file *),
Bash(gh pr view *), Bash(gh api *), Bash(sh "[plugin-root]/scripts/hpy" *),
Skill, ToolSearch.

## Step 0 — Pre-flight precondition check (dry-run mode only)

If this dispatch is a dry-run (the dispatcher's prompt says "DRY-RUN"
or "no SHAs should have changed"), verify the precondition BEFORE
doing anything else:

  git -C "<repo-root>" rev-parse HEAD

The output must match the `head_sha` field already in the JSON. If it
does NOT match, the dry-run premise is violated — the branch has
advanced past the JSON's recorded HEAD. Abort with:

  "Dry-run precondition violated: local HEAD <sha> does not match
   JSON head_sha <sha>. Cannot test metadata-refresh workflow on a
   moving target. Either (a) re-run as a real refresh (drop the
   dry-run flag); or (b) reset the JSON to reflect a stable state."

In a real (non-dry-run) refresh, skip Step 0 and proceed to Step 1.

## Step 1 — Fetch new SHAs (self-sufficient)

The agent fetches SHAs itself; the dispatcher does NOT need to embed
them in the prompt. If the dispatcher provides "expected" SHAs as
bootstrap hints (to speed up Step 2 mapping), treat those as hints,
not authority — verify them against the live `gh pr view` output
before using.

Run, capturing stdout verbatim:

  gh pr view [N] --json headRefName,baseRefName,commits --jq '{headRefName, baseRefName, first_sha: .commits[0].oid, last_sha: .commits[-1].oid, commit_messages: [.commits[].messageHeadline]}'

Record `first_sha`, `last_sha`, and the new commit headlines.

Then expand commit-by-commit detail:

  git -C "<repo-root>" log --oneline [first_sha]^..[last_sha]
  git -C "<repo-root>" show --stat [each_sha]

Use the `--stat` output (files changed) plus the commit message
headlines to build the OLD->NEW conceptual mapping in Step 2 — the
files-touched signature is the most reliable identity signal across
a rebase that may have squashed, reordered, or renamed commits.

## Step 2 — Capture OLD SHAs BEFORE overwriting

Read the review JSON. Extract every existing SHA reference from:
- `base_sha`, `head_sha`
- `verification_log.*` sub-objects
- `verdict`, `bubble_up[*].reason`
- `post_review_resolutions[*].evidence`
- `merge_strategy_recommendation.rationale`
- `issues.*[*].description`, `strengths[*]`

Store the OLD SHA list in memory before any Edit calls. The Step 4
mapping needs both OLD and NEW; losing the OLDs mid-edit is the
classic failure mode.

## Step 3 — Refresh top-level SHA fields + verification_log

**Schema compatibility note (post-PR-#1128).** The `bubble_up` array is a required top-level field in
`PR_REVIEW.schema.json`. If refreshing a pre-PR-#1128 review JSON (one that predates the schema rename),
the JSON may lack the field; in that case, add `"bubble_up": []` during this step so the refreshed JSON
satisfies the updated schema's required-field set. All review JSONs landed after PR #1128 already carry
the field, so this guidance is preventive.

Update verbatim from Step 1:

- `base_sha`           -> Step 1 first_sha
- `head_sha`           -> Step 1 last_sha
- `review_date`        -> today's date in YYYY-MM-DD (Bash: `date +%F`)
- `verification_log.dispatch_time.pr_metadata_check.stdout` -> paste
  the JSON output of the `gh pr view` call from Step 1 verbatim,
  wrapped as a JSON string (escape internal quotes).
- `verification_log.pre_fix_time.sha_ancestry_check` -> if this
  sub-object exists (the JSON's Phase 4 has run), refresh the
  WHOLE block, not just the SHA fields. The sub-object embeds the
  old SHAs in `base_ancestor_command` / `head_ancestor_command`
  strings and records `base_ancestor_exit` / `head_ancestor_exit` /
  `result` against those old SHAs; refreshing only `base_sha` and
  `.head_sha` leaves the embedded commands and exit codes
  internally inconsistent. Re-run the merge-base checks against
  the new SHAs and rewrite the entire sub-object verbatim.
  (If `verification_log.pre_fix_time` is still the literal string
  `"pending - to be populated in Phase 4"`, leave it untouched —
  Phase 4 has not run yet for this review JSON, and refreshing
  pre-fix-time SHAs is a no-op until it does.)

## Step 4 — Refresh body-text SHA references (three-mode resolution)

For each OLD SHA captured in Step 2, decide:

- **MAPPED**: the commit still exists at the same conceptual role
  (e.g., "the spawn-stream fix commit"). Update the SHA to the new
  equivalent. Use `git log --grep="<keyword>"` or `git show --stat`
  to locate the new SHA by message body or files-touched signature.
- **SQUASHED**: the commit no longer exists (squashed away).
  Replace the SHA with `(squashed: previously <old_sha>, now in <new_sha>)`
  and keep the descriptive text.
- **NEEDS USER VERIFICATION**: cannot map old->new with confidence.
  Mark the reference with `[NEEDS USER VERIFICATION: was <old_sha>]`
  and list it in your final report.

Do NOT invent SHAs. Do NOT use placeholder strings. Only paste SHAs
you have verified via `git cat-file -e <sha>` (exit 0) or
`git rev-parse --verify <sha>^{commit}`.

## Step 5 — Schema validation

Validate the updated JSON with the harness's review gate (the schema the
project pins under its schemas_dir, else the plugin's, plus the issue-count
check). Run:

  sh "[plugin-root]/scripts/hpy" -c "import json, sys; from pathlib import Path; \
  sys.path.insert(0, r'[plugin-root]/lib'); \
  from harness_lib.review_merge import validate_review; \
  doc = json.loads(Path(r'[review-json-abs-path]').read_text(encoding='utf-8')); \
  problems = validate_review(doc, Path(r'<repo-root>')); \
  print('\n'.join(problems) or 'SCHEMA OK')"

Capture stdout and stderr; any printed line other than `SCHEMA OK` is a problem.
If validation fails: read the error verbatim, identify the offending
field, fix it (one round of edits permitted; if a second round of
schema errors appears, STOP and report).

If validation passes, capture the literal `SCHEMA OK` line as evidence.

## Step 6 — verification-before-completion skill

Invoke the `superpowers:verification-before-completion` skill via the
Skill tool. Pass it your work summary:
- Files modified (one: the review JSON).
- Schema validation result.
- Any `[NEEDS USER VERIFICATION]` markers from Step 4.
- The before/after SHAs for the refreshed fields.

Follow the skill's checklist. If the skill flags an issue you cannot
resolve, surface it in your final report — do NOT silently ship.

## Step 7 — Final report

Output, exactly in this order:

1. `OLD -> NEW SHA map` (Step 1 + Step 2).
2. List of fields updated (Steps 3 + 4).
3. List of `[NEEDS USER VERIFICATION]` markers (if any).
4. Schema validation result (Step 5): `SCHEMA OK` or the verbatim error.
5. verification-before-completion skill result (Step 6): `VERIFIED`
   or the verbatim flagged issue.
6. One-sentence verdict: "Ready for user review" OR "BLOCKED: <reason>".

Do NOT commit. Do NOT push. Do NOT modify any other files.
```

## Pre-flight

- [ ] Rebase complete; `git status` clean
- [ ] PR head pushed to GitHub (the agent reads from `gh pr view`, not local-only state)
- [ ] `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" -c "import jsonschema, referencing, pydantic"` exits 0 (the
  launcher's interpreter carries the schema-check dependencies)

## Authority Hierarchy

The agent is self-sufficient: `gh` and `git` are the authority for new SHAs. Dispatcher-provided "expected" SHAs are hints; the agent must verify them against `gh pr view` output before using.

The most reliable identity signal across a rebase is the files-touched signature (`git show --stat <new_sha>`), not the message-body — squashes change messages but rarely change which files a logical unit touches.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Agent overwrites JSON's old SHAs before reading them | Step 2 explicitly captures OLD before Step 3 mutates |
| Trusting bootstrap-hint mapping blindly | Agent verifies every hint via `git show --stat` |
| Treating squashed commits as MAPPED 1:1 | Three-mode resolution (`MAPPED` / `SQUASHED` / `NEEDS USER VERIFICATION`) is mandatory |
| Skipping `superpowers:verification-before-completion` | Step 6 is non-negotiable |

## Worked Example

A 9-commit pre-rebase history compressed to 5 post-rebase, with two squashes (two old SHAs each folding into one new SHA). Agent identified all 7 mappings via `git show --stat` signature, schema-validated, no `[NEEDS USER VERIFICATION]` markers. Total runtime ~3 minutes.
