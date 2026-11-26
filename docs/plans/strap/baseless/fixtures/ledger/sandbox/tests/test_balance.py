from ledger.balance import balance


def test_empty_ledger_is_zero():
    assert balance([]) == 0.0


def test_sales_add_up():
    assert balance([("sale", 10.0), ("sale", 2.5)]) == 12.5


def test_refund_takes_the_amount_back():
    assert balance([("sale", 10.0), ("refund", 4.0)]) == 6.0
