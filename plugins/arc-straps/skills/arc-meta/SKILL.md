---
name: arc-meta
description: "Use when writing, fixing or applying the help users see for a tool in an ArcGIS Pro toolbox archive (.atbx): the hover tooltips, the tool summary, the ? help page or the canonical per-tool help XML; when a tooltip or help page is blank, wrong, stale or badly spaced in ArcGIS Pro; or when checking which tools still need their help applied."
argument-hint: "<ToolName> [-- <guidance>]"
---

# arc-meta: toolbox help, from code to ArcGIS Pro

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token. Before it: the tool name (the `<Tool>.tool` folder name in the
archive, also the canonical XML stem). After it: guidance for this run.

A tool's help reaches users on two surfaces, both inside the toolbox archive (the `.atbx` zip the configured
`atbx` names; by default the one `.atbx` at the project root): the dialog and its hover tooltips
(`<Tool>.tool/tool.content.rc`, referenced from `tool.content`) and the "?" page
(`<Tool>.tool/tool.metadata.xml`). Both are generated from one canonical source, `<Tool>.xml` in the
configured `tool_dir` (default `tool_metadata/tools`), by the apply calls of this skill (`apply_rc` and
`apply_page`). The help states what the code does today, and the canonical XML is the only file written by
hand.

Every command below runs with the Bash tool from the project checkout. The API and the apply calls run
through `harness-skill-api`, which the harness plugin puts on the Bash PATH; every refusal is one `problem:`
line and exit 1. The locations come from `plugins.arc-straps.arc_meta` in `.claude/harness.json`;
`print(paths())` shows them resolved.

## Rules

- **Existing help text is a claim, not a source.** Every sentence in the canonical XML, the rc file or an
  old help page is re-derived from the entry module, the params model and the validator before it is kept,
  reworded or shortened. This holds when the request says "prose only", "keep the meaning" or "the content is
  accurate": rewording a claim publishes it again, and a vouched-for sentence is exactly the one nobody
  checked. Help rewritten from code routinely finds false claims: inverted semantics,
  "deletes files in the folder" for a tool that clears only its own run geodatabase, units the code never
  converts, choices the value list no longer offers, "added to the active map" for outputs that are only set
  as derived parameters.
- **A contradicted claim is replaced and named.** Write what the code does instead, and list each replaced
  claim in the reply, with the file and line that contradicts it. The developer vouched for the old text, so a
  silent correction reads as a style edit and the wrong belief survives.
