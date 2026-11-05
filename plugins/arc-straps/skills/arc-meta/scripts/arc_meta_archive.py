"""arc-meta: read helpers for a toolbox archive (``.atbx``, a zip) and its one rewrite-validate-swap routine.

Readers tolerate UTF-8, UTF-8 with a byte-order mark and UTF-16 members. They refuse any other encoding,
and a member that fails its CRC or does not inflate, with an ``ApiError`` naming the member and the
archive. ``rewrite`` is the only writer: the check API reads, the three apply writers call it. Imports only
the standard library and the sibling models module.
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Optional
from xml.etree import ElementTree as ET

from arc_meta_models import ApiError

__all__ = ["decode", "read_bytes", "read_text", "read_json", "rewrite"]

_JSON_MEMBERS = frozenset({"tool.content", "toolbox.content"})


def decode(raw: bytes) -> str:
    """Archive entry text: UTF-16 when it carries a UTF-16 byte-order mark, else UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def read_bytes(zf: zipfile.ZipFile, name: str, label: str) -> Optional[bytes]:
    """The raw bytes of member ``name``, None when absent; refused when it fails its CRC or does not inflate.

    ``label`` names the archive in the refusal (its file name).
    """
    if name not in zf.namelist():
        return None
    try:
        return zf.read(name)
    except (zipfile.BadZipFile, zlib.error) as exc:
        raise ApiError(f"{name} in {label} is corrupt ({exc})") from exc


def read_text(zf: zipfile.ZipFile, name: str, label: str) -> Optional[str]:
    """The text of member ``name``, None when absent; refused when corrupt or not UTF-8 or UTF-16.

    ``label`` names the archive in the refusal (its file name).
    """
    raw = read_bytes(zf, name, label)
    if raw is None:
        return None
    try:
        return decode(raw)
    except UnicodeDecodeError as exc:
        raise ApiError(f"{name} in {label} is not UTF-8 or UTF-16 text ({exc})") from exc


def read_json(zf: zipfile.ZipFile, name: str, label: str) -> Optional[dict]:
    """Member ``name`` parsed as JSON, None when absent; refused when it is not valid JSON."""
    text = read_text(zf, name, label)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiError(f"{name} in {label} is not valid JSON ({exc})") from exc


def rewrite(atbx: Path, replacements: Dict[str, bytes]) -> None:
    """Replace (or append) the members in ``replacements``, keeping a ``<atbx>.bak`` copy of the original.

    The new archive is written to ``<atbx>.tmp`` beside it, reopened, checked with ``testzip`` and each
    replaced member parsed (JSON for ``*.rc``, ``tool.content`` and ``toolbox.content``; XML for
    ``*.xml``); only then is the backup taken and the temp file swapped over ``atbx``. A failure removes
    the temp file, leaves ``atbx`` byte-identical and raises ``ApiError`` naming the member. A failure in
    writing or validation leaves an existing backup untouched; a failure on the swap itself comes after the
    backup, which then holds the unchanged archive. A locked archive (held by ArcGIS Pro, an indexer or a
    scan) is an ``ApiError`` saying so.
    """
    atbx = Path(atbx)
    tmp = atbx.with_name(atbx.name + ".tmp")
    try:
        _write_copy(atbx, tmp, replacements)
        _validate(tmp, replacements, atbx.name)
        shutil.copy2(atbx, atbx.with_name(atbx.name + ".bak"))
        os.replace(tmp, atbx)
    except PermissionError as exc:
        tmp.unlink(missing_ok=True)
        hint = "close the toolbox in ArcGIS Pro, then rerun"
        raise ApiError(f"{atbx.name} is locked: {hint} ({exc})") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _write_copy(atbx: Path, tmp: Path, replacements: Dict[str, bytes]) -> None:
    """Every member of ``atbx`` into ``tmp`` in order with its compression; absent replacements appended."""
    pending = dict(replacements)
    try:
        with zipfile.ZipFile(atbx) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                name = item.filename
                payload = replacements[name] if name in replacements else zin.read(item)
                pending.pop(name, None)
                zout.writestr(item, payload, compress_type=item.compress_type)
            for name, payload in pending.items():
                zout.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
    except zipfile.BadZipFile as exc:
        raise ApiError(f"{atbx.name} cannot be rewritten ({exc})") from exc


def _validate(tmp: Path, names: Dict[str, bytes], label: str) -> None:
    """Refuse a rewritten archive that is corrupt or whose replaced members do not parse."""
    try:
        with zipfile.ZipFile(tmp) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise ApiError(f"{bad} in the rewritten {label} is corrupt")
            for name in names:
                _parse_member(zf.read(name), name, label)
    except zipfile.BadZipFile as exc:
        raise ApiError(f"the rewritten {label} is corrupt ({exc})") from exc


def _parse_member(raw: bytes, name: str, label: str) -> None:
    """Parse one rewritten member by its name: JSON resources and definitions, XML pages."""
    base = name.rsplit("/", 1)[-1]
    try:
        if base.endswith(".rc") or base in _JSON_MEMBERS:
            json.loads(decode(raw))
        elif base.endswith(".xml"):
            ET.fromstring(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ET.ParseError) as exc:
        raise ApiError(f"{name} in the rewritten {label} does not parse ({exc})") from exc
