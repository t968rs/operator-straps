---
name: arc-help-pages
description: "Use when writing, rebuilding or checking the server-hosted help page of a tool in an ArcGIS Pro toolbox archive (.atbx), the page its ? help page links to; when a tool's help link points at a missing, outside-the-checkout or relative target; or when a help page is stale against the tool's canonical help XML."
argument-hint: "<page> [-- <guidance>]"
---

# arc-help-pages: a tool's help page, built from code and linked from Pro

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token. Before it: the page name (the stem of the fragment file, usually
the tool name). After it: guidance for this run.

A tool's "?" page in ArcGIS Pro can link to a longer help page hosted as a file in the project. This skill
builds that page from two sources, the tool's canonical help XML (`<Tool>.xml` in the `tool_dir` of
`arc-meta`) and a hand-written page fragment, and checks that the page is current and that the tool's links
resolve. The page states what the code does today; the fragment is the only page file written by hand.

Every command below runs with the Bash tool from the project checkout. The API and the apply calls run
through `harness-skill-api`, which the harness plugin puts on the Bash PATH; every refusal is one `problem:`
line and exit 1. The locations come from `plugins.arc-straps.arc_help_pages` in `.claude/harness.json`
(`atbx`, `tool_dir`, `help_dir`); `print(paths())` shows them resolved.

## Project content

All of it lives in the project, under `help_dir` (default `tool_metadata/tool_help`):

- `_template.html`: the page frame. It takes `$title`, `$summary`, `$nav` and `$sections`, and optionally
  `$footer`. A missing required slot, an unknown slot or a malformed one is refused, naming the template.
- `_fragments/<page>.html`: the hand-written source of one page. Its first line is the tool line
  `<!-- help:tool <Tool> -->`, where `<Tool>` is the archive's `<Tool>.tool` folder name. The rest is page
  content in `<section class="panel" id="...">` blocks, each with a unique `id` and an `<h2>`. The two lines
  `<!-- help:parameters -->` and `<!-- help:syntax -->` each stand once where the generated Parameters and
  Python syntax sections go; their ids, `parameters` and `syntax`, are reserved, and the build refuses a
  fragment section that uses one or repeats an id.
- `<page>.html`: the built page. Never edit it by hand; `apply_help` writes it from the template, the
  fragment and the canonical XML, and an edited page is reported stale.
- `img/`: images the fragments reference.

The build fills the generated sections from the canonical XML and `tool.content`: the Parameters table in
dialog order with its reference text ("No description." when a parameter has none), and the one-line Python
syntax with optional parameters in braces and derived outputs listed after it. The nav lists each section by
its `id` and `<h2>` in page order. A rebuild of unchanged sources is byte-identical at any checkout root.

## Link contract

The tool's canonical XML links to the page with its development href, `paths().page_href(page)`: the
`file:` URI of the repository's main checkout plus the page's path relative to the project root. The main
checkout is used even from a linked worktree, so the href is the same in every worktree. The href goes in a
CDATA rich field (`<usage>` or a CDATA `<dialogReference>`), never in a `<para>`. The production swap of the
development href for a hosted URL happens downstream of this skill, which only checks the development form.

## Rules

- **Existing page text is a claim, not a source.** Every sentence of an old page or fragment is re-checked
  against the entry module, the params model and the validator before the fragment keeps it. A contradicted
  claim is replaced and named in the reply, with the file and line that contradicts it. This holds when the
  request says "keep the content".
- **A bug is documented as it behaves, and reported apart.** Never describe intended behavior, and never edit
  code from a help task.
- **The generated sections are not written by hand.** Parameter names, types and reference text come from the
  canonical XML; to change them, change the canonical XML with `arc-meta`.
- **Written is not applied.** A fragment or canonical XML change is invisible until `apply_help` rebuilds the
  page and, for the link, `arc-meta` applies the canonical XML to the archive.

## Steps

1. **Read the tool's code.** Read the entry module (the `entry` that `arc-meta`'s `entry_sources` names, or
   the script embedded in the archive), the params model (its mapping from a dialog position to a field) and
   the validator (`tool.script.validate.py` in the archive, or a project validator module): it disables
   parameters, sets dialog defaults and raises dialog-only warnings. Read the existing page and fragment last,
   as claims to re-check.
2. **Write or update the fragment** at `_fragments/<page>.html`: the tool line, then the sections the page
   needs, with the two generated-section markers in place. Keep the fragment to what the code does; leave
   parameter descriptions to the canonical XML.
