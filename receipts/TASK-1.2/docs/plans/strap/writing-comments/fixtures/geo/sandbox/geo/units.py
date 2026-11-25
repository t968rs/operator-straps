"""Unit conversions for area values."""

SQFT_PER_M2 = 10.7639


def sqft_to_m2(sqft: float) -> float:
    return sqft * 0.0929


def m2_to_sqft(m2: float) -> float:
    return m2 * SQFT_PER_M2
