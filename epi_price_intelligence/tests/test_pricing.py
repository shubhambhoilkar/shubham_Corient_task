from app.services.pricing import compute_discount, compute_effective_price, parse_inr


def test_parse_inr_handles_currency_symbols_and_commas():
    assert parse_inr("₹1,29,490") == 129490.0
    assert parse_inr("Rs. 1,29,490.00") == 129490.0
    assert parse_inr(129490) == 129490.0
    assert parse_inr(None) is None
    assert parse_inr("") is None


def test_compute_discount_basic():
    amount, pct = compute_discount(mrp=134900, selling_price=129490)
    assert amount == 5410
    assert pct == round(5410 / 134900 * 100, 2)


def test_compute_discount_missing_inputs_returns_none():
    assert compute_discount(None, 1000) == (None, None)
    assert compute_discount(1000, None) == (None, None)


def test_compute_effective_price_stacks_bank_discounts():
    effective = compute_effective_price(selling_price=129490, bank_offer_discounts=[4000, 1000])
    assert effective == 124490.0


def test_compute_effective_price_never_goes_negative():
    effective = compute_effective_price(selling_price=1000, bank_offer_discounts=[5000])
    assert effective == 0.0


def test_compute_effective_price_none_selling_price():
    assert compute_effective_price(None, [1000]) is None
