# lap-times shows the last N laps

Date: 2026-11-20

## Request

/lap-times should take --last N and show only the last N laps of the session.

## Goals

- /lap-times accepts --last N.
- With --last N, only the last N laps of the session are shown.
- The total time of the shown laps is printed under the table.

## Avoid

- Without --last, the output does not change.
