import pytest

from app.services.emi import calculate_emi


def test_standard_emi_matches_reducing_balance_formula():
    result = calculate_emi(price=100000, down_payment=0, tenure_months=12, annual_rate_pct=12.0)
    # Known value for 1,00,000 @ 12% p.a. reducing balance over 12 months ~ 8884.88
    assert result.monthly_emi == pytest.approx(8884.88, abs=0.5)
    assert result.financed_amount == 100000
    assert result.is_no_cost is False
    assert result.total_repayment > result.financed_amount


def test_no_cost_emi_has_zero_interest():
    result = calculate_emi(price=120000, down_payment=20000, tenure_months=10, annual_rate_pct=0)
    assert result.is_no_cost is True
    assert result.total_interest == 0
    assert result.monthly_emi == pytest.approx(10000.0)


def test_down_payment_reduces_financed_amount():
    result = calculate_emi(price=100000, down_payment=25000, tenure_months=6, annual_rate_pct=13.0)
    assert result.financed_amount == 75000


def test_invalid_down_payment_raises():
    with pytest.raises(ValueError):
        calculate_emi(price=100000, down_payment=150000, tenure_months=12, annual_rate_pct=12.0)


def test_invalid_tenure_raises():
    with pytest.raises(ValueError):
        calculate_emi(price=100000, down_payment=0, tenure_months=0, annual_rate_pct=12.0)
