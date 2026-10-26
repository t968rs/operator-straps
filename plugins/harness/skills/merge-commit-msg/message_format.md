# Merge Message Format

Layout of the `text` fence in `PR<N>_merge.md`, which `merge_commit_msg.py build` copies to
`PR<N>_merge.txt`. Every line sits at column 0 except the file bullets (two-space indent). No markdown fence, no
backtick wrapper around the whole message: select-all in the TXT is the pasteable merge body.

## Layout

```
Merge PR #NNN — <PR title verbatim>

<"What + why" prose. Lead with the action; explain the underlying problem. Wrap lines at ~110 columns; split
multi-sentence content into 2-3 short paragraphs.>

  - filename.py: key change
  - filename.py: key change

Branch lineage: `<base>` -> `<parent if any>` -> `<head>`

<Optional "Also lands" paragraph>

<Optional "Companion docs:" line>

Review artifacts: <{reviews}/{NNNN}_*.json path>.
Includes N review fixes (Critical: N, Important: N, Minor: N).
```

## Section order (fixed)

1. Subject line (`Merge PR #NNN — <title>`), script-filled.
2. Prose paragraph(s).
3. Bullets: 4-7 representative files from Changed files, `  - filename: key change`. Curate to the changes that
   explain the PR; never enumerate every file.
4. `Branch lineage:` (script-filled; backticked names). Build rejects a lineage line above the last bullet.
5. Optional `Also lands` paragraph: secondary scope that travelled with the primary change. Omit when the PR has
   one logical scope. Break a long parenthetical across lines at comma boundaries.
6. Optional `Companion docs:` followed by comma-separated repo-relative paths with parenthetical annotations,
   only when the diff holds companion documentation. Never URLs.
7. `Review artifacts:` and `Includes N review fixes (...)` (script-filled, only when a review JSON exists). No
   verdict prefix; no individual issue IDs (C1, I2, M3).

## Rules

- **Verbatim title.** The subject is exactly `Merge PR #NNN — <title>`; build compares it with the captured title.
- **No commit SHAs.** The merge UI records them. Build rejects a hex run of 7-40 characters holding a digit.
- **No placeholders left.** Build rejects any line that is a bare `<...>` or `  - <...>`.
- **No vendor or tool names** in prose or bullets (verbatim paths and the verbatim title are exempt), and no
  filler words (enhance, improve, streamline, robust, reliable, maintainable, readable, seamless, comprehensive,
  leverage, various): name the change instead.
- **No emojis, no marketing voice, no sign-offs or authoring credits** (`Co-authored-by:`, `Signed-off-by:`).
- **No invented content.** No follow-up tracking, issue numbers or "also lands" scope the PR does not have.
- **No forward PR references by number.** Write "next PR" or "follow-up PR".
- **Plan step IDs match the plan** exactly (`FCC-1`), never "Phase 5" or "Step 3".
- **Length.** 10-20 lines of body, bias shorter; build rejects more than 30 lines and any line over 110 columns.

## Worked example (PR #887)

```
Merge PR #887 — [BUG] Worker pool crash on spawn

Diagnoses and fixes a BrokenProcessPool failure in the export ProcessPoolExecutor.
Spawned children under pythonw.exe attach to invalid stdio handles; a defensive
_silence_invalid_streams() helper at init_worker entry prevents the OSError cascade.

  - workers/export.py: add _silence_invalid_streams() worker guard
  - test_export_full_run.py: full-run integration test
  - worker_utils.py: CPU-scaling worker-count helper
  - probe_stdio.py: diagnostic probe used to isolate root cause

Branch lineage: `main` -> `250-TEST-export_full_run` -> `850-BUG-worker_spawn`

Also lands diagnostic probe infrastructure and a CPU-scaling worker-count helper uncovered
during the investigation.

Companion docs: docs/RESEARCH/workers/spawn_debug.md (diagnostic chain),
docs/RESEARCH/workers/init_worker_snapshot.md (research).

Review artifacts: docs/PR_REVIEWS/0887_BUG_worker_spawn.json.
Includes 24 review fixes (Critical: 1, Important: 11, Minor: 12).
```

Receipt (the only chat output):

```
Saved: docs/_commit_messages/PR887_merge.txt - merge message for PR #887
Subject: Merge PR #887 — [BUG] Worker pool crash on spawn
Final as saved: ...
```
