"""arc-meta: read-only checks over a project's toolbox archive and its canonical tool help sources.

The API reads two things and writes nothing:

- the toolbox archive (``.atbx``, a zip; per tool ``<Tool>.tool/tool.content``, ``tool.content.rc``,
  ``tool.metadata.xml``, ``tool.script.execute.link``, ``tool.script.validate.py``,
  ``tool.illustration.png``);
- the canonical sources ``<tool_dir>/<Tool>.xml``.

Every comparison uses the generator (``arc_meta_format``) and the "?" page builder (``arc_meta_canonical``)
the apply writers use, so the checker and the writers cannot drift. Locations come from
``plugins.arc-straps.arc_meta`` in ``.claude/harness.json`` through ``paths(repo)``; ``repo`` defaults to
the active project. Refusals raise ``ApiError``, a ``ValueError``; a configuration defect raises the
harness ``ConfigError`` unchanged. ``__all__`` is the surface the api heredoc binds.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

import arc_meta_canonical
import arc_meta_format as mf
from arc_meta_archive import read_bytes, read_json, read_text
from arc_meta_config import ArcMetaPaths, RepoLike, paths
from arc_meta_models import ApiError, Direction, ParamRow, ParamType, Problem, ProblemCode, ToolSources
from harness_lib.config import ConfigError

__all__ = [
    "ApiError", "Direction", "ParamType", "ProblemCode", "tool_names", "param_table", "check_canonical",
    "check_applied", "entry_sources", "format_rows", "format_problems", "paths",
]

SUPPORTED_TAGS = frozenset({"p", "b", "strong", "i", "em", "ul", "li", "para"})
PARAM_ATTRS = ("displayname", "type", "direction", "datatype")
_PREFIX = re.compile(r"^\d+[A-Za-z]?[\s_]")
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)")
_TYPES = {"required": ParamType.REQUIRED, "optional": ParamType.OPTIONAL, "derived": ParamType.DERIVED}


# --- locations ------------------------------------------------------------------------------------------

def _archive(p: ArcMetaPaths) -> zipfile.ZipFile:
    if not p.atbx.is_file():
        raise ApiError(f"no toolbox at {p.atbx.as_posix()}")
    try:
        return zipfile.ZipFile(p.atbx)
    except zipfile.BadZipFile as exc:
        raise ApiError(f"{p.atbx.name} is not a zip archive ({exc})") from exc


def _tool_json(p: ArcMetaPaths, tool: str) -> Tuple[dict, Dict[str, str]]:
    """``tool.content`` and the rc map of ``tool``; refused when the tool is not in the archive."""
    names, label = (f"{tool}.tool/tool.content", f"{tool}.tool/tool.content.rc"), p.atbx.name
    with _archive(p) as zf:
        content = read_json(zf, names[0], label)
        if content is None:
            raise ApiError(f"{tool} is not a tool in {label}")
        blank = not (read_text(zf, names[1], label) or "").strip()
        rc = None if blank else read_json(zf, names[1], label)
    return _checked_content(content, f"{names[0]} in {label}"), _rc_map(rc)


def _checked_content(content: object, where: str) -> dict:
    """``tool.content`` refused unless it, its ``params`` and every parameter are JSON objects."""
    if not isinstance(content, dict):
        raise ApiError(f"{where} is not a JSON object")
    params = content.get("params", {})
    if not isinstance(params, dict) or not all(isinstance(param, dict) for param in params.values()):
        raise ApiError(f"{where}: params must be an object of parameter objects")
    return content


def _rc_map(rc: object) -> Dict[str, str]:
    """The rc ``map``; {} when the rc is absent or blank, or it or its map is not a JSON object."""
    found = rc.get("map") if isinstance(rc, dict) else None
    return found if isinstance(found, dict) else {}


def _tool_element(tree: ET.Element, tool: str) -> ET.Element:
    return arc_meta_canonical.tool_element(tree, f"{tool}.xml")


# --- tool_names / param_table ---------------------------------------------------------------------------

def tool_names(repo: RepoLike = None) -> List[str]:
    """Every tool in the archive, sorted."""
    with _archive(paths(repo)) as zf:
        names = {n.split("/", 1)[0][:-5] for n in zf.namelist() if n.split("/", 1)[0].endswith(".tool")}
    return sorted(names)


def _resolve(value: str, rc: Dict[str, str]) -> str:
    return rc.get(value[4:], value) if value.startswith("$rc:") else value


def _domain_values(domain: object) -> List[str]:
    """The coded ``value`` of every value-list item, nested composite domains included."""
    if not isinstance(domain, dict):
        return []
    items = domain.get("items") or []
    if domain.get("type") == "GPCodedValueDomain":
        return [str(item.get("value")) for item in items if isinstance(item, dict)]
    return [value for item in items for value in _domain_values(item)]


def _default(value: object) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def _row(name: str, param: dict, rc: Dict[str, str]) -> ParamRow:
    key = f"{name.lower()}.descr"
    datatype = param.get("datatype")
    return ParamRow(
        name=name,
        title=_resolve(str(param.get("displayname", "")), rc),
        type=_TYPES.get(str(param.get("type", "required")).lower(), ParamType.REQUIRED),
        direction=Direction.OUTPUT if str(param.get("direction", "in")).lower().startswith("out")
        else Direction.INPUT,
        datatype=str(datatype.get("type", "")) if isinstance(datatype, dict) else str(datatype or ""),
        hover_wired=param.get("description") == f"$rc:{key}" and bool(str(rc.get(key, "")).strip()),
        symbology=param.get("symbologylayer"),
        values=_domain_values(param.get("domain")),
        default=_default(param.get("value")),
    )


def _rows(p: ArcMetaPaths, tool: str) -> List[ParamRow]:
    content, rc = _tool_json(p, tool)
    return [_row(name, param, rc) for name, param in content.get("params", {}).items()]


def param_table(tool: str, repo: RepoLike = None) -> List[ParamRow]:
    """Each ``tool.content`` parameter of ``tool``, in dialog order."""
    return _rows(paths(repo), tool)


# --- check_canonical ------------------------------------------------------------------------------------

def _problem(code: ProblemCode, tool: str, detail: str, param: Optional[str] = None) -> Problem:
    return Problem(code=code, tool=tool, param=param, detail=detail)


def _rich_fields(tool_el: ET.Element) -> Iterable[Tuple[Optional[str], str, str]]:
    """``(param, field, html)`` for the summary, the usage and every dialogReference."""
    for tag in ("summary", "usage"):
        yield None, tag, mf.inner_html(tool_el.find(tag))
    for param in tool_el.iter("param"):
        yield param.get("name"), "dialogReference", mf.inner_html(param.find("dialogReference"))


def _max_list_depth(html: str) -> int:
    depth = deepest = 0
    for closing, tag in _TAG.findall(html):
        if tag.lower() == "ul":
            depth = depth - 1 if closing else depth + 1
            deepest = max(deepest, depth)
    return deepest


def _parse_problems(tool: str, field: str, html: str, param: Optional[str]) -> List[Problem]:
    """An ``unparseable`` problem when the generator refuses ``html``, as the apply writers do."""
    try:
        mf.parse(html)
    except ValueError as exc:
        return [_problem(ProblemCode.UNPARSEABLE, tool, f"{field}: the generator refuses it ({exc})", param)]
    return []


def _field_markup_problems(tool: str, field: str, html: str, param: Optional[str]) -> List[Problem]:
    problems: List[Problem] = []
    tags = sorted({tag.lower() for _, tag in _TAG.findall(html)} - SUPPORTED_TAGS)
    if tags:
        problems.append(_problem(ProblemCode.UNSUPPORTED_TAG, tool, f"{field}: <{'>, <'.join(tags)}>", param))
    if _max_list_depth(html) > 2:
        problems.append(_problem(ProblemCode.DEEP_NESTING, tool,
                                 f"{field}: lists nest past one level", param))
    else:
        problems += _parse_problems(tool, field, html, param)
    return problems


def _markup_problems(tool: str, tool_el: ET.Element) -> List[Problem]:
    return [problem for param, field, html in _rich_fields(tool_el)
            for problem in _field_markup_problems(tool, field, html, param)]


def _text_problems(tool: str, text: str, tool_el: ET.Element) -> List[Problem]:
    problems: List[Problem] = []
    if _PREFIX.match(tool_el.get("displayname", "")):
        shown = tool_el.get("displayname")
        problems.append(_problem(ProblemCode.PREFIXED_DISPLAYNAME, tool,
                                 f"displayname {shown!r} carries the rc ordering prefix"))
    lines = [n for n, line in enumerate(text.splitlines(), 1) if any(ord(c) > 127 for c in line)]
    if lines:
        problems.append(_problem(ProblemCode.NON_ASCII, tool, f"non-ASCII text on lines {lines[:10]}"))
    if re.search(r"<(Binary|Thumbnail)\b", text):
        problems.append(_problem(ProblemCode.THUMBNAIL, tool, "embedded <Binary>/<Thumbnail> block"))
    return problems


def _param_problems(tool: str, tool_el: ET.Element, rows: List[ParamRow]) -> List[Problem]:
    known = {row.name: row for row in rows}
    canon = {p.get("name", ""): p for p in tool_el.iter("param")}
    problems = [_problem(ProblemCode.UNKNOWN_PARAM, tool,
                         "not a tool.content parameter; its text is dropped", n)
                for n in canon if n not in known]
    problems += [_problem(ProblemCode.MISSING_PARAM, tool,
                          "absent from the canonical XML; the help page drops it", n)
                 for n in known if n not in canon]
    for name in (n for n in canon if n in known):
        row, el = known[name], canon[name]
        if el.get("type") != row.type.value:
            problems.append(_problem(ProblemCode.TYPE_MISMATCH, tool,
                                     f"type {el.get('type')!r}, tool.content says {row.type.value!r}", name))
        if el.get("direction") != row.direction.value:
            problems.append(_problem(ProblemCode.DIRECTION_MISMATCH, tool,
                                     f"direction {el.get('direction')!r}, "
                                     f"tool.content says {row.direction.value!r}", name))
    return problems


def check_canonical(tool: str, repo: RepoLike = None) -> List[Problem]:
    """Defects of the canonical ``<tool>.xml`` alone and against ``tool.content``; [] when clean."""
    p = paths(repo)
    text, tree = arc_meta_canonical.load(p.tool_dir, tool)
    tool_el = _tool_element(tree, tool)
    return (_text_problems(tool, text, tool_el) + _markup_problems(tool, tool_el)
            + _param_problems(tool, tool_el, _rows(p, tool)))


# --- check_applied: hover text --------------------------------------------------------------------------

def _plain(markup: Optional[str]) -> str:
    return " ".join(mf.plain_text(mf.parse(markup or "")).split())


def _shown_plain(markup: Optional[str]) -> Optional[str]:
    """``_plain`` of archive text; None when the generator refuses it, so that surface reads as stale
    instead of blaming the canonical XML."""
    try:
        return _plain(markup)
    except ValueError:
        return None


_Hover = Tuple[Optional[str], str, str, object]


def _hover_wanted(tree: ET.Element, tool: str, content: dict) -> List[_Hover]:
    """``(param, rc key, expected rc value, tool.content reference)`` for the summary and each parameter.

    The expected text comes from ``arc_meta_canonical.fields_of``, the reader the hover writer uses, so the
    two match parameters the same way (by lower-cased name).
    """
    params = content.get("params", {})
    summary, descr = arc_meta_canonical.fields_of(tree, f"{tool}.xml")
    wanted: List[_Hover] = [(None, "description", summary, content.get("description"))]
    by_lower = {name.lower(): name for name in params}
    for lower, expected in descr.items():
        name = by_lower.get(lower)
        if name is not None:
            wanted.append((name, f"{lower}.descr", expected, params[name].get("description")))
    return wanted


def _hover_problem(tool: str, key: str, expected: str, ref: object, actual: Optional[str],
                   param: Optional[str]) -> List[Problem]:
    if ref != f"$rc:{key}":
        return [_problem(ProblemCode.HOVER_UNWIRED, tool,
                         f"tool.content does not reference $rc:{key}", param)]
    if _shown_plain(actual) != _plain(expected):
        return [_problem(ProblemCode.HOVER_STALE, tool, f"rc {key} differs from the canonical text", param)]
    if actual != expected:
        return [_problem(ProblemCode.HOVER_STYLE_STALE, tool,
                         f"rc {key} markup differs from what the generator writes now", param)]
    return []


def _hover_problems(p: ArcMetaPaths, tool: str, tree: ET.Element) -> List[Problem]:
    """Hover defects of every surface with non-empty canonical text; empty canonical text is not compared."""
    content, rc = _tool_json(p, tool)
    return [problem for param, key, expected, ref in _hover_wanted(tree, tool, content) if expected
            for problem in _hover_problem(tool, key, expected, ref, rc.get(key), param)]


# --- check_applied: the "?" page ------------------------------------------------------------------------

def _field_problem(tool: str, field: str, expected: str, actual: Optional[str],
                   param: Optional[str] = None) -> List[Problem]:
    if _shown_plain(actual) != _plain(expected):
        return [_problem(ProblemCode.PAGE_STALE, tool,
                         f"help page {field} text differs from the canonical text", param)]
    if (actual or "").strip() != expected.strip():
        return [_problem(ProblemCode.PAGE_STYLE_STALE, tool,
                         f"help page {field} markup differs from what the generator writes now", param)]
    return []


def _ref_text(field: Optional[ET.Element]) -> Optional[str]:
    """The text of a page field (summary, usage, dialogReference): one <para> as its whole text, several
    as subset HTML (so none is dropped), none as the field's own escaped HTML."""
    if field is None:
        return None
    paras = field.findall("para")
    if len(paras) == 1:
        return "".join(paras[0].itertext())
    return mf.inner_html(field) if paras else field.text


