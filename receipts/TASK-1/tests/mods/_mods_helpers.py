"""Readers for exported TypeScript literals in the mods' hook modules."""
from __future__ import annotations

import re
from typing import List, Optional


def ts_string_array(source: str, name: str) -> List[str]:
    """Quoted members of ``export const <name> = [ ... ] as const``."""
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.DOTALL)
    assert match is not None, f"{name} not found"
    return re.findall(r"'([^']*)'", match.group(1))


def ts_string(source: str, name: str) -> str:
    """The literal of ``export const <name> = '...'``."""
    match = re.search(rf"export const {name} = '([^']*)'", source)
    assert match is not None, f"{name} not found"
    return match.group(1)


def ts_optional_string(source: str, name: str) -> Optional[str]:
    """The literal of ``export const <name>[: type] = '...'`` or ``= null``."""
    match = re.search(rf"export const {name}(?::[^=]+)? = (?:'([^']*)'|(null))", source)
    assert match is not None, f"{name} not found"
    return match.group(1)


def ts_number(source: str, name: str) -> float:
    """The literal of ``export const <name>[: type] = <number>`` (``_`` digit separators allowed)."""
    pattern = rf"export const {name}(?::[^=]+)? = (-?[0-9][0-9_]*(?:\.[0-9]+)?)\s*$"
    match = re.search(pattern, source, re.MULTILINE)
    assert match is not None, f"{name} not found"
    return float(match.group(1).replace("_", ""))


def ts_boolean(source: str, name: str) -> bool:
    """The literal of ``export const <name>[: type] = true`` or ``= false``."""
    match = re.search(rf"export const {name}(?::[^=]+)? = (true|false)\s*$", source, re.MULTILINE)
    assert match is not None, f"{name} not found"
    return match.group(1) == "true"