- **A bug is documented as it behaves, and reported apart.** When the code fails or ignores an input, the help
  says so in plain words ("a Hazard row stops the tool with an error", "the tool does not currently set this
  output") and the reply reports the bug as a separate fix. Never describe the intended behavior, and never
  edit code from a help task. When the bug is fixed, the canonical XML changes in the same change.
- **A parameter the tool never reads gets no behavior.** Its hover is "Not read by the current version of the
  tool." plus "The tool dialog disables this parameter." when the validator disables it; the usage lists such
  parameters once under **Parameters not in use**. No recommended values, no description inferred from the
  name.
- **Written is not applied.** A change to a canonical XML or to `arc_meta_format.py` is invisible in Pro until
  the apply calls write it into the archive. When the developer asks whether a change is ready, shows, or
  "uses the new X now", apply it (Steps 4 and 5) and answer from `check_applied`, never from the generator's
  tests or a dry-run. Applying is the step the question implies, so do it rather than hand it back. The apply
  can run with the toolbox open in Pro; reopen the toolbox afterward to see the change. When the project
  tracks the archive in git, git is the rollback (`.atbx.bak` keeps only the state before the last apply). A
  `problem: ApiError: <archive> is locked` line (a `PermissionError: [WinError 5]` on the swap) means Pro, an
  indexer or a scan holds the file; it leaves the archive unchanged, and a rerun (after closing the toolbox in
  Pro, if it persists) clears it. An apply publishes everything the canonical XML holds, not
  only the change at hand, so scope it: a change to one tool's XML applies that tool; a change to
  `arc_meta_format.py` re-applies only tools whose `check_applied` problems are `page_style_stale`,
  `hover_style_stale` or `page_image_stale` alone (with `hover_unwired` allowed beside the page codes).
  `page_style_stale` re-runs `apply_page` (`hover_unwired` may sit beside it, since that call never touches
  the rc); `hover_style_stale` re-runs `apply_rc`, but only when the tool reports no `hover_unwired`, since
  that call wires every missing reference. `page_image_stale` comes from a `tool.illustration.png` added,
  changed or removed in the archive, not from a generator change; it re-runs `apply_page` on its own, on the
  same terms as `page_style_stale`. A tool that also reports `page_stale` or `hover_stale` holds canonical
  text never published and never checked against code; leave it out and list it in the reply.
  `check_applied` is per tool and never reads the toolbox page, so a change to `arc_meta_format.py` then
  dry-runs `apply_toolbox` and applies it when it does not report `UNCHANGED`.
- **Join keys come from `param_table`, never from memory.** A canonical `<param name>` that differs from the
  `tool.content` name by one character drops its text without an error; the Python field names of the params
  model are not the join keys.
- **Never use Pro's metadata Import** to update a tool: it merges into the existing metadata rather than
  replacing it, so parameters and summaries are duplicated.

## Steps

1. **Map the tool.** Run `param_table`, `entry_sources` and `check_canonical` (API section). The param table is
   the join-key authority and shows which parameters already have wired hovers.
2. **Read the code.** Read the entry module `entry_sources` names (never a configured registry's `py_path`,
   which can be stale). When `entry` is None, the code is the embedded script that
   `ToolSources.embedded_script` names, read inside the archive. When `entry` is set but `entry_exists` is
   False, the link dangles: stop and report it as a bug instead of writing help from it. Then read the params model (the
   params model's mapping from a dialog position to a field; a field without one is never read from the
   dialog) and the validator (`tool.script.validate.py` inside the archive, or a project validator module the
   entry module imports): it disables parameters, sets dialog defaults and raises dialog-only warnings. Output
   slots are often hard-coded indexes, so confirm an index in code rather than by its position in the dialog.
3. **Write the canonical XML** (Authoring section), then run `check_canonical` until it prints `clean`. It
   runs the generator's parser over every rich field, so `unparseable` names markup the apply calls refuse.
4. **Apply.** For each tool changed, dry-run then apply both calls, with the commands below. A dry run that
   would write ends "DRY-RUN: nothing written. Re-run with apply=True to write."; when there is nothing to
   write, `apply_page` reports "UP TO DATE: the archive page matches the canonical source; nothing to
   write.", `apply_toolbox` reports "UNCHANGED: the archive already matches the source; nothing written."
   and `apply_rc` reports `<Tool>: no changes`, and that apply is skipped. For `apply_rc` the first line
   decides: a `<Tool>: no changes` head means nothing to write, whatever the last line says. An `apply_rc` line
   "tool.content references $rc:<key>, which the rc lacks; not added" is never cured by a rerun: that key
   stays `hover_stale` in `check_applied`. A summary or parameter whose `tool.content` description is a
   literal string or another `$rc:` key is left alone the same way and stays `hover_unwired`.

```bash
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_rc.py" <Tool> <<'PY'
print("\n".join(apply_rc(name).lines))
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_rc.py" <Tool> <<'PY'
print("\n".join(apply_rc(name, apply=True).lines))
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_page.py" <Tool> <<'PY'
print("\n".join(apply_page(name).lines))
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_page.py" <Tool> <<'PY'
print("\n".join(apply_page(name, apply=True).lines))
PY
```

`apply_rc` writes the hover text and wires a missing `$rc:` reference into `tool.content` for every parameter
with non-empty canonical text and no `description` at all; it never rewrites a description that is present,
and never adds an rc key `tool.content` already references; `apply_page` regenerates the "?" page. The toolbox page itself comes from
`apply_toolbox` (no tool argument), which writes the toolbox title, description and item page from the
configured `toolbox_source`:

```bash
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_toolbox.py" <<'PY'
print("\n".join(apply_toolbox().lines))
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_toolbox.py" <<'PY'
print("\n".join(apply_toolbox(apply=True).lines))
PY
```

5. **Verify.** `check_applied` prints `clean` for every tool changed, or only `hover_unwired` for a tool
   re-applied for style or image alone (see Rules and Judgment). A `hover_stale` on a key the `apply_rc` report
   named as lacking, or a `hover_unwired` on a literal or mis-keyed description, is not reached by any apply
   call: only a manual `tool.content` or rc edit clears it, and the reply names it. Then the developer
   reopens the toolbox in Pro, hovers a parameter and the tool itself, and clicks "?".
6. **Hand off** (Hand off section).

## Authoring

- **Format:** ArcGIS metadata format 1.0, `ItemDescription` profile. `<summary>` and `<usage>` are
  CDATA-wrapped HTML; `<dialogReference>` is a `<para>` or CDATA HTML. The subset is `<p>`, `<b>`, `<i>`,
  `<ul>`/`<li>` with one level of `<ul>` inside an `<li>`. The generator emits the heavy
  `<DIV STYLE=...><SPAN>` markup; never write it by hand. No `<Binary>`/`<Thumbnail>` in the canonical XML, no
  links (the "?" page is rendered from a temp copy, so relative links break and the hover renders none). ASCII
  punctuation only.
- **Images:** a tool's `<Tool>.tool/tool.illustration.png` in the archive is embedded by `apply_page` as
  `<Binary><Thumbnail><img src="data:image/png;base64,..."/>` in the "?" page, the element Pro's stylesheets
  draw as the page illustration. The canonical XML never carries it; `page_image_stale` means the page and the
  archive image disagree, and a re-apply of the page call cures it. `tool.icon.png` is the toolbox-tree icon
  and is not part of the page.
- **Names:** `type` and `direction` as `param_table` spells them; the tool `displayname` without the numeric
  ordering prefix the rc title carries ("00b ...", "01 ...").
- **Every parameter appears**, hidden and derived ones included, with an empty `<para></para>` when it has no
  text: a parameter left out of the XML disappears from the "?" page.
- **Summary:** one sentence on what the tool produces.
- **Usage:** a short opener on what the tool writes and where, then bold heading paragraphs as they apply:
  **Outputs**, **How the inputs shape the result**, **Parameters not in use**, **The tool stops with an error
  when**, **Warnings**, **Large inputs**, plus tool-specific ones. Bullets of at most two sentences;
  sub-bullets for field lists, value-list choices and multi-effect tolerances.
- **Derived outputs:** "Derived output set to <what>. When ArcGIS Pro adds it to the map, it is drawn with the
  <X> layer symbology.", with X from the `symbology` column; never "added to the map".
- **Defaults and choices:** quote a default only when Pro shows it (the `default` column) or say where it
  comes from. A value-list choice renamed in help needs its `value` changed in `tool.content`, not only its rc
  label.
- **A restructure of existing usage** keeps every fact: diff the words against the committed version, and the
  only words lost are connectives.

## The "?" page rendering

Pro renders summary and usage through `elementSupportingMarkup` in
`Resources\Metadata\Stylesheets\ArcGIS_Imports\generalPro.xslt` (install folder from
`arcpy.GetInstallInfo()['InstallDir']`), which wraps the decoded HTML in `<pre class="wrap">`, and then
pretty-prints the page: a newline and indentation between every tag. Under `white-space: pre-wrap` each of
those renders as a blank line, and the stylesheet also pads every `p` and `li` by 1em. The generator answers
both: `PRO_DIV_STYLE` puts `white-space:normal` and negative top and bottom margins on the outer DIV, list
items carry no inner `<P>`, and the `PRO_*_STYLE` constants pad each block inline. Spacing that looks wrong
is first a `check_applied` question (`page_style_stale` means the archive still holds older markup or a parameter order that differs from the
canonical XML); padding
changes alone never cure the blank lines.

To see a real render: Pro writes it to `%TEMP%\ArcGISProTemp<pid>\<hash>.htm` and deletes it within about a
minute, so copy it the moment its path is known. Older renders are UTF-16 with a byte-order mark. An offline
preview is faithful only with Pro's stylesheet, the `<p><pre class="wrap">` wrapper and the content
pretty-printed with CRLF and two-space indentation; without the injected whitespace a preview looks fine
while Pro does not.

## API

The heredoc runs with the API module's `__all__` bound, plus `name` (the tool name). It reads the archive, the
canonical XML and the generator, and writes nothing. The generator, `arc_meta_format.py`, ships with
arc-straps, so a change to it arrives as an arc-straps update. An apply heredoc binds its own module's
`__all__` the same way.

```bash
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_api.py" <Tool> <<'PY'
print(paths())
print(format_rows(param_table(name)))
print(entry_sources(name))
print(format_problems(check_canonical(name)))
print(format_problems(check_applied(name)))
PY
```

| Call | Returns |
|---|---|
| `paths()` | the resolved locations: project root, archive, `tool_dir`, `toolbox_source` and registry (None when none is configured) |
| `param_table(tool)` | one row per `tool.content` parameter: join key, dialog title, type and direction as the canonical XML spells them, datatype, whether the hover is wired, symbology layer, value-list values, Pro default |
| `entry_sources(tool)` | the entry module from `tool.script.execute.link` with `entry_exists` (False when the link dangles), the embedded script as `embedded_script` (None when the archive holds none), the embedded validator, and the configured registry's `py_path` with a `registry_stale` flag |
| `check_canonical(tool)` | join-key, type and direction mismatches, a numeric-prefixed displayname, non-ASCII text, thumbnails, unsupported tags, lists nested past one level, markup the generator refuses (`unparseable`) |
| `check_applied(tool)` | each surface whose archive state differs from the canonical XML: `hover_unwired`, `hover_stale`, `hover_style_stale`, `page_stale` (a missing `tool.metadata.xml` page, text, the resTitle or keywords, a dropped or extra parameter, or a displayname, type, direction or datatype attribute), `page_style_stale` (older generator markup, or a parameter order that differs from the canonical XML), `page_image_stale` (the page's illustration differs from the archive's `tool.illustration.png`, is missing, or is present when the archive has none); a summary or parameter whose canonical text is empty is not compared against the rc |
| `tool_names()` | every tool in the archive, for a sweep of `check_applied` |

## Judgment

| Situation | Call |
|---|---|
| The request vouches for the old text or asks for wording only | Re-derive each claim anyway; replace and name the ones the code contradicts. |
| The suggested sentence describes behavior the code does not have | Write what the code does, report the gap as a bug; no code edit. |
| A parameter is in `tool.content` but no code reads it | The standard hover sentence; listed under Parameters not in use. |
| The developer asks whether a change shows in Pro | Apply, run `check_applied`, then answer; tests and dry-runs do not answer it. |
| A generator change and a sweep shows many stale tools | Re-apply the style-only ones; list the `page_stale` / `hover_stale` ones as unpublished text, unapplied. |
| `check_applied` reports `page_image_stale` (the archive illustration was added, changed or removed) | Re-run `apply_page` for that tool only, unless it also reports `page_stale` or `hover_stale`; then `check_applied`. |
| `check_applied` reports `hover_unwired` for a tool not yet code-verified | Leave the hover unwired and say so: wiring publishes text nobody checked. |
| `hover_stale` or `hover_unwired` survives an `apply_rc` rerun (a key the rc lacks, or a literal or mis-keyed description in `tool.content`) | Stop re-applying; the writer leaves both alone. Name the key and the manual `tool.content` or rc edit that clears it in the reply. |
| Help and code disagree on a range or default | Document what the code accepts and report the mismatch. |

## Hand off

Report each tool applied with its `check_applied` result, each replaced claim with the code that contradicts
it, each bug found (as a separate item, never fixed here), and the Pro step left to the developer: reopen the
toolbox, hover, click "?".

## Related

- `${CLAUDE_SKILL_DIR}/scripts/arc_meta_api.py` and `arc_meta_models.py`: the API and its records.
- `${CLAUDE_SKILL_DIR}/scripts/arc_meta_rc.py`, `arc_meta_page.py` and `arc_meta_toolbox.py`: the apply calls.
- The arc-straps plugin README, Configuration section: the `plugins.arc-straps.arc_meta` keys and their
  defaults.
