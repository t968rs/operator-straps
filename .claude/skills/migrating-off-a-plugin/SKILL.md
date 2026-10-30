---
name: migrating-off-a-plugin
description: Use when removing operator-straps' dependence on a third-party plugin (references in skills, agents, rules, schemas or config), deleting a skill that leaned on it, or uninstalling that plugin from user, project or local scope, once its replacement skill or feature exists.
---

# Migrating off a plugin

A migration is three changes landed in order: confirm the replacement, swap the references, uninstall. Out of order, skills point at nothing. `CLAUDE.md` holds the standing rules; this skill covers the order and the traps.

## 0. Gate: is the replacement real?

For each skill or feature of the plugin that the repo uses, name its replacement and prove it exists: merged on the default branch, or installable from the marketplace, and invocable under its final name. A reference with no replacement stays. Report the unmatched list to the developer; "nothing seems to use it" is not a reason to remove.

## 1. Inventory

Search every spelling, hidden directories included, `.git` excluded: `<plugin>:`, `<plugin>@`, `<marketplace>`, the bare name. Classify each hit:

| Class | Examples | Action |
|---|---|---|
| Live prose | skills, agents, rules, README tables | edit |
| Propagating text | templates and schemas whose text is copied into consumers' plan or review files | edit; existing consumer files keep the old text |
| Path or config convention | default planning prefixes, ignore entries | a decision, often a data move; not a rename |
| Code | scripts, hooks, mods | search separately; zero hits is a finding |
| Tests and fixtures | a foreign name used as a stand-in string | leave unless the test asserts on the plugin |
| History | PR reviews, plans, research notes, PROVENANCE, release notes | never rewrite |

Then split live prose into **hard** (names the plugin's skill as the required tool of a gate, or a "non-negotiable" step) and **soft** ("when installed", "e.g.", a fallback clause). List the distinct skills referenced and which already have a replacement. Hard references need a designed replacement step; soft ones lose a clause.

## 2. Decide each reference

- **Replace**: point at the in-repo equivalent.
- **Delete**: the referencing skill existed only to chain the plugin's skills, and every skill it chains passes the Section 0 gate or the developer accepts losing the unmatched one. Delete it with every list that classifies it (a test's skill list, README tables, the marketplace line) instead of renaming through it.
- **Soften**: drop the "when installed" clause so the fallback becomes primary. A skill whose description triggers on "the plugin's skill is not installed" needs a standalone trigger.
- **Leave**: history and fixtures.

An interim bridge is allowed: a renamed fork in the marketplace lets references move before the pruning. Rename only the `<plugin>:` form, with a boundary-aware pattern so `docs/<plugin>/` paths and names like `using-<plugin>` stay. List the files first, substitute, then re-search and read what remains.

## 3. Land the change

- **Cut the worktree from the branch that receives it** when possible. `harness:a-w` measures only the worktree's own changes from its cut commit, so a cut from another branch, or from a base since squash-merged, still attaches; conflicts arise only on paths the worktree and the target both changed. Expect those when the cut base differs, and resolve them in the target.
- **Version** is the target branch's current plugin version plus a patch, never the worktree's. A `marketplace.json` conflict keeps both sides.
- Run the contract tests by file, every test that enumerates skills, and `claude plugin validate --strict` on the root and the changed plugin.

## 4. Uninstall: last, on the developer's go-ahead

This edits live configuration for every project, so it waits for the merged change above and an explicit request.

1. Read `~/.claude/plugins/installed_plugins.json` for every scope entry (user, project with its `projectPath`, local), and `enabledPlugins` in user and project settings.
2. Run `claude plugin uninstall <plugin>@<marketplace> --scope user`. For `project` or `local`, run it from that project's directory (PowerShell tool: `Set-Location <dir>; claude plugin uninstall ...` in one call, since the cwd resets after each call). A project-scope uninstall edits that project's `.claude/settings.json`, which may be a committed file in another repository: report the diff to the developer, who commits it there.
3. Search `installed_plugins.json`, the settings files and each affected project's `.claude/` for the id again.
4. Keep sibling plugins from the same marketplace and the marketplace registration when a sibling needs it.
5. The running session keeps the plugin's skills and hook text until it restarts.

## Red flags

| Thought | Reality |
|---|---|
| "Rename everything that matches" | History and fixtures are not live; the path convention is a data move. |
| "Uninstall first, then fix references" | References then name skills that do not exist. |
| "A project-scope uninstall from here will do" | It targets the current directory's project only. |
| "Nothing in code uses it" | Hard prose references are gates; deleting the plugin breaks them. |
