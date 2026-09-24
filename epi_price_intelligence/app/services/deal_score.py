"""
Deal score (spec section 15, optional advanced feature): a single 0-100 number so results can
be ranked by more than raw price alone. Weighted, documented, and intentionally simple --
not a black box.
"""
from __future__ import annotations

SOURCE_RELIABILITY = {
    "croma": 0.95,
    "vijay_sales": 0.9,
    "reliance_digital": 0.9,
}


def compute_deal_score(
    effective_price: float,
    min_price: float,
    max_price: float,
    discount_pct: float | None,
    has_offers: bool,
    availability: str,
    source: str,
) -> float:
    """Higher is better, 0-100. Weights:
    - 55%: how close effective_price is to the cheapest option in this comparison set
    - 20%: discount_pct off MRP
    - 10%: whether any offers were found (bank/EMI/exchange)
    - 10%: in-stock availability
    - 5%: source reliability (heuristic, based on typical fulfilment consistency)
    """
    if max_price == min_price:
        price_component = 1.0
    else:
        price_component = 1 - ((effective_price - min_price) / (max_price - min_price))
    price_component = max(0.0, min(1.0, price_component))

    discount_component = min((discount_pct or 0) / 40, 1.0)  # 40%+ discount maxes this out
    offer_component = 1.0 if has_offers else 0.0
    availability_component = 1.0 if availability == "in_stock" else (0.5 if availability == "unknown" else 0.0)
    reliability_component = SOURCE_RELIABILITY.get(source, 0.8)

    score = (
        0.55 * price_component
        + 0.20 * discount_component
        + 0.10 * offer_component
        + 0.10 * availability_component
        + 0.05 * reliability_component
    )
    return round(score * 100, 1)
