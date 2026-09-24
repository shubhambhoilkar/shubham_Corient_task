"""
Offer classification: retailer offer text is free-form ("Flat Rs. 4,000 instant discount on
HDFC Bank Credit Cards", "No Cost EMI available on orders above Rs 3000", "Get up to Rs 12,000
off on exchange"). We classify and extract structured fields where possible, but always retain
the raw offer_text and never silently assume unrelated offers are combinable (spec section 9).
"""
from __future__ import annotations

import re
from typing import Optional

BANK_NAMES = [
    "HDFC", "ICICI", "SBI", "Axis", "Kotak", "IndusInd", "HSBC", "IDFC", "Yes Bank",
    "American Express", "Amex", "Federal Bank", "RBL", "Bank of Baroda", "Citibank",
]

AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+)", re.IGNORECASE)
PCT_RE = re.compile(r"(\d{1,2})\s*%")
TENURE_RE = re.compile(r"(\d{1,2})\s*month", re.IGNORECASE)


def classify_offer_type(text: str) -> str:
    t = text.lower()
    if "no cost emi" in t or "no-cost emi" in t or "zero cost emi" in t:
        return "no_cost_emi"
    if "emi" in t:
        return "low_cost_emi" if any(k in t for k in ("low cost", "reduced")) else "emi"
    if "exchange" in t:
        return "exchange"
    if "cashback" in t:
        return "cashback"
    if any(bank.lower() in t for bank in BANK_NAMES) or "bank" in t or "credit card" in t or "debit card" in t:
        return "bank_discount"
    if "coupon" in t or "code" in t:
        return "coupon"
    return "other"


def extract_bank(text: str) -> Optional[str]:
    for bank in BANK_NAMES:
        if bank.lower() in text.lower():
            return bank
    return None


def extract_amount(text: str, reference_price: Optional[float] = None) -> Optional[float]:
    """Pull an absolute INR value out of offer text; if only a percentage is present and a
    reference price is supplied, compute the equivalent amount."""
    amount_match = AMOUNT_RE.search(text)
    if amount_match:
        digits = amount_match.group(1).replace(",", "")
        try:
            return float(digits)
        except ValueError:
            pass
    pct_match = PCT_RE.search(text)
    if pct_match and reference_price:
        return round(reference_price * (int(pct_match.group(1)) / 100), 2)
    return None


def extract_emi_tenure(text: str) -> Optional[int]:
    match = TENURE_RE.search(text)
    return int(match.group(1)) if match else None


def parse_offer_text(text: str, reference_price: Optional[float] = None) -> dict:
    """Best-effort structured extraction from one offer's free text. Returns a dict matching
    the Offer model's scraped-fact fields (never touches emi_monthly -- that is calculated,
    not scraped, per emi.py)."""
    offer_type = classify_offer_type(text)
    is_emi = offer_type in {"emi", "no_cost_emi", "low_cost_emi"}
    return {
        "offer_type": offer_type,
        "bank": extract_bank(text),
        "offer_discount": extract_amount(text, reference_price) if not is_emi else None,
        "emi_available": is_emi,
        "emi_tenure_months": extract_emi_tenure(text) if is_emi else None,
        "emi_rate_annual_pct": 0.0 if offer_type == "no_cost_emi" else None,
    }


def stackable_bank_discounts(offer_dicts: list[dict]) -> list[float]:
    """Conservative stacking rule: only bank_discount and cashback offers are treated as
    combinable into the effective price; EMI/exchange/coupon offers are surfaced separately
    since they depend on a choice the user makes (tenure, trade-in device) rather than being
    an unconditional price reduction. This is a documented assumption, not a scraped fact."""
    return [
        o["offer_discount"]
        for o in offer_dicts
        if o.get("offer_type") in {"bank_discount", "cashback"} and o.get("offer_discount")
    ]
