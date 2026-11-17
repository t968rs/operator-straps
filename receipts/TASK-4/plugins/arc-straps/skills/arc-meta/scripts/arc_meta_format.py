"""Shared rich-text translation for the toolbox metadata generators.

Parses a small HTML subset from the canonical per-tool XML and renders it to the two
native ArcGIS forms used by the two display surfaces:

  - Pro item metadata (the "?" HTML help page, tool.metadata.xml):
        <DIV STYLE="text-align:Left;white-space:normal;..">
        <P STYLE=".."><SPAN STYLE="font-weight:bold;">..</SPAN></P>
        <UL STYLE=".."><LI STYLE=".."><SPAN>..</SPAN></LI></UL></DIV>
  - resource xdoc (the tool dialog / hover tooltip, tool.content.rc):
        <xdoc><p><b>..</b><span>..</span></p><ul><li><p><span>..</span></p></li></ul></xdoc>

Supported subset: ``<p>``, ``<b>`` (and ``<strong>``), ``<i>`` (and ``<em>``),
``<ul>``/``<li>``, with one level of ``<ul>`` nested inside an ``<li>``, and ``<a href>``. A
``<para>`` element is treated as a paragraph (the metadata-native form). Any other tag collapses
to its text.

A link keeps its ``href`` on each run it covers, independent of bold and italic, so ``<a>`` may
wrap or sit inside ``<b>``/``<i>``/``<span>``. The Pro help page renders an anchor inside the
run's span, the canonical form writes the ``<a href>`` back, and xdoc keeps the link text only.
An ``<a>`` without an ``href`` (or with a blank one), an ``<a>`` without text, an ``<a>``
nested in another ``<a>``, and an ``<a>`` still open where its paragraph or list item (or the
markup) ends or a new paragraph, list or list item starts raise ``ValueError``. The ``href`` is
stored stripped of surrounding whitespace.

A nested list parses to a ``("sub", items)`` block placed right after the ``("ul", ...)``
block whose last item is its parent; the renderers nest it back inside that item. Sibling
nested lists inside one item each parse to a ``sub`` block, and the renderers merge them into
one nested list under that item. A list nested deeper than one level, and item text after a
nested list inside the same ``<li>``, raise ``ValueError`` rather than losing or moving text.

Plain single-paragraph content is reported by :func:`is_plain` so callers can keep the
simpler legacy forms (``<para>`` / a bare string) and avoid churning already-clean tools.

The "?" page illustration contract also lives here: :func:`illustration_entry` names the archive member
and :func:`illustration_data_uri` renders its bytes as the ``Binary/Thumbnail/img/@src`` value.
"""

from __future__ import annotations

import base64
import re
from html.parser import HTMLParser
from typing import Callable, List, NamedTuple, Optional, Tuple, Union
from xml.sax.saxutils import escape

_WS_RE = re.compile(r"\s+")
_INLINE = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic"}

# Pro pretty-prints the help HTML inside pre.wrap (white-space: pre-wrap), so every newline and
# indent between tags renders as a blank line. The outer DIV resets white-space, and its negative
# margins cancel the one blank line the indentation leaves before and after the DIV.
PRO_DIV_STYLE = "text-align:Left;white-space:normal;margin-top:-1.2em;margin-bottom:-1.2em;"
# Inline spacing for the Pro help page; overrides the 1em pre.wrap p / li padding.
PRO_P_STYLE = "padding-bottom:0.5em;"
PRO_LI_STYLE = "padding-bottom:0.25em;"
PRO_UL_STYLE = "margin-top:0;margin-bottom:0.5em;"
PRO_SUBUL_STYLE = "margin-top:0.25em;margin-bottom:0;"


class Run(NamedTuple):
    """A text run with bold/italic state and the href of the link it sits in (None outside a link)."""

    text: str
    bold: bool
    italic: bool
    href: Optional[str] = None


# A block is ("p", [Run, ...]), ("ul", [[Run, ...], ...]) or ("sub", [[Run, ...], ...]).
Block = Tuple[str, list]
# A list-tree item is (item runs, [child item runs, ...]).
TreeItem = Tuple[List[Run], List[List[Run]]]
# A grouped block is ("p", [Run, ...]) or ("list", [TreeItem, ...]).
GroupedBlock = Tuple[str, Union[List[Run], List[TreeItem]]]


