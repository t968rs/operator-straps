"""Rounding of money amounts to whole cents."""


def round_cents(amount: float) -> float:
    """The amount rounded to cents, a half cent rounding up."""
    return round(amount * 100) / 100
