from shop.tax import tax


def test_us_rate() -> None:
    assert tax(100.0, "US") == 7.0


def test_unknown_region_pays_none() -> None:
    assert tax(100.0, "XX") == 0.0
