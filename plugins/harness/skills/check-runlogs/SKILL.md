---
name: check-runlogs
description: Use when asked to check, read or debug the latest run log (test-runner or script console output). Triggers on "check the run logs", "check-runlogs", "what failed in the last run", "why did the test run fail". Finds the newest log in the project's configured run-log folder and hands it to a read-only investigator that applies systematic debugging.
argument-hint: "[question about the run]"
---

# check-runlogs: diagnose the newest run log

The bundled command finds the log; a read-only `Explore` agent reads it and diagnoses. The log never enters the
main session's context, and the agent cannot edit files, so the diagnosis comes back before any fix starts.

## Step 1: locate the log

Run with the Bash tool from the project root:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/latest_runlog.py" --count 2
```

- **stdout** is the newest log's absolute path, then the previous one when it exists. stderr is one summary
  line (log count, folder, newest timestamp).
- The folder is `runlogs.dir` in `.claude/harness.json`; dated subfolders under it (archived logs) are searched
  too. A file counts as a log when its name fully matches `runlogs.name_pattern` (default: a name ending in
  `<YYYY-MM-DD>[_<HHMMSS>].txt` or `.log`; a date-only name sorts as midnight). The command only reads.
- When the developer names another folder, add `--dir <path>` (project-relative or absolute).
- **Exit 1** prints `problem:` lines: relay them and stop. When the problem is an unset `runlogs.dir`, show the
  key to add, for example `"runlogs": {"dir": "logs/test_runs"}`; do not guess a folder.

## Step 2: dispatch the investigator

One `Agent` call: `subagent_type="Explore"`, `model="opus"`, `description="Diagnose newest run log"`. Pass the
model explicitly; `Explore` otherwise runs a small model. The prompt is the block below with the placeholders
filled: the paths from Step 1 (`none` when only one printed), the project root, and the developer's question
(`$ARGUMENTS`), or `What failed in this run, and why?` when it is empty.

```
Run log: <newest path>
Previous run log: <second path, or none>
Project root: <absolute project root>
Question: <question>

Load the superpowers:systematic-debugging skill and apply its Phases 1-3 (root cause investigation, pattern
analysis, hypothesis) to this run. If that skill is not available, follow the steps below as written. Diagnose
only: propose no patch and change nothing, because the fix belongs to the main session.

1. The log may be large. Grep it first (Traceback, Error, FAILED, failed, ERROR, assert, Exception,
   warnings, the summary line), then Read around each hit with offset and limit.
2. When a previous log is given, compare the two runs: what newly fails, what stopped failing, what changed
   in counts or duration.
3. Trace each failure to the code it names: Read that file at the cited line and the function around it.
4. Check recent changes with read-only git: git -C "<project root>" log -5 --stat, then git diff on the files
   the failures name.
5. Separate root causes from cascades: one broken import or fixture can fail many tests.

Reply in this shape, nothing else:
Verdict: <PASSED | FAILED n | ERRORED | INCOMPLETE>, one line on what ran.
Failures: one bullet each: test or step; error; file:line; root cause (confirmed or hypothesis); evidence
(log line, code line or commit).
Changed since the previous run: bullets, or "no previous log".
Unknowns: what the log cannot answer, and the command that would answer it.
```

## Step 3: report

Relay the agent's reply as it stands, with the log path. Do not re-read the log in the main session; when the
reply leaves a question open, send the agent a follow-up instead. A fix starts only once the developer agrees,
and follows systematic debugging's Phase 4: a failing test first, then one change, then the run again.
