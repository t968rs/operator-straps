"""arc-help-pages API: the pages a project has, the two checks that keep a page and its links honest.

``check_help_page`` reports a fragment the build refuses (``fragment_invalid``, alone), a page the build
cannot make (one ``help_page_stale`` naming the refusal), a page a rebuild would change
(``help_page_stale``; the tracked page is read with universal newlines, so a CRLF checkout of an unchanged
page is current) and a tool whose canonical XML holds no href naming the page (``help_page_unlinked``).

``check_links`` reads every href in a tool's canonical XML. ``#...`` anchors and schemes other than ``file:``
are skipped; a ``file:`` href under the main checkout prefix (matched ignoring case) must name a file in the
current tree (``link_target_missing``), any other ``file:`` href is dead in production
(``link_outside_checkout``), and an href with no scheme that is not rooted at ``/`` or ``\\`` resolves
against Pro's temp copy of the page (``link_relative``).

``__all__`` is the surface the ``harness-skill-api --file`` heredoc binds. Imports only the standard library
and the sibling modules of the skill; nothing from arc-meta.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlsplit

import arc_help_pages_build as build
from arc_help_pages_build import apply_help, build_page
from arc_help_pages_config import HelpPaths, RepoLike, paths
from arc_help_pages_models import FragmentError, HelpError, HelpProblem, HelpProblemCode

__all__ = ["HelpError", "HelpProblemCode", "paths", "help_pages", "build_page", "apply_help",
           "check_help_page", "check_links", "format_problems"]

FRAGMENTS = "_fragments"
_HREF = re.compile(r"""(?<![\w-])href\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def help_pages(repo: RepoLike = None) -> List[str]:
    """Sorted stems of ``<help_dir>/_fragments/*.html``; empty when the folder is absent."""
    folder = paths(repo).help_dir / FRAGMENTS
    return sorted(path.stem for path in folder.glob("*.html") if path.is_file())


def format_problems(problems: List[HelpProblem]) -> str:
    """One line per problem (``code | subject | detail``), or ``clean``."""
    if not problems:
        return "clean"
    return "\n".join(f"{p.code.value} | {p.subject} | {p.detail}" for p in problems)


def _problem(code: HelpProblemCode, subject: str, detail: str) -> HelpProblem:
    return HelpProblem(code=code, subject=subject, detail=detail)


# --- hrefs ----------------------------------------------------------------------------------------------

def _hrefs(p: HelpPaths, tool: str) -> List[str]:
    """Every ``href="..."`` or ``href='...'`` value in ``<tool_dir>/<tool>.xml``, entity-decoded."""
    path = p.tool_dir / f"{tool}.xml"
    if not path.is_file():
        raise HelpError(f"no canonical source at {path.as_posix()}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HelpError(f"{path.as_posix()} is not UTF-8 text ({exc})") from exc
    return [html.unescape(double if double is not None else single)
            for double, single in _HREF.findall(text)]


def _under_prefix(href: str, prefix: str) -> bool:
    return href[:len(prefix)].lower() == prefix.lower()


def _is_relative(href: str) -> bool:
    """True for an href with no scheme that is neither an anchor nor rooted at ``/`` or ``\\``."""
    return not href.startswith(("#", "/", "\\")) and not urlsplit(href).scheme


def _link_problem(p: HelpPaths, tool: str, href: str) -> Optional[HelpProblem]:
    """The defect of one href, or None for an anchor, a non-``file:`` link or a present target."""
    if _is_relative(href):
        return _problem(HelpProblemCode.LINK_RELATIVE, tool, href)
    if href.startswith("#") or urlsplit(href).scheme != "file":
        return None
    if not _under_prefix(href, p.prefix):
        return _problem(HelpProblemCode.LINK_OUTSIDE_CHECKOUT, tool, href)
    tail = unquote(re.split(r"[#?]", href[len(p.prefix):], maxsplit=1)[0])
    if (p.root / tail).is_file():
        return None
    return _problem(HelpProblemCode.LINK_TARGET_MISSING, tool, tail)


def check_links(tool: str, repo: RepoLike = None) -> List[HelpProblem]:
    """Problems with the hrefs of ``tool``'s canonical XML, in document order; subject is ``tool``."""
    p = paths(repo)
    found = (_link_problem(p, tool, href) for href in _hrefs(p, tool))
    return [problem for problem in found if problem is not None]


# --- page -----------------------------------------------------------------------------------------------

def _fragment_tool(p: HelpPaths, page: str, repo: RepoLike) -> str:
    """The tool the fragment of ``page`` names (the build has already accepted the fragment)."""
    text = (p.help_dir / FRAGMENTS / f"{page}.html").read_text(encoding="utf-8")
    return build.parse_fragment(page, text, repo).tool


def _is_current(target: Path, built: str) -> bool:
    """True when ``target`` exists and its text, read with universal newlines, equals ``built``."""
    if not target.is_file():
        return False
    try:
        return target.read_text(encoding="utf-8") == built
    except UnicodeDecodeError:
        return False


def _links_page(p: HelpPaths, tool: str, page: str) -> bool:
    """True when ``tool``'s canonical XML holds the page href, its prefix compared ignoring case."""
    tail = p.page_href(page)[len(p.prefix):]
    return any(_under_prefix(href, p.prefix) and href[len(p.prefix):] == tail for href in _hrefs(p, tool))


def check_help_page(page: str, repo: RepoLike = None) -> List[HelpProblem]:
    """Problems with ``<help_dir>/<page>.html`` and its link; subject is ``page``.

    A refused fragment is one ``fragment_invalid`` problem and any other build refusal one
    ``help_page_stale`` problem (``cannot build <page>: <message>``), each alone.
    """
    p = paths(repo)
    try:
        built = build_page(page, repo)
    except FragmentError as exc:
        return [_problem(HelpProblemCode.FRAGMENT_INVALID, page, str(exc))]
    except HelpError as exc:
        return [_problem(HelpProblemCode.HELP_PAGE_STALE, page, f"cannot build {page}: {exc}")]
    problems: List[HelpProblem] = []
    target = p.help_dir / f"{page}.html"
    rel = target.relative_to(p.root).as_posix()
    if not _is_current(target, built):
        what = "absent" if not target.is_file() else "differs from a rebuild"
        problems.append(_problem(HelpProblemCode.HELP_PAGE_STALE, page, f"{rel} {what}"))
    tool = _fragment_tool(p, page, repo)
    if not _links_page(p, tool, page):
        problems.append(_problem(HelpProblemCode.HELP_PAGE_UNLINKED, page,
                                 f"{tool}.xml holds no development href to {rel}"))
    return problems
