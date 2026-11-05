"""arc-meta hover writer: a tool's summary and parameter descriptions into its ``tool.content.rc``.

On an ``.atbx`` script tool the tool summary and per-parameter dialog explanations are owned by the tool
definition's resource file (``<Tool>.tool/tool.content.rc``), not by importable metadata. ArcGIS Pro
re-syncs the metadata summary and tooltips from the rc, so a metadata XML import cannot durably set them.
This module edits the rc directly from the canonical per-tool XML ``<tool_dir>/<Tool>.xml``.

The rc is plain JSON keyed by the lowercased parameter name: parameter ``Output_Polygon`` maps to
``output_polygon.descr``. The rc has no ``usage`` slot; usage is metadata-only and not handled here.

A text shows in Pro only when ``tool.content`` references its key: the top-level
``"description": "$rc:description"`` for the summary, and ``params.<name>.description =
"$rc:<lowercased name>.descr"`` for a parameter. Non-empty canonical text whose reference is missing gets
the reference added to ``tool.content`` and the key to the rc. A parameter with empty canonical text
(hidden or internal) is never wired. Nothing else in ``tool.content`` changes and no key is removed.

Dry run by default: nothing is written until ``apply=True``. On apply, ``arc_meta_archive.rewrite``
validates the new archive, keeps ``<atbx>.bak`` and swaps it in. Members are written as UTF-8 without a
byte-order mark. Reopen the toolbox in ArcGIS Pro afterward so it re-syncs the displayed metadata.
"""
from __future__ import annotations

import copy
import json
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import arc_meta_canonical as canonical
from arc_meta_archive import read_json, rewrite
from arc_meta_config import RepoLike, paths
from arc_meta_models import ApiError, ApplyOutcome, Surface

__all__ = ["apply_rc", "run_rc", "missing_refs", "wire_content", "ApplyOutcome"]

SUMMARY_KEY = "description"
Changes = Dict[str, Tuple[str, str]]
Plan = Tuple[Tuple[str, ...], Tuple[str, ...]]


def _rc_entry_name(tool: str) -> str:
    """The archive path of the tool's resource file."""
    return f"{tool}.tool/tool.content.rc"


def _content_entry_name(tool: str) -> str:
    """The archive path of the tool's definition file."""
    return f"{tool}.tool/tool.content"


def missing_refs(content: dict, summary: str, descr: Dict[str, str]) -> Tuple[str, ...]:
    """The rc keys whose canonical text is non-empty but ``tool.content`` never references."""
    keys = [SUMMARY_KEY] if summary and SUMMARY_KEY not in content else []
    for name, param in content.get("params", {}).items():
        if descr.get(name.lower()) and "description" not in param:
            keys.append(f"{name.lower()}.descr")
    return tuple(keys)


def _wire_params(params: dict, wanted: set) -> dict:
    """A copy of the ``params`` object with ``description`` references added for the wanted keys."""
    out = {}
    for name, param in params.items():
        param = dict(param)
        if f"{name.lower()}.descr" in wanted:
            param["description"] = f"$rc:{name.lower()}.descr"
        out[name] = param
    return out


def wire_content(content: dict, keys: Iterable[str]) -> dict:
    """A copy of ``tool.content`` with a ``$rc:`` reference added for each key, in the original key order.

    A wired summary reference absent from ``content`` goes just before ``params`` (at the end without one).
    """
    wanted = set(keys)
    add_summary = SUMMARY_KEY in wanted and SUMMARY_KEY not in content
    out: dict = {}
    for key, value in content.items():
        if key == "params":
            if add_summary:
                out[SUMMARY_KEY] = f"$rc:{SUMMARY_KEY}"
            value = _wire_params(value, wanted)
        out[key] = value
    if add_summary and SUMMARY_KEY not in out:
        out[SUMMARY_KEY] = f"$rc:{SUMMARY_KEY}"
    return out


def _apply_to_rc(rc: dict, summary: str, descr: Dict[str, str],
                 add_keys: Iterable[str] = ()) -> Tuple[str, Changes]:
    """``(new rc JSON, changes)`` where changes maps key -> (old, new); ``rc`` is left untouched.

    Existing keys are updated; a key absent from the rc is added only when listed in ``add_keys``.
    """
    data = copy.deepcopy(rc)
    rc_map = data["map"]
    addable = set(add_keys)
    changes: Changes = {}

    def _set(key: str, new: str) -> None:
        if (key in rc_map or key in addable) and rc_map.get(key) != new:
            changes[key] = (str(rc_map.get(key) or ""), new)
            rc_map[key] = new

    if summary:
        _set(SUMMARY_KEY, summary)
    for pname, text in descr.items():
        if text:
            _set(f"{pname}.descr", text)
    return json.dumps(data, ensure_ascii=False, indent=1), changes


