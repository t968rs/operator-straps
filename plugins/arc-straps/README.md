# arc-straps

ArcGIS Pro toolbox skills for Claude Code, one plugin beside `harness`.

## What it is

`arc-straps` holds skills that work on ArcGIS Pro toolboxes. Its first skill, `arc-meta`, checks and applies
tool help in a project's `.atbx` archive:

- **Check** (read-only): each tool's canonical help XML against its parameters, and the archive's hover text,
  "?" page and toolbox-level help against that XML (`check_canonical`, `check_applied`, `entry_sources`).
- **Apply** (dry run first): the hover text (`arc_meta_rc.py`), the "?" page (`arc_meta_page.py`) and the
  toolbox-level help (`arc_meta_toolbox.py`).

The checks and the writers share one generator (`arc_meta_format.py`), so a passing `check_applied` means the
archive holds exactly what an apply writes. Every project value (archive, XML folder, registry) comes from
`.claude/harness.json`; nothing in the plugin names a project.

## Install

```
claude plugin install arc-straps@operator-straps
```

## Requirements

- **`harness` 0.56.0 or later, enabled.** The manifest declares the dependency. Every collaborator needs it
  before a project commits a `plugins` key to `.claude/harness.json`: an older harness rejects the key, and
  every harness hook then fails on load.
- **No ArcGIS Pro.** Nothing in `arc-meta` imports arcpy; it needs the standard library, pydantic and jsonschema
  under the harness interpreter (the one `hpy` picks; pin it with `HARNESS_PY`). A future skill that imports arcpy must
  pin an ArcGIS Pro interpreter of its own.

## Boundary with harness

| Goes in `harness` | Goes in `arc-straps` |
|---|---|
| Project-independent rules, review, commit and summary tooling, worktree flow | Anything that needs ArcGIS Pro, arcpy or the `.atbx` layout |

`arc-straps` ships no launcher, no `hpy` copy and no `lib/` package. It reaches harness only through:

- `harness-skill-api`, the PATH shim harness puts on the Bash PATH, run as
  `harness-skill-api --file "${CLAUDE_SKILL_DIR}/scripts/<module>.py"`; it loads the module with its folder on
  `sys.path`, so sibling modules import by bare name.
- `harness_lib.config` (`active`, `load_config`, `ConfigError`) and
  `harness_lib.plugin_config.plugin_section`, which merges this plugin's `config/defaults.json` under the
  project's `plugins.arc-straps` section and validates it against `config/arc-straps.schema.json`.

Its tests follow the marketplace conventions: `tests/<area>/test_<name>.py` one level deep, consuming projects
built with `make_project`, never a live checkout. `strap-skills` cannot target this plugin yet, so its
judgment rules live in `SKILL.md` prose and its mechanical behaviors in pytest.

## Configuration

Set under `plugins.arc-straps.arc_meta` in the project's `.claude/harness.json`. Every key is optional;
`config/defaults.json` fills the rest. Paths are relative to the project root. The schema refuses an absolute
path, and every other schema check beyond unknown keys, only when `jsonschema` is importable: without it,
`plugin_section` rejects unknown keys and nothing else.

| Key | Default | Meaning |
|---|---|---|
| `atbx` | `null` | Toolbox archive (`.atbx`). `null` means the one `.atbx` at the project root; none or several there is a config error naming this key |
| `tool_dir` | `tool_metadata/tools` | Folder of canonical per-tool help XML, `<Tool>.xml` |
| `toolbox_source` | `null` | Toolbox-level help XML. `null` means `<parent of tool_dir>/<archive file name>.xml` |
| `registry` | `null` | Optional tool registry JSON, `{"tools": [{"tool_name": ..., "py_path": ...}]}`, for the stale-path check in `entry_sources`; `null` skips the check |

```json
{
  "plugins": {
    "arc-straps": {
      "arc_meta": {
        "atbx": "MyTools.atbx",
        "tool_dir": "tool_metadata/tools",
        "toolbox_source": null,
        "registry": "tools/registry.json"
      }
    }
  }
}
```

The skill prints the resolved locations with `print(paths())`. A new key touches `config/defaults.json`,
`config/arc-straps.schema.json`, `ArcMetaPaths` and `paths()` in `arc_meta_config.py`, and this table; harness
files do not change.

## Apply writes

- An apply rewrites the archive in place after copying it to `<archive>.bak`; the rewritten archive is
  validated before it replaces the original. Projects should gitignore `*.atbx.bak`.
- Every writer defaults to a dry run that reports what would change; `apply=True` writes.
- An `arc-straps` update can change the generator. After updating, sweep `check_applied` over `tool_names()`
  and apply the tools it flags.

## Migrating a project copy

For a project that carries its own `arc-meta` skill and apply scripts:

1. Install `harness` (0.56.0 or later) and `arc-straps`, then add the `plugins.arc-straps.arc_meta` section to
   `.claude/harness.json` (only the keys that differ from the defaults).
2. Remove the project's `.claude/skills/arc-meta/` (both copies would load), with its skill tests and test
   registry entries.
3. Delete the project's apply scripts (hover text, "?" page, toolbox help) and their tests; their commands
   become the skill's apply heredocs (a batch is a heredoc loop over `tool_names()`). Keep a project-side
   generator only while a bootstrap script still imports it, marked as such: two live generators let a
   project-side apply and the plugin's `check_applied` disagree.
4. Archive the project's frozen strap spec for `arc-meta`; it is stale against the plugin's skill.

## Checks

```
claude plugin validate --strict plugins/arc-straps
```

Source and import history: `docs/PROVENANCE.md` at the marketplace root.
