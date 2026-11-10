# Plan 1011: arc straps help links

> Rendered by `plan.py render` from `1011_arc_straps_help_links_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-09
**Spec:** `consuming project: docs/superpowers/specs/2026-11-09-toolbox-help-links-design.md`
**Branch:** none -> main
**Base commit:** `e703a52`
**Frozen:** 2026-11-09 at `d71476a`
**Execution model:** serial

## Decisions

- **D1** A <para> dialogReference flattens its child elements: arc_meta_format.inner_html joins itertext() (arc_meta_format.py:253-255), so <para>See <a href="...">x</a></para> loses the href silently, and check_canonical never sees the <a> (it scans inner_html's output). Most canonical dialogReferences in the consuming project are <para>. How does a link in a <para> field behave? Chosen: `flag_para_children` (check_canonical reports an element child of <para> (such as <a>) as unsupported_para_markup, so the author moves the field to CDATA; writers unchanged. Adds a TASK-2 node.). Rejected: `cdata_only` (Links go in CDATA fields only; the arc-meta SKILL.md sentence says so; no code change, the href in a <para> is still dropped without a report.), `serialize_para_children` (inner_html (and arc-help-pages' own <para> reader) serialize child elements, so <a> in a <para> passes through like CDATA. Adds TASK-1 and TASK-5 nodes.). A <para> stays plain text; check_canonical names the dropped markup so the author moves the field to CDATA, and no reader changes. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).
- **D2** checkout_root: harness already computes the parent of `git rev-parse --path-format=absolute --git-common-dir` as harness_lib.project.main_worktree (project.py:49-64), but CLAUDE.md:13-14 and plugins/arc-straps/README.md:51 limit arc-straps to project_root from that module. Chosen: `harness_main_worktree` (arc_help_pages_config imports harness_lib.project.main_worktree; CLAUDE.md:14 and the plugin README Boundary section name it beside project_root.). Rejected: `local_git_call` (arc_help_pages_config runs the git command itself (subprocess, stdin closed, timeout), mirroring main_worktree's fallbacks; the documented harness surface stays as it is.). harness_lib.project.main_worktree already implements the rule with its outside-git and bare-repository fallbacks; arc-straps documents it beside project_root instead of a second git call. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).
- **D3** Fragment markers: the spec spells them <!-- fpm:tool X -->, <!-- fpm:parameters -->, <!-- fpm:syntax -->. `fpm` is the consuming project's package name, and CLAUDE.md:9-11 bars consumer names under plugins/ (the ban test's `\bfpm\.[a-z_]` pattern, tests/contract/test_no_repo_literals.py:27, does not catch `fpm:`). Chosen: `generic` (A plugin-owned prefix, e.g. <!-- help:tool X -->, <!-- help:parameters -->, <!-- help:syntax -->; the project's fragments use it.). Rejected: `fpm` (Keep the spec's fpm: prefix verbatim in the plugin.), `configurable` (A new arc_help_pages key (e.g. marker_prefix, default generic) so a project keeps fpm:; one more key through the four-place touch list.). help: names no consuming project; the arc-help-pages skill contract bans fpm: in SKILL.md. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).
- **D4** The spec names the $footer template slot but not what fills it. Chosen: `generated_note` (A fixed generated line naming the tool and the fragment the page was built from (no path, no timestamp, so a rebuild stays byte-identical and identical across worktrees).). Rejected: `empty` (An empty string; the template owns any footer text.), `fragment_footer` (A third fragment marker block supplies the footer text.). One fixed line, FOOTER = 'Built by arc-help-pages from the canonical tool help and a page fragment. Edit those sources, not this page.': no path, time or version, so rebuilds stay byte-identical across roots and worktrees. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).
- **D5** Spec HelpPaths(atbx, tool_dir, help_dir, checkout_root) has no field for the checkout the call runs in, which link_target_missing ('absent from the current tree') and the repo-relative page href need when the checks run from a linked worktree. Chosen: `add_root` (HelpPaths adds root, as ArcMetaPaths carries it.). Rejected: `four_fields` (Keep four fields; derive the tree from help_dir's parents.). arc_meta_config.ArcMetaPaths carries root the same way (arc_meta_config.py:21-29); deriving it from help_dir breaks when help_dir is configured at another depth. Confirmed by the developer on 2026-11-09 (relayed by the coordinator).
- **D6** Spec Section 3 Tests puts the tests in tests/arc-help-pages/; this repo keeps arc-straps tests in tests/arc/ (plugins/arc-straps/README.md:54, tests/arc/test_arc_meta_*.py). Chosen: `tests_arc` (tests/arc/test_arc_help_pages_*.py beside the arc-meta tests.). Rejected: `tests_arc_help_pages` (A new tests/arc-help-pages/ folder.). The plugin README names tests/<area>/test_<name>.py with the arc-meta tests under tests/arc/, and tests/arc already holds the _-prefixed helpers tools/select_tests.py treats as an import root; the spec's path yields to the repo convention as the task brief directs. Confirmed by the developer on 2026-11-09 (relayed by the coordinator).
- **D7** Toolbox page links: arc_meta_toolbox renders idAbs and useLimit through to_pro_html (arc_meta_toolbox.py:138,144), so once TASK-1 lands a link in the toolbox source reaches toolbox.metadata.xml. check_links(tool) reads only per-tool canonical XML, so that link goes unchecked in development. The spec is silent on the toolbox surface. Chosen: `pass_through` (Accept: the toolbox page carries links; development leaves them unchecked (Production_Convert's swap still checks every swapped href). Adds a TASK-1 node pinning the anchor in build_metadata.). Rejected: `strip_on_toolbox` (The toolbox writer renders link text only until a toolbox-level check exists. Adds a TASK-1 node pinning no anchor in build_metadata.), `check_toolbox_source` (arc-help-pages also scans the toolbox source; needs a toolbox_source key in arc_help_pages.). One generator for both surfaces; Production_Convert's swap and check still cover toolbox links, and three TASK-1 nodes pin the toolbox behavior. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).
- **D8** A tool.content parameter with no <param> in the canonical XML: the spec orders rows by tool.content but does not say what a row without canonical attributes shows. Chosen: `refuse` (tool_doc raises HelpError naming the parameter; arc-meta's check_canonical already reports it as missing_param.). Rejected: `row_without_text` (A row with the name and the tool.content datatype and 'No description.'.). A help page row nobody wrote text for publishes an unchecked gap; the fix is in the canonical XML, which arc-meta's check_canonical names (missing_param, arc_meta_api.py:214-216). Confirmed by the developer on 2026-11-09 (relayed by the coordinator).
- **D9** Relative hrefs in check_links (review R5): an href that is not '#...', has no scheme and is not absolute (docs/demo.html, ../x.html) resolves against Pro's temp copy of the '?' page and breaks; the spec's Section 3 Checks name no code for it. Chosen: `link_relative` (A new HelpProblemCode link_relative reports each one.). Rejected: `skip_relative` (check_links skips them, as it skips web links.), `as_outside` (Report them as link_outside_checkout.). A relative href is dead on the '?' page, and its own code tells the author to write the development href instead. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).
- **D10** Section 2 ships first (review R3): the spec's Order of work puts the Gate between Section 2 and Section 3, so the arc-meta change can ship and be clicked in Pro before arc-help-pages exists. Chosen: `split_pr` (PR A = TASK-1 to TASK-3.1 (arc-straps 0.1.0 -> 0.2.0); PR B = TASK-4 to TASK-9 (0.2.0 -> 0.3.0), started after the Gate passes.). Rejected: `one_pr` (One pull request for Sections 2 and 3, one bump to 0.2.0.). The Gate can stop Section 3; a separate PR A ships the link pass-through the Gate needs without waiting on, or being reverted with, arc-help-pages. The developer accepted this recommendation on 2026-11-09 (relayed by the coordinator).

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| arc-straps version | PR A (TASK-3.1) 0.1.0 -> 0.2.0; PR B (TASK-9) 0.2.0 -> 0.3.0; only plugin.json and the release notes carry it | plugins/arc-straps/.claude-plugin/plugin.json:3; CLAUDE.md Releases | split_pr |
| release notes file | docs/RELEASES/v0.7.0.md while v0.7.0 is uncut (latest release v0.6.0 on 2026-11-09): arc-straps row '(new) \| 0.2.0' after PR A, '(new) \| 0.3.0' after PR B; once cut, the next file with '<old> \| <new>' rows | docs/RELEASES/v0.7.0.md:11; CLAUDE.md:99-112 | split_pr |
| generated section ids and headings | parameters / <h2>Parameters</h2>; syntax / <h2>Python syntax</h2> | spec Section 3 Build rules and Nav; labels from the consuming project's existing page nav | - |
| parameter tags | <td>{name} <span class="tag">optional</span></td> (or derived); none for required | spec Section 3 Build rules; consuming project tool_help/smooth_simplify.html:27 | - |
| empty parameter text | No description. | spec Section 3 Build rules | - |
| syntax line | arcpy.<alias>.<Tool>(required, {optional}) on one line in tool.content order; derived outputs left out and listed after it | spec Section 3 Build rules | - |
| page bytes | template and fragment read as UTF-8 with universal newlines; page written as page.encode('utf-8') bytes (LF, no BOM); the tracked page is read with universal newlines before any comparison, so a CRLF checkout (core.autocrlf=true, git ls-files --eol i/lf w/crlf in the consuming repo) is current; no timestamp or absolute path, so an unchanged rebuild is byte-identical at any root | spec Section 3 Project content | - |
| template slots | $title (escaped displayname), $summary (escaped plain text of <summary>), $nav, $sections, $footer through string.Template.substitute; a missing or stray $name is a HelpError naming _template.html | spec Section 3 Project content | - |
| href checks | prefix = checkout_root.as_uri() + '/', matched ignoring case; tail stripped of #... and ?..., URL-decoded, checked as a file under root (the current tree); #anchor and non-file schemes skipped; any other file: href is link_outside_checkout | spec Section 1 and Section 3 Checks | - |
| fragment markers | <!-- help:tool <Tool> -->, <!-- help:parameters -->, <!-- help:syntax --> | spec Section 3 (Project content), prefix per D3 | generic |
| arc_help_pages key types | _KEYS = (atbx, tool_dir, help_dir); _OPTIONAL = (atbx,); tool_dir and help_dir non-empty strings | arc_meta_config.py:16-17 pattern; spec Section 3 Shared plugin files | - |
| apply report lines | 'DRY-RUN: nothing written. Re-run with apply=True to write.' and 'UP TO DATE: ...' as arc-meta's page writer prints them | plugins/arc-straps/skills/arc-meta/scripts/arc_meta_page.py:136,154 | - |
| Parameters table header | <table><thead><tr><th>Python parameter</th><th>Label</th><th>Description</th><th>ArcGIS data type</th></tr></thead><tbody>...</tbody></table> | review R7; consuming project tool_help/smooth_simplify.html:24 (its three headers, plus Label for the displayname column) | - |
| derived outputs under the syntax | <p>Derived output: <code>A</code>, <code>B</code></p> after the <pre><code> signature; omitted when the tool has none | spec Section 3 Build rules; golden page in the planned build test | - |
| sections assembly | fragment lines after the tool line, each marker line replaced by its generated section, joined with '\n' and stripped | spec Section 3 Project content; golden page in the planned build test | - |
| unbuildable page | check_help_page reports one help_page_stale problem, detail 'cannot build <page>: <HelpError message>', and no other problem | review R13 | - |
| apply report path | apply_help lines name the page as its POSIX path relative to the root, e.g. tool_metadata/tool_help/<page>.html; the dry run ends with the DRY-RUN line | review R12 | - |
| unclosed link refusal | ValueError naming 'unclosed <a>' at </p>, </para>, </li> or the end of the markup; <a href=""> is refused as '<a> without href' | review R9 | - |
| footer | Built by arc-help-pages from the canonical tool help and a page fragment. Edit those sources, not this page. | decision D4 | generated_note |
| para markup problem code | unsupported_para_markup, detail '<field>: <para> holds <tag>; write the field as CDATA HTML' | decision D1 | flag_para_children |
| relative href problem code | link_relative for an href not starting with '#', with no scheme and not starting with '/' or '\' | decision D9 | link_relative |

## Formats

- **canonical link markup (CDATA rich field)**: `<usage><![CDATA[<p>See <a href="file:///C:/work/project/tool_metadata/tool_help/demo.html">the guide</a>.</p>]]></usage>`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:121-143`
- **Pro help-page anchor**: `<SPAN><A HREF="file:///C:/work/project/tool_metadata/tool_help/demo.html">the guide</A></SPAN>; bold: <SPAN STYLE="font-weight:bold;"><A HREF="u">B</A></SPAN>`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:278-284`
- **hover rc for a link (text only)**: `<xdoc><p><span>See </span><span>the guide</span><span>.</span></p></xdoc>`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:314-326`
- **development href**: `file:///C:/work/project/tool_metadata/tool_help/demo.html = Path(checkout_root).as_uri() + '/' + repo-relative path; checkout_root = parent of git --git-common-dir`, copied from `plugins/harness/lib/harness_lib/project.py:56`
- **plugins.arc-straps.arc_help_pages section**: `{"plugins": {"arc-straps": {"arc_help_pages": {"atbx": null, "tool_dir": "tool_metadata/tools", "help_dir": "tool_metadata/tool_help"}}}}`, copied from `plugins/harness/lib/harness_lib/plugin_config.py:18-21`
- **help fragment file**: `line 1: <!-- help:tool Demo --> (the name is the archive's <Tool>.tool folder); then <section class="panel" id="overview"><h2>Overview</h2>...</section> blocks and the two lines <!-- help:parameters --> and <!-- help:syntax --> where the generated sections go`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:58`
- **toolbox alias**: `toolbox.content: {"version": "1.0", "alias": "demo", ...}`, copied from `tests/arc/test_arc_meta_toolbox.py:43`
- **tool.content params (dialog order)**: `{"params": {"in_poly": {...}, "Mode": {"type": "optional"}, "Out_Poly": {"type": "derived", "direction": "out"}}} (absent type = required, absent direction = in)`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:117-131`
- **canonical dialogReference forms**: `<dialogReference><para>Text.</para></dialogReference> or <dialogReference><![CDATA[<p>..</p>]]></dialogReference>`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:245-256`
- **help problem line**: `link_target_missing | Demo | tool_metadata/tool_help/gone.html`, copied from `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:524-528`

## Sweeps

- **S1** `mf\.(parse|is_plain|plain_text|to_pro_html|to_xdoc|to_canonical|inner_html)\(`: `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py` (check path: parse as the refusal probe (170), plain_text inside _plain (241; TASK-2 switches it to text_with_links), inner_html readers (153, 155, 314); anchored in TASK-2), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py` (writer helpers: rc_text and add_dialog_ref call is_plain/plain_text/to_xdoc/to_pro_html, _set_rich and _add_tool call parse/to_pro_html; no edit, behavior follows TASK-1; anchored in TASK-1), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_toolbox.py` (toolbox writer: parse refusal probe (78), rc_description reads run.text (99; link text only), idAbs/useLimit through to_pro_html (138, 144; anchors pass through, see D7)), `tests/arc/test_arc_meta_api.py` (test: rc_text over BOLD_OUT (197); unchanged), `tests/arc/test_arc_meta_format.py` (tests of link-free markup; unchanged, they pin byte-identical output for content without links)
- **S2** `(^|[^A-Za-z_])Run\(`: `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py` (class Run and its one construction in _SubsetParser.handle_data (174); TASK-1 adds href), `plugins/harness/lib/harness_lib/strap_models.py` (unrelated: strap Run pydantic model), `plugins/harness/scripts/strap.py` (unrelated: strap Run), `tests/arc/test_arc_meta_format.py` (positional Run(text, bold, False) in _r (27); stays valid because href defaults to None), `tests/lib/test_strap_api.py` (unrelated: strap Run keyword constructions), `tests/lib/test_strap_runs.py` (unrelated: strap Run keyword constructions)
- **S3** `rc_text\(|SUPPORTED_TAGS|_plain\(`: `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py` (SUPPORTED_TAGS (38, 178) and _plain/_shown_plain (240-297); TASK-2 edits both), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py` (rc_text definition and its fields_of callers; is_plain callers; no edit), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py` (is_plain definition (259); TASK-1 adds the href condition), `tests/arc/test_arc_meta_api.py` (rc_text over BOLD_OUT; unchanged), `tests/arc/test_arc_meta_format.py` (rc_text tests over link-free markup; unchanged), `tests/lib/test_pr_summary.py` (unrelated: test_level_one_is_plain)
- **S4** `<a href`: `tests/arc/_arc_toolbox.py` (BAD_CANONICAL summary (75): its only unsupported tag; TASK-2 swaps it for <code> so test_check_canonical_flags_join_key_and_lint_problems keeps its unsupported_tag)
- **S5** `plugins/arc-straps/skills/arc-meta/scripts`: `docs/PROVENANCE.md` (port record of arc-meta; unchanged (arc-help-pages is new, not a port)), `docs/PR_REVIEWS/0220_1129_new_arcgis_plugin.json` (historical review; unchanged), `docs/TODO/RepoToDo.json` (TODO prose; unchanged), `pyproject.toml` (pytest pythonpath (10) and pylint init-hook (27); TASK-4 appends the arc-help-pages scripts folder to both), `tests/scripts/test_select_tests.py` (arc-meta import-root test (491) and the mirror test (498-505); unchanged), `tools/select_tests.py` (DEFAULT_PYTHONPATH mirror (73); TASK-4 appends the same folder)
- **S6** `arc-meta checks and applies`: `.claude-plugin/marketplace.json` (arc-straps description; TASK-3.1 keeps it equal to the manifest's, TASK-9 names arc-help-pages), `plugins/arc-straps/.claude-plugin/plugin.json` (manifest description; TASK-3.1 keeps it equal to the marketplace's, TASK-9 names arc-help-pages)
- **S7** `` ArcMetaPaths|skills \(`arc-meta`\)|`arc-meta` checks each ``: `CLAUDE.md` (key-touch list (17); TASK-4 names arc_help_pages_config.py beside it), `README.md` (arc-straps row (35) and plugins/arc-straps/ row (577); TASK-9 names arc-help-pages), `docs/PR_REVIEWS/0220_1129_new_arcgis_plugin.json` (historical review; unchanged), `plugins/arc-straps/README.md` ('A new key touches' paragraph (91); TASK-4 names arc_help_pages_config.py), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py` (uses of ArcMetaPaths; unchanged), `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py` (ArcMetaPaths definition; unchanged (mirrored, never imported, by arc_help_pages_config))

## Tasks

### TASK-1: arc-meta generator: <a href> pass-through in arc_meta_format

**Status:** COMPLETE | **Model:** opus | **Depends on:** none
**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py`, `tests/arc/test_arc_meta_links.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:13-15` holds `Any other tag collapses to its text.`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:52-57` holds `class Run(NamedTuple):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:121-143` holds `def handle_starttag(self, tag, attrs):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:144-166` holds `def handle_endtag(self, tag):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:168-175` holds `run = Run(text, self._bold > 0, self._ital > 0)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:182-196` holds `runs[0] = runs[0]._replace(text=runs[0].text.lstrip())`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:245-256` holds `return "".join(f"<p>{''.join(p.itertext())}</p>" for p in paras)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:259-264` holds `return len(runs) == 1 and not runs[0].bold and not runs[0].italic`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:267-275` holds `parts.append("".join(r.text for r in content))`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:278-284` holds `out += f"<SPAN{style}>{escape(r.text)}</SPAN>"`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:314-326` holds `out += f"<span>{text}</span>"`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:346-358` holds `def _runs_canon(runs: List[Run]) -> str:`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py:35-40` holds `return mf.plain_text(blocks) if summary or mf.is_plain(blocks) else mf.to_xdoc(blocks)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py:43-49` holds `if mf.is_plain(blocks):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py:79-81` holds `ET.SubElement(parent, tag).text = mf.to_pro_html(blocks)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py:94-97` holds `usage_blocks = mf.parse(mf.inner_html(src_tool.find("usage")))`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py:107` holds `add_dialog_ref(pe, mf.parse(mf.inner_html(p.find("dialogReference"))))`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_page.py:81-83` holds `return arc_meta_canonical.page(arc_meta_canonical.load(tool_dir, tool)[1], illustration)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_rc.py:163-165` holds `summary, descr = canonical.fields(tool_dir, tool)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_toolbox.py:96-102` holds `lines.extend("".join(run.text for run in runs) for runs in groups)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_toolbox.py:138` holds `_add(did, "idAbs", mf.to_pro_html(mf.parse(source.abstract_html)))`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_toolbox.py:143-144` holds `_add(did, "resConst/Consts/useLimit", mf.to_pro_html(mf.parse(source.use_limit_html)))`
- `tests/arc/test_arc_meta_format.py:26-27` holds `return Run(text, bold, False)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_toolbox.py:69-81` holds `raise ApiError(f"{path.as_posix()} <{tag}> cannot be converted ({exc})") from exc`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/arc/test_arc_meta_links.py)
1. Run gains a fourth field `href: Optional[str] = None` (a NamedTuple default: the positional Run(text, bold, italic) in tests/arc/test_arc_meta_format.py:27 and _trim_edges' _replace keep working).
2. _SubsetParser tracks the open link (self._href). handle_starttag('a'): when a link is already open raise ValueError naming '<a> nested in another <a>'; read dict(attrs).get('href') and raise ValueError naming '<a> without href' when it is None or empty; else store it. handle_endtag('a') clears it. An <a> still open where its block ends (handle_endtag of p, para or li) or at the end of the markup (close()) raises ValueError naming 'unclosed <a>', so no href leaks into the next block. handle_data builds Run(text, bold, ital, self._href). <a> may sit inside or wrap <b>/<i>/<span>: the href is independent of the bold and italic counters.
3. _runs_pro: a run with an href renders <SPAN{style}><A HREF="{escape(href, {'"': '&quot;'})}">{escape(text)}</A></SPAN>; a run without one renders byte for byte as today.
4. _runs_xdoc: unchanged; it writes the link text only and never the href (pinned by test_to_xdoc_writes_the_link_text_only).
5. _runs_canon: a run with an href wraps its rendering in <a href="...">...</a> (attribute-escaped), so parse(to_canonical(blocks)) == blocks and '<p>See <a href="u">x</a>.</p>' renders back verbatim.
6. is_plain also requires runs[0].href is None, so a lone-link parameter goes to the '?' page as Pro HTML (add_dialog_ref) and to the hover as xdoc text (rc_text).
7. New public text_with_links(blocks): plain_text with each link run's href appended after its text (e.g. 'the guide [href]'), whitespace-collapsed like plain_text; equal to plain_text without links.
8. Module docstring: the subset gains <a href>; name the two refusals.
No edit to arc_meta_canonical/page/rc/toolbox: their anchored calls pick the behavior up. D7 = pass_through: arc_meta_toolbox needs no edit; build_metadata carries anchors through to_pro_html, rc_description keeps run.text and load_source's parse probe refuses an <a> without href, each pinned by a node. D1 = flag_para_children leaves inner_html and every reader as they are (TASK-2 adds the check).

- [x] Test `tests/arc/test_arc_meta_links.py::test_parse_keeps_the_href_on_the_link_run` fails with TypeError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_a_link_may_wrap_or_sit_inside_bold_and_italic` fails with TypeError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_an_a_without_href_is_refused` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_an_a_nested_in_another_a_is_refused` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_to_pro_html_writes_an_anchor_inside_the_run_span` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_to_pro_html_escapes_the_href_attribute` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_to_canonical_round_trips_a_link` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_is_plain_is_false_for_a_lone_link` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_add_dialog_ref_writes_pro_html_for_a_lone_link` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_apply_page_writes_the_links_into_the_help_page` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_apply_rc_writes_the_link_text_without_the_href` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_parse_reads_back_a_link_from_pro_html` fails with AttributeError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_to_xdoc_writes_the_link_text_only` fails with AttributeError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_text_with_links_appends_each_href` fails with AttributeError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_an_unclosed_a_is_refused_at_the_end_of_its_block[p]` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_an_unclosed_a_is_refused_at_the_end_of_its_block[li]` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_an_unclosed_a_is_refused_at_the_end_of_its_block[markup_end]` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_a_closed_link_does_not_leak_into_the_next_block` fails with AttributeError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_a_link_inside_a_list_item_round_trips` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_to_canonical_keeps_an_href_with_an_ampersand_and_quotes` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_the_toolbox_page_carries_a_link_and_its_rc_the_text` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_links.py::test_load_source_refuses_an_a_without_href` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/arc/test_arc_meta_format.py -q`: passed
- [x] Run `python -m pytest tests/arc/test_arc_meta_page.py tests/arc/test_arc_meta_rc.py tests/arc/test_arc_meta_roundtrip.py tests/arc/test_arc_meta_toolbox.py -q`: passed
- [x] Run `python -m ruff check plugins/arc-straps tests/arc`: All checks passed!
- [x] Record it: `plan.py record 1011 TASK-1 --sha <sha>` or `--staged`

**Evidence:** staged tree 4a93008: 22 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `4a93008`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/arc/test_arc_meta_links.py::test_parse_keeps_the_href_on_the_link_run tests/arc/test_arc_meta_links.py::test_a_link_may_wrap_or_sit_inside_bold_and_italic tests/arc/test_arc_meta_links.py::test_an_a_without_href_is_refused tests/arc/test_arc_meta_links.py::test_an_a_nested_in_another_a_is_refused tests/arc/test_arc_meta_links.py::test_to_pro_html_writes_an_anchor_inside_the_run_span tests/arc/test_arc_meta_links.py::test_to_pro_html_escapes_the_href_attribute tests/arc/test_arc_meta_links.py::test_to_canonical_round_trips_a_link tests/arc/test_arc_meta_links.py::test_is_plain_is_false_for_a_lone_link tests/arc/test_arc_meta_links.py::test_add_dialog_ref_writes_pro_html_for_a_lone_link tests/arc/test_arc_meta_links.py::test_apply_page_writes_the_links_into_the_help_page tests/arc/test_arc_meta_links.py::test_apply_rc_writes_the_link_text_without_the_href tests/arc/test_arc_meta_links.py::test_parse_reads_back_a_link_from_pro_html tests/arc/test_arc_meta_links.py::test_to_xdoc_writes_the_link_text_only tests/arc/test_arc_meta_links.py::test_text_with_links_appends_each_href tests/arc/test_arc_meta_links.py::test_an_unclosed_a_is_refused_at_the_end_of_its_block[p] tests/arc/test_arc_meta_links.py::test_an_unclosed_a_is_refused_at_the_end_of_its_block[li] tests/arc/test_arc_meta_links.py::test_an_unclosed_a_is_refused_at_the_end_of_its_block[markup_end] tests/arc/test_arc_meta_links.py::test_a_closed_link_does_not_leak_into_the_next_block tests/arc/test_arc_meta_links.py::test_a_link_inside_a_list_item_round_trips tests/arc/test_arc_meta_links.py::test_to_canonical_keeps_an_href_with_an_ampersand_and_quotes tests/arc/test_arc_meta_links.py::test_the_toolbox_page_carries_a_link_and_its_rc_the_text tests/arc/test_arc_meta_links.py::test_load_source_refuses_an_a_without_href`

### TASK-2: arc-meta checks: <a> is a supported tag; _plain compares text with links

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-1
**Files:** `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py`, `tests/arc/_arc_toolbox.py`, `tests/arc/test_arc_meta_link_checks.py`, `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:38` holds `SUPPORTED_TAGS = frozenset({"p", "b", "strong", "i", "em", "ul", "li", "para"})`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:167-173` holds `mf.parse(html)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:176-186` holds `tags = sorted({tag.lower() for _, tag in _TAG.findall(html)} - SUPPORTED_TAGS)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:240-241` holds `return " ".join(mf.plain_text(mf.parse(markup or "")).split())`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:244-250` holds `return _plain(markup)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:278` holds `if _shown_plain(actual) != _plain(expected):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:297-299` holds `return [_problem(ProblemCode.PAGE_STALE, tool,`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:347-349` holds `problems += _field_problem(tool, "dialogReference", expected,`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:418-421` holds `problems += _field_problem(tool, tag, expected, actual)`
- `tests/arc/_arc_toolbox.py:75` holds `See <a href="docs/demo.html">the page</a>.`
- `tests/arc/test_arc_meta_api.py:137-143` holds `("unsupported_tag", None), ("deep_nesting", None), ("thumbnail", None), ("unparseable", "Mode"),`
- `tests/arc/test_arc_meta_api.py:378` holds `root = _toolbox(make_project, canonical=BAD_CANONICAL, page="<metadata/>")`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:150-155` holds `yield param.get("name"), "dialogReference", mf.inner_html(param.find("dialogReference"))`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:189-191` holds `def _markup_problems(tool: str, tool_el: ET.Element) -> List[Problem]:`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py:37-55` holds `UNSUPPORTED_TAG = "unsupported_tag"`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/arc/test_arc_meta_link_checks.py)
1. SUPPORTED_TAGS gains "a" (arc_meta_api.py:38).
2. _plain returns ' '.join(mf.text_with_links(mf.parse(markup or '')).split()); _shown_plain keeps calling _plain. Both the hover check (278) and the page check (297) use it: the rc never holds an href, so hover results do not move, and an href-only page change now reports page_stale instead of page_style_stale.
3. tests/arc/_arc_toolbox.py:75: BAD_CANONICAL's summary link <a href="docs/demo.html">the page</a> becomes <code>the page</code>, so test_check_canonical_flags_join_key_and_lint_problems (tests/arc/test_arc_meta_api.py:137-143) keeps its one unsupported_tag; nothing else reads that summary.
4. D1 = flag_para_children: arc_meta_models.ProblemCode gains UNSUPPORTED_PARA_MARKUP = 'unsupported_para_markup'. check_canonical adds, for the summary, the usage and each parameter's dialogReference, one problem per <para> holding a child element, detail '<field>: <para> holds <tag>; write the field as CDATA HTML' (param set for a dialogReference). It reads the parsed elements, since inner_html's output has already dropped them; inner_html and the readers stay as they are.
5. Module docstrings name the new code; the SKILL.md change is TASK-3.

- [x] Test `tests/arc/test_arc_meta_link_checks.py::test_the_anchor_is_a_supported_tag` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_link_checks.py::test_check_canonical_accepts_links` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_link_checks.py::test_check_canonical_reports_an_a_without_href_as_unparseable` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_link_checks.py::test_check_applied_reports_an_href_only_change_as_page_stale` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_link_checks.py::test_check_canonical_flags_markup_inside_a_para[a]` fails with AssertionError, then passes
- [x] Test `tests/arc/test_arc_meta_link_checks.py::test_check_canonical_flags_markup_inside_a_para[b]` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/arc/test_arc_meta_api.py tests/arc/test_arc_meta_links.py tests/arc/test_arc_meta_link_checks.py -q`: passed
- [x] Run `python -m ruff check plugins/arc-straps tests/arc`: All checks passed!
- [x] Record it: `plan.py record 1011 TASK-2 --sha <sha>` or `--staged`

**Evidence:** staged tree 4a93008: 6 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `4a93008`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/arc/test_arc_meta_link_checks.py::test_the_anchor_is_a_supported_tag tests/arc/test_arc_meta_link_checks.py::test_check_canonical_accepts_links tests/arc/test_arc_meta_link_checks.py::test_check_canonical_reports_an_a_without_href_as_unparseable tests/arc/test_arc_meta_link_checks.py::test_check_applied_reports_an_href_only_change_as_page_stale tests/arc/test_arc_meta_link_checks.py::test_check_canonical_flags_markup_inside_a_para[a] tests/arc/test_arc_meta_link_checks.py::test_check_canonical_flags_markup_inside_a_para[b]`

### TASK-3: arc-meta SKILL.md: the Authoring 'no links' rule becomes the pass-through sentence

**Status:** COMPLETE | **Model:** haiku | **Depends on:** TASK-2
**Files:** `plugins/arc-straps/skills/arc-meta/SKILL.md`, `tests/skills/test_arc_meta_skill_contract.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/SKILL.md:138-139` holds `` The subset is `<p>`, `<b>`, `<i>`, `<ul>`/`<li>` with one level of `<ul>` inside an `<li>`. ``
- `plugins/arc-straps/skills/arc-meta/SKILL.md:140-142` holds `links (the "?" page is rendered from a temp copy, so relative links break and the hover renders none)`
- `tests/skills/test_arc_meta_skill_contract.py:140-142` holds `def test_pinned_rule_sentences_appear_verbatim(sentence: str) -> None:`
- `plugins/arc-straps/skills/arc-meta/SKILL.md:206` holds `` | `check_canonical(tool)` | join-key, type and direction mismatches ``

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/skills/test_arc_meta_skill_contract.py: the existing file plus test_authoring_passes_links_through_and_hands_targets_to_arc_help_pages)
1. plugins/arc-straps/skills/arc-meta/SKILL.md Authoring, Format bullet (140-142): replace ', no links (the "?" page is rendered from a temp copy, so relative links break and the hover renders none)' with one sentence: '`<a href>` passes through to the "?" page, hovers show the link text, and link targets and help pages belong to `arc-help-pages`.' Keep 'No `<Binary>`/`<Thumbnail>` in the canonical XML' and 'ASCII punctuation only.'
2. D1: the Format bullet adds that a `<para>` holds plain text only, and markup or links go in CDATA HTML; the API table row for check_canonical (206) names `unsupported_para_markup`.

- [x] Test `tests/skills/test_arc_meta_skill_contract.py::test_authoring_passes_links_through_and_hands_targets_to_arc_help_pages` fails with AssertionError, then passes
- [x] Test `tests/skills/test_arc_meta_skill_contract.py::test_the_skill_names_the_para_markup_check` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/skills/test_arc_meta_skill_contract.py -q`: passed
- [x] Record it: `plan.py record 1011 TASK-3 --sha <sha>` or `--staged`

**Evidence:** staged tree 4a93008: 2 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `4a93008`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/skills/test_arc_meta_skill_contract.py::test_authoring_passes_links_through_and_hands_targets_to_arc_help_pages tests/skills/test_arc_meta_skill_contract.py::test_the_skill_names_the_para_markup_check`

### TASK-3.1: PR A release: arc-straps 0.1.0 -> 0.2.0 for the link pass-through

**Status:** COMPLETE | **Model:** haiku | **Depends on:** TASK-3
**Files:** `plugins/arc-straps/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `plugins/arc-straps/README.md`, `docs/RELEASES/v0.7.0.md`, `tests/contract/test_arc_straps_registration.py`

**Anchors:**
- `plugins/arc-straps/.claude-plugin/plugin.json:3-4` holds `"version": "0.1.0",`
- `.claude-plugin/marketplace.json:13-17` holds `ArcGIS Pro toolbox skills: arc-meta checks and applies tool help in a project's .atbx archive`
- `plugins/arc-straps/README.md:7-8` holds `` Its first skill, `arc-meta`, checks and applies ``
- `docs/RELEASES/v0.7.0.md:11` holds `| arc-straps | (new) | 0.1.0 |`
- `pyproject.toml:3` holds `version = "0.1.0"`
- `tests/contract/test_arc_straps_registration.py:21-24` holds `assert manifest["dependencies"] == [{"name": "harness", "version": ">=0.56.0"}]`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/contract/test_arc_straps_registration.py: the existing nodes plus test_the_release_notes_carry_the_manifest_version and test_the_manifest_and_the_marketplace_describe_the_plugin_alike, guards that hold through both bumps, and test_the_plugin_readme_says_links_pass_through)
1. plugins/arc-straps/.claude-plugin/plugin.json: version 0.1.0 -> 0.2.0. No other file pins the arc-straps version: pyproject.toml:3 is the repository's own version, and tools/select_tests.py and tests/scripts/test_select_tests.py mirror the pytest pythonpath, not a version.
2. docs/RELEASES/v0.7.0.md: the arc-straps row becomes '| arc-straps | (new) | 0.2.0 |' and one change line says arc-meta passes `<a href>` through to the '?' page and reports `<para>` markup (unsupported_para_markup). If `gh release list --limit 1` shows v0.7.0 already cut, start the next release file per CLAUDE.md Releases with '| arc-straps | 0.1.0 | 0.2.0 |'.
3. plugins/arc-straps/README.md 'What it is': one sentence in the arc-meta account that `<a href>` passes through to the '?' page and hovers show the link text.
4. Descriptions: plugin.json and the marketplace entry stay word-for-word equal; Section 2 needs no new wording, so edit both or neither. No arc-help-pages mention anywhere: that is PR B.

- [x] Test `tests/contract/test_arc_straps_registration.py::test_the_plugin_readme_says_links_pass_through` fails with AssertionError, then passes
- [x] Run `python -m pytest tests/contract/test_arc_straps_registration.py -q`: passed
- [x] Run `claude plugin validate --strict plugins/arc-straps`: Validation passed
- [x] Record it: `plan.py record 1011 TASK-3.1 --sha <sha>` or `--staged`

**Evidence:** staged tree 4a93008: 1 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `4a93008`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/contract/test_arc_straps_registration.py::test_the_plugin_readme_says_links_pass_through`

### TASK-4: arc-help-pages config: the arc_help_pages section, HelpPaths and paths()

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-3.1
**Files:** `plugins/arc-straps/skills/arc-help-pages/scripts/arc_help_pages_config.py`, `plugins/arc-straps/config/defaults.json`, `plugins/arc-straps/config/arc-straps.schema.json`, `plugins/arc-straps/README.md`, `CLAUDE.md`, `pyproject.toml`, `tools/select_tests.py`, `tests/arc/test_arc_help_pages_config.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py:14-17` holds `_KEYS = ("atbx", "tool_dir", "toolbox_source", "registry")`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py:21-29` holds `class ArcMetaPaths:`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py:38-39` holds `section = plugin_section(PLUGIN, _CONFIG / "defaults.json", _CONFIG / "arc-straps.schema.json", cfg)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py:49-65` holds `def _meta(section: Dict[str, Any]) -> Dict[str, Any]:`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py:68-73` holds `if path is not None and not path.resolve().is_relative_to(base):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_config.py:76-82` holds `found = sorted(root.glob("*.atbx"))`
- `plugins/harness/lib/harness_lib/project.py:35-46` holds `def project_root(start: Optional[Path] = None) -> Path:`
- `plugins/harness/lib/harness_lib/project.py:49-64` holds `def main_worktree(start: Path) -> Path:`
- `plugins/harness/lib/harness_lib/plugin_config.py:34-42` holds `unknown = sorted(set(data) - set(schema.get("properties", {}))) if closed else []`
- `plugins/arc-straps/config/defaults.json:1-8` holds `"arc_meta": {`
- `plugins/arc-straps/config/arc-straps.schema.json:10` holds `"optPath": {"oneOf": [{"$ref": "#/$defs/relPath"}, {"type": "null"}]}`
- `plugins/arc-straps/config/arc-straps.schema.json:12-23` holds `"arc_meta": {`
- `plugins/arc-straps/README.md:60-66` holds `` Set under `plugins.arc-straps.arc_meta` in the project's `.claude/harness.json`. ``
- `plugins/arc-straps/README.md:90-93` holds `` The skill prints the resolved locations with `print(paths())`. A new key touches `config/defaults.json`, ``
- `plugins/arc-straps/README.md:51-52` holds `` `harness_lib.project.project_root`, which resolves a `repo` argument inside a subfolder to its project ``
- `CLAUDE.md:13-14` holds `` it reaches harness only through `harness-skill-api`, `harness_lib.config`, ``
- `CLAUDE.md:16-19` holds `` `ArcMetaPaths` and `paths()` in `arc_meta_config.py`, `_meta()` with its `_OPTIONAL` tuple ``
- `pyproject.toml:10` holds `pythonpath = ["plugins/harness/lib", "tests", "plugins/arc-straps/skills/arc-meta/scripts"]`
- `pyproject.toml:27` holds `init-hook = "import sys; sys.path[:0] = ['plugins/harness/lib', 'tests', 'plugins/arc-straps/skills/arc-meta/scripts']"`
- `tools/select_tests.py:73` holds `DEFAULT_PYTHONPATH = ("plugins/harness/lib", "tests", "plugins/arc-straps/skills/arc-meta/scripts")`
- `tests/scripts/test_select_tests.py:498-505` holds `assert list(sel.DEFAULT_PYTHONPATH) == sel.pythonpath_roots(REPO_ROOT)`
- `tests/arc/test_arc_meta_config.py:49-55` holds `jsonschema.Draft202012Validator(schema).validate(defaults)`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/arc/test_arc_help_pages_config.py)
1. New plugins/arc-straps/skills/arc-help-pages/scripts/arc_help_pages_config.py, mirroring arc_meta_config.py without importing it: PLUGIN = 'arc-straps'; _CONFIG = Path(__file__).resolve().parents[3] / 'config'; _KEYS = ('atbx', 'tool_dir', 'help_dir'); _OPTIONAL = ('atbx',); RepoLike.
   @dataclass(frozen=True) HelpPaths(root, atbx, tool_dir, help_dir, checkout_root) (D5), with property prefix = checkout_root.as_uri() + '/' and method page_href(page) = prefix + (help_dir / f'{page}.html').relative_to(root).as_posix().
   paths(repo=None): cfg = active() when repo is None else load_config(project_root(Path(repo))); section = plugin_section(PLUGIN, _CONFIG / 'defaults.json', _CONFIG / 'arc-straps.schema.json', cfg); _section(section) checks section['arc_help_pages'] is an object, has no unknown keys, tool_dir and help_dir are strings, atbx is a string or None, none is '' (messages 'plugins.arc-straps.arc_help_pages[.<key>]: ...', as _meta words them); atbx = root / atbx or the only *.atbx at root (refusal '<what> at <root>; set plugins.arc-straps.arc_help_pages.atbx in .claude/harness.json'); _inside refuses '<key>: resolves outside the project root'; checkout_root = main_worktree(root) from harness_lib.project (D2: no git call of its own; main_worktree returns root outside git or in a bare repository). __all__ = ['HelpPaths', 'RepoLike', 'paths'].
2. config/defaults.json gains "arc_help_pages": {"atbx": null, "tool_dir": "tool_metadata/tools", "help_dir": "tool_metadata/tool_help"}; config/arc-straps.schema.json gains the arc_help_pages object (additionalProperties false; atbx optPath, tool_dir relPath, help_dir relPath, each described).
3. plugins/arc-straps/README.md Configuration: a `plugins.arc-straps.arc_help_pages` paragraph saying it resolves apart from arc_meta, followed by its own key table whose rows are exactly `atbx`, `tool_dir` and `help_dir` (the first table after the first mention of `plugins.arc-straps.arc_help_pages`); the 'A new key touches' paragraph (90-93) names arc_help_pages_config.py (HelpPaths, paths(), _section() with _OPTIONAL) beside arc_meta_config.py. The Boundary list (51) names `harness_lib.project.main_worktree` beside project_root (D2).
4. CLAUDE.md:12-19: the key-touch list names each section's config module; line 14 names `main_worktree` beside `project_root` (D2).
5. pyproject.toml pythonpath (10) and pylint init-hook (27), and tools/select_tests.py DEFAULT_PYTHONPATH (73): append 'plugins/arc-straps/skills/arc-help-pages/scripts' to all three, in the same position (test_default_pythonpath_mirrors_pyproject_and_the_pylint_hook pins them equal).

- [x] Test `tests/arc/test_arc_help_pages_config.py::test_defaults_resolve_every_location` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_overrides_win` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_the_section_resolves_apart_from_arc_meta` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_checkout_root_from_a_worktree_is_the_main_checkout` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_page_href_is_the_main_checkout_uri_plus_the_repo_path` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_an_ambiguous_archive_is_refused[none]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_an_ambiguous_archive_is_refused[two]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_unknown_keys_are_refused` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[section]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[atbx]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[help_dir]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[tool_dir]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_locations_outside_the_project_are_refused[help_dir]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_locations_outside_the_project_are_refused[atbx]` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_defaults_and_schema_carry_the_section` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_the_plugin_readme_documents_every_key` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_no_repo_reads_the_active_project` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_config.py::test_checkout_root_outside_git_falls_back_to_the_root` fails with ImportError, then passes
- [x] Run `python -m pytest tests/scripts/test_select_tests.py::test_default_pythonpath_mirrors_pyproject_and_the_pylint_hook -q`: 1 passed
- [x] Run `python -m pytest tests/arc/test_arc_meta_config.py tests/contract/test_arc_straps_registration.py -q`: passed
- [x] Run `claude plugin validate --strict plugins/arc-straps`: Validation passed
- [x] Run `python -m pytest tests/schemas/test_schema_meta_valid.py -q`: passed
- [x] Record it: `plan.py record 1011 TASK-4 --sha <sha>` or `--staged`

**Evidence:** staged tree 021d85f: 18 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `021d85f`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/arc/test_arc_help_pages_config.py::test_defaults_resolve_every_location tests/arc/test_arc_help_pages_config.py::test_overrides_win tests/arc/test_arc_help_pages_config.py::test_the_section_resolves_apart_from_arc_meta tests/arc/test_arc_help_pages_config.py::test_checkout_root_from_a_worktree_is_the_main_checkout tests/arc/test_arc_help_pages_config.py::test_page_href_is_the_main_checkout_uri_plus_the_repo_path tests/arc/test_arc_help_pages_config.py::test_an_ambiguous_archive_is_refused[none] tests/arc/test_arc_help_pages_config.py::test_an_ambiguous_archive_is_refused[two] tests/arc/test_arc_help_pages_config.py::test_unknown_keys_are_refused tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[section] tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[atbx] tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[help_dir] tests/arc/test_arc_help_pages_config.py::test_bad_types_raise_config_error_without_jsonschema[tool_dir] tests/arc/test_arc_help_pages_config.py::test_locations_outside_the_project_are_refused[help_dir] tests/arc/test_arc_help_pages_config.py::test_locations_outside_the_project_are_refused[atbx] tests/arc/test_arc_help_pages_config.py::test_defaults_and_schema_carry_the_section tests/arc/test_arc_help_pages_config.py::test_the_plugin_readme_documents_every_key tests/arc/test_arc_help_pages_config.py::test_no_repo_reads_the_active_project tests/arc/test_arc_help_pages_config.py::test_checkout_root_outside_git_falls_back_to_the_root`

### TASK-5: arc-help-pages models and source: the records and the canonical/archive reader

**Status:** COMPLETE | **Model:** sonnet | **Depends on:** TASK-4
**Files:** `plugins/arc-straps/skills/arc-help-pages/scripts/arc_help_pages_models.py`, `plugins/arc-straps/skills/arc-help-pages/scripts/arc_help_pages_source.py`, `tests/arc/_arc_help_project.py`, `tests/arc/test_arc_help_pages_source.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:56-65` holds `names, label = (f"{tool}.tool/tool.content", f"{tool}.tool/tool.content.rc"), p.atbx.name`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:134-136` holds `return [_row(name, param, rc) for name, param in content.get("params", {}).items()]`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_archive.py:26-30` holds `return raw.decode("utf-8-sig")`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_canonical.py:19-32` holds `raise ApiError(f"no canonical source at {path.as_posix()}")`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py:245-256` holds `paras = element.findall("para")`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py:15` holds `_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py:18-19` holds `class ApiError(ValueError):`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py:22-27` holds `REQUIRED = "Required"`
- `tests/arc/test_arc_meta_toolbox.py:43` holds `"toolbox.content": b'{"version": "1.0", "alias": "demo"}',`
- `tests/arc/_arc_toolbox.py:130-141` holds `def make_toolbox(make_project: Callable[..., Path], canonical: str = CANONICAL,`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/arc/_arc_help_project.py, the demo-project helper TASK-5 to TASK-7 share, and tests/arc/test_arc_help_pages_source.py)
1. New arc_help_pages_models.py (standard library and pydantic only; frozen, extra='forbid', as arc_meta_models._MODEL_CONFIG): HelpError(ValueError); FragmentError(HelpError); ParamKind(str, Enum) REQUIRED='Required', OPTIONAL='Optional', DERIVED='Derived'; HelpProblemCode(str, Enum) in spec order help_page_stale, help_page_unlinked, fragment_invalid, link_target_missing, link_outside_checkout, then link_relative (D9); ParamDoc(name, displayname, type: ParamKind, direction: str, datatype: str, reference_html: str); ToolDoc(name, displayname, summary, alias, params: List[ParamDoc]); Fragment(page, tool, body); HelpProblem(code, subject, detail); HelpOutcome(page, changed, applied, lines).
2. New arc_help_pages_source.py: has_tool(tool, repo=None) is True when <tool_dir>/<Tool>.xml exists and the archive holds <Tool>.tool/tool.content. tool_doc(tool, repo=None) -> ToolDoc: the canonical XML read as UTF-8 (HelpError when absent, undecodable or malformed, as arc_meta_canonical.load refuses); displayname from <tool displayname>; summary = whitespace-collapsed plain text of <summary> (tags stripped, entities decoded); params in tool.content 'params' key order (member decoded by the UTF-16/UTF-8-sig rule of arc_meta_archive.decode, re-implemented), each matched to the canonical <param name> exactly; a tool.content param without one raises HelpError naming it (D8); canonical params absent from tool.content are left out. ParamDoc attributes come from the canonical <param>; reference_html is CDATA text as-is, each <para> as '<p>' + html-escaped itertext + '</p>' (D1: readers unchanged; arc-meta's check_canonical reports <para> markup), '' when the field holds no text. alias = toolbox.content JSON 'alias' ('' when absent). Imports nothing from arc-meta.

- [x] Test `tests/arc/test_arc_help_pages_source.py::test_tool_doc_reads_the_canonical_text_and_the_archive_alias` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_source.py::test_params_follow_tool_content_order_not_the_canonical_order` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_source.py::test_param_doc_carries_the_canonical_attributes_and_reference_html` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_source.py::test_a_tool_content_param_missing_from_the_canonical_xml_is_refused` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_source.py::test_a_tool_needs_both_its_canonical_xml_and_its_archive_entry` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_source.py::test_records_are_frozen_and_forbid_extra_keys` fails with ImportError, then passes
- [x] Test `tests/arc/test_arc_help_pages_source.py::test_problem_codes_spell_the_spec_values` fails with ImportError, then passes
- [x] Run `python -m ruff check plugins/arc-straps tests/arc`: All checks passed!
- [x] Record it: `plan.py record 1011 TASK-5 --sha <sha>` or `--staged`

**Evidence:** staged tree bde5885: 7 test node(s) passed

**Recorded:** 2026-11-09, staged, tree `bde5885`
- `python -m pytest -q -p no:cacheprovider --tb=auto tests/arc/test_arc_help_pages_source.py::test_tool_doc_reads_the_canonical_text_and_the_archive_alias tests/arc/test_arc_help_pages_source.py::test_params_follow_tool_content_order_not_the_canonical_order tests/arc/test_arc_help_pages_source.py::test_param_doc_carries_the_canonical_attributes_and_reference_html tests/arc/test_arc_help_pages_source.py::test_a_tool_content_param_missing_from_the_canonical_xml_is_refused tests/arc/test_arc_help_pages_source.py::test_a_tool_needs_both_its_canonical_xml_and_its_archive_entry tests/arc/test_arc_help_pages_source.py::test_records_are_frozen_and_forbid_extra_keys tests/arc/test_arc_help_pages_source.py::test_problem_codes_spell_the_spec_values`

### TASK-6: arc-help-pages build: fragment parsing, template fill, Parameters, syntax, nav, apply_help

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-5
**Files:** `plugins/arc-straps/skills/arc-help-pages/scripts/arc_help_pages_build.py`, `tests/arc/test_arc_help_pages_build.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_page.py:131-138` holds `return lines + ["", "DRY-RUN: nothing written. Re-run with apply=True to write."]`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_page.py:153-155` holds `lines.append("UP TO DATE: the archive page matches the canonical source; nothing to write.")`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_models.py:107-120` holds `class ApplyOutcome(BaseModel):`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/arc/test_arc_help_pages_build.py)
1. New arc_help_pages_build.py. Markers (D3 = generic): tool_line(tool) returns '<!-- help:tool {tool} -->', PARAMETERS_MARKER = '<!-- help:parameters -->', SYNTAX_MARKER = '<!-- help:syntax -->'. FOOTER (D4 = generated_note) = 'Built by arc-help-pages from the canonical tool help and a page fragment. Edit those sources, not this page.'. The planned tests pin all four literally; other tests read them by name.
2. parse_fragment(page, text) -> Fragment, FragmentError for: a first non-blank line that is not a tool line; a tool source.has_tool rejects; a missing marker; a <section ...> without id or without <h2>. The body is every line after the tool line.
3. render(fragment, doc, template): string.Template(template).substitute(title=escape(displayname), summary=escape(summary), nav=..., sections=..., footer=FOOTER); a KeyError or ValueError from the template is a HelpError naming _template.html (a template without $footer is fine). sections = the body lines with each marker line replaced by its generated section, joined with '\n' and stripped. Parameters: <section class="panel" id="parameters"><h2>Parameters</h2><table><thead><tr><th>Python parameter</th><th>Label</th><th>Description</th><th>ArcGIS data type</th></tr></thead><tbody> + one row per ToolDoc param <tr><td>{name}[ <span class="tag">optional|derived</span>]</td><td>{escaped displayname}</td><td>{reference_html or 'No description.'}</td><td>{datatype}</td></tr> + </tbody></table></section>, no whitespace between tags. Syntax: <section class="panel" id="syntax"><h2>Python syntax</h2><pre><code>arcpy.{alias}.{tool}(a, {b}, c)</code></pre> (non-derived params in tool.content order, optional ones in braces) + <p>Derived output: <code>X</code>, <code>Y</code></p> when there are derived outputs + </section>. nav = <a href="#{id}">{h2 text, tags stripped}</a> per section in page order, joined with ''. GOLDEN in the planned test pins the whole layout.
4. build_page(page, repo=None) -> str: reads <help_dir>/_fragments/<page>.html and <help_dir>/_template.html (UTF-8, universal newlines; HelpError when absent), source.tool_doc, render. No timestamp and no absolute path: two projects at different roots build the same bytes.
5. apply_help(page, apply=False, repo=None) -> HelpOutcome: reads <help_dir>/<page>.html with universal newlines (a CRLF checkout under core.autocrlf compares equal; the consuming repo has core.autocrlf=true and `git ls-files --eol` shows i/lf w/crlf for its page) and compares it with the build; equal -> changed False, the file untouched, an 'UP TO DATE: ...' line; else lines naming the page as its POSIX path relative to the root (tool_metadata/tool_help/<page>.html) with the size change, ending with exactly 'DRY-RUN: nothing written. Re-run with apply=True to write.', or with apply=True writing page.encode('utf-8') bytes (LF) and an 'APPLIED ...' line. The skill prints "\n".join(apply_help(name).lines). Imports nothing from arc-meta.

- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_template_fill_replaces_every_slot` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_nav_lists_each_section_by_id_and_h2_in_page_order` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_parameters_table_follows_tool_content_order_with_tags` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_syntax_braces_optional_params_and_lists_derived_outputs_after_it` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_rebuild_is_byte_identical_and_apply_writes_it` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_fragment_refusals[no_parameters]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_fragment_refusals[no_section_h2]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_fragment_refusals[no_section_id]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_fragment_refusals[no_syntax]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_fragment_refusals[no_tool_line]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_fragment_refusals[unknown_tool]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_the_build_matches_the_golden_page_wherever_the_project_sits` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_the_dry_run_report_names_the_page_and_ends_with_the_notice` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_a_crlf_checkout_of_the_page_is_up_to_date` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_the_marker_spellings_are_the_fragment_contract` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_build.py::test_the_footer_is_one_fixed_line` fails with ImportError, then passes
- [ ] Run `python -m ruff check plugins/arc-straps tests/arc`: All checks passed!
- [ ] Record it: `plan.py record 1011 TASK-6 --sha <sha>` or `--staged`

**Evidence:** not started

### TASK-7: arc-help-pages API: help_pages, check_help_page, check_links, format_problems

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-6
**Files:** `plugins/arc-straps/skills/arc-help-pages/scripts/arc_help_pages_api.py`, `tests/arc/test_arc_help_pages_api.py`, `tests/contract/test_root_separation.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:33-36` holds `__all__ = [`
- `plugins/arc-straps/skills/arc-meta/scripts/arc_meta_api.py:524-528` holds `if not problems: return "clean"`
- `plugins/harness/scripts/skill_api.py:61-71` holds `if folder not in sys.path:`
- `tests/contract/test_root_separation.py:171-184` holds `def _arc_rc_args(root: Path) -> Tuple[List[str], str]:`
- `tests/contract/test_root_separation.py:235-236` holds `"todo_sync refresh", "todo_sync migrate-ids"})`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/arc/test_arc_help_pages_api.py)
1. New arc_help_pages_api.py; __all__ binds HelpError, HelpProblemCode, paths, help_pages, build_page, apply_help, check_help_page, check_links and format_problems (build_page and apply_help re-exported from the build module), the heredoc surface harness-skill-api binds.
2. help_pages(repo=None): sorted stems of <help_dir>/_fragments/*.html.
3. check_help_page(page, repo=None): a FragmentError -> [fragment_invalid] alone; any other HelpError from the build (tool_doc, template) -> one help_page_stale problem whose detail is 'cannot build <page>: <message>', alone; else help_page_stale when <help_dir>/<page>.html is absent or its text, read with universal newlines (CRLF equals LF), differs from build_page, and help_page_unlinked when the fragment tool's canonical XML holds no href naming this page: equal to paths().page_href(page) with the prefix compared ignoring case (a link to another page does not count).
4. check_links(tool, repo=None): every href in the tool's canonical XML text (href="..." or href='...', entity-decoded); skip '#...' and non-file: schemes; under the prefix (ignoring case) strip '#'/'?' suffixes, URL-decode the tail, link_target_missing when root / tail is not a file; any other file: href is link_outside_checkout. subject = page or tool; detail names the href.
5. format_problems: 'code | subject | detail' per problem, or 'clean'. Imports nothing from arc-meta.
6. tests/contract/test_root_separation.py (planned file): the 'arc-help-pages apply_help' case runs apply_help through harness-skill-api (scripts/skill_api.py --file .../arc_help_pages_api.py <page>) on the demo help project, joins MUST_EXIT_ZERO, and test_arc_help_pages_apply_lands_in_the_project checks the page lands under the project.
7. D9 = link_relative: check_links reports link_relative for each href that does not start with '#', has no scheme (urllib.parse.urlsplit) and does not start with '/' or '\\'; the detail names the href.

- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_the_api_binds_the_spec_surface` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_help_pages_lists_each_fragment_stem` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_reports_a_missing_or_edited_page_as_stale` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_reports_an_unlinked_page` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_matches_the_link_prefix_ignoring_case` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_reports_an_invalid_fragment_alone` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_reports_a_missing_target` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_decodes_the_tail_and_drops_the_fragment` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_reports_a_file_href_outside_the_checkout` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_ignores_anchors_and_web_links` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_the_checks_from_a_worktree_use_the_main_checkout_prefix` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_format_problems_prints_one_line_each_or_clean` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_no_module_of_the_skill_imports_arc_meta` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_reads_a_crlf_page_as_current` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_counts_a_link_to_another_page_as_unlinked` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_help_page_reports_a_page_it_cannot_build_as_one_problem` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_matches_the_prefix_ignoring_case[upper]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_matches_the_prefix_ignoring_case[lower_drive]` fails with ImportError, then passes
- [ ] Test `tests/contract/test_root_separation.py::test_arc_help_pages_apply_lands_in_the_project` fails with ImportError, then passes
- [ ] Test `tests/contract/test_root_separation.py::test_entry_point_writes_nothing_under_plugins[arc-help-pages apply_help]` fails with ImportError, then passes
- [ ] Test `tests/arc/test_arc_help_pages_api.py::test_check_links_reports_relative_hrefs` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/contract/test_no_repo_literals.py -q`: passed
- [ ] Run `python -m ruff check plugins/arc-straps tests/arc`: All checks passed!
- [ ] Record it: `plan.py record 1011 TASK-7 --sha <sha>` or `--staged`

**Evidence:** not started

### TASK-8: arc-help-pages SKILL.md: the procedure

**Status:** PENDING | **Model:** sonnet | **Depends on:** TASK-7
**Files:** `plugins/arc-straps/skills/arc-help-pages/SKILL.md`, `tests/skills/test_arc_help_pages_skill_contract.py`

**Anchors:**
- `plugins/arc-straps/skills/arc-meta/SKILL.md:191-198` holds `harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_meta_api.py" <Tool> <<'PY'`
- `tests/skills/test_arc_meta_skill_contract.py:28-32` holds `LAUNCHER = 'harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/'`
- `CLAUDE.md:41-43` holds `arc-straps skills run their Python through`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/skills/test_arc_help_pages_skill_contract.py)
1. New plugins/arc-straps/skills/arc-help-pages/SKILL.md. Frontmatter: name arc-help-pages; a description starting 'Use when' that names a toolbox tool's server-hosted help page and its link from the '?' page; argument-hint '<page> [-- <guidance>]'.
2. Body: the project content (template, fragments, built pages, img/) and the link contract (paths().page_href; the production swap happens downstream); Steps per spec Section 3 Skill procedure: (1) read the tool's code: the entry module, the params model, the validator; an existing page's text is a claim to re-check, a contradicted claim is replaced and named; (2) write or update the fragment; (3) dry-run, then apply, apply_help; (4) add or confirm the link in the tool's canonical XML and apply it with arc-meta; (5) check_help_page and check_links until both are clean. Heredocs through harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/arc_help_pages_api.py" <page> (a <Tool> heredoc for check_links); the apply heredocs are exactly print("\n".join(apply_help(name).lines)) then the apply=True form. An API table and a Hand off section. No project literal (BANNED in the test, fpm: included, R2); fragments use the help: markers <!-- help:tool <Tool> -->, <!-- help:parameters -->, <!-- help:syntax --> (D3).

- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_frontmatter_names_the_skill_folder` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_description_says_when_to_use_it` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_every_heredoc_goes_through_the_launcher` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_an_argument_follows_the_file_path_exactly_when_name_is_read` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_heredoc_calls_are_bound_names_or_builtins` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_apply_heredocs_dry_run_then_apply` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_the_procedure_names_its_sources_and_checks[entry]` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_the_procedure_names_its_sources_and_checks[params]` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_the_procedure_names_its_sources_and_checks[validator]` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_the_procedure_names_its_sources_and_checks[check_page]` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_the_procedure_names_its_sources_and_checks[check_links]` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_the_procedure_names_its_sources_and_checks[arc_meta]` fails with ImportError, then passes
- [ ] Test `tests/skills/test_arc_help_pages_skill_contract.py::test_body_has_no_project_literal` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/contract/test_no_repo_literals.py -q`: passed
- [ ] Run `claude plugin validate --strict plugins/arc-straps`: Validation passed
- [ ] Run `python -m pytest tests/contract/test_root_separation.py -k help -q`: passed
- [ ] Record it: `plan.py record 1011 TASK-8 --sha <sha>` or `--staged`

**Evidence:** not started

### TASK-9: PR B release: arc-straps 0.2.0 -> 0.3.0, descriptions and READMEs name arc-help-pages

**Status:** PENDING | **Model:** haiku | **Depends on:** TASK-8
**Files:** `plugins/arc-straps/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `plugins/arc-straps/README.md`, `README.md`, `docs/RELEASES/v0.7.0.md`, `tests/contract/test_arc_help_pages_registration.py`

**Anchors:**
- `plugins/arc-straps/.claude-plugin/plugin.json:3-4` holds `"version": "0.1.0",`
- `.claude-plugin/marketplace.json:13-17` holds `ArcGIS Pro toolbox skills: arc-meta checks and applies tool help in a project's .atbx archive`
- `README.md:35` holds `` `arc-meta` checks each tool's canonical help XML against its parameters ``
- `README.md:577` holds `` ArcGIS Pro toolbox skills (`arc-meta`) and the `plugins.arc-straps` defaults and schema ``
- `plugins/arc-straps/README.md:7-8` holds `` Its first skill, `arc-meta`, checks and applies ``
- `docs/RELEASES/v0.7.0.md:11` holds `| arc-straps | (new) | 0.1.0 |`

Copy each planned file from docs/plans/1011/tests/<repo path> to its repo path first. (tests/contract/test_arc_help_pages_registration.py, new; PR A's tests/contract/test_arc_straps_registration.py guards keep running)
1. plugins/arc-straps/.claude-plugin/plugin.json: version 0.2.0 -> 0.3.0; the description names arc-meta and arc-help-pages. .claude-plugin/marketplace.json: the arc-straps description the same, word for word.
2. plugins/arc-straps/README.md 'What it is': a paragraph for `arc-help-pages` (pages built from fragments and the canonical XML, the two checks).
3. README.md:35 arc-straps row names `arc-help-pages`; README.md:577 names both skills.
4. Release notes: while v0.7.0 is uncut, its arc-straps row becomes '| arc-straps | (new) | 0.3.0 |' plus one change line for arc-help-pages; once v0.7.0 is cut, the next release file carries '| arc-straps | 0.2.0 | 0.3.0 |' (CLAUDE.md Releases).

- [ ] Test `tests/contract/test_arc_help_pages_registration.py::test_every_description_of_the_plugin_names_the_help_pages_skill` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/contract/test_arc_help_pages_registration.py tests/contract/test_arc_straps_registration.py -q`: passed
- [ ] Run `claude plugin validate --strict plugins/arc-straps`: Validation passed
- [ ] Run `claude plugin validate --strict .`: Validation passed
- [ ] Record it: `plan.py record 1011 TASK-9 --sha <sha>` or `--staged`

**Evidence:** not started
