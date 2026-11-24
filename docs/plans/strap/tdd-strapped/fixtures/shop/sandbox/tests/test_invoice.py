from shop.invoice import invoice_line


def test_invoice_line_shows_the_tax() -> None:
    assert invoice_line(10.0, "EU") == "10.00 + tax 2.00"
