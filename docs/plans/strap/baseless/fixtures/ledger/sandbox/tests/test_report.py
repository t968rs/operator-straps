from ledger.report import format_total


def test_two_decimals():
    assert format_total(12.5) == "Balance: 12.50"
