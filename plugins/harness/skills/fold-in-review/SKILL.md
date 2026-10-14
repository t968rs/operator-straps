---
name: fold-in-review
description: Use when a GitHub PR review URL is provided during an active / nascent pr-review execution
  — fetch the external review, validate it, and merge it as an additional reviewer entry in the consolidated JSON
  after in-flight reviewers return.
---

# fold-in-review

Fold an external GitHub PR review into the active `harness:pr-review` run as a findings source. The driver
fetches, validates and records it; never map comments or edit the draft or review JSON by hand. Run it with
the Bash tool from the project checkout.

## Procedure

URL shape: `https://github.com/{owner}/{repo}/pull/{pr}#pullrequestreview-{id}` (the PR must be the run's PR).

1. Wait until every in-flight reviewer has returned (steps 3-4 apply before `build`; after it, see below).
2. Fold it, one snake_case source id per review (re-folding the same id replaces it):

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" fold --pr <N> \
     --source <login>_review --kind external --from-gh-review "<URL>"
   ```

   Exit 1 with `DISMISSED` or `blank body and no inline comments` means nothing to fold: report it and move on.
   A `review body not folded` note means the body has no file anchor; when it names a defect, fold it
   separately with `--findings` (a JSON list of findings).
3. `merge` (or `merge --force` when the draft was already amended), then grade each folded finding by blast
   radius with `amend --regrade` — every comment arrives at one severity (`minor` by default).
4. Continue the pr-review Phase 3 sequence (`build`). The folded source is credited as `<id> (external)`.

Mid-Phase 5 (review already built) the same `fold` command works: it appends the comments as new ids instead
(no `merge` / `amend` step; regrading is unavailable), then follow its `next:` line.
