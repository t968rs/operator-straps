---
name: porting-into-straps
description: Use when moving a skill, agent, hook, script, library module, test or TypeScript mod from another repository (its .claude/ or scripts/ tree) into operator-straps, splitting a project-coupled file into a generic plugin half, or planning or reviewing such a transfer.
---

# Porting into operator-straps

A port is a decoupling, not a copy. Each file lands generic, so project values come from `.claude/harness.json`. It runs from an installed plugin's cache, and tests prove it against a throwaway project; each test must fail without the change. `CLAUDE.md` holds the standing rules; this skill covers the steps those rules leave to memory.

## 0. Should it move?

A file moves when its value survives without the source repo: commit tooling, review flow, guards. When the value **is** the domain content, it stays: rules about one library, one data model or one layout, where the scan flags the core text and not just paths. Do not hollow it into a generic shell plus a new config key unless a second project will use that shell. Report "stays" to the developer with the reason.

## 1. Scan the source

```bash
python .claude/skills/porting-into-straps/port_scan.py <source files or dirs>
```

The scan prints `path:line: [label] text` for every literal `tests/contract/test_no_repo_literals.py` bans, plus porting smells: inline PowerShell, bare `python`/`pytest`, `.claude/...` paths, hard-coded `docs/` folders, a `dev` branch literal, `gh api` lists without `--paginate`, un-namespaced dispatches, `sys.path` depth, unquoted `exec $VAR` and missing frontmatter. Each `banned:` line is a decoupling task. Each smell is a task or a stated false positive.

Then list what the source depends on: imports, by-path loads, skills it invokes, agents it dispatches, settings and registry entries. The dependencies either move with it or stay behind as a config key. A file "mostly copy-paste" scans clean; anything else is not.

## 2. Map each file

| Source | Destination | Invoked as |
|---|---|---|
| Skill | `plugins/harness/skills/<name>/SKILL.md` (frontmatter `name` + "Use when..." `description`) | `harness:<name>` |
| Code inside a skill (PowerShell, `python -c`) | Python: `skills/<s>/commands/` when only that skill runs it, `scripts/` when several skills or agents do, logic worth unit tests in `lib/harness_lib/` | `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/<file>.py"` (or `${CLAUDE_PLUGIN_ROOT}/scripts/...`), Bash tool |
| Agent | `plugins/harness/agents/<id>.md` | `harness:<id>` in every dispatch and table |
| Hook | `plugins/harness/hooks/<name>.py`; helper modules `_<name>.py` | shell form through `hpy` in `hooks/hooks.json`; deny via JSON `permissionDecision`, exit 0 |
| Library | `plugins/harness/lib/harness_lib/` | imported; reads `active()` inside functions |
| Test | `tests/<area>/test_<name>.py`, **one level deep** (CI collects `tests/*/test_*.py`) | `make_project` fixture |
| TS mod | `plugins/<mod>/`: manifest, `tsconfig.json`, `types/`, `.gitignore` from `git-status`; `config.ts` / `root.ts` patterns from `pr-review-watch` | `claude plugin test` |

Split a coupled file. Checks of live repo data, settings-shape asserts and domain rules stay in the source repo. Values become config keys. Fixture data is vendored into `tests/fixtures/`.

## 3. Order

1. **Verbatim import first**: paths move, content stays (renames happen in the decouple step), plus a `docs/PROVENANCE.md` row with the source SHA. Later decoupling diffs are reviewed against it. Commit it in a worktree. It is knowingly red on `test_no_repo_literals.py`; only the staged end state has to be green.
2. **Tests, red**: port or write the test against `make_project` and watch it fail on the verbatim code. When the source had no code (logic inline in a skill), the red is the missing module, then each behavior's assertion.
3. **Decouple**, then run the wire-up below.

## 4. Wire-up (each row was missed at least once)

