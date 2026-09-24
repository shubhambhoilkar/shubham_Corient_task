"""
Price normalization keeps 'scraped facts' (mrp, selling_price, discount, offer_text) separate
from "calculated values" (effective_price, EMI, deal_score) per the spec's section 9 principle:
"separate scraped offer facts from calculated values ... label calculated values as estimates".
"""
from __future__ import annotations

import re
from typing import Optional

CURRENCY_PREFIX_RE = re.compile(r"(?i)\b(rs\.?|inr)\b|₹")
NON_NUMERIC_RE = re.compile(r"[^\d.]")


def parse_inr(text: str | float | int | None) -> Optional[float]:
    """Turn "₹1,29,490", "Rs. 1,29,490.00", 129490, or None into a float, or None.

    Currency markers are stripped as whole tokens *before* removing other punctuation --
    stripping character-by-character (dropping only letters) left the "." in "Rs." behind,
    producing a string with two decimal points that float() rejects outright."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    without_currency = CURRENCY_PREFIX_RE.sub("", text)
    without_commas = without_currency.replace(",", "")
    cleaned = NON_NUMERIC_RE.sub("", without_commas).strip(".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def compute_discount(mrp: Optional[float], selling_price: Optional[float]):
    """Returns (discount_amount, discount_pct), both None if inputs are insufficient."""
    if mrp is None or selling_price is None or mrp <= 0:
        return None, None
    amount = round(mrp - selling_price, 2)
    pct = round((amount / mrp) * 100, 2) if amount > 0 else 0.0
    return amount, pct


def compute_effective_price(
    selling_price: Optional[float],
    bank_offer_discounts: list[float],
    exchange_bonus: Optional[float] = None,
) -> Optional[float]:
    """Effective price = selling price minus *stackable* bank/card discounts the source states
    as combinable, minus an optional exchange bonus if the user opted into exchange. We do not
    assume every discount on a page is combinable with every other -- callers should only pass
    discounts that the offer text/rules indicate can stack (see services/offers.py)."""
    if selling_price is None:
        return None
    total_discount = sum(d for d in bank_offer_discounts if d)
    if exchange_bonus:
        total_discount += exchange_bonus
    effective = selling_price - total_discount
    return round(max(effective, 0.0), 2)
