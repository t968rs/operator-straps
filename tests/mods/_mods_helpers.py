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