def _attribute_problems(tool: str, attrs: Iterable[str], want: ET.Element, shown: ET.Element,
                        param: Optional[str] = None) -> List[Problem]:
    """A ``page_stale`` problem per attribute of the expected page that ``shown`` does not hold."""
    return [_problem(ProblemCode.PAGE_STALE, tool,
                     f"help page {attr} {shown.get(attr)!r}, "
                     f"the canonical XML says {want.get(attr, '')!r}", param)
            for attr in attrs if shown.get(attr) != want.get(attr, "")]


def _param_set_problems(tool: str, want: Dict[str, ET.Element],
                        shown: Dict[str, ET.Element]) -> List[Problem]:
    """Parameters missing from or extra on the page, and a page order that differs from the canonical."""
    problems = [_problem(ProblemCode.PAGE_STALE, tool, "missing from the help page", n)
                for n in want if n not in shown]
    problems += [_problem(ProblemCode.PAGE_STALE, tool, "on the help page but not in the canonical XML", n)
                 for n in shown if n not in want]
    want_order, shown_order = [n for n in want if n in shown], [n for n in shown if n in want]
    if want_order != shown_order:
        problems.append(_problem(ProblemCode.PAGE_STYLE_STALE, tool,
                                 f"help page parameter order {shown_order}, "
                                 f"the canonical order {want_order}"))
    return problems


