"""arc-help-pages build: one page fragment and the canonical tool help filled into the page template.

A fragment (``<help_dir>/_fragments/<page>.html``) opens with the tool line ``<!-- help:tool <Tool> -->``;
every later line is page content, where the two marker lines ``<!-- help:parameters -->`` and
``<!-- help:syntax -->`` stand for the generated Parameters and Python syntax sections. Every ``<section>``
carries an ``id`` and an ``<h2>``, which the nav lists in page order; the ids are unique, and ``parameters``
and ``syntax`` are reserved for the generated sections. The template
(``<help_dir>/_template.html``) takes ``$title``, ``$summary``, ``$nav``, ``$sections`` and, optionally,
``$footer`` through ``string.Template``. The page names no path, time or version, so an unchanged rebuild is
byte-identical at any root. ``apply_help`` is a dry run unless ``apply=True``; it compares pages read with
universal newlines, so a CRLF checkout of an unchanged page counts as up to date.

Refusals raise ``FragmentError`` (a fragment that breaks the contract) or ``HelpError`` (a missing or
unreadable source, a broken template). Imports only the standard library and the sibling config, models
and source modules.
"""
from __future__ import annotations

import re
import string
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Set, Tuple

import arc_help_pages_source as source
from arc_help_pages_config import RepoLike, paths
from arc_help_pages_models import (
    Fragment, FragmentError, HelpError, HelpOutcome, ParamDoc, ParamKind, ToolDoc,
)

__all__ = ["FOOTER", "PARAMETERS_MARKER", "SYNTAX_MARKER", "apply_help", "build_page", "parse_fragment",
           "render", "tool_line"]

PARAMETERS_MARKER = "<!-- help:parameters -->"
SYNTAX_MARKER = "<!-- help:syntax -->"
FOOTER = ("Built by arc-help-pages from the canonical tool help and a page fragment. "
          "Edit those sources, not this page.")
TEMPLATE_NAME = "_template.html"
RESERVED_IDS = ("parameters", "syntax")
DRY_RUN = "DRY-RUN: nothing written. Re-run with apply=True to write."

_TOOL_LINE = re.compile(r"<!-- help:tool (\S+) -->")
_REQUIRED_SLOTS = ("title", "summary", "nav", "sections")
_THEAD = ("<table><thead><tr><th>Python parameter</th><th>Label</th><th>Description</th>"
          "<th>ArcGIS data type</th></tr></thead><tbody>")
_TAGS = {ParamKind.OPTIONAL: "optional", ParamKind.DERIVED: "derived"}


def tool_line(tool: str) -> str:
    """The first line of a fragment for ``tool``."""
    return f"<!-- help:tool {tool} -->"


# --- fragment -------------------------------------------------------------------------------------------

def parse_fragment(page: str, text: str, repo: RepoLike = None) -> Fragment:
    """The fragment of ``page``; refused unless it names a known tool, holds both markers once and every
    ``<section>`` has an ``id`` and an ``<h2>``; an id may not repeat or be ``parameters`` or ``syntax``,
    which the generated sections own."""
    lines = _lines(text)
    index, tool = _find_tool_line(page, lines)
    if not source.has_tool(tool, repo):
        raise FragmentError(f"fragment {page}: {tool} has no canonical XML or no tool in the archive")
    body = lines[index + 1:]
    for marker in (PARAMETERS_MARKER, SYNTAX_MARKER):
        count = sum(1 for line in body if line.strip() == marker)
        if count != 1:
            raise FragmentError(f"fragment {page}: holds {marker} {count} times, not once")
    _check_sections(page, "\n".join(body))
    return Fragment(page=page, tool=tool, body="\n".join(body))


