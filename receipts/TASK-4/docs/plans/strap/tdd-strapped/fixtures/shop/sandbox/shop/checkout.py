"""Order totals: line totals plus tax."""
from __future__ import annotations

from typing import List, Tuple

from shop.pricing import line_total
from shop.tax import tax


def order_total(lines: List[Tuple[str, int]], region: str) -> float:
    """The total of ``lines`` (sku, qty) with the region's tax added."""
    subtotal = sum(line_total(sku, qty) for sku, qty in lines)
    return round(subtotal + tax(subtotal, region), 2)
