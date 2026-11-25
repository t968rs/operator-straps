"""Unit prices and line totals."""
from __future__ import annotations

_PRICES = {"tea": 4.25, "mug": 12.5, "kettle": 39.99}


def unit_price(sku: str) -> float:
    """The catalog price of one unit of ``sku``."""
    return _PRICES[sku]


def line_total(sku: str, qty: int) -> float:
    """The price of ``qty`` units of ``sku``, rounded to cents."""
    return round(unit_price(sku) * qty, 2)