def _lines(text: str) -> List[str]:
    """``text`` split on any line ending."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _find_tool_line(page: str, lines: List[str]) -> Tuple[int, str]:
    """``(index, tool)`` of the first non-blank line, which must be the tool line."""
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = _TOOL_LINE.fullmatch(line.strip())
        if match is None:
            raise FragmentError(f"fragment {page}: the first line is not {tool_line('<Tool>')}")
        return index, match.group(1)
    raise FragmentError(f"fragment {page}: empty, no {tool_line('<Tool>')} line")


def _check_sections(page: str, html: str) -> None:
    """Refuse a ``<section>`` without an ``id`` or an ``<h2>``, with a reserved id or with a repeated id."""
    seen: Set[str] = set()
    for number, (section_id, heading) in enumerate(_sections(html), start=1):
        if not section_id:
            raise FragmentError(f"fragment {page}: <section> {number} has no id")
        if heading is None:
            raise FragmentError(f"fragment {page}: <section id=\"{section_id}\"> has no <h2>")
        if section_id in RESERVED_IDS:
            raise FragmentError(f"fragment {page}: <section id=\"{section_id}\"> uses an id reserved for "
                                f"a generated section ({', '.join(RESERVED_IDS)})")
        if section_id in seen:
            raise FragmentError(f"fragment {page}: <section id=\"{section_id}\"> repeats an id")
        seen.add(section_id)


class _SectionScan(HTMLParser):
    """Collects ``[id, h2 text]`` per ``<section>`` in document order; the text has its tags stripped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: List[List[Optional[str]]] = []
        self._open: List[int] = []
        self._h2: Optional[List[str]] = None
        self._h2_owner = -1

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "section":
            self._open.append(len(self.found))
            self.found.append([dict(attrs).get("id"), None])
        elif tag == "h2" and self._open and self.found[self._open[-1]][1] is None:
            self._h2, self._h2_owner = [], self._open[-1]

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._open:
            self._open.pop()
        elif tag == "h2" and self._h2 is not None:
            self.found[self._h2_owner][1] = " ".join("".join(self._h2).split())
            self._h2 = None

    def handle_data(self, data: str) -> None:
        if self._h2 is not None:
            self._h2.append(data)


def _sections(html: str) -> List[Tuple[Optional[str], Optional[str]]]:
    """``(id, h2 text)`` of each ``<section>`` in ``html``, in document order."""
    scan = _SectionScan()
    scan.feed(html)
    scan.close()
    return [(section_id, heading) for section_id, heading in scan.found]


# --- generated sections ---------------------------------------------------------------------------------

def _param_row(param: ParamDoc) -> str:
    """One Parameters row: name with its type tag, label, reference text, data type."""
    tag = _TAGS.get(param.type)
    name = escape(param.name) + (f' <span class="tag">{tag}</span>' if tag else "")
    text = param.reference_html or "No description."
    return (f"<tr><td>{name}</td><td>{escape(param.displayname)}</td><td>{text}</td>"
            f"<td>{escape(param.datatype)}</td></tr>")


def _parameters_section(doc: ToolDoc) -> str:
    rows = "".join(_param_row(param) for param in doc.params)
    return (f'<section class="panel" id="parameters"><h2>Parameters</h2>{_THEAD}{rows}'
            "</tbody></table></section>")


def _syntax_code(doc: ToolDoc) -> str:
    """``import arcpy``, the ``ImportToolbox`` line naming the archive file under a ``<folder>`` stand-in,
    then the call in ``tool.content`` order with optional parameters braced; escaped for ``<code>``."""
    args = [f"{{{p.name}}}" if p.type is ParamKind.OPTIONAL else p.name
            for p in doc.params if p.type is not ParamKind.DERIVED]
    lines = ["import arcpy", f'arcpy.ImportToolbox(r"<folder>\\{doc.archive}")',
             f"arcpy.{doc.alias}.{doc.name}({', '.join(args)})"]
    return escape("\n".join(lines), quote=False)


def _syntax_section(doc: ToolDoc) -> str:
    """The import and call lines, a note on the alias and the folder stand-in, then the derived outputs.

    ``arcpy.<alias>`` exists only once ``arcpy.ImportToolbox`` has loaded the archive, so the call alone
    would read as part of arcpy. The archive is named by file only, keeping the page free of paths.
    """
    note = (f"<p><code>ImportToolbox</code> adds the tools of {escape(doc.archive)} to arcpy under the "
            f"toolbox alias <code>{escape(doc.alias)}</code>; &lt;folder&gt; stands for the folder that "
            "holds it.</p>")
    derived = [f"<code>{escape(p.name)}</code>" for p in doc.params if p.type is ParamKind.DERIVED]
    tail = f"<p>Derived output: {', '.join(derived)}</p>" if derived else ""
    return (f'<section class="panel" id="syntax"><h2>Python syntax</h2>'
            f"<pre><code>{_syntax_code(doc)}</code></pre>{note}{tail}</section>")