def _page_param_problems(tool: str, want_tool: ET.Element, page_tool: ET.Element) -> List[Problem]:
    want = {el.get("name", ""): el for el in want_tool.iter("param")}
    shown = {el.get("name", ""): el for el in page_tool.iter("param")}
    problems = _param_set_problems(tool, want, shown)
    for name in (n for n in want if n in shown):
        problems += _attribute_problems(tool, PARAM_ATTRS, want[name], shown[name], name)
        expected = _ref_text(want[name].find("dialogReference")) or ""
        problems += _field_problem(tool, "dialogReference", expected,
                                   _ref_text(shown[name].find("dialogReference")), name)
    return problems


def _image_src(page_root: ET.Element) -> Optional[str]:
    img = page_root.find("Binary/Thumbnail/img")
    return img.get("src") if img is not None else None


def _image_problems(tool: str, page_root: ET.Element, want_root: ET.Element) -> List[Problem]:
    """A ``page_image_stale`` problem when the help page's illustration differs from the archive's image."""
    shown, expected = _image_src(page_root), _image_src(want_root)
    if shown == expected:
        return []
    detail = ("the help page shows no illustration, the archive holds tool.illustration.png" if shown is None
              else "the help page shows an illustration the archive does not hold" if expected is None
              else "the help page illustration differs from tool.illustration.png")
    return [_problem(ProblemCode.PAGE_IMAGE_STALE, tool, detail)]


