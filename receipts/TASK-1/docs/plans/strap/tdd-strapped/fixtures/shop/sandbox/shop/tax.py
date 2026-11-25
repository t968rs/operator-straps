"""Sales tax by region."""
from __future__ import annotations

_RATES = {"US": 0.07, "EU": 0.2}


def tax(amount: float, region: str) -> float:
    """The tax on ``amount`` in ``region``, in cents precision; unknown regions pay none."""
    rate = _RATES.get(region, 0.0)
    return int(amount * rate * 100) / 100