# --- page -----------------------------------------------------------------------------------------------

def _sections_html(fragment: Fragment, doc: ToolDoc) -> str:
    """The fragment body with each marker line replaced by its generated section."""
    generated = {PARAMETERS_MARKER: _parameters_section(doc), SYNTAX_MARKER: _syntax_section(doc)}
    lines = [generated.get(line.strip(), line) for line in _lines(fragment.body)]
    return "\n".join(lines).strip()


def _nav(sections: str) -> str:
    return "".join(f'<a href="#{escape(section_id or "")}">{escape(heading or "", quote=False)}</a>'
                   for section_id, heading in _sections(sections))


def render(fragment: Fragment, doc: ToolDoc, template: str) -> str:
    """The page: ``template`` with its slots filled; a broken template is a HelpError naming it."""
    sections = _sections_html(fragment, doc)
    tpl = string.Template(template)
    missing = [f"${slot}" for slot in _REQUIRED_SLOTS if slot not in tpl.get_identifiers()]
    if missing:
        raise HelpError(f"{TEMPLATE_NAME} has no {', '.join(missing)} slot")
    try:
        return tpl.substitute(title=escape(doc.displayname), summary=escape(doc.summary),
                              nav=_nav(sections), sections=sections, footer=FOOTER)
    except KeyError as exc:
        raise HelpError(f"{TEMPLATE_NAME} has an unknown slot ${exc.args[0]}") from exc
    except ValueError as exc:
        raise HelpError(f"{TEMPLATE_NAME} has a malformed slot ({exc})") from exc


def _read_text(path: Path) -> str:
    """``path`` as UTF-8 text with universal newlines; refused when absent or not UTF-8."""
    if not path.is_file():
        raise HelpError(f"no {path.name} at {path.parent.as_posix()}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HelpError(f"{path.as_posix()} is not UTF-8 text ({exc})") from exc


def build_page(page: str, repo: RepoLike = None) -> str:
    """The page ``page`` built from its fragment, the template and the canonical tool help."""
    p = paths(repo)
    fragment = parse_fragment(page, _read_text(p.help_dir / "_fragments" / f"{page}.html"), repo)
    template = _read_text(p.help_dir / TEMPLATE_NAME)
    return render(fragment, source.tool_doc(fragment.tool, repo), template)


# --- apply ----------------------------------------------------------------------------------------------

def _current(target: Path) -> Tuple[Optional[str], str]:
    """``(text, origin)`` of the page on disk; text is None when absent or not UTF-8."""
    if not target.is_file():
        return None, "new file"
    size = target.stat().st_size
    try:
        return target.read_text(encoding="utf-8"), f"{size:,} bytes"
    except UnicodeDecodeError:
        return None, f"unreadable page ({size:,} bytes)"


def apply_help(page: str, apply: bool = False, repo: RepoLike = None) -> HelpOutcome:
    """Dry-run (default) or write ``<help_dir>/<page>.html``; an unchanged page is never rewritten."""
    p = paths(repo)
    target = p.help_dir / f"{page}.html"
    new = build_page(page, repo)
    old, origin = _current(target)
    rel = target.relative_to(p.root).as_posix()
    lines = [f"{rel}: {origin} -> {len(new.encode('utf-8')):,} bytes"]
    if old == new:
        lines.append("UP TO DATE: the page matches its fragment and the canonical source; nothing to write.")
        return HelpOutcome(page=page, changed=False, applied=False, lines=lines)
    if not apply:
        return HelpOutcome(page=page, changed=True, applied=False, lines=lines + ["", DRY_RUN])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(new.encode("utf-8"))
    return HelpOutcome(page=page, changed=True, applied=True, lines=lines + ["", f"APPLIED: wrote {rel}."])