def _page_root(zf: zipfile.ZipFile, name: str, label: str) -> Tuple[Optional[ET.Element], str]:
    """The parsed help page ``name``, or None and the ``page_stale`` detail saying why it cannot be compared.

    A corrupt, undecodable or malformed page, or one without a ``<tool>`` element, reads as stale rather
    than refused, as the page writer reads it, so the ``apply_page`` rewrite that repairs it shows as due.
    Parsed as ``str``, so the declared encoding of a UTF-16 member does not apply twice.
    """
    if name not in zf.namelist():
        return None, "the archive holds no tool.metadata.xml help page"
    try:
        root = ET.fromstring(read_text(zf, name, label) or "")
    except (ApiError, ET.ParseError) as exc:
        return None, f"the archive help page is not readable XML ({exc}); apply_page rewrites it"
    if root.find("tool") is None:
        return None, "the archive help page has no <tool> element; apply_page rewrites it"
    return root, ""


def _archive_page(p: ArcMetaPaths, tool: str) -> Tuple[Optional[ET.Element], str, Optional[bytes]]:
    """The parsed ``tool.metadata.xml`` (or None and why it is stale) and the ``tool.illustration.png``
    bytes, None when absent; a corrupt illustration is refused, as ``arc_meta_page`` refuses it."""
    with _archive(p) as zf:
        page_root, why = _page_root(zf, f"{tool}.tool/tool.metadata.xml", p.atbx.name)
        return page_root, why, read_bytes(zf, mf.illustration_entry(tool), p.atbx.name)


