# arc-straps plugin and the arc-meta port: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `harness:parallel2` dispatches this plan as three waves of
> lanes (Section 3). Each lane follows superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Issues:** #210 (new plugin `arc-straps`), #211 (port `arc-meta` from the toolbox project).

**Goal:** A third Python-bearing plugin, `arc-straps`, holds ArcGIS Pro / `.atbx` skills; its first skill,
`arc-meta`, checks and applies tool help in any project's toolbox archive with every project value coming
from `.claude/harness.json`.

**Architecture:** Harness gains one generic config key, `plugins` (a per-plugin section it stores but does
not interpret), and one helper, `harness_lib.plugin_config.plugin_section`, that merges a plugin's own
defaults under that section and validates it against the plugin's own schema. `arc-straps` declares
`"dependencies": [{"name": "harness", "version": ">=0.56.0"}]` and runs all its Python through the harness
launcher `harness-skill-api --file`,
so it ships no launcher, no `hpy` copy and no `lib/` package. The skill owns the whole toolchain: the
read-only check API, the vendored stdlib-only rich-text generator and the three apply writers (rc, page,
toolbox), so a second toolbox project needs nothing but config.

**Tech stack:** Python 3.11 syntax (`Optional`/`Union`), stdlib `zipfile`/`xml.etree`/`json`, pydantic v2
(features up to 2.4 only: an ArcGIS Pro interpreter may pin an old pydantic), pytest with `make_project`.

**Lineage:** `main --> 1129-new-arcgis-plugin` (target checkout `E:/automation/operator-straps`).

**Source pin:** toolbox project `E:/automation/toolboxes/floodplain_development` (below: `SRC`), commit
`0c4e45eb68765e152a5c17069ec8387aef6763df`, the last commit touching every source file below; the files are
clean in its working tree. Lanes read source with
`git -C "<SRC>" show 0c4e45eb6:<path>` and **never write, check out or stage anything in SRC** (it has
unrelated staged work on another branch).

**Interpreter:** `PY` = `C:/Users/t968rs/miniforge3/envs/o-s/python.exe` (pydantic 2.14.1, jsonschema,
ruff 0.12.0). The bare `python` on PATH lacks pydantic; never use it.

---

## 1. Decisions

