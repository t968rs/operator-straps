from shop.pricing import line_total, unit_price


def test_unit_price_reads_the_catalog() -> None:
    assert unit_price("mug") == 12.5


def test_line_total_multiplies_and_rounds() -> None:
    assert line_total("tea", 3) == 12.75