class _SubsetParser(HTMLParser):
    """Parse the supported subset into a list of blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.blocks: List[Block] = []
        self._bold = 0
        self._ital = 0
        self._runs: Optional[List[Run]] = None
        self._items: Optional[list] = None
        self._loose: List[Run] = []
        self._span_fmt: List[Tuple[int, int]] = []
        self._in_li = False
        self._nested = False
        self._outer_li = False
        self._href: Optional[str] = None
        self._link_text = False

    def _open_link(self, attrs) -> None:
        """Store the stripped href of an opening ``<a>``; refuse a nested link or a missing or blank href."""
        if self._href is not None:
            raise ValueError("<a> nested in another <a>")
        href = (dict(attrs).get("href") or "").strip()
        if not href:
            raise ValueError("<a> without href")
        self._href = href
        self._link_text = False

    def _close_link(self) -> None:
        """Close the open ``<a>``; refuse a link that received no text, which no surface could show."""
        if self._href is not None and not self._link_text:
            raise ValueError("<a> without text")
        self._href = None

    def _refuse_open_link(self, where: str) -> None:
        """Refuse an ``<a>`` still open at ``where``, so its href cannot leak into the next block."""
        if self._href is not None:
            raise ValueError(f"unclosed <a> at {where}")

    def _flush_loose(self) -> None:
        if self._loose:
            self.blocks.append(("p", self._loose))
            self._loose = []

    def _open_sub_list(self) -> None:
        """Close the open top-level item and list part, then collect the nested items."""
        if self._runs:
            self._items.append(self._runs)
        if self._items:
            self.blocks.append(("ul", self._items))
        self._items, self._runs = [], None
        self._in_li, self._nested, self._outer_li = False, True, True

    def _open_list(self) -> None:
        """Open a top-level list, a nested list, or a sibling nested list in the same item."""
        if self._nested:
            raise ValueError("nested list deeper than one level")
        if self._outer_li:
            self._items, self._nested = [], True
        elif self._in_li and self._items is not None:
            self._open_sub_list()
        else:
            self._flush_loose()
            self._items = []

    def _close_list(self) -> None:
        """Emit the open list as a ``ul`` block, or as a ``sub`` block when nested."""
        if self._nested:
            if self._items:
                self.blocks.append(("sub", self._items))
            self._items, self._nested, self._in_li = [], False, True
            return
        if self._items:
            self.blocks.append(("ul", self._items))
        self._items = None

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "para", "li", "ul"):
            self._refuse_open_link(f"<{tag}>")
        if tag in ("p", "para"):
            if not self._in_li:
                self._flush_loose()
                self._runs = []
        elif tag == "ul":
            self._open_list()
        elif tag == "li":
            self._runs = []
            self._in_li = True
        elif tag == "a":
            self._open_link(attrs)
        elif tag in _INLINE:
            if _INLINE[tag] == "bold":
                self._bold += 1
            else:
                self._ital += 1
        elif tag == "span":
            style = (dict(attrs).get("style") or "").replace(" ", "").lower()
            bold = 1 if "font-weight:bold" in style else 0
            ital = 1 if "font-style:italic" in style else 0
            self._span_fmt.append((bold, ital))
            self._bold += bold
            self._ital += ital

    def handle_endtag(self, tag):
        if tag in ("p", "para", "li"):
            self._refuse_open_link(f"</{tag}>")
        if tag == "a":
            self._close_link()
        elif tag in ("p", "para"):
            if not self._in_li and self._runs is not None:
                self.blocks.append(("p", self._runs))
                self._runs = None
        elif tag == "li":
            if self._runs is not None and self._items is not None:
                self._items.append(self._runs)
            self._runs = None
            self._in_li = False
            if not self._nested:
                self._outer_li = False
        elif tag == "ul":
            self._close_list()
        elif tag in _INLINE:
            if _INLINE[tag] == "bold":
                self._bold = max(0, self._bold - 1)
            else:
                self._ital = max(0, self._ital - 1)
        elif tag == "span" and self._span_fmt:
            bold, ital = self._span_fmt.pop()
            self._bold = max(0, self._bold - bold)
            self._ital = max(0, self._ital - ital)

    def handle_data(self, data):
        text = _WS_RE.sub(" ", data)
        if not text.strip():
            return
        if self._runs is None and self._outer_li and not self._nested:
            raise ValueError(f"item text after a nested list inside the same <li>: {text.strip()!r}")
        run = Run(text, self._bold > 0, self._ital > 0, self._href)
        self._link_text = self._link_text or self._href is not None
        (self._runs if self._runs is not None else self._loose).append(run)

    def close(self):
        super().close()
        self._refuse_open_link("the end of the markup")
        self._flush_loose()


def _trim_edges(runs: List[Run]) -> List[Run]:
    """Drop whitespace-only edge runs and trim leading/trailing space of the edges.

    Inter-run spaces are preserved -- the trailing space before a bold run is significant.
    """
    runs = list(runs)
    while runs and not runs[0].text.strip():
        runs.pop(0)
    while runs and not runs[-1].text.strip():
        runs.pop()
    if not runs:
        return []
    runs[0] = runs[0]._replace(text=runs[0].text.lstrip())
    runs[-1] = runs[-1]._replace(text=runs[-1].text.rstrip())
    return runs


def _normalize(blocks: List[Block]) -> List[Block]:
    """Trim paragraph/list-item edges and drop blocks that become empty."""
    out: List[Block] = []
    for kind, content in blocks:
        if kind == "p":
            runs = _trim_edges(content)
            if runs:
                out.append(("p", runs))
        else:
            items = [r for r in (_trim_edges(item) for item in content) if r]
            if items:
                out.append((kind, items))
    return out


def _grouped(blocks: List[Block]) -> List[GroupedBlock]:
    """Merge consecutive list blocks into ("list", [(runs, [child_runs, ...]), ...]) trees.

    A ``sub`` block attaches its items as children of the preceding list item; one with no
    preceding item becomes top-level items.
    """
    out: List[GroupedBlock] = []
    for kind, content in blocks:
        if kind == "p":
            out.append(("p", content))
            continue
        if not out or out[-1][0] != "list":
            out.append(("list", []))
        tree = out[-1][1]
        if kind == "sub" and tree:
            tree[-1][1].extend(content)
        else:
            tree.extend((runs, []) for runs in content)
    return out


def parse(markup: Optional[str]) -> List[Block]:
    """Parse subset HTML (or plain text) into normalized blocks."""
    if not markup or not markup.strip():
        return []
    parser = _SubsetParser()
    parser.feed(markup)
    parser.close()
    return _normalize(parser.blocks)


def inner_html(element) -> str:
    """Return a tool field's authored content as subset HTML.

    Handles both canonical conventions: a ``<para>`` child (the metadata form) and CDATA
    HTML text (the summary/usage form).
    """
    if element is None:
        return ""
    paras = element.findall("para")
    if paras:
        return "".join(f"<p>{''.join(p.itertext())}</p>" for p in paras)
    return element.text or ""


def is_plain(blocks: List[Block]) -> bool:
    """Return True for a single paragraph with one unformatted run outside any link."""
    if len(blocks) != 1 or blocks[0][0] != "p":
        return False
    runs = blocks[0][1]
    return len(runs) == 1 and not runs[0].bold and not runs[0].italic and runs[0].href is None


def _flatten(blocks: List[Block], run_text: Callable[[Run], str]) -> str:
    """Join every paragraph and list item into one whitespace-collapsed line of ``run_text`` output."""
    parts: List[str] = []
    for kind, content in blocks:
        if kind == "p":
            parts.append("".join(run_text(r) for r in content))
        else:
            parts.extend("".join(run_text(r) for r in item) for item in content)
    return _WS_RE.sub(" ", " ".join(parts)).strip()


def plain_text(blocks: List[Block]) -> str:
    """Flatten blocks to a single plain-text line."""
    return _flatten(blocks, lambda r: r.text)


def text_with_links(blocks: List[Block]) -> str:
    """Flatten blocks like :func:`plain_text`, with each link run's href appended as ``text [href]``.

    Equal to :func:`plain_text` for blocks without links, so a changed href changes the result.
    """
    return _flatten(blocks, lambda r: r.text if r.href is None else f"{r.text} [{r.href}]")


def _attr(value: str) -> str:
    """``value`` escaped for a double-quoted attribute."""
    return escape(value, {'"': "&quot;"})


def _runs_pro(runs: List[Run]) -> str:
    out = ""
    for r in runs:
        styles = ("font-weight:bold;" if r.bold else "") + ("font-style:italic;" if r.italic else "")
        style = f' STYLE="{styles}"' if styles else ""
        text = escape(r.text) if r.href is None else f'<A HREF="{_attr(r.href)}">{escape(r.text)}</A>'
        out += f"<SPAN{style}>{text}</SPAN>"
    return out


def _pro_list(tree: List[TreeItem], ul_style: str) -> str:
    """Render one list tree as Pro HTML; children render as a nested list in their item."""
    items = "".join(
        f'<LI STYLE="{PRO_LI_STYLE}">{_runs_pro(runs)}'
        f'{_pro_list([(c, []) for c in children], PRO_SUBUL_STYLE) if children else ""}</LI>'
        for runs, children in tree
    )
    return f'<UL STYLE="{ul_style}">{items}</UL>'


def to_pro_html(blocks: List[Block]) -> str:
    """Render blocks as Pro's item-metadata HTML (caller stores it as element text).

    Pro's help page pretty-prints this HTML inside ``<pre class="wrap">``, whose stylesheet
    preserves whitespace and pads each ``p`` and ``li`` by 1em. The outer DIV resets
    ``white-space`` (PRO_DIV_STYLE), list items carry no inner ``<P>``, and every block carries
    an inline padding or margin style that overrides the stylesheet.
    """
    parts: List[str] = []
    for kind, content in _grouped(blocks):
        if kind == "p":
            parts.append(f'<P STYLE="{PRO_P_STYLE}">{_runs_pro(content)}</P>')
        else:
            parts.append(_pro_list(content, PRO_UL_STYLE))
    return f'<DIV STYLE="{PRO_DIV_STYLE}">{"".join(parts)}</DIV>'


def _runs_xdoc(runs: List[Run]) -> str:
    out = ""
    for r in runs:
        text = escape(r.text)
        if r.bold and r.italic:
            out += f"<b><i>{text}</i></b>"
        elif r.bold:
            out += f"<b>{text}</b>"
        elif r.italic:
            out += f"<i>{text}</i>"
        else:
            out += f"<span>{text}</span>"
    return out


def _xdoc_list(tree: List[TreeItem]) -> str:
    """Render one list tree as xdoc; children render as a nested list in their item."""
    items = "".join(
        f"<li><p>{_runs_xdoc(runs)}</p>{_xdoc_list([(c, []) for c in children]) if children else ''}</li>"
        for runs, children in tree
    )
    return f"<ul>{items}</ul>"


def to_xdoc(blocks: List[Block]) -> str:
    """Render blocks as resource-file xdoc rich text."""
    parts: List[str] = []
    for kind, content in _grouped(blocks):
        parts.append(f"<p>{_runs_xdoc(content)}</p>" if kind == "p" else _xdoc_list(content))
    return f"<xdoc>{''.join(parts)}</xdoc>"


def _run_canon(r: Run) -> str:
    """One run in the authoring subset; a link run wraps its formatting in ``<a href>``."""
    text = escape(r.text)
    if r.bold and r.italic:
        text = f"<b><i>{text}</i></b>"
    elif r.bold:
        text = f"<b>{text}</b>"
    elif r.italic:
        text = f"<i>{text}</i>"
    return text if r.href is None else f'<a href="{_attr(r.href)}">{text}</a>'


def _runs_canon(runs: List[Run]) -> str:
    return "".join(_run_canon(r) for r in runs)


def to_canonical(blocks: List[Block]) -> str:
    """Render blocks as the canonical authoring subset (for a CDATA source field).

    Plain text carries no wrapper; ``<b>``/``<i>`` mark inline formatting, ``<a href>`` marks a
    link and ``<ul>``/``<li>`` mark lists. This is the inverse of :func:`parse` for the supported subset.
    """
    parts: List[str] = []
    for kind, content in _grouped(blocks):
        parts.append(f"<p>{_runs_canon(content)}</p>" if kind == "p" else _canon_list(content))
    return "".join(parts)


def _canon_list(tree: List[TreeItem]) -> str:
    """Render one list tree in the authoring subset; children nest inside their item."""
    items = "".join(
        f"<li>{_runs_canon(runs)}{_canon_list([(c, []) for c in children]) if children else ''}</li>"
        for runs, children in tree
    )
    return f"<ul>{items}</ul>"


def illustration_entry(tool: str) -> str:
    """Return the archive member holding the tool's illustration image."""
    return f"{tool}.tool/tool.illustration.png"


def illustration_data_uri(png: bytes) -> str:
    """Return ``png`` as the ``data:`` URI Pro's "?" page stylesheet draws from
    ``Binary/Thumbnail/img/@src``."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