| ID | Question (issue) | Decision | Why |
|---|---|---|---|
| D1 | Where project values live (#210 scope, #211) | `.claude/harness.json` key `plugins.arc-straps.arc_meta.*`; harness stores `plugins` as opaque per-plugin sections | Keeps "one harness.json" (CLAUDE.md rule) and keeps ArcGIS names out of harness: harness learns one generic key, arc-straps owns its defaults and schema and can add keys without a harness release |
| D2 | Do the generator and apply scripts move? (#211 decisions, #210 open question 2) | **Move.** `metadata_format.py` is vendored as `arc_meta_format.py`; the three apply scripts are re-cut as `arc_meta_rc.py`, `arc_meta_page.py`, `arc_meta_toolbox.py` with paths from config | All four are stdlib-only and generic to any `.atbx`; their only coupling is `fpm.PF` path lookups. `check_applied` must compare against the same generator that applies, so generator and writers ship together. The by-path generator load and its mtime cache go away |
| D3 | Does the plugin need ArcGIS Pro to load? (#210 open question 1) | **No.** Nothing in `arc-meta` imports arcpy; it needs stdlib and pydantic under the harness interpreter | Documented in the plugin README; a future arcpy-importing skill must pin a Pro interpreter (named as a follow-up, not built) |
| D4 | How arc-straps runs Python | Through `harness-skill-api --file "${CLAUDE_SKILL_DIR}/scripts/<module>.py"` only; `plugin.json` declares `"dependencies": [{"name": "harness", "version": ">=0.56.0"}]` (precedent for the field: `plugins/band-line/.claude-plugin/plugin.json:9`). Strict validation accepts the object form (checked before dispatch) | `${CLAUDE_PLUGIN_ROOT}` is per plugin, so `hpy` is unreachable from arc-straps; the PATH shim is the existing cross-plugin route, and the source skill already uses it. The floor matters: a harness older than 0.56.0 has no `plugin_config` and rejects the `plugins` key, which would break every harness hook in a project that commits it |
| D5 | Literal ban on `arcpy` (`tests/contract/test_no_repo_literals.py:30`) | Exempt `plugins/arc-straps/` from that one pattern; every other ban (project name, `scripts/fpm`, `$FPM_PY`, machine paths) still applies there | arcpy is that plugin's domain, not a consumer leak |
| D6 | Frozen `SkillSpec.json` (#211 decision 2) | Not carried. B1-B4 (mechanical) become pytest in this repo. B5-B9 (judgment) stay as SKILL.md Rules prose, de-coupled only by the H2 substitution list; the contract test pins B5's lead sentence and B8's lead and answer sentences verbatim (they name nothing project-specific); B6, B7 and B9 are carried unpinned. Re-strapping needs strap-skills support for a non-harness plugin target and a toolbox consumer root (follow-up F1). The source spec stays in SRC for the cutover to archive | The spec is already stale in SRC (content hash `b5c95292fd1e` vs frozen `b09189ee957c` after SRC PR #1722), a profile change cannot be made on a frozen spec, its runs carry SRC SHAs and absolute machine paths, and `strap.target` accepts only `harness`/`project` |
| D7 | Source-repo cutover (#211 done-when 2) | **Separate change, not in this plan** (`porting-into-straps` Section 9). Runbook in Section 6 | The cutover edits SRC, which has unrelated in-flight work; it can only follow an installed plugin |
| D8 | Module layout | Bare-stem modules in `plugins/arc-straps/skills/arc-meta/scripts/` (strap project-profile shape), siblings imported by bare name; the folder joins pytest `pythonpath` | `skill_api._load_file` appends the module folder to `sys.path` (`plugins/harness/scripts/skill_api.py:61-75`), so siblings resolve at run time. pytest (`--import-mode=importlib`) and `tools/select_tests.py` need the folder on pythonpath for a test's bare `import arc_meta_api`; module-to-module sibling imports already resolve from the module's own folder in select_tests. Proven by a new select_tests case (C1) |
| D9 | `harvest_canonical.py` (SRC one-time bootstrap) | Not ported | SKILL.md never names it; follow-up F3 |
| D10 | Verbatim import commit (`porting-into-straps` Section 3 step 1) | Waived | Every SRC writer imports `fpm`, so a verbatim copy cannot import here and its only red is ImportError. Reviewers diff each lane against `git -C <SRC> show 0c4e45eb6:<path>`; each task names its SRC paths; the PROVENANCE row records the pin |

## 2. File structure

### New: `plugins/arc-straps/`

| Path | Responsibility | Lane |
|---|---|---|
| `.claude-plugin/plugin.json` | name `arc-straps`, version `0.1.0`, description, author, `dependencies` per D4 | B |
| `.claude-plugin/icon.png` | square PNG 1024x1024 (the other plugins' size), under 2 MB (`tests/contract/test_plugin_icons.py`) | B |
| `README.md` | what the plugin is; the harness/arc-straps boundary; config keys; ArcGIS Pro requirement; migrating a project copy | B |
| `config/defaults.json` | `{"arc_meta": {"atbx": null, "tool_dir": "tool_metadata/tools", "toolbox_source": null, "registry": null}}` | A |
| `config/arc-straps.schema.json` | JSON Schema (2020-12) for the `plugins.arc-straps` section | A |
| `skills/arc-meta/SKILL.md` | the ported, decoupled skill | H |
| `skills/arc-meta/scripts/arc_meta_config.py` | `paths(repo) -> ArcMetaPaths`: resolves the section into absolute paths | A |
| `skills/arc-meta/scripts/arc_meta_models.py` | ported records + `ApiError`, `Surface`, `ApplyOutcome` | C |
| `skills/arc-meta/scripts/arc_meta_format.py` | SRC `metadata_format.py`, verbatim except docstring de-coupling | C |
| `skills/arc-meta/scripts/arc_meta_canonical.py` | canonical-XML readers and the "?" page builder, shared by the API, the writers and the tests (one builder, so checker and writer cannot drift) | C |
| `skills/arc-meta/scripts/arc_meta_archive.py` | `.atbx` read helpers and the one rewrite-validate-swap routine (SRC had three copies) | C |
| `skills/arc-meta/scripts/arc_meta_rc.py` | hover text writer (SRC `patch_tool_rc.py`) | D |
| `skills/arc-meta/scripts/arc_meta_page.py` | "?" page writer (SRC `clean_tool_metadata.py`) | E |
| `skills/arc-meta/scripts/arc_meta_toolbox.py` | toolbox-level rc and page writer (SRC `patch_toolbox_metadata.py`) | F |
| `skills/arc-meta/scripts/arc_meta_api.py` | read-only checks (SRC `arc_meta_api.py`) | G |

### New tests

| Path | Proves | Lane |
|---|---|---|
| `tests/lib/test_plugin_config.py` | `plugin_section` merge, validation, missing section, no-jsonschema fallback | A |
| `tests/arc/test_arc_meta_config.py` | `paths()` defaults, overrides, single-archive discovery, refusals | A |
| `tests/arc/_arc_toolbox.py` | shared builder: demo archive + canonical XML in a `make_project` repo (helper, not a test) | C |
| `tests/arc/test_arc_meta_format.py` | ported SRC `scripts/__tests__/_tbx_staging/test_metadata_format.py` | C |
| `tests/arc/test_arc_meta_archive.py` | decode, entry read, rewrite keeps `.bak`, refuses an invalid result | C |
| `tests/arc/test_arc_meta_rc.py` | ported SRC `scripts/__tests__/_tbx_staging/test_patch_tool_rc.py` + `apply_rc` | D |
| `tests/arc/test_arc_meta_page.py` | ported SRC API tests 9-11 (illustration) + `apply_page` | E |
| `tests/arc/test_arc_meta_toolbox.py` | ported SRC `scripts/__tests__/_tbx_staging/test_patch_toolbox_metadata.py` minus its live-repo test + `apply_toolbox` | F |
| `tests/arc/test_arc_meta_api.py` | ported SRC `scripts/__tests__/skills/test_arc_meta_api.py` tests 1-8, 12-21 | G |
| `tests/skills/test_arc_meta_skill_contract.py` | ported SRC contract test + launcher heredocs + B5/B8 rule pins | H |
| `tests/arc/test_arc_meta_roundtrip.py` | the writers' output passes `check_applied` (checker and writer agree) | H |
| `tests/contract/test_arc_straps_registration.py` | marketplace, manifest, dependency, README, CLAUDE.md, PROVENANCE | B |

### Modified

| Path | Change | Lane |
|---|---|---|
| `plugins/harness/config/defaults.json` | `"plugins": {}` | A |
| `plugins/harness/config/harness.schema.json` | `plugins` property | A |
| `plugins/harness/lib/harness_lib/config.py` | `HarnessConfig.plugins` + `plugin()` accessor + `_plugins` builder | A |
| `plugins/harness/lib/harness_lib/plugin_config.py` | new module (listed here because it is harness code) | A |
| `plugins/harness/.claude-plugin/plugin.json` | `0.55.3` -> `0.56.0` | A |
| `tests/lib/test_config.py` | `plugins` default, override and no-jsonschema cases | A |
| `plugins/harness/scripts/pr_review.py` | `config_data` dumps `plugins` as objects, so `config --get plugins.<name>.<key>` works | A |
| `tests/scripts/test_pr_review_driver.py` | `config --get plugins.demo.x` case | A |
| `pyproject.toml` | pytest `pythonpath` and pylint `init-hook` gain the arc-meta scripts folder | C |
| `tools/select_tests.py` | `DEFAULT_PYTHONPATH` mirrors pyproject | C |
| `tests/scripts/test_select_tests.py` | the arc-meta scripts folder is in the import closure | C |
| `tests/contract/test_no_repo_literals.py` | `ALLOWED_UNDER` exemption for the arcpy pattern + its tests | B |
| `.claude-plugin/marketplace.json` | `arc-straps` entry | B |
| `README.md` | plugin table row, companion prose, install line, Develop path row, key-table row `plugins` | B |
| `CLAUDE.md` | intro names `arc-straps`; Rules line on the boundary and the arcpy exemption | B |
| `docs/PROVENANCE.md` | additional-sources row and path-map rows for the port | B |
| `.claude/harness.json` | `plugins/arc-straps/skills/` joins the `Agent` commit bucket | B |
| `tests/contract/test_root_separation.py` | raw-string stdin in `_run`; case `arc-meta apply_rc` in `CASES` and `MUST_EXIT_ZERO` | H |

## 3. Waves

Lanes inside a wave have disjoint file sets. Interfaces crossing lanes are pinned in Section 4, so a lane
never waits on another lane's prose. Every lane works in its own parallel2 worktree, commits there, and
runs only the test files it names, with `PY`.

| Wave | Lane | Model | Depends on |
|---|---|---|---|
| 1 | **A** `harness-plugins-key` | opus | none |
| 1 | **B** `arc-wiring` | opus | none (documents the Section 4 names) |
| 1 | **C** `arc-core` | opus | none |
| 2 | **D** `arc-rc` | opus | A, C |
| 2 | **E** `arc-page` | opus | A, C |
| 2 | **F** `arc-toolbox` | opus | A, C |
| 2 | **G** `arc-api` | opus | A, C (shares the page and rc builders with E and D through `arc_meta_canonical`, so no D/E dependency) |
| 3 | **H** `arc-skill` | opus | all |

Wave 1 lanes that need the new pythonpath before C lands run pytest with the override
`-o pythonpath="plugins/harness/lib tests plugins/arc-straps/skills/arc-meta/scripts"`.

**Lane tools** (parallel2 `tools`): `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Bash(pytest *)`,
`Bash(ruff *)`, `Bash(git *)`. **Inside a lane, every `PY -m pytest ...` line runs as bare `pytest ...`**
(the pytest-scope mod rewrites it to `PY`; verified) and every `PY -m ruff ...` as bare `ruff ...`
(0.15 on PATH; the main session reruns ruff 0.12 at I3). Lanes never run `claude plugin validate`; the
main session runs it at I4. The Bash hooks block `cd ... &&`, so a lane runs pytest as
`pytest -c "<worktree>/pyproject.toml" "<worktree>/tests/<area>/test_<name>.py" -q` (absolute test paths;
`-c` makes the worktree the rootdir, so pythonpath entries resolve there) and ruff with absolute paths;
git calls use `git -C "<worktree>"`. Lint new and edited lines strictly; E501 hits on untouched older lines
are out of scope (CI passes `--extend-ignore E501`).

**Pre-dispatch fact (D4):** `claude plugin validate --strict` passes a manifest with
`"dependencies": [{"name": "harness", "version": ">=0.56.0"}]` (checked on a scratch manifest), so B4 uses
the object form without a fallback.

**Every lane** also runs `PY -m pytest tests/contract/test_no_repo_literals.py -q` before committing (wave-1
lanes other than B lack the arcpy exemption, so their files must not mention arcpy at all).

## 4. Pinned interfaces

### 4.1 Harness: `plugins` key (lane A)

`plugins/harness/config/defaults.json` gains, after `"strap"`:

```json
  "plugins": {},
```

`plugins/harness/config/harness.schema.json` gains, after the `strap` property:

```json
    "plugins": {
      "type": "object",
      "description": "Settings owned by other plugins of this marketplace, one object per plugin name. Harness stores each section unread; the owning plugin merges its own defaults under it and validates it against its own schema.",
      "propertyNames": {"pattern": "^[a-z][a-z0-9-]*$"},
      "additionalProperties": {"type": "object"}
    },
```

`config.py`: field, accessor and builder. The field is a tuple of `(name, JSON text)` pairs so
`HarnessConfig` stays frozen, hashable and copyable.

```python
    strap: StrapConfig
    plugins: Tuple[Tuple[str, str], ...]

    def plugin(self, name: str) -> Dict[str, Any]:
        """A fresh copy of the ``plugins.<name>`` section; empty when the project sets none."""
        return json.loads(dict(self.plugins).get(name, "{}"))
```

```python
def _plugins(p: Dict[str, Any]) -> Tuple[Tuple[str, str], ...]:
    """``plugins`` as sorted ``(name, JSON text)`` pairs, checked also on a load without ``jsonschema``."""
    if not isinstance(p, dict):
        raise ConfigError("plugins: must be an object")
    names = sorted(n for n in p if not re.fullmatch(r"[a-z][a-z0-9-]*", n))
    if names:
        raise ConfigError(f"plugins: section names {names} must match ^[a-z][a-z0-9-]*$")
    bad = sorted(name for name, section in p.items() if not isinstance(section, dict))
    if bad:
        raise ConfigError(f"plugins: sections {bad} must be objects")
    return tuple((name, json.dumps(p[name], sort_keys=True)) for name in sorted(p))
```

`_build` passes `plugins=_plugins(m["plugins"])` after `strap=...`.

`plugins/harness/scripts/pr_review.py:2184-2186` `config_data` gains, after the `asdict` dump,
`data["plugins"] = {name: json.loads(text) for name, text in active().plugins}` so
`config --get plugins.<name>.<key>` reads a section the same way as every other key.

### 4.2 Harness: `plugin_section` (lane A)

`plugins/harness/lib/harness_lib/plugin_config.py`:

```python
"""Per-plugin sections of ``.claude/harness.json``: another plugin's defaults merged under its section."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from harness_lib.config import ConfigError, HarnessConfig, active, deep_merge


def plugin_section(name: str, defaults_path: Path, schema_path: Optional[Path] = None,
                   cfg: Optional[HarnessConfig] = None) -> Dict[str, Any]:
    """``plugins.<name>`` of ``cfg`` (default: the active config) merged over the plugin's defaults.

    The merged section is validated against ``schema_path`` when given; a defect raises ConfigError
    naming ``plugins/<name>/<json path>``.
    """
    merged = deep_merge(_read(defaults_path), (cfg or active()).plugin(name))
    if schema_path is not None:
        _check(merged, _read(schema_path), name)
    return merged


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be an object")
    return data


def _check(data: Dict[str, Any], schema: Dict[str, Any], name: str) -> None:
    try:
        import jsonschema
    except ImportError:
        unknown = sorted(set(data) - set(schema.get("properties", {})))
        if unknown:
            raise ConfigError(f"plugins/{name}: unknown keys {unknown}")
        return
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        where = "/".join(["plugins", name, *(str(p) for p in errors[0].absolute_path)])
        raise ConfigError(f"{where}: {errors[0].message}")
```

### 4.3 arc-straps config (lane A)

`plugins/arc-straps/config/defaults.json`:

```json
{
  "arc_meta": {
    "atbx": null,
    "tool_dir": "tool_metadata/tools",
    "toolbox_source": null,
    "registry": null
  }
}
```

`plugins/arc-straps/config/arc-straps.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/t968rs/operator-straps/plugins/arc-straps/config/arc-straps.schema.json",
  "title": "harness.json plugins.arc-straps",
  "description": "The arc-straps section of <project>/.claude/harness.json. Every key is optional; plugins/arc-straps/config/defaults.json fills the rest.",
  "type": "object",
  "additionalProperties": false,
  "$defs": {
    "relPath": {"type": "string", "minLength": 1, "pattern": "^(?![/\\x5c])(?![A-Za-z]:)"},
    "optPath": {"oneOf": [{"$ref": "#/$defs/relPath"}, {"type": "null"}]}
  },
  "properties": {
    "arc_meta": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "atbx": {"$ref": "#/$defs/optPath", "description": "Toolbox archive (.atbx); null means the one .atbx at the project root."},
        "tool_dir": {"$ref": "#/$defs/relPath", "description": "Folder of canonical per-tool help XML, <Tool>.xml."},
        "toolbox_source": {"$ref": "#/$defs/optPath", "description": "Toolbox-level help XML; null means <parent of tool_dir>/<archive file name>.xml."},
        "registry": {"$ref": "#/$defs/optPath", "description": "Optional tool registry JSON {\"tools\": [{\"tool_name\", \"py_path\"}]} for the stale-path check; null skips it."}
      }
    }
  }
}
```

`plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py`:

```python
"""Where arc-meta reads and writes: the ``plugins.arc-straps.arc_meta`` section resolved to absolute paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from harness_lib.config import ConfigError, active, load_config
from harness_lib.plugin_config import plugin_section

__all__ = ["ArcMetaPaths", "RepoLike", "paths"]

PLUGIN = "arc-straps"
_CONFIG = Path(__file__).resolve().parents[3] / "config"
RepoLike = Optional[Union[str, Path]]


@dataclass(frozen=True)
class ArcMetaPaths:
    """Absolute locations arc-meta reads and writes in one project."""

    root: Path
    atbx: Path
    tool_dir: Path
    toolbox_source: Path
    registry: Optional[Path]


def paths(repo: RepoLike = None) -> ArcMetaPaths:
    """Resolve the section for ``repo`` (default: the active project); refuses an ambiguous archive."""
    cfg = active() if repo is None else load_config(Path(repo))
    section = plugin_section(PLUGIN, _CONFIG / "defaults.json", _CONFIG / "arc-straps.schema.json", cfg)
    meta, root = section["arc_meta"], cfg.project_root
    atbx = root / meta["atbx"] if meta["atbx"] else _only_archive(root)
    tool_dir = root / meta["tool_dir"].rstrip("/")
    source = root / meta["toolbox_source"] if meta["toolbox_source"] else tool_dir.parent / f"{atbx.name}.xml"
    registry = root / meta["registry"] if meta["registry"] else None
    return ArcMetaPaths(root, atbx, tool_dir, source, registry)


def _only_archive(root: Path) -> Path:
    found = sorted(root.glob("*.atbx"))
    if len(found) != 1:
        what = "no .atbx" if not found else f"{len(found)} .atbx files"
        raise ConfigError(f"{what} at {root.as_posix()}; "
                          f"set plugins.{PLUGIN}.arc_meta.atbx in .claude/harness.json")
    return found[0]
```

The glob lives in the plugin module, not the test, so `tests/arc/test_arc_meta_config.py` needs no
`WALK_ROOTS` marker (the marker rule reads test source only).

### 4.4 Shared records (lane C) in `arc_meta_models.py`

Ported unchanged from SRC `.claude/skills/arc-meta/scripts/arc_meta_models.py` (`ParamType`, `Direction`,
`ProblemCode`, `ParamRow`, `Problem`, `ToolSources`, `_MODEL_CONFIG`), plus, moved or new:

```python
class ApiError(ValueError):
    """A refused ``arc-meta`` call; the message names the defect."""


class Surface(str, Enum):
    """Which part of the archive an apply call writes."""

    RC = "rc"
    PAGE = "page"
    TOOLBOX = "toolbox"


class ApplyOutcome(BaseModel):
    """What one apply call found and, with ``apply=True``, wrote."""

    model_config = _MODEL_CONFIG

    surface: Surface
    tool: Optional[str] = None
    changed: bool
    applied: bool
    lines: List[str] = Field(default_factory=list)
```

`changed`: the archive differs from what the canonical source produces. `applied`: the archive was rewritten
in this call (`apply=True` and `changed`). `lines`: the report the SRC script printed, one string per line.

### 4.5 Shared helpers (lane C)

`arc_meta_archive.py` (`__all__` lists all four):

```python
def decode(raw: bytes) -> str: ...            # SRC arc_meta_api._decode, unchanged
def read_text(zf: zipfile.ZipFile, name: str, label: str) -> Optional[str]: ...
    # SRC arc_meta_api._entry; ApiError names ``label`` (the archive file name) instead of the ATBX constant
def read_json(zf: zipfile.ZipFile, name: str, label: str) -> Optional[dict]: ...
    # read_text + SRC _json_entry
def rewrite(atbx: Path, replacements: Dict[str, bytes]) -> None: ...
    # the SRC rewrite (patch_tool_rc.py:145-209 is the reference copy), with the .bak taken only after
    # validation passes (lane C review: a failed rewrite leaves any older .bak untouched; a locked
    # archive is an ApiError and leaves no temp file). Write every
    # member with ``replacements`` substituted (members not in the archive are appended with
    # ZIP_DEFLATED), keep each existing member's compression type and order, write to a temp file beside
    # the archive, reopen it, testzip(), then parse every member named in ``replacements`` by name
    # (``*.rc``, ``tool.content``, ``toolbox.content``: json.loads of the decoded text; ``*.xml``:
    # ET.fromstring), as all three SRC copies did; then os.replace over ``atbx``. Any failure (bad entry,
    # JSONDecodeError, ParseError) unlinks the temp file, leaves ``atbx`` byte-identical and raises ApiError
    # naming the member, chained ``from`` the original error.
```

`arc_meta_canonical.py` (`__all__` lists these five plus `tool_element` and `fields_of`, made public at
integration so the check API reads hover text through the same reader as the rc writer):

```python
def load(tool_dir: Path, tool: str) -> Tuple[str, ET.Element]: ...
    # SRC arc_meta_api._canonical + _xml: ApiError "no canonical source at ..." / "... is not well-formed XML"
def rc_text(blocks: list, summary: bool = False) -> str: ...
    # SRC arc_meta_api._rc_text semantics (a superset of patch_tool_rc._param_text): "" when blank; plain
    # text when ``summary`` or mf.is_plain(blocks); else mf.to_xdoc(blocks). The tool summary is always plain.
def add_dialog_ref(param_el: ET.Element, blocks: list) -> None: ...   # SRC clean_tool_metadata._set_dialog_ref
def fields(tool_dir: Path, tool: str) -> Tuple[str, Dict[str, str]]: ...
    # SRC patch_tool_rc._canonical_fields, reading through ``load`` (so a missing or broken XML raises
    # ApiError): (rc_text(summary, summary=True), {lowercased param: rc_text(dialogReference)})
def page(src: ET.Element, illustration: Optional[bytes] = None) -> str: ...
    # SRC clean_tool_metadata._build_clean_metadata body after its ET.parse (clean_tool_metadata.py:95-129),
    # with _set_rich and _add_illustration as private helpers; ``src`` is the parsed canonical root.
    # The one "?" page builder: arc_meta_page.build_page, arc_meta_api's expected page and the tests'
    # default page all call it.
```

Both import the generator as `import arc_meta_format as mf`.

### 4.6 Writers (lanes D, E, F)

Each writer module exports a pure core taking explicit paths (for tests) and one config-reading entry point
for the skill. `RepoLike` comes from `arc_meta_config`.

| Module | `__all__` | Pure core (tests) | Entry point (skill) |
|---|---|---|---|
| `arc_meta_rc.py` | `apply_rc`, `run_rc`, `missing_refs`, `wire_content`, `ApplyOutcome` | `run_rc(tool: str, atbx: Path, tool_dir: Path, apply: bool = False) -> ApplyOutcome` | `apply_rc(tool: str, apply: bool = False, repo: RepoLike = None) -> ApplyOutcome` |
| `arc_meta_page.py` | `apply_page`, `run_page`, `build_page`, `read_illustration`, `ApplyOutcome` | `run_page(tool: str, atbx: Path, tool_dir: Path, apply: bool = False) -> ApplyOutcome`; `build_page(tool, tool_dir, illustration=None) -> str` returns `arc_meta_canonical.page(arc_meta_canonical.load(tool_dir, tool)[1], illustration)` | `apply_page(tool: str, apply: bool = False, repo: RepoLike = None) -> ApplyOutcome` |
| `arc_meta_toolbox.py` | `apply_toolbox`, `run_toolbox`, `load_source`, `build_rc`, `build_metadata`, `ApplyOutcome` | `run_toolbox(atbx: Path, source: Path, apply: bool = False) -> ApplyOutcome` | `apply_toolbox(apply: bool = False, repo: RepoLike = None) -> ApplyOutcome` |

Each `apply_*` is `p = paths(repo)` followed by its `run_*`; nothing else.

Port rules, applied to every SRC writer:

1. `from fpm._tbx_staging.metadata import metadata_format as mf` -> `import arc_meta_format as mf`.
2. `ensure_tool_dir()` / `ensure_atbx()` / `default_source_path()` / `default_atbx()` and every `fpm.PF` lookup
   are deleted; functions take `atbx: Path`, `tool_dir: Path`, `source: Path` parameters, and only the
   `apply_*` entry point calls `arc_meta_config.paths(repo)`.
3. The SRC `run()` + argparse `main()` become the `apply_*` entry point: same dry-run default, same report
   text collected into `ApplyOutcome.lines` instead of printed, and no `sys.exit`.
4. The private rewrite-validate-swap copy is replaced by `arc_meta_archive.rewrite`; `_param_text` by
   `arc_meta_canonical.rc_text`; `_set_dialog_ref` by `arc_meta_canonical.add_dialog_ref`;
   `_canonical_fields` by `arc_meta_canonical.fields`.
5. Literals: the archive name, `ShrinkwrapFloodplain` usage examples and every project name leave the code
   and docstrings; examples say `<Tool>`.
6. Functions stay under 50 lines; `Optional`/`Union` only; no first/second person in comments.
7. Archive members are read through `arc_meta_archive.read_text` / `read_json` (UTF-8, UTF-8-BOM and UTF-16
   tolerated) and written with the encoding the SRC writer used; any change of write encoding from SRC is
   named in the lane's commit body.
8. A missing archive member the writer needs (for example `toolbox.content.rc`) is an `ApiError` naming the
   member and the archive, never a `KeyError`.
9. SRC paths for the reviewer diff: D = `scripts/fpm/_tbx_staging/metadata/patch_tool_rc.py`,
   E = `.../clean_tool_metadata.py`, F = `.../patch_toolbox_metadata.py`, each with its SRC test under
   `scripts/__tests__/_tbx_staging/`.

### 4.7 Check API (lane G)

`arc_meta_api.py` keeps the SRC `__all__` and every public signature
(`tool_names`, `param_table`, `check_canonical`, `check_applied`, `entry_sources`, `format_rows`,
`format_problems`, re-exported `ApiError`, `Direction`, `ParamType`, `ProblemCode`) and adds `paths`
(re-exported from `arc_meta_config`). Changes from SRC:

- `ATBX`, `TOOL_DIR`, `MF_REL`, `REGISTRY_REL`, `_MF_CACHE`, `_root`, `_mf` are deleted. Every function
  resolves `p = paths(repo)` once and reads `p.atbx`, `p.tool_dir`, `p.registry`; error messages name
  `p.atbx.name` where SRC named `ATBX`.
- `_mf(root)` call sites import the generator directly (`import arc_meta_format as mf`).
- `_decode`/`_entry`/`_json_entry` -> `arc_meta_archive`; `_canonical`/`_xml` -> `arc_meta_canonical.load`;
  `_rc_text(mf, b, summary=s)` -> `arc_meta_canonical.rc_text(b, summary=s)`; `_expected_ref` builds through
  `arc_meta_canonical.add_dialog_ref`; wherever SRC compared against a page the apply script would write,
  the expected page is `arc_meta_canonical.page(...)`.
- `entry_sources` resolves the link relative to `p.atbx.parent / p.atbx.name / f"{tool}.tool"` (SRC
  `:461` semantics with the configured archive), and reads the registry only when `p.registry` is set and
  exists.
- A `ConfigError` from `paths()` propagates unchanged (the launcher prints it as `problem:`).
- Module docstring rewritten generically (no project name, no `scripts/fpm`).

### 4.8 Test builder (lane C) `tests/arc/_arc_toolbox.py`

```python
"""A demo toolbox project for arc-meta tests: one archive, its canonical XML, optional config."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional

TOOL = "Demo"
ATBX = "demo_toolbox.atbx"
LYRX = "layers/demo.lyrx"      # SRC LYRX, neutral path
CONTENT: dict = {...}          # SRC test_arc_meta_api.py CONTENT, verbatim
RC: dict = {...}               # SRC RC
CANONICAL: str = "..."         # SRC CANONICAL
BAD_CANONICAL: str = "..."     # SRC BAD_CANONICAL
PNG_A: bytes = b"..."          # SRC PNG_A
PNG_B: bytes = b"..."          # SRC PNG_B
ILLUSTRATION_ENTRY = mf.illustration_entry(TOOL)


def write_archive(path: Path, members: Dict[str, bytes]) -> Path:
    """Write ``members`` into a fresh zip at ``path``."""


def default_page(canonical: str = CANONICAL, illustration: Optional[bytes] = None) -> str:
    """The page the writer produces: ``arc_meta_canonical.page`` over ``canonical``."""
    return arc_meta_canonical.page(ET.fromstring(canonical.encode("utf-8")), illustration)


def toolbox_members(canonical: str = CANONICAL, content: Optional[dict] = None, rc: Optional[dict] = None,
                    page: Optional[str] = None, extra: Optional[Dict[str, bytes]] = None) -> Dict[str, bytes]:
    """The ``Demo.tool/`` members SRC ``_make_repo`` wrote: content, rc and ``tool.metadata.xml``
    (``page``, default ``default_page(canonical)``), plus ``extra``."""


def make_toolbox(make_project: Callable[..., Path], canonical: str = CANONICAL,
                 members: Optional[Dict[str, bytes]] = None, config: Optional[dict] = None) -> Path:
    """A committed project holding ``ATBX`` at its root and ``tool_metadata/tools/Demo.xml``.

    ``make_project`` writes only text, so the archive is written after it with ``write_archive``
    (``members`` default ``toolbox_members(canonical)``) and committed with ``conftest.git``.
    """
```

Lane C fills the bodies from SRC `_make_repo` (`test_arc_meta_api.py:171-190`) minus the generator copy;
SRC `_built_page`/`_page` (`:146-168`) become `default_page`, and the `div_style`/`drop_param` post-edits of
SRC `_page` stay in lane G's test. SRC's entry path `scripts/fpm/demo/run.py` becomes `tools/demo/run.py`
(project paths stay out of this repo's tests too).

**Import convention:** every test imports the builder as `from arc._arc_toolbox import ...` (`tests` is on
pythonpath, so `arc` is a namespace package; precedent `from mods._..._helpers import ...` in `tests/mods/`).
A bare `import _arc_toolbox` fails under `--import-mode=importlib`.

### 4.9 Skill heredocs (lane H)

Every API call in SKILL.md has this shape (pinned by the contract test):

```bash
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_api.py" <Tool> <<'PY'
print(format_problems(check_canonical(name)))
PY
```

Apply calls use `arc_meta_rc.py` / `arc_meta_page.py` / `arc_meta_toolbox.py` with
`print("\n".join(apply_rc(name).lines))` for the dry run, then
`print("\n".join(apply_rc(name, apply=True).lines))`. No `$FPM_PY`, no `PYTHONPATH`, no `scripts/fpm`.
Location prose reads "the configured `tool_dir` (default `tool_metadata/tools`)"; the agent learns the
resolved paths with `print(paths())`.

## 5. Tasks

Each task lists its files, then TDD steps. "Run" lines use `PY` and name files, never directories.

### Task A: harness `plugins` key, `plugin_section`, arc-straps config (wave 1)

**Files:** `plugins/harness/config/defaults.json`, `plugins/harness/config/harness.schema.json`,
`plugins/harness/lib/harness_lib/config.py`, `plugins/harness/lib/harness_lib/plugin_config.py` (new),
`plugins/harness/.claude-plugin/plugin.json`, `plugins/harness/scripts/pr_review.py`,
`tests/lib/test_config.py`, `tests/lib/test_plugin_config.py` (new), `tests/scripts/test_pr_review_driver.py`,
`plugins/arc-straps/config/defaults.json` (new), `plugins/arc-straps/config/arc-straps.schema.json`
(new), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py` (new),
`tests/arc/test_arc_meta_config.py` (new).

- [ ] **A1: failing config tests.** Append to `tests/lib/test_config.py`:

```python
def test_plugins_default_is_empty(make_project) -> None:
    cfg = load_config(make_project())
    assert cfg.plugins == ()
    assert cfg.plugin("arc-straps") == {}


def test_plugins_sections_load_and_copy(make_project) -> None:
    cfg = load_config(make_project({"plugins": {"arc-straps": {"arc_meta": {"atbx": "a.atbx"}}}}))
    section = cfg.plugin("arc-straps")
    assert section == {"arc_meta": {"atbx": "a.atbx"}}
    section["arc_meta"]["atbx"] = "changed"
    assert cfg.plugin("arc-straps")["arc_meta"]["atbx"] == "a.atbx"
    assert hash(cfg) == hash(cfg)


BAD_PLUGINS = [{"plugins": {"Arc": {}}}, {"plugins": {"arc-straps": 3}}, {"plugins": []}]


@pytest.mark.parametrize("bad", BAD_PLUGINS)
def test_plugins_rejects_bad_sections(make_project, bad: dict) -> None:
    # Today's message reads "<root>: Additional properties ... 'plugins' was unexpected"; the new one
    # names the plugins path itself.
    with pytest.raises(ConfigError, match=r": plugins(/|: )"):
        load_config(make_project(bad))


@pytest.mark.parametrize("bad", BAD_PLUGINS)
def test_plugins_rejects_bad_sections_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch,
                                                         bad: dict) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match=r"plugins: "):
        load_config(make_project(bad))
```

- [ ] **A2:** Run `PY -m pytest tests/lib/test_config.py -q`. Expected: the two named tests FAIL with
  `AttributeError: 'HarnessConfig' object has no attribute 'plugins'`, and all six parametrized cases FAIL
  (today's messages carry `<root>: ... 'plugins' was unexpected` / `unknown keys ['plugins']`).
- [ ] **A3:** Apply Section 4.1 to defaults, schema and `config.py` (`re` is already imported). Also add
  `{"plugins": {"Arc": {}}}` and `{"plugins": {"arc-straps": 3}}` to the parametrize list of the existing
  `test_minimal_validation_without_jsonschema` (`tests/lib/test_config.py:81`).
- [ ] **A4:** Run `PY -m pytest tests/lib/test_config.py -q`. Expected: all PASS.
- [ ] **A4b: config --get.** Add to `tests/scripts/test_pr_review_driver.py` (inside its config-command
  test class, following its existing cases): a project with `{"plugins": {"demo": {"x": 1}}}` makes
  `config --get plugins.demo.x` print `1`. Run `PY -m pytest tests/scripts/test_pr_review_driver.py -q -k config`;
  Expected: the new case FAILS. Apply the `config_data` line from Section 4.1; rerun; PASS.
- [ ] **A5: failing helper tests.** Create `tests/lib/test_plugin_config.py`:

```python
"""``plugin_section``: a plugin's defaults merged under its harness.json section and checked by its schema."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness_lib.config import ConfigError, load_config
from harness_lib.plugin_config import plugin_section

SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"x": {"type": "object", "additionalProperties": False,
                               "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}}}


@pytest.fixture()
def files(tmp_path: Path) -> tuple:
    defaults, schema = tmp_path / "defaults.json", tmp_path / "schema.json"
    defaults.write_text(json.dumps({"x": {"a": "d", "b": 1}}), encoding="utf-8")
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    return defaults, schema


def test_defaults_without_a_section(make_project, files: tuple) -> None:
    cfg = load_config(make_project())
    assert plugin_section("demo", *files, cfg=cfg) == {"x": {"a": "d", "b": 1}}


def test_section_merges_over_defaults(make_project, files: tuple) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"x": {"b": 2}}}}))
    assert plugin_section("demo", *files, cfg=cfg) == {"x": {"a": "d", "b": 2}}


def test_schema_defect_names_the_path(make_project, files: tuple) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"x": {"b": "two"}}}}))
    with pytest.raises(ConfigError, match=r"plugins/demo/x/b"):
        plugin_section("demo", *files, cfg=cfg)


def test_no_schema_skips_validation(make_project, files: tuple) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"y": 1}}}))
    assert plugin_section("demo", files[0], cfg=cfg)["y"] == 1


def test_unknown_key_without_jsonschema(make_project, files: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"y": 1}}}))
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match=r"plugins/demo: unknown keys \['y'\]"):
        plugin_section("demo", *files, cfg=cfg)


def test_unreadable_defaults_raise(make_project, tmp_path: Path) -> None:
    cfg = load_config(make_project())
    with pytest.raises(ConfigError, match="missing.json"):
        plugin_section("demo", tmp_path / "missing.json", cfg=cfg)
```

- [ ] **A6:** Run `PY -m pytest tests/lib/test_plugin_config.py -q`. Expected: collection ERROR
  `ModuleNotFoundError: harness_lib.plugin_config`.
- [ ] **A7:** Create `plugin_config.py` from Section 4.2. Run the same command. Expected: 6 PASS.
- [ ] **A8: failing arc config tests.** Create `tests/arc/test_arc_meta_config.py` (it imports
  `arc_meta_config` by bare name, which needs the pythonpath override until lane C lands):

```python
"""arc-meta paths: the plugins.arc-straps section resolved against one project."""
from __future__ import annotations

import pytest

import arc_meta_config
from harness_lib.config import ConfigError

SECTION = "arc-straps"


def _cfg(**meta) -> dict:
    return {"plugins": {SECTION: {"arc_meta": meta}}}


def test_defaults_find_the_only_archive(make_project) -> None:
    root = make_project(files={"box.atbx": "zip"})
    p = arc_meta_config.paths(root)
    assert p.atbx == root / "box.atbx"
    assert p.tool_dir == root / "tool_metadata" / "tools"
    assert p.toolbox_source == root / "tool_metadata" / "box.atbx.xml"
    assert p.registry is None


def test_overrides_win(make_project) -> None:
    root = make_project(_cfg(atbx="tbx/x.atbx", tool_dir="help/tools/", toolbox_source="help/tb.xml",
                             registry="reg.json"))
    p = arc_meta_config.paths(root)
    assert (p.atbx, p.tool_dir) == (root / "tbx" / "x.atbx", root / "help" / "tools")
    assert (p.toolbox_source, p.registry) == (root / "help" / "tb.xml", root / "reg.json")


@pytest.mark.parametrize("files,match", [({}, "no .atbx"), ({"a.atbx": "z", "b.atbx": "z"}, "2 .atbx files")])
def test_ambiguous_archive_is_refused(make_project, files: dict, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        arc_meta_config.paths(make_project(files=files))


def test_schema_refuses_unknown_and_absolute(make_project) -> None:
    with pytest.raises(ConfigError, match="plugins/arc-straps"):
        arc_meta_config.paths(make_project(_cfg(nope=1)))
    with pytest.raises(ConfigError, match="plugins/arc-straps/arc_meta/atbx"):
        arc_meta_config.paths(make_project(_cfg(atbx="C:/x.atbx")))


def test_defaults_validate_against_the_schema(repo_root) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    config = repo_root / "plugins" / "arc-straps" / "config"
    defaults = json.loads((config / "defaults.json").read_text(encoding="utf-8"))
    schema = json.loads((config / "arc-straps.schema.json").read_text(encoding="utf-8"))
    assert jsonschema.Draft202012Validator(schema).is_valid(defaults)
```

  (add `import json` to the test's imports).

- [ ] **A9:** Run `PY -m pytest tests/arc/test_arc_meta_config.py -q -o pythonpath="plugins/harness/lib tests plugins/arc-straps/skills/arc-meta/scripts"`.
  Expected: collection ERROR `No module named 'arc_meta_config'`.
- [ ] **A10:** Create the two `plugins/arc-straps/config/` files and `arc_meta_config.py` from Section 4.3.
  Run A9's command. Expected: 6 PASS.
- [ ] **A11:** Bump `plugins/harness/.claude-plugin/plugin.json` `version` to `0.56.0`.
- [ ] **A12:** Run, each its own call: `PY -m pytest tests/lib/test_config.py tests/lib/test_plugin_config.py tests/scripts/test_pr_review_driver.py tests/schemas/test_schema_meta_valid.py tests/contract/test_no_repo_literals.py -q`;
  `PY -m ruff check --no-cache plugins/harness/lib/harness_lib/config.py plugins/harness/lib/harness_lib/plugin_config.py plugins/arc-straps tests/lib/test_plugin_config.py tests/arc/test_arc_meta_config.py`.
  Expected: PASS, `All checks passed!`.
- [ ] **A13:** Mutation proofs, each restored after: `_plugins` returning `()` makes
  `test_plugins_sections_load_and_copy` FAIL; deleting the `bad` check makes the `arc-straps: 3`
  no-jsonschema case FAIL. Commit in the lane worktree:
  `git add` the lane files, `git commit -m "feat(harness): plugins config key and plugin_section helper"`.

### Task B: plugin wiring and docs (wave 1)

**Files:** `plugins/arc-straps/.claude-plugin/plugin.json`, `plugins/arc-straps/.claude-plugin/icon.png`,
`plugins/arc-straps/README.md`, `.claude-plugin/marketplace.json`, `README.md`, `CLAUDE.md`,
`docs/PROVENANCE.md`, `.claude/harness.json`, `tests/contract/test_no_repo_literals.py`,
`tests/contract/test_arc_straps_registration.py` (new).

- [ ] **B1: failing exemption tests.** In `tests/contract/test_no_repo_literals.py`, add after `BANNED`:

```python
# A ban a plugin may lift for its own files: its domain library, never a consumer's names or paths.
ALLOWED_UNDER: Dict[str, Tuple[str, ...]] = {"project domain library": ("plugins/arc-straps/",)}
```

  and these tests (they fail until `_hits` honours the map):

```python
def test_arcpy_is_allowed_only_under_arc_straps(tmp_path: Path) -> None:
    pattern = dict(BANNED)["project domain library"]
    inside = REPO_ROOT / "plugins" / "arc-straps" / "x.md"
    outside = REPO_ROOT / "plugins" / "harness" / "x.md"
    assert not _allowed("project name", inside)
    assert _allowed("project domain library", inside)
    assert not _allowed("project domain library", outside)
    assert pattern.search("import arcpy")


def test_exemptions_name_existing_labels() -> None:
    assert set(ALLOWED_UNDER) <= {label for label, _ in BANNED}
```

- [ ] **B2:** Run `PY -m pytest tests/contract/test_no_repo_literals.py -q`. Expected: FAIL
  (`NameError: _allowed`).
- [ ] **B3:** Implement:

```python
def _allowed(label: str, path: Path) -> bool:
    """True when ``path`` sits under a folder that lifts the ban ``label``."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    return any(rel.startswith(prefix) for prefix in ALLOWED_UNDER.get(label, ()))
```

  and change `test_no_consumer_literal` to scan `[p for p in FILES if not _allowed(label, p)]`. Add
  `Dict` to the `typing` import. `port_scan.py` reads only `BANNED` and `BARE_AGENT`, so it keeps working
  and keeps flagging arcpy in source repos (where it is a real coupling). Run B2's command. Expected: PASS.
- [ ] **B4:** (Order: write and run B7-B8 first, so every registration test is red; then B4-B6 and B9.)
  Create `plugins/arc-straps/.claude-plugin/plugin.json`:

```json
{
  "name": "arc-straps",
  "version": "0.1.0",
  "description": "ArcGIS Pro toolbox skills: arc-meta checks and applies tool help in a project's .atbx archive",
  "author": {
    "name": "Kevin Gabelman"
  },
  "dependencies": [{"name": "harness", "version": ">=0.56.0"}]
}
```

  (The object form is pre-verified; see Section 3.)

- [ ] **B5:** Generate `icon.png` with a scratchpad stdlib script (zlib + struct, no third-party
  imports): 1024x1024 RGB, a dark slate background with a light contour-map motif (three concentric
  rounded rings and a grid), distinct from the other plugin icons. Write the script under the session
  scratchpad, never under the repo. Verify: `PY -m pytest tests/contract/test_plugin_icons.py -q` passes
  after B6.
- [ ] **B6:** Add to `.claude-plugin/marketplace.json` after the `harness` entry:

```json
    {
      "name": "arc-straps",
      "source": "./plugins/arc-straps",
      "description": "ArcGIS Pro toolbox skills: arc-meta checks and applies tool help in a project's .atbx archive"
    },
```

- [ ] **B7: failing registration test.** Create `tests/contract/test_arc_straps_registration.py`:

```python
"""The arc-straps plugin is registered where every plugin is, and declares its harness dependency."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _text(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_the_marketplace_lists_the_plugin(repo_root: Path) -> None:
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next((p for p in plugins if p["name"] == "arc-straps"), None)
    assert entry is not None and entry["source"] == "./plugins/arc-straps"


def test_the_manifest_depends_on_harness(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, "plugins/arc-straps/.claude-plugin/plugin.json"))
    assert manifest["name"] == "arc-straps"
    assert manifest["dependencies"] == [{"name": "harness", "version": ">=0.56.0"}]


def test_the_readme_documents_and_installs_the_plugin(repo_root: Path) -> None:
    readme = _text(repo_root, "README.md")
    assert "claude plugin install arc-straps@operator-straps" in readme
    assert re.search(r"\|[^|\n]*\|\s*`arc-straps`\s*\|", readme)
    assert "`plugins`" in readme


def test_claude_md_names_the_plugin(repo_root: Path) -> None:
    assert "`arc-straps`" in _text(repo_root, "CLAUDE.md")


def test_the_plugin_readme_documents_its_keys(repo_root: Path) -> None:
    text = _text(repo_root, "plugins/arc-straps/README.md")
    schema = json.loads(_text(repo_root, "plugins/arc-straps/config/arc-straps.schema.json"))
    keys = list(schema["properties"]["arc_meta"]["properties"])
    assert keys, "the schema lists no arc_meta keys"
    for key in [*keys, "harness-skill-api"]:
        assert f"`{key}`" in text, key


def test_provenance_records_the_port(repo_root: Path) -> None:
    text = _text(repo_root, "docs/PROVENANCE.md")
    assert "plugins/arc-straps/skills/arc-meta/" in text and "0c4e45eb6" in text
```

- [ ] **B8:** Run `PY -m pytest tests/contract/test_arc_straps_registration.py -q`. Expected: the README,
  CLAUDE.md, plugin README and PROVENANCE tests FAIL.
- [ ] **B9: docs.**
  - `README.md`: a row for `arc-straps` in the "What you can do" table and the plugin table (the row must
    match `| ... | \`arc-straps\` |`); a sentence in the companion-plugin prose ("`arc-straps` needs
    `harness`: it runs its Python through `harness-skill-api`"); `claude plugin install arc-straps@operator-straps`
    in the install block; a Develop path-table row `plugins/arc-straps/` ; and a key-table row:
    `| \`plugins\` | \`{}\` | Settings owned by other plugins of this marketplace, one object per plugin name; harness stores each section and the owning plugin validates it (\`arc-straps\`: see its README) |`.
    Read each README section first and follow its exact row format.
  - `CLAUDE.md` line 3: name `arc-straps` beside `harness` ("the `harness` plugin ... and the `arc-straps`
    plugin (ArcGIS Pro toolbox skills) plus eight TypeScript mods"); keep the word "eight"
    (`tests/contract/test_mod_count.py`). Under "Rules for changes", one bullet: "**ArcGIS material lives in
    `arc-straps`.** A skill that needs ArcGIS Pro, arcpy or the `.atbx` format goes under
    `plugins/arc-straps/`; it reaches harness only through `harness-skill-api` and `harness_lib.config` /
    `harness_lib.plugin_config`, and its project values live under `plugins.arc-straps` in
    `.claude/harness.json`. The literal ban lifts only the arcpy pattern there (`ALLOWED_UNDER`). An
    arc-straps key touches `plugins/arc-straps/config/defaults.json`, `config/arc-straps.schema.json`,
    `ArcMetaPaths` and `paths()` in `arc_meta_config.py`, and the plugin README Configuration table; harness
    files do not change."
  - `plugins/arc-straps/README.md`, sections: **What it is**; **Requirements** (harness >= 0.56.0 enabled,
    for every collaborator before `plugins` is committed to `.claude/harness.json`, since an older harness
    rejects the key and every harness hook then fails on load; no ArcGIS
    Pro needed to load or to run arc-meta, which needs stdlib and pydantic under the harness interpreter;
    a future skill that imports arcpy must pin a Pro interpreter); **Boundary with harness** (a table: goes
    in harness = project-independent rules, review, commit, worktree flow; goes in arc-straps = anything
    that needs ArcGIS Pro, arcpy or the `.atbx` layout; arc-straps may call `harness-skill-api --file`,
    `harness_lib.config` (`active`, `load_config`, `ConfigError`) and `harness_lib.plugin_config.plugin_section`;
    its tests follow this repo's conventions: `tests/<area>/test_<name>.py` one level deep, `make_project`
    projects, no live checkout; strap-skills cannot target this plugin yet); **Configuration** (the
    `plugins.arc-straps.arc_meta` keys `atbx`, `tool_dir`, `toolbox_source`, `registry` with defaults and
    meanings from Section 4.3, plus a full `harness.json` example); **Apply writes** (an apply rewrites the
    archive in place after copying it to `<archive>.bak`; projects should gitignore `*.atbx.bak`; an
    arc-straps update can change the generator, so sweep `check_applied` over `tool_names()` after updating);
    **Migrating a project copy** (the Section 6 runbook, condensed).
  - `docs/PROVENANCE.md`: one "Additional sources" row:
    `| \`plugins/arc-straps/skills/arc-meta/**\` | toolbox project at \`0c4e45eb6\` (2026-11-04), \`.claude/skills/arc-meta/\` and \`scripts/fpm/_tbx_staging/metadata/{metadata_format,patch_tool_rc,clean_tool_metadata,patch_toolbox_metadata}.py\`: paths moved to \`plugins.arc-straps\` config, the three apply scripts re-cut as \`arc_meta_{rc,page,toolbox}.py\` over one shared archive rewrite, the generator vendored as \`arc_meta_format.py\`; no verbatim import commit |`
    plus path-map rows for each source file. Read the table first; do not name the project (`floodplain`
    is banned only under `plugins/`, but the existing rows use the neutral "toolbox project" form only if
    they do; follow what the file already does).
  - `.claude/harness.json`: add `"plugins/arc-straps/skills/"` to the `Agent` bucket's `prefixes`, before
    `"plugins/harness/reference/"`.
- [ ] **B10:** Run, each its own call (`test_the_plugin_readme_documents_its_keys` reads lane A's schema
  file, so it is deselected here and runs at I2):
  `PY -m pytest tests/contract/test_arc_straps_registration.py tests/contract/test_no_repo_literals.py tests/contract/test_plugin_icons.py tests/contract/test_mod_count.py -q -k "not documents_its_keys"`;
  (strict validation runs in the main session at I4). Expected: all PASS. Commit: `git commit -m "feat(arc-straps): plugin manifest, wiring and boundary docs"`.

### Task C: core modules, test builder, pythonpath (wave 1)

**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py`, `arc_meta_format.py`,
`arc_meta_canonical.py`, `arc_meta_archive.py` (all new, same folder), `tests/arc/_arc_toolbox.py`,
`tests/arc/test_arc_meta_format.py`, `tests/arc/test_arc_meta_archive.py` (new), `pyproject.toml`,
`tools/select_tests.py`, `tests/scripts/test_select_tests.py`.
SRC paths for the reviewer diff: `scripts/fpm/_tbx_staging/metadata/metadata_format.py`,
`.claude/skills/arc-meta/scripts/arc_meta_models.py`, `arc_meta_api.py:56-139` (archive and canonical
readers), `scripts/__tests__/_tbx_staging/test_metadata_format.py`, `scripts/__tests__/skills/test_arc_meta_api.py:1-197`.

- [ ] **C1: pythonpath, test first.** Add to `tests/scripts/test_select_tests.py` (follow its existing
  helpers for the real-repo call; read the file first):
  a test that `affected_tests(REPO_ROOT, ["plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py"])`
  (or the module's equivalent public function) selects `tests/arc/test_arc_meta_archive.py`, a test that
  imports `arc_meta_archive`, which imports `arc_meta_canonical` and then `arc_meta_format`, without naming
  `arc_meta_format` itself. Run `PY -m pytest tests/scripts/test_select_tests.py -q`; Expected: the new test
  FAILS (the archive test file does not exist yet, and the folder is not a pythonpath root). Then
  `pyproject.toml:10` -> `pythonpath = ["plugins/harness/lib", "tests", "plugins/arc-straps/skills/arc-meta/scripts"]`;
  `pyproject.toml:27` init-hook gains the same third entry; `tools/select_tests.py:73`
  `DEFAULT_PYTHONPATH` gains it too. The test turns green at C8, once the archive test exists.
  Mutation proof at C8: drop the third pyproject entry; the test FAILS; restore.
- [ ] **C2: failing format tests.** Port SRC `scripts/__tests__/_tbx_staging/test_metadata_format.py` to
  `tests/arc/test_arc_meta_format.py`: `import arc_meta_format as mf` and `from arc_meta_format import Run`
  replace the two package imports; tests unchanged otherwise. Run
  `PY -m pytest tests/arc/test_arc_meta_format.py -q`. Expected: collection ERROR
  `No module named 'arc_meta_format'`.
- [ ] **C3:** Copy SRC `scripts/fpm/_tbx_staging/metadata/metadata_format.py` to `arc_meta_format.py`
  (`git -C <SRC> show 0c4e45eb6:<path> > <dest>`); edit only the module docstring and comments that name the
  project, its folders or its scripts (the writer names become `arc_meta_rc` / `arc_meta_page`). Run C2's
  command. Expected: PASS.
- [ ] **C4: models, test first.** Start `tests/arc/test_arc_meta_archive.py` with model cases:
  `ApplyOutcome(surface="rc", changed=True, applied=False, extra=1)` raises `ValidationError`; assigning
  to a field raises; `issubclass(ApiError, ValueError)`. Run it; Expected: collection ERROR
  `No module named 'arc_meta_models'`. Copy SRC `arc_meta_models.py` (it already imports `Field`) and add
  Section 4.4. Keep the pydantic-2.4 note. Rerun; PASS.
- [ ] **C5: failing archive tests.** Create `tests/arc/test_arc_meta_archive.py` with:
  - `decode` of UTF-8, UTF-8-BOM and UTF-16-LE-BOM bytes;
  - `read_text` returns None for an absent member and raises `ApiError` naming the label for undecodable
    bytes (`b"\xff\x00\xd8"` without a BOM);
  - `read_json` raises `ApiError` "is not valid JSON" naming the label;
  - `rewrite` replaces one member, appends a new one, keeps the others byte-identical, leaves
    `<atbx>.bak` equal to the original bytes, and leaves no temp file beside the archive;
  - `rewrite` with a monkeypatched `zipfile.ZipFile.testzip` returning a member name raises `ApiError`
    and leaves the original archive bytes unchanged;
  - `rewrite` with `{"Demo.tool/tool.content.rc": b"{not json"}` and, separately,
    `{"Demo.tool/tool.metadata.xml": b"<metadata><unclosed></metadata>"}` raises `ApiError` naming that
    member, with `__cause__` a `JSONDecodeError` / `ParseError`, the archive bytes unchanged and no temp
    file left beside it.
  Build archives with `write_archive` from `arc._arc_toolbox` in `tmp_path` (no walk call, so no
  `WALK_ROOTS`). Run `PY -m pytest tests/arc/test_arc_meta_archive.py -q`. Expected: collection ERROR
  `No module named 'arc_meta_archive'` (or `arc._arc_toolbox`).
- [ ] **C6a: canonical tests first.** Append to `tests/arc/test_arc_meta_format.py`:
  - `arc_meta_canonical.rc_text(mf.parse(""))` is `""`; a plain paragraph gives its plain text; a `<b>` run
    gives `mf.to_xdoc(...)` output; `rc_text(mf.parse("<p><b>X</b> y</p>"), summary=True) == "X y"`;
  - `arc_meta_canonical.fields(tool_dir, "Demo")` on `CANONICAL` returns the plain summary and the
    lower-cased parameter keys. Derive the expected literals by reading SRC `_canonical_fields` against the
    SRC CANONICAL constant; if a value is not obvious, run the SRC function on a copy under the session
    scratchpad, never inside SRC; `fields(tool_dir, "Nope")` raises `ApiError` "no canonical source";
  - `arc_meta_canonical.load` raises `ApiError` "no canonical source" for a missing tool and
    "not well-formed XML" for broken XML;
  - `arc_meta_canonical.page(...)` of `CANONICAL` carries `direction` and `datatype` on every param and a
    `Binary/Thumbnail/img` only when an illustration is given, its `src` equal to
    `mf.illustration_data_uri(PNG_A)`.
  Run C2's command. Expected: the new tests FAIL with `No module named 'arc_meta_canonical'`.
- [ ] **C6b:** Write `tests/arc/_arc_toolbox.py` (Section 4.8), `arc_meta_archive.py` and
  `arc_meta_canonical.py` (Section 4.5). Port the rewrite from SRC `patch_tool_rc.py:145-209`, reading the
  other two SRC copies (`clean_tool_metadata.py:132-199`, `patch_toolbox_metadata.py:159-194`) and keeping
  any behavior one of them has that the reference lacks; list each kept difference in the commit message
  body. Port `page` from SRC `clean_tool_metadata.py:88-129` (with `_set_rich`, `_add_illustration`).
  Run C2's and C5's commands. Expected: PASS.
- [ ] **C8:** Run, each its own call: `PY -m pytest tests/arc/test_arc_meta_format.py tests/arc/test_arc_meta_archive.py tests/scripts/test_select_tests.py tests/contract/test_no_repo_literals.py -q`;
  `PY -m ruff check --no-cache plugins/arc-straps tests/arc tools/select_tests.py tests/scripts/test_select_tests.py`;
  then the C1 mutation proof. Commit: `git commit -m "feat(arc-straps): arc-meta models, generator, archive and canonical helpers"`.

### Task D: hover writer `arc_meta_rc.py` (wave 2)

**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_rc.py`, `tests/arc/test_arc_meta_rc.py`.

- [ ] **D1:** Port SRC `scripts/__tests__/_tbx_staging/test_patch_tool_rc.py` to `tests/arc/test_arc_meta_rc.py`
  under the Section 4.6 rules: `import arc_meta_rc as rc`; SRC `run(...)` calls become `rc.run_rc(...)` with
  the same injected `atbx`/`tool_dir`; capsys checks become `outcome.lines` checks; `outcome.backup`
  becomes `atbx.with_name(atbx.name + ".bak")`; the SRC fixture constants stay, and only `write_archive`
  (from `arc._arc_toolbox`) is reused. Add:
  - an rc stored as UTF-8 with a BOM is read and rewritten (state the resulting encoding SRC used);
  - `apply_rc("Demo", repo=root)` on a stale project returns `changed=True, applied=False` and leaves the
    archive bytes unchanged;
  - `apply_rc("Demo", apply=True, repo=root)` returns `applied=True`, writes `<atbx>.bak`, and a second
    dry run returns `changed=False`;
  - `apply_rc("Nope", repo=root)` raises `ApiError`.
  For the `apply_rc` cases build the project with `make_toolbox(make_project, members=toolbox_members(rc={"map": {**RC["map"], "description": "Old."}}))`.
- [ ] **D2:** Run `PY -m pytest tests/arc/test_arc_meta_rc.py -q`. Expected: collection ERROR
  `No module named 'arc_meta_rc'`.
- [ ] **D3:** Write `arc_meta_rc.py` from SRC `patch_tool_rc.py` per Section 4.6.
- [ ] **D4:** Run D2's command, then `PY -m ruff check --no-cache plugins/arc-straps/skills/arc-meta/scripts/arc_meta_rc.py tests/arc/test_arc_meta_rc.py`.
  Expected: PASS, clean. Mutation proof: make `apply_rc` skip `rewrite`; the apply test must FAIL; restore.
  Commit: `git commit -m "feat(arc-straps): arc-meta hover writer"`.

### Task E: page writer `arc_meta_page.py` (wave 2)

**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_page.py`, `tests/arc/test_arc_meta_page.py`.

- [ ] **E1:** Port SRC API tests 9-11 (`test_built_page_embeds_the_illustration_as_a_data_uri`,
  `test_built_page_without_an_illustration_has_no_binary_block`,
  `test_read_illustration_returns_the_archive_member_or_none`, SRC `test_arc_meta_api.py:285-308`) to
  `tests/arc/test_arc_meta_page.py`, replacing `mock.patch` of `ensure_tool_dir`/`ensure_atbx` with the
  explicit `tool_dir`/`atbx` arguments of `build_page(tool, tool_dir, illustration)` and
  `read_illustration(atbx, tool)`. Add the three `apply_page` cases from D1 (dry run on a project whose page
  member is `<metadata/>`, apply + `.bak` + idempotent rerun, unknown tool), plus: a linked-script tool
  with no `tool.metadata.xml` member gets one appended (SRC `clean_tool_metadata.py:149-150`), and
  `build_page("Demo", tool_dir) == default_page()`.
- [ ] **E2:** Run `PY -m pytest tests/arc/test_arc_meta_page.py -q`. Expected: collection ERROR
  `No module named 'arc_meta_page'`.
- [ ] **E3:** Write `arc_meta_page.py` from SRC `clean_tool_metadata.py` per Section 4.6;
  `_build_clean_metadata` becomes `build_page`, a one-line call of `arc_meta_canonical.page` (lane C owns the
  builder body; a defect found there is reported back, not patched in lane E).
- [ ] **E4:** Run E2's command and ruff on the two files. Expected: PASS, clean. Mutation proof: drop the
  illustration embed; the data-URI test must FAIL; restore. Commit: `git commit -m "feat(arc-straps): arc-meta page writer"`.

### Task F: toolbox writer `arc_meta_toolbox.py` (wave 2)

**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_toolbox.py`, `tests/arc/test_arc_meta_toolbox.py`.

- [ ] **F1:** Port SRC `scripts/__tests__/_tbx_staging/test_patch_toolbox_metadata.py` to
  `tests/arc/test_arc_meta_toolbox.py`, **dropping** SRC `:126-136` (it reads the live project's source and
  asserts its title). SRC `run(...)` calls become `run_toolbox(atbx, source, apply)`; the SRC test that
  expects `ET.ParseError` (SRC `:117-125`) now expects `ApiError` with `isinstance(exc.__cause__, ET.ParseError)`.
  Replace the dropped test with a `make_project` test on
  `make_toolbox(make_project, members=toolbox_members(extra={"toolbox.content.rc": json.dumps({"map": {"title": "Old", "descr": "old"}}).encode()}))`
  plus a demo `tool_metadata/demo_toolbox.atbx.xml`: `apply_toolbox(repo=root)` returns `changed=True`; with
  `apply=True` the archive's `toolbox.content.rc` and `toolbox.metadata.xml` match `build_rc`/`build_metadata`;
  a missing source raises `ApiError` naming the path; an archive without `toolbox.content.rc` raises
  `ApiError` naming the member (rule 8).
- [ ] **F2:** Run `PY -m pytest tests/arc/test_arc_meta_toolbox.py -q`. Expected: collection ERROR
  `No module named 'arc_meta_toolbox'`.
- [ ] **F3:** Write `arc_meta_toolbox.py` from SRC `patch_toolbox_metadata.py` per Section 4.6
  (`ToolboxSource`/`PatchOutcome` dataclasses may stay; `PatchOutcome` maps onto `ApplyOutcome` in
  `apply_toolbox`).
- [ ] **F4:** Run F2's command and ruff on the two files. Expected: PASS, clean. Mutation proof: make
  `build_rc` drop the description; a ported test must FAIL; restore. Commit:
  `git commit -m "feat(arc-straps): arc-meta toolbox writer"`.

### Task G: check API `arc_meta_api.py` (wave 2)

**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py`, `tests/arc/test_arc_meta_api.py`.

- [ ] **G1:** Port SRC `scripts/__tests__/skills/test_arc_meta_api.py` tests 1-8 and 12-21 to
  `tests/arc/test_arc_meta_api.py`: `import arc_meta_api as api`, `import arc_meta_models`; projects from
  `make_toolbox(make_project, ...)` from `arc._arc_toolbox`; every call passes `repo=root`. SRC `_built_page`
  becomes `default_page(canonical, illustration)`; SRC `_page`'s `div_style`/`drop_param` post-edits
  (SRC `:154-168`) stay in this test as a local `_page` helper over `default_page`. Never read SRC's older
  plan copy of this test: it is stale. Test 20 uses `tools/demo/run.py`. Test 21 asserts
  `api.ApiError is arc_meta_models.ApiError`. Add: a project with two archives and no `atbx` key makes
  `api.tool_names(repo=root)` raise `ConfigError`; a configured `registry` path that is absent gives
  `registry_path is None`; a canonical summary `<p><b>Makes</b> polygons.</p>` with rc description
  `Makes polygons.` (page built from that canonical) gives `check_applied` with no `hover_style_stale`.
  SRC paths for the reviewer diff: `.claude/skills/arc-meta/scripts/arc_meta_api.py`,
  `scripts/__tests__/skills/test_arc_meta_api.py`.
- [ ] **G2:** Run `PY -m pytest tests/arc/test_arc_meta_api.py -q`. Expected: collection ERROR
  `No module named 'arc_meta_api'`.
- [ ] **G3:** Write `arc_meta_api.py` from SRC per Section 4.7.
- [ ] **G4:** Run G2's command and ruff on the two files. Expected: PASS (21 tests), clean. Mutation proof:
  make `check_applied` skip the page comparison; the `page_stale` tests must FAIL; restore. Commit:
  `git commit -m "feat(arc-straps): arc-meta check API on configured paths"`.

### Task H: skill text, contract test, root separation (wave 3)

**Files:** `plugins/arc-straps/skills/arc-meta/SKILL.md`, `tests/skills/test_arc_meta_skill_contract.py`,
`tests/arc/test_arc_meta_roundtrip.py` (new), `tests/contract/test_root_separation.py`.
SRC paths for the reviewer diff: `.claude/skills/arc-meta/SKILL.md`,
`scripts/__tests__/skills/test_arc_meta_skill_contract.py`.

- [ ] **H1: failing contract test.** Port SRC `scripts/__tests__/skills/test_arc_meta_skill_contract.py`:
  paths from `conftest.REPO_ROOT / "plugins" / "arc-straps" / "skills" / "arc-meta"`; modules imported by
  bare name (pythonpath); `LAUNCHER` becomes
  `'harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/'`. Add:
  - each module named in a heredoc (`arc_meta_api.py`, `arc_meta_rc.py`, `arc_meta_page.py`,
    `arc_meta_toolbox.py`) exists, and every bare identifier called inside a heredoc body is in that
    module's `__all__` or a Python builtin (parse the `<<'PY' ... PY` blocks with a regex);
  - the body has no `$FPM_PY`, `PYTHONPATH`, `scripts/fpm`, `.atbx` file name literal, and none of
    `patch_tool_rc.py`, `clean_tool_metadata.py`, `patch_toolbox_metadata.py`, `metadata_format.py`;
  - three pinned sentences appear verbatim after whitespace is collapsed (they are exact SRC text and name
    nothing project-specific):

```python
B5_RULE = ("**Existing help text is a claim, not a source.** Every sentence in the canonical XML, the rc "
           "file or an old help page is re-derived from the entry module, the params model and the validator "
           "before it is kept, reworded or shortened.")
B8_LEAD = "**Written is not applied.**"
B8_ANSWER = ("When the developer asks whether a change is ready, shows, or \"uses the new X now\", apply it "
             "(Steps 4 and 5) and answer from `check_applied`, never from the generator's tests or a dry-run.")
```

  Run `PY -m pytest tests/skills/test_arc_meta_skill_contract.py -q`. Expected: FAIL (no SKILL.md).
- [ ] **H2: SKILL.md.** Port SRC `.claude/skills/arc-meta/SKILL.md` per Section 4.9: frontmatter `name:
  arc-meta`, description starting "Use when" and naming ArcGIS Pro toolbox (`.atbx`) help without a project
  name; every API call through the pinned heredoc; Step 4's four commands become `apply_rc` and `apply_page`
  heredocs (dry run, then `apply=True`), and the toolbox page sentence names `apply_toolbox`. Rules and
  Judgment bullets keep their SRC meaning and wording; the only edits allowed in them are this substitution
  list:
  - `metadata_format.py` -> `arc_meta_format.py` (the generator, which ships with arc-straps: "a change to
    `arc_meta_format.py`" means an arc-straps update);
  - `patch_tool_rc.py` -> `apply_rc`; `clean_tool_metadata.py` -> `apply_page`;
    `patch_toolbox_metadata.py` -> `apply_toolbox`; "the apply scripts" / "that script" -> "the apply calls"
    / "that call";
  - "Help rewritten from code on this toolbox found false claims in every tool:" -> "Help rewritten from
    code routinely finds false claims:" (the example list stays);
  - "The archive is tracked in git, so git is the rollback" -> "When the project tracks the archive in git,
    git is the rollback";
  - `TbxField(<index>)` -> "the params model's mapping from a dialog position to a field (a field without
    one is never read from the dialog)";
  - the registry sentence -> "never a configured registry's `py_path`, which can be stale";
  - `scripts/_validations/` -> "a project validator module the entry module imports".
  Elsewhere: the "Cleanup tolerances, Method selection" examples become "tool-specific ones"; the Related
  entries for `tool_metadata/tools/README.md` and `CreateRegularGrid.xml` are dropped; add one Related line
  naming the plugin README's Configuration section; the API section says it reads "the archive, the canonical
  XML and the generator" and adds `print(paths())` to its example; the arcpy stylesheet note stays.
  Run H1's command. Expected: PASS.
- [ ] **H3: round trip, test first.** Create `tests/arc/test_arc_meta_roundtrip.py`: a project from
  `make_toolbox(make_project, members=toolbox_members(rc={"map": {**RC["map"], "description": "Old."}}, page="<metadata/>", extra={ILLUSTRATION_ENTRY: PNG_A}))`
  (adjust so `Mode` has canonical text but no `$rc:` wiring, following SRC test 5's setup); assert
  `check_applied` is not empty; run `apply_rc("Demo", apply=True, repo=root)` and
  `apply_page("Demo", apply=True, repo=root)`; assert `check_applied("Demo", repo=root) == []`.
  Parametrize a second case where the canonical summary and one `dialogReference` are bold CDATA. Run
  `PY -m pytest tests/arc/test_arc_meta_roundtrip.py -q`; Expected: PASS. Mutation proof: change only
  the writer side (`arc_meta_canonical.fields`, which the rc writer calls) to build the summary without
  `summary=True`; the bold case FAILS with `hover_style_stale`; restore. (Mutating the shared `fields_of`
  moves checker and writer together and proves nothing.)
- [ ] **H4: root separation.** In `tests/contract/test_root_separation.py`: `_run` sends a `str` payload as
  is (`stdin = payload if isinstance(payload, str) else (None if payload is None else json.dumps(payload))`);
  add

```python
from arc._arc_toolbox import ATBX, CANONICAL, RC, TOOL, toolbox_members, write_archive  # noqa: E402

ARC_SCRIPTS = REPO_ROOT / "plugins" / "arc-straps" / "skills" / "arc-meta" / "scripts"


def _arc_rc_args(root: Path) -> Tuple[List[str], str]:
    """apply_rc through the harness launcher on a stale demo toolbox written into ``root``."""
    stale = toolbox_members(rc={"map": {**RC["map"], "description": "Old."}})
    write_archive(root / ATBX, stale)
    (root / "tool_metadata" / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tool_metadata" / "tools" / f"{TOOL}.xml").write_text(CANONICAL, encoding="utf-8")
    argv = ["scripts/skill_api.py", "--repo", str(root), "--file", str(ARC_SCRIPTS / "arc_meta_rc.py"), TOOL]
    return argv, "print(apply_rc(name, apply=True).applied)\n"


def test_arc_meta_apply_lands_in_the_project(project: Path, tmp_path: Path) -> None:
    script, payload = _arc_rc_args(project)
    done = _run([str(PLUGIN_ROOT / script[0]), *script[1:]], project, payload)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "True"
    assert (project / f"{ATBX}.bak").is_file()
```

  with the `CASES` entry `"arc-meta apply_rc": lambda r, t: _arc_rc_args(r)` and `"arc-meta apply_rc"` in
  `MUST_EXIT_ZERO`. Run `PY -m pytest tests/contract/test_root_separation.py -q -k arc`. Expected: PASS.
  Mutation proof: temporarily make `arc_meta_archive.rewrite` write its `.bak` to
  `Path(__file__).parent / (atbx.name + ".bak")`; the run still exits 0 and the snapshot case FAILS with
  `wrote under plugins/` and a `+ arc-straps/...` line; delete the stray file and restore.
- [ ] **H5:** Run `PY -m pytest tests/contract/test_no_repo_literals.py -q` and ruff on the four files;
  commit: `git commit -m "feat(arc-straps): arc-meta skill text, contract, round trip and root separation"`.

### Task I: integration (main session, after wave 3 stages)

- [ ] **I1:** Each its own call, from the target checkout:
  `PY -m pytest tests/lib/test_config.py tests/lib/test_plugin_config.py tests/scripts/test_pr_review_driver.py tests/arc/test_arc_meta_config.py tests/arc/test_arc_meta_format.py tests/arc/test_arc_meta_archive.py tests/arc/test_arc_meta_rc.py tests/arc/test_arc_meta_page.py tests/arc/test_arc_meta_toolbox.py tests/arc/test_arc_meta_api.py tests/arc/test_arc_meta_roundtrip.py tests/skills/test_arc_meta_skill_contract.py -q`
- [ ] **I2:** `PY -m pytest tests/contract/test_no_repo_literals.py tests/contract/test_root_separation.py tests/contract/test_hooks_json_paths.py tests/contract/test_plugin_icons.py tests/contract/test_mod_count.py tests/contract/test_arc_straps_registration.py tests/scripts/test_select_tests.py tests/scripts/test_skill_api_file.py tests/schemas/test_schema_meta_valid.py -q`
- [ ] **I3:** `PY -m ruff check --no-cache plugins tests tools`
- [ ] **I4:** `claude plugin validate --strict .`, `claude plugin validate --strict plugins/arc-straps`,
  `claude plugin validate --strict plugins/harness`
- [ ] **I5:** `PY tools/select_tests.py --base main`. Expected: a full run (`pyproject.toml` and
  `tools/select_tests.py` changed); the import-closure claim is proven by the C1 test, not by this preview.
- [ ] **I6:** Manual smoke for the developer (a model's free-text reply is not evidence): start
  `claude --plugin-dir plugins/harness --plugin-dir plugins/arc-straps` and confirm `arc-straps:arc-meta` is
  listed in `/skills`.
- [ ] **I7:** Full-suite run is the developer's (`PY -m pytest tests/*/test_*.py -q`): hand it over.
- [ ] **I8:** The PR body says `Part of #210; refs #211 (done-when 2 waits on the Section 6 cutover)`, and
  F1-F3 plus the cutover are handed to the developer as drafted issue texts.

## 6. Out of scope: cutover runbook and follow-ups

**Cutover in the toolbox project** (separate change, after the plugin is installed there; #211 done-when 2):

1. Install `harness` (>= 0.56.0) and `arc-straps`; add to its `.claude/harness.json`:
   `"plugins": {"arc-straps": {"arc_meta": {"atbx": "<its archive>", "registry": "<its registry json>"}}}`
   (`tool_dir` and `toolbox_source` match the defaults there).
2. Remove `.claude/skills/arc-meta/` (both copies would load) and its two skill tests and registry entries.
3. Delete `patch_tool_rc.py`, `clean_tool_metadata.py`, `patch_toolbox_metadata.py` and their tests; the
   README apply commands become the skill's apply heredocs (a batch is a heredoc loop over `tool_names()`).
   Keep `metadata_format.py` only while `harvest_canonical.py` (F3) still imports it, marked harvest-only:
   archives are applied and checked by the plugin's `arc_meta_format.py`. Two live generators would let a
   project-side apply and the plugin's `check_applied` disagree.
4. Archive `docs/PLANS/strap/arc-meta/` there (it is stale against its own skill).

**Follow-up issues (drafted, not filed):**

- **F1** strap-skills: a profile for a non-harness plugin (`strap.target` naming a plugin, project-style
  `scripts/` layout, `${CLAUDE_PLUGIN_ROOT}` rewrite, plugin search outside the project root) so
  arc-meta's judgment behaviors B5-B9 can be re-strapped from a toolbox consumer.
- **F2** arc-straps: an interpreter pin for skills that import arcpy (ArcGIS Pro's conda environment).
- **F3** arc-straps: port `harvest_canonical.py` (bootstrap canonical XML from an archive).