3. **Build.** Dry-run, then apply. A dry run that would write ends "DRY-RUN: nothing written. Re-run with
   apply=True to write."; when the page already matches, `apply_help` reports "UP TO DATE" and the apply is
   skipped.

```bash
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py" <page> <<'PY'
print("\n".join(apply_help(name).lines))
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py" <page> <<'PY'
print("\n".join(apply_help(name, apply=True).lines))
PY
```

4. **Link.** Print the development href with `print(paths().page_href(name))` (API section) and add or confirm
   it as an `<a href="...">` in a CDATA field of the tool's canonical XML. Then apply the XML with
   `arc-meta`: `check_canonical`, then the dry-run and apply of `apply_page` (and `apply_rc` when the same
   change touched hover text).
5. **Check.** Run `check_help_page` for the page and `check_links` for the tool until both print `clean`
   (API section). A problem is cured at its source: `fragment_invalid` and `help_page_stale` by the fragment
   or a rebuild, `help_page_unlinked` and the `link_*` codes by the canonical XML.
6. **Hand off** (Hand off section).

## API

The heredoc runs with the API module's `__all__` bound, plus `name` (the page, or the tool for `check_links`).
It reads the project and writes nothing, except `apply_help(name, apply=True)`, which writes
`<help_dir>/<page>.html` and nothing else.

```bash
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py" <<'PY'
print(paths())
print(help_pages())
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py" <page> <<'PY'
print(paths().page_href(name))
print(format_problems(check_help_page(name)))
PY
harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py" <Tool> <<'PY'
print(format_problems(check_links(name)))
PY
```

| Call | Returns |
|---|---|
| `paths()` | the resolved locations: project root, archive, `tool_dir`, `help_dir` and the main checkout; `page_href(page)` is the development href of a page |
| `help_pages()` | the sorted stems of `_fragments/*.html` |
| `build_page(page)` | the page text built from its fragment, the template and the canonical XML; writes nothing |
| `apply_help(page, apply=False)` | the dry-run or write report of `<help_dir>/<page>.html` |
| `check_help_page(page)` | `fragment_invalid` alone for a fragment the build refuses; one `help_page_stale` alone for a page the build cannot make; otherwise `help_page_stale` (page absent or different from a rebuild; a CRLF checkout of an unchanged page is current) and `help_page_unlinked` (the fragment tool's canonical XML holds no href to this page) |
| `check_links(tool)` | one problem per defective href in the tool's canonical XML: `link_target_missing` (a development href naming no file in the current tree), `link_outside_checkout` (dead in production: any other `file:` href, a development href whose path leaves the checkout through `..`, a drive path such as `C:\x.html`, an href rooted at `/` or `\` including UNC paths, and an href the URL parser refuses such as `http://[`, detail `(malformed href)`), `link_relative` (no scheme and not rooted, which resolves against Pro's temp copy of the page); only `#` anchors and web links (schemes of two or more letters other than `file:`) are skipped |
| `format_problems(problems)` | one `code \| subject \| detail` line per problem, or `clean` |

## Judgment

| Situation | Call |
|---|---|
| The request vouches for the old page text | Re-check each claim against the code anyway; replace and name the contradicted ones. |
| The code and the canonical XML disagree on a parameter | The generated section follows the canonical XML; fix the XML through `arc-meta` and report the mismatch. |
| `check_links` reports `link_relative` | Replace the href with the development href of the page. |
| `check_links` reports `link_outside_checkout` | The href names another checkout, a path outside the repository, a drive or rooted path, or is malformed; replace it with the development href. |
| `check_help_page` reports `help_page_stale` after an apply | Another source changed since: rebuild; a refusal naming the canonical XML or the archive is fixed there, not in the page. |
| The page is current but `help_page_unlinked` | Add the development href to the tool's canonical XML and apply it with `arc-meta`. |

## Hand off

Report each page built with its `check_help_page` result and each tool with its `check_links` result, each
replaced claim with the code that contradicts it, each bug found (as a separate item, never fixed here), and
the Pro step left to the developer: reopen the toolbox, click "?" and follow the link.

## Related

- `${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py`: the API; `arc_help_pages_build.py` builds the page,
  `arc_help_pages_source.py` reads the canonical XML and the archive, `arc_help_pages_config.py` resolves the
  locations and `arc_help_pages_models.py` holds the records.
- The `arc-meta` skill: the canonical XML and its apply calls.
- The arc-straps plugin README, Configuration section: the `plugins.arc-straps.arc_help_pages` keys and their
  defaults.
