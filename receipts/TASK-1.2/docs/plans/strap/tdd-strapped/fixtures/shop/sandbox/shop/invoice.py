"""Invoice lines: one tax amount per line."""
from __future__ import annotations

from shop.tax import tax


def invoice_line(amount: float, region: str) -> str:
    """One invoice line: the amount and its tax."""
    return f"{amount:.2f} + tax {tax(amount, region):.2f}"
