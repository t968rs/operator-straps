"""Parses gauge readings from CSV rows."""
from typing import Dict, Iterable, List

from ingest.util import clean_cell, to_float


def parse_rows(rows: Iterable[List[str]]) -> List[Dict[str, float]]:
    """Parse."""
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        out.append({"station": clean_cell(row[0]), "stage": to_float(row[1])})
    return out


def header_ok(header: List[str]) -> bool:
    """Header check."""
    return [clean_cell(cell).lower() for cell in header[:2]] == ["station", "stage"]
