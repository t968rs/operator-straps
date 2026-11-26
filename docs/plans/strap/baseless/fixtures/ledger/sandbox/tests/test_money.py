from ledger.money import round_cents


def test_whole_cents_stay():
    assert round_cents(1.25) == 1.25


def test_below_half_rounds_down():
    assert round_cents(0.124) == 0.12


def test_half_cent_rounds_up():
    assert round_cents(0.125) == 0.13
