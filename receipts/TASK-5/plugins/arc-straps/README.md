# arc-straps

ArcGIS Pro toolbox skills for Claude Code, one plugin beside `harness`.

## What it is

`arc-straps` holds skills that work on ArcGIS Pro toolboxes. Its first skill, `arc-meta`, checks and applies
tool help in a project's `.atbx` archive:

- **Check** (read-only): each tool's canonical help XML against its parameters, and the archive's hover text
  and "?" page against that XML (`check_canonical`, `check_applied`, `entry_sources`). The checks are per
  tool; toolbox-level drift shows only in the `apply_toolbox` dry run (`UNCHANGED` versus `DRY-RUN`).
- **Apply** (dry run first): the hover text (`arc_meta_rc.py`), the "?" page (`arc_meta_page.py`) and the
  toolbox-level help (`arc_meta_toolbox.py`).

The checks and the writers share one generator (`arc_meta_format.py`), so a passing `check_applied` means the
tool's hover text and "?" page hold what an apply writes. Two hover states the hover writer leaves alone (a
`tool.content` reference to a key the rc lacks, and a literal or mis-keyed description) keep `check_applied`
failing until a manual `tool.content` or rc edit. Every project value (archive, XML folder, registry) comes from
`.claude/harness.json`; nothing in the plugin names a project.

Authored `<a href>` links pass through to the "?" page, and hovers show the link text. arc-meta does not check
link targets: write an absolute href, since Pro renders the "?" page from a temp copy and a relative href breaks.
An `<a>` without an `href` or text, nested in another `<a>` or left open is refused as `unparseable`, and the
apply calls refuse that field.

Its second skill, `arc-help-pages`, builds the longer help page a tool's "?" page links to and checks the link:

- **Build** (dry run first): `<help_dir>/<page>.html` from a hand-written fragment, the page template and the
  tool's canonical help XML, with the Parameters table and the Python syntax generated in `tool.content`
  order (`apply_help`); the syntax opens with `import arcpy` and the `arcpy.ImportToolbox` line that puts the toolbox alias
  into arcpy. A rebuild of unchanged sources is byte-identical at any checkout root.
- **Check** (read-only): `check_help_page` reports a stale, unbuildable or unlinked page and an invalid
  fragment; `check_links` reports each href in the canonical XML whose target is missing, outside the
  checkout (drive, rooted and malformed hrefs included) or relative; only `#` anchors and web links are
  skipped. The development href is the main checkout's `file:` URI plus the page path, so it is
  the same from any linked worktree.

## Install

```
claude plugin install arc-straps@operator-straps
```

## Requirements

- **`harness` 0.56.0 or later, enabled.** The manifest declares the dependency. Every collaborator needs it
  before a project commits a `plugins` key to `.claude/harness.json`: an older harness rejects the key, and
  every harness hook then fails on load.
- **No ArcGIS Pro.** Nothing in `arc-meta` or `arc-help-pages` imports arcpy; both need the standard library and pydantic
  (`jsonschema` optional, for the full schema check under Configuration) under the harness interpreter (the one `hpy` picks; pin it with `HARNESS_PY`). A future skill that imports arcpy must
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
- `harness_lib.project.project_root`, which resolves a `repo` argument inside a subfolder to its project
  before `paths(repo)` loads that project's configuration, and `harness_lib.project.main_worktree`, which
  gives `arc-help-pages` the main checkout of the repository (the checkout a development href names) from a
  linked worktree.

Its tests follow the marketplace conventions: `tests/<area>/test_<name>.py` one level deep, consuming projects
built with `make_project`, never a live checkout. `strap-skills` cannot target this plugin yet, so its
judgment rules live in `SKILL.md` prose and its mechanical behaviors in pytest.

## Configuration

Set under `plugins.arc-straps.arc_meta` in the project's `.claude/harness.json`. Every key is optional;
`config/defaults.json` fills the rest. Paths are relative to the project root, and every resolved location
must lie inside it: one that resolves outside (an absolute path elsewhere, or `..`) is a config error. Every
load checks, with or without `jsonschema`, unknown keys directly under `plugins.arc-straps`
(`plugin_section`), and each `arc_meta` key's type, empty values and unknown `arc_meta` keys (`_meta()` in
`arc_meta_config.py`). Only with `jsonschema` importable does the schema also refuse an absolute path that
points inside the project.

| Key | Default | Meaning |
|---|---|---|
| `atbx` | `null` | Toolbox archive (`.atbx`). `null` means the one `.atbx` at the project root; none or several there is a config error naming this key |
| `tool_dir` | `tool_metadata/tools` | Folder of canonical per-tool help XML, `<Tool>.xml` |
| `toolbox_source` | `null` | Toolbox-level help XML. `null` means `<parent of tool_dir>/<archive file name, extension included>.xml` (e.g. `Tools.atbx.xml`) |
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
      },
      "arc_help_pages": {
        "atbx": "MyTools.atbx",
        "tool_dir": "tool_metadata/tools",
        "help_dir": "tool_metadata/tool_help"
      }
    }
  }
}
```

The `arc-meta` skill prints the resolved locations with `print(paths())`. A new key touches
`config/defaults.json`, `config/arc-straps.schema.json`, `ArcMetaPaths`, `paths()` and the type checks in
`_meta()` in `arc_meta_config.py` (a nullable path also joins `_OPTIONAL`; without `jsonschema` those checks
are the only type validation), and this table; harness files do not change. An `arc_help_pages` key touches the
same two config files, `HelpPaths`, `paths()` and `_section()` with its `_OPTIONAL` tuple in
`arc_help_pages_config.py`, and the `arc_help_pages` table below.

### arc_help_pages

`plugins.arc-straps.arc_help_pages` configures `arc-help-pages` and resolves apart from `arc_meta`: it has its
own defaults, its own type checks (`_section()` in `arc_help_pages_config.py`) and its own archive lookup, so
setting one section never changes the other. Paths follow the same rules as above. `paths()` also returns the
checkout the call runs in (`root`) and the main checkout of its repository (`checkout_root`, from
`harness_lib.project.main_worktree`; the project root itself outside git).

| Key | Default | Meaning |
|---|---|---|
| `atbx` | `null` | Toolbox archive (`.atbx`). `null` means the one `.atbx` at the project root; none or several there is a config error naming this key |
| `tool_dir` | `tool_metadata/tools` | Folder of canonical per-tool help XML, `<Tool>.xml` |
| `help_dir` | `tool_metadata/tool_help` | Folder of the tracked help pages, `<page>.html` (the fragment stem, usually the tool name), with `_fragments/`, `_template.html` and `img/` |

## Apply writes

- An apply writes a temp copy, validates it, then copies the original to `<archive>.bak` and swaps the copy
  in; a failed validation leaves the archive and any older `.bak` unchanged. Projects should gitignore
  `*.atbx.bak`.
- Every writer defaults to a dry run that reports what would change; `apply=True` writes.
- An `arc-straps` update can change the generator. After updating, sweep `check_applied` over `tool_names()`
  and apply the tools it flags, then dry-run `apply_toolbox` and apply it when it does not report
  `UNCHANGED`.

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