_TITLE = "dataIdInfo/idCitation/resTitle"
_KEYWORDS = "dataIdInfo/searchKeys/keyword"


def _id_problems(tool: str, want_root: ET.Element, page_root: ET.Element) -> List[Problem]:
    """``page_stale`` problems for the ``dataIdInfo`` title and keyword list the writer copies."""
    problems: List[Problem] = []
    want_title, shown_title = want_root.findtext(_TITLE), page_root.findtext(_TITLE)
    if (shown_title or "") != (want_title or ""):
        problems.append(_problem(ProblemCode.PAGE_STALE, tool,
                                 f"help page resTitle {shown_title!r}, "
                                 f"the canonical XML says {want_title!r}"))
    want_keys = [kw.text or "" for kw in want_root.findall(_KEYWORDS)]
    shown_keys = [kw.text or "" for kw in page_root.findall(_KEYWORDS)]
    if shown_keys != want_keys:
        problems.append(_problem(ProblemCode.PAGE_STALE, tool,
                                 f"help page keywords {shown_keys}, the canonical XML says {want_keys}"))
    return problems


def _text_field_problems(tool: str, want_tool: ET.Element, page_tool: ET.Element) -> List[Problem]:
    """Summary and usage drift; the writer always writes the summary, the usage only when it holds text."""
    problems: List[Problem] = []
    for tag in ("summary", "usage"):
        expected, actual = _ref_text(want_tool.find(tag)) or "", _ref_text(page_tool.find(tag))
        if expected or (actual or "").strip():
            problems += _field_problem(tool, tag, expected, actual)
    return problems


def _page_problems(p: ArcMetaPaths, tool: str, tree: ET.Element) -> List[Problem]:
    page_root, why, illustration = _archive_page(p, tool)
    page_tool = page_root.find("tool") if page_root is not None else None
    if page_root is None or page_tool is None:
        return [_problem(ProblemCode.PAGE_STALE, tool, why)]
    want_root = ET.fromstring(arc_meta_canonical.page(tree, illustration))
    want_tool = _tool_element(want_root, tool)
    problems = _attribute_problems(tool, ("displayname",), want_tool, page_tool)
    problems += _image_problems(tool, page_root, want_root) + _id_problems(tool, want_root, page_root)
    problems += _text_field_problems(tool, want_tool, page_tool)
    return problems + _page_param_problems(tool, want_tool, page_tool)


