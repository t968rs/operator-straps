"""Invoice totals for the billing service."""
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum


class TaxMode(Enum):
    AUTO = "auto"
    INCLUSIVE = "inclusive"
    EXCLUSIVE = "exclusive"


REGION_MODE = {"EU": TaxMode.INCLUSIVE, "UK": TaxMode.INCLUSIVE, "US": TaxMode.EXCLUSIVE}
CENT = Decimal("0.01")


def invoice_total(lines, region, mode=TaxMode.AUTO, rate=Decimal("0.20")):
    """Total of ``lines`` (``(quantity, unit_price)`` pairs) for ``region``, tax applied per ``mode``."""
    raise NotImplementedError
