"""
EMI calculation (spec section 9).

Standard reducing-balance EMI:
    EMI = P * r * (1 + r)^n / ((1 + r)^n - 1)
where P = principal financed, r = monthly interest rate (annual_rate / 12 / 100), n = tenure
in months.

"No-cost EMI" means the effective annual rate is 0 (the retailer/bank absorbs the interest,
usually by loading it into the sticker price beforehand or via a subvention) -- when a source
explicitly states no-cost EMI we set rate=0 rather than guessing, and label the output as an
estimate either way, per spec's "UI should label calculated values as estimates".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EmiResult:
    principal: float
    down_payment: float
    financed_amount: float
    tenure_months: int
    annual_rate_pct: float
    monthly_emi: float
    total_repayment: float
    total_interest: float
    is_no_cost: bool

    def to_dict(self):
        return {
            "principal": self.principal,
            "down_payment": self.down_payment,
            "financed_amount": self.financed_amount,
            "tenure_months": self.tenure_months,
            "annual_rate_pct": self.annual_rate_pct,
            "monthly_emi": round(self.monthly_emi, 2),
            "total_repayment": round(self.total_repayment, 2),
            "total_interest": round(self.total_interest, 2),
            "is_no_cost_emi": self.is_no_cost,
            "note": "Estimate calculated using a standard reducing-balance formula; "
            "actual bank terms may vary.",
        }


def calculate_emi(
    price: float,
    down_payment: float = 0.0,
    tenure_months: int = 12,
    annual_rate_pct: Optional[float] = 13.0,
) -> EmiResult:
    if price < 0:
        raise ValueError("price must be >= 0")
    if down_payment < 0 or down_payment > price:
        raise ValueError("down_payment must be between 0 and price")
    if tenure_months <= 0:
        raise ValueError("tenure_months must be > 0")

    financed = round(price - down_payment, 2)
    is_no_cost = not annual_rate_pct or annual_rate_pct <= 0

    if is_no_cost:
        monthly = round(financed / tenure_months, 2) if tenure_months else financed
        total_repayment = monthly * tenure_months
        return EmiResult(
            principal=price,
            down_payment=down_payment,
            financed_amount=financed,
            tenure_months=tenure_months,
            annual_rate_pct=0.0,
            monthly_emi=monthly,
            total_repayment=total_repayment,
            total_interest=0.0,
            is_no_cost=True,
        )

    r = (annual_rate_pct / 12) / 100
    n = tenure_months
    factor = (1 + r) ** n
    monthly = financed * r * factor / (factor - 1)
    total_repayment = monthly * n
    total_interest = total_repayment - financed
    return EmiResult(
        principal=price,
        down_payment=down_payment,
        financed_amount=financed,
        tenure_months=tenure_months,
        annual_rate_pct=annual_rate_pct,
        monthly_emi=monthly,
        total_repayment=total_repayment,
        total_interest=total_interest,
        is_no_cost=False,
    )