| When the port adds | Also change |
|---|---|
| A Python script, hook or skill command | A case in `CASES` in `tests/contract/test_root_separation.py`, with the input files it needs to get past its early exits. The test checks only listed entry points, so an unlisted one passes vacuously, and a case that exits at once proves nothing. A TS mod has no case; its writes go under the project root by review |
| A config key | The four places `CLAUDE.md` names, plus a `tests/lib/test_config.py` case for its default and an override. Skill and agent prose reads it with `pr_review.py config --get <dotted.key>`. If a mod reads the key, also its `config.ts` mirror and a `tests/mods/test_<mod>_config_mirror.py` (a mod cannot read the harness plugin's `defaults.json`: separate cache dirs) |
| A plugin | `.claude-plugin/marketplace.json`, the hard-coded mod loop in `.github/workflows/ci.yml`, the README plugin table and install lines, and the mod count in `CLAUDE.md` |
| A `lib/` directory | Check `git status --ignored`: the Python template ignores `lib/` (hence `!plugins/*/lib/`, `!tests/lib/`) |
| A shell launcher | `eol=lf` in `.gitattributes`, and an executable bit if there is a shebang (Linux CI: EXE001) |
| Any plugin change | `version` in that plugin's `plugin.json`, and the PROVENANCE row |

## 5. Decoupling rules not in CLAUDE.md

- **Paths in skill text** read "the project's configured X (default Y)". Read values with `pr_review.py config --get KEY`. Never put `${CLAUDE_PLUGIN_ROOT}` in a non-raw Python string: on Windows, `\U` becomes a SyntaxError.
- Strip trailing slashes from configured directories before building prefixes.
- Branches come from `cfg.resolve_base_branch()` / `integration_branches`. The code must work in a repo with no `origin`.
- Drivers catch `ConfigError` and print `problem: ...` with exit 1. An explicit `--repo` must be a git repo. Put `--repo` on a shared parent parser.
- `sys.path` gets `parents[1] / "lib"` for scripts and hooks and `parents[3] / "lib"` for `skills/<s>/commands`. Follow the insert with `# noqa: E402`.
- `gh api` list calls get `--paginate` plus a count check against the PR's `changedFiles` / `commits`.
- Mods: a function that receives `$` from another file is a `function` declaration. Roots resolve as git top level, then `CLAUDE_PROJECT_DIR`, then cwd, matching `project_root`. Per-repository state, like Phase 5 sentinels, anchors at the main checkout (`sentinel_dir_under`), not the worktree.

## 6. A port is a review

Ported code brings the source repo's latent bugs, and its tests were written around them. Before staging, review each ported hook, approval or launcher for:

- prefix-only matching that lets `;`, newlines, `&`, `|` or `$(...)` through. Python uses `harness_lib.shell_scan.is_single_command`; a TS tokenizer gets the same cases by hand and in its tests
- unquoted shell variables
- unpaginated API lists
- silent fallbacks

## 7. Prove the tests

- **Every new or ported test fails without its change.** Revert or mutate the code and rerun. These passed vacuously during earlier ports:
  - a helper whose `git add -A` committed the file under test
  - an xfail standing in for `pytest.raises`
  - a skipif keyed on a substring of the source
  - a payload missing the field under test
- **Smoke tests run in a throwaway project** (`make_project`, or a scratch repo under the scratchpad), never in the source checkout. Pass `--root <tmp>` to anything that creates worktrees.

## 8. Verify

Run each command in its own Bash call. `python` below means an interpreter with `requirements-dev.txt` installed: pinned ruff, `jsonschema` and `pydantic`. A bare `python` on PATH may be a different environment; when it is, substitute the full interpreter path.

```bash
python -m pytest tests/<area>/test_<new>.py -q
python -m pytest tests/contract/test_no_repo_literals.py tests/contract/test_root_separation.py tests/contract/test_hooks_json_paths.py -q
python -m pytest tests/*/test_*.py -q
python -m ruff check plugins tests
claude plugin validate --strict .
claude plugin validate --strict plugins/<name>
claude plugin test plugins/<mod>
```

Skills and agents have no unit tests. Strict validation checks their frontmatter, the literal ban checks their `harness:` ids, and a load smoke proves they register: `claude -p --plugin-dir plugins/harness "list the harness: skills and agents"` from a scratch directory. `claude plugin test` does not type-check. Run `tsc` on a changed mod when it is available, or say it was not run.

## 9. Source-repo cutover is a separate change

Make it only after the plugin is installed there:
- remove the local copy, or both copies load
- add the `harness.json` keys
- drop the moved tests' registry entries
- point the source repo's docs at `harness:<name>`, the new command names or the new tool names
- for a mod, unregister the moved hook from the source mod so two guards do not both fire

Never fold it into the port.

## Red flags

| Thought | Reality |
|---|---|
| "Mostly copy-paste" | Run the scan first; the hits are the work. |
| "Every repo should get this" | If the scan flags the core text, the value is domain content; it stays. |
| "Contract tests pass" | The root-separation test passes for an entry point it does not list. |
| "Ported tests pass" | Did they fail first, for the right reason? |
| "Smoke it on the real repo" | It writes into a checkout someone works in. |
| "Fix the bug later, this is just a move" | The move is when review happens; ported approval hooks have shipped prefix-only checks before. |
