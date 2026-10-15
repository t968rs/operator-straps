---
name: merge-commit
description: Use when asked to assemble a PR merge body from the current branch's already-written commit-message TXT files (the output of branch-commit-msg or c-msg). Triggers on "merge body", "build the merge body from the commit messages", "merge-commit". For a merge message drafted from a PR's commits, use harness:merge-commit-msg instead.
---

# merge-commit: PR Merge Body from Commit Messages

`commands/merge_body.py` consumes the commit-message `.txt` files that already exist in the project's configured
commit_messages directory (`artifacts.commit_messages`, default `docs/_commit_messages`) and writes one Markdown
merge body next to them. It never regenerates messages from git history.

## Run

From the project root, with the Bash tool:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/merge_body.py"
```

- **Exit 0** prints one line: the absolute path of `merge-body-<branch>.md`. Report that path. Do not print the
  file's contents.
- **Exit 1** prints `problem:` lines: no git repository, a detached HEAD, a missing commit_messages directory, no
  `.txt` files, or no file for the current branch. Report them verbatim and stop.

When the only problem is "no .txt file for branch", ask the developer before rerunning with `--all`, which takes
every `.txt` in the directory, including other branches' files.

## What it builds

- **Sources:** `*.txt` whose stem contains the current branch name, both sanitized (`\ / : * ? " < > |` become
  `_`), sorted by filename. Generated `.md` files are never inputs.
- **Output:** `<commit_messages>/merge-body-<sanitized-branch>.md`, UTF-8, overwritten when present.
- **Layout:**

`````markdown
## Merge Summary

Generated from existing commit-message files in `<commit_messages>/`.

## Source Files

- `<file-1>.txt`

## Commit Messages

### `<file-1>.txt`

````text
<contents of file-1, trailing whitespace trimmed>
````
`````

Each file's text is preserved inside a fence of at least four backticks, one longer than any backtick run in
the file, so fenced code inside a commit message cannot close it early.
