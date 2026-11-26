"""Account balance from ledger entries."""
from typing import Iterable, Tuple


def balance(entries: Iterable[Tuple[str, float]]) -> float:
    """Sum of the entries: a sale adds its amount, a refund takes its amount back."""
    total = 0.0
    for kind, amount in entries:
        if kind == "sale":
            total += amount
        elif kind == "refund":
            total += amount
    return round(total, 2)
