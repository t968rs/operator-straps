---
name: pr-sum-alt
description: Use when asked for a quick or cheap PR summary built only from gh commands
argument-hint: "<PR number>"
model: haiku
effort: low
---

# PR Summary (Lightweight)

Budget PR summary built from two `gh` commands.

## Data Gathering

Run these 2 commands (replace NNN). All use `gh` to read from GitHub — never local git state.

```bash
# 1. Metadata and commits
gh pr view NNN --json number,title,headRefName,baseRefName,additions,deletions,changedFiles,commits

# 2. Files changed with status (added/modified/removed/renamed); --paginate, since one page stops at 30 files
gh api --paginate repos/{owner}/{repo}/pulls/NNN/files --jq '.[] | [.status, .filename] | @tsv'
```

The file count from command 2 must equal `changedFiles` from command 1; a shortfall means a page was missed.

Derive `{owner}/{repo}` from `gh repo view --json nameWithOwner -q .nameWithOwner`.

These 2 commands are the ONLY data source for the summary content. No file diffs. No file content reads. No
local git. (Reading `.claude/harness.json` for the output directory is the one permitted file read.)

For the script-built, validated summary, use `harness:pr-sum` instead.

## Verbatim-Only Rule

Every file path and commit message MUST come directly from command output.
If it does not appear in the command results, it does not appear in the summary.
The Summary section may paraphrase. Commits and file lists are transcriptions only.

## Output Location

Summaries go to the project's configured summaries directory: the `artifacts.summaries` value in the
project's `.claude/harness.json`, or the plugin default `docs/PR_SUMMARIES` when the file or key is absent.
Read that one key; written below as `<summaries>`. The project is the git top level of the working directory.

## Markdown Template

Save to `<summaries>/{NNNN}_{Title}.md` (4-digit zero-padded PR number, underscored title).

```markdown
# PR #NNN: Title

**Branch:** <headRefName>
**Base:** <baseRefName>
**Date:** YYYY-MM-DD
**Files Changed:** N (+A / -D lines)

## Summary

2-3 sentences. What changed and why.

<details><summary>Commits</summary>
<p>

{commit oid (first 8 chars) + messageHeadline from gh pr view JSON, one per line}

</p>
</details>

## Files Changed

| File | Change | Description |
|------|--------|-------------|
| `path/to/file.py` | A | Brief description from filename context |

Change codes from `gh api` status field: added, modified, removed, renamed
```

## Chat Output

After saving, output **one line only**:

```
Saved: <summaries>/{NNNN}_{Title}.md — Merge PR #NNN: Title (headRefName -> baseRefName)
```

Suppress all progress messages, status updates, and intermediate output. Report errors only.

## Rules

- **Base branch**: Verify from `gh pr view`, never assume
- **Backticks**: Every code identifier gets backticks
- **No review language**: No verdict, status, strengths, issues, recommendations
- **No JSON**: Never produce a JSON artifact
- **No file reads**: No diffs, no file content reads (beyond the `artifacts.summaries` key above)
- **No fabrication**: Only data from command output appears in the summary