def _dangling(content: dict, rc_map: dict, summary: str, descr: Dict[str, str]) -> Tuple[str, ...]:
    """The rc keys ``tool.content`` already references for non-empty canonical text but the rc lacks.

    The writer leaves them out, as the source script did; the report names them.
    """
    keys = [SUMMARY_KEY] if summary and SUMMARY_KEY in content and SUMMARY_KEY not in rc_map else []
    for name, param in content.get("params", {}).items():
        key = f"{name.lower()}.descr"
        if descr.get(name.lower()) and "description" in param and key not in rc_map:
            keys.append(key)
    return tuple(keys)


def _member(zf: zipfile.ZipFile, name: str, label: str) -> dict:
    """Member ``name`` as a JSON object; refused when absent or not an object."""
    data = read_json(zf, name, label)
    if data is None:
        raise ApiError(f"{name} is missing from {label}")
    if not isinstance(data, dict):
        raise ApiError(f"{name} in {label} is not a JSON object")
    return data


def _check_params(content: dict, tool: str, label: str) -> None:
    """Refuse a ``params`` object that is not an object of objects."""
    params = content.get("params", {})
    if not isinstance(params, dict) or not all(isinstance(p, dict) for p in params.values()):
        raise ApiError(f"{_content_entry_name(tool)} in {label} has a malformed params object")


def _read_tool(tool: str, atbx: Path) -> Tuple[dict, dict]:
    """``(rc, tool.content)`` of ``tool`` in ``atbx``; refused when the rc has no ``map`` object or the
    content's ``params`` is malformed."""
    try:
        with zipfile.ZipFile(atbx) as zf:
            rc_data = _member(zf, _rc_entry_name(tool), atbx.name)
            content = _member(zf, _content_entry_name(tool), atbx.name)
    except (OSError, zipfile.BadZipFile, zlib.error) as exc:
        raise ApiError(f"{atbx.name} cannot be read ({exc})") from exc
    if not isinstance(rc_data.get("map"), dict):
        raise ApiError(f"{_rc_entry_name(tool)} in {atbx.name} has no map object")
    _check_params(content, tool, atbx.name)
    return rc_data, content


def _replacements(tool: str, atbx: Path, tool_dir: Path) -> Tuple[Dict[str, bytes], Changes, Plan]:
    """``(new member bytes, rc changes, (wired keys, dangling keys))`` for one tool."""
    summary, descr = canonical.fields(tool_dir, tool)
    rc_data, content = _read_tool(tool, atbx)
    wired = missing_refs(content, summary, descr)
    dangling = _dangling(content, rc_data["map"], summary, descr)
    new_rc, changes = _apply_to_rc(rc_data, summary, descr, wired)
    out = {_rc_entry_name(tool): new_rc.encode("utf-8")} if changes else {}
    if wired:
        text = json.dumps(wire_content(content, wired), ensure_ascii=False, indent=4) + "\n"
        out[_content_entry_name(tool)] = text.encode("utf-8")
    return out, changes, (wired, dangling)


def _report(tool: str, changes: Changes, plan: Plan) -> List[str]:
    """A readable before/after diff, the references added to ``tool.content`` and the ones left dangling."""
    wired, dangling = plan
    notes = [f"  tool.content references $rc:{key}, which the rc lacks; not added" for key in dangling]
    if not changes and not wired:
        head = f"{tool}: no changes" if dangling else f"{tool}: no changes (already matches canonical XML)"
        return [head] + notes
    lines = [f"{tool}: {len(changes)} field(s) would change", ""]
    for key, (old, new) in changes.items():
        lines += [f"  [{key}]", f"    - {old[:140]}", f"    + {new[:140]}", ""]
    lines += [f"  tool.content: add reference $rc:{key}" for key in wired]
    return lines + notes


def run_rc(tool: str, atbx: Path, tool_dir: Path, apply: bool = False) -> ApplyOutcome:
    """Dry-run (default) or apply the rc patch and reference wiring for ``tool`` in ``atbx``."""
    atbx = Path(atbx)
    replacements, changes, plan = _replacements(tool, atbx, Path(tool_dir))
    lines = _report(tool, changes, plan)
    changed = bool(replacements)
    if not apply:
        lines.append("DRY-RUN: nothing written. Re-run with apply=True to write.")
    elif changed:
        rewrite(atbx, replacements)
        backup = atbx.with_name(atbx.name + ".bak")
        lines.append(f"APPLIED. Backup at {backup.name}. Reopen the toolbox in ArcGIS Pro to re-sync.")
    return ApplyOutcome(surface=Surface.RC, tool=tool, changed=changed, applied=apply and changed,
                        lines=lines)


def apply_rc(tool: str, apply: bool = False, repo: RepoLike = None) -> ApplyOutcome:
    """``run_rc`` over the configured archive and canonical folder of ``repo`` (default: active project)."""
    p = paths(repo)
    return run_rc(tool, p.atbx, p.tool_dir, apply=apply)
