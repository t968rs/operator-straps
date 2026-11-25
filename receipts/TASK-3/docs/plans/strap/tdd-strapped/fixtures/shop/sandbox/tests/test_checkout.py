from shop.checkout import order_total


def test_order_total_adds_us_tax() -> None:
    assert order_total([("mug", 2)], "US") == 26.75