def check_applied(tool: str, repo: RepoLike = None) -> List[Problem]:
    """Surfaces of ``tool`` whose archive state differs from the canonical XML; [] when fully applied.

    A parameter or summary whose canonical text is empty is not compared against the rc, since the apply
    never writes or clears that rc key.
    """
    p = paths(repo)
    tree = arc_meta_canonical.load(p.tool_dir, tool)[1]
    _tool_element(tree, tool)
    try:
        return _hover_problems(p, tool, tree) + _page_problems(p, tool, tree)
    except (ApiError, ConfigError):
        raise
    except ValueError as exc:
        raise ApiError(f"{tool}.xml cannot be generated ({exc}); fix it, then run check_canonical") from exc


# --- entry_sources --------------------------------------------------------------------------------------

def _registry_path(p: ArcMetaPaths, tool: str) -> Optional[str]:
    """The ``py_path`` the configured registry claims for ``tool``; None when unset, absent or unlisted."""
    if p.registry is None or not p.registry.is_file():
        return None
    tools = _registry_tools(p.registry)
    return next((t.get("py_path") for t in tools if t.get("tool_name") == tool), None)


def _registry_tools(path: Path) -> List[dict]:
    """The registry's ``tools`` list; refused unless it is UTF-8 JSON, an object, and each entry an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(f"registry {path.as_posix()} is not UTF-8 JSON ({exc})") from exc
    tools = data.get("tools", []) if isinstance(data, dict) else None
    if not isinstance(tools, list) or not all(isinstance(entry, dict) for entry in tools):
        raise ApiError(f"registry {path.as_posix()} must be an object whose tools list holds objects")
    return tools


def _link_target(p: ArcMetaPaths, tool: str, link: Optional[str]) -> Optional[str]:
    """The module a ``tool.script.execute.link`` names: project-relative, or absolute when the link resolves
    outside the project (a registry ``py_path`` then never matches it). The link resolves as if the archive
    were a folder holding ``<Tool>.tool/``."""
    if not link or not link.strip():
        return None
    folder = p.atbx.parent / p.atbx.name / f"{tool}.tool"
    joined = Path(os.path.normpath(str(folder / link.strip().replace("\\", "/"))))
    try:
        return joined.resolve().relative_to(p.root.resolve()).as_posix()
    except ValueError:
        return joined.as_posix()


def entry_sources(tool: str, repo: RepoLike = None) -> ToolSources:
    """The implementing module (from the link, never the registry), the validator and the registry's claim."""
    p = paths(repo)
    with _archive(p) as zf:
        names = set(zf.namelist())
        if f"{tool}.tool/tool.content" not in names:
            raise ApiError(f"{tool} is not a tool in {p.atbx.name}")
        link = read_text(zf, f"{tool}.tool/tool.script.execute.link", p.atbx.name)
    entry = _link_target(p, tool, link)
    script, validator = f"{tool}.tool/tool.script.execute.py", f"{tool}.tool/tool.script.validate.py"
    registry = _registry_path(p, tool)
    return ToolSources(
        tool=tool, entry=entry,
        entry_exists=entry is not None and (p.root / entry).is_file(),
        embedded_script=script if script in names else None,
        validator=validator if validator in names else None,
        registry_path=registry,
        registry_stale=registry is not None and entry is not None and registry != entry,
    )


# --- printing -------------------------------------------------------------------------------------------

def format_rows(rows: List[ParamRow]) -> str:
    """One line per parameter: name, title, type, direction, datatype, hover, symbology, values, default."""
    lines = ["name | title | type | direction | datatype | hover | symbology | values | default"]
    for r in rows:
        lines.append(" | ".join([r.name, r.title, r.type.value, r.direction.value, r.datatype,
                                 "wired" if r.hover_wired else "-", r.symbology or "-",
                                 ", ".join(r.values) or "-", r.default if r.default is not None else "-"]))
    return "\n".join(lines)


def format_problems(problems: List[Problem]) -> str:
    """One line per problem (``code | param | detail``), or ``clean``."""
    if not problems:
        return "clean"
    return "\n".join(f"{p.code.value} | {p.param or '-'} | {p.detail}" for p in problems)
