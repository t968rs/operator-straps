# strap.py rename does the moves and the name swap

Date: 2026-11-25

## Request

strap.py rename should do the work it now leaves to the developer: move the skill folder and every part made
from the old name, swap the old name's kebab, snake and title forms inside the moved parts, and only report
the old name where it lingers outside them. Test files the spec's planned tests cite follow the rename too. A
skill renamed before this change, spec-it, finishes its rename with the new command, so its leftover old-named
test files take its name.

## Goals

- strap.py rename moves the skill folder and every part made from the old name itself, on any OS.
- strap.py rename --dry-run prints each move and changes nothing.
- A rename refuses before any move when a move target already exists.
- A rename that fails part way leaves the skill folder, the parts and the spec as they were.
- Inside the moved parts, the old name's kebab, snake and title forms become the new name's.
- Each swap inside a part prints one line naming the file and the line.
- A test file named from the old name that a planned test cites moves to the new name, and the planned test follows it.
- Each other tracked file that still names an old form prints one line naming the file and the line.
- After rename [done], strap.py check on the new name reports no name problem.
- A tree the developer already moved by hand still renames.
- A skill renamed before this change can finish its rename, so its old-named test files and planned tests take the new name.
- spec-it's four test files and its spec carry the spec-it name.

## Avoid

- A file outside the parts and the cited test files is rewritten.
- A recorded reply changes.
- rename emits a shell script.
