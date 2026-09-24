"""
Every retailer adapter implements `BaseAdapter.search(query, filters) -> list[RawListing]`
and must not raise: scraping failures are caught internally and reported via `self.errors`,
so one broken source degrades the crawl instead of failing it (see orchestrator.py).

Adapters try, in order:
  1. Live HTTP fetch + parse (only if `settings.SCRAPE_LIVE` is true), preferring embedded
     schema.org JSON-LD ("Product"/"Offer") because it is far less brittle than CSS
     selectors and is what these sites use to power rich search-engine snippets.
  2. CSS-selector fallback for pages without usable JSON-LD.
  3. Bundled fixture data (seed_data/fixtures/<source>.json) when live scraping is disabled,
     blocked by robots.txt, or fails outright -- this keeps the app reproducible in
     environments with no outbound access to retail domains (see README "Live vs fixture mode").

This keeps the adapter interface identical regardless of data source, so swapping fixture
data for a live, permitted feed (or an official partner API) later is a one-line config change.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup

from app.utils.http import build_session, get
from app.utils.logging import get_logger


@dataclass
class RawOffer:
    offer_text: str
    offer_type: Optional[str] = None
    bank: Optional[str] = None
    offer_discount: Optional[float] = None
    emi_available: bool = False
    emi_tenure_months: Optional[int] = None
    emi_rate_annual_pct: Optional[float] = None


@dataclass
class RawListing:
    """Everything a source adapter can observe about one product page at scrape time."""

    source: str
    product_name: str
    brand: str
    model: str
    product_url: str
    storage: Optional[str] = None
    colour: Optional[str] = None
    sku: Optional[str] = None
    image_url: Optional[str] = None
    currency: str = "INR"
    mrp: Optional[float] = None
    selling_price: Optional[float] = None
    availability: str = "unknown"
    seller: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    offers: list[RawOffer] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseAdapter:
    source_name = "base"
    base_url = ""

    def __init__(self, settings):
        self.settings = settings
        self.logger = get_logger(f"epi.scraper.{self.source_name}")
        self.session = build_session(
            settings.SCRAPE_USER_AGENT,
            max_retries=settings.SCRAPE_MAX_RETRIES,
            timeout=settings.SCRAPE_TIMEOUT_SECONDS,
        )
        self.errors: list[str] = []

    # ---- public entrypoint -------------------------------------------------
    def search(self, query: str, filters: dict[str, Any]) -> list[RawListing]:
        if self.settings.SCRAPE_LIVE:
            try:
                listings = self._search_live(query, filters)
                if listings:
                    return listings
                self.logger.info(
                    "live scrape returned no results, falling back to fixtures",
                    extra={"ctx": {"source": self.source_name, "query": query}},
                )
            except Exception as exc:  # noqa: BLE001 - never let one adapter crash the crawl
                self.errors.append(str(exc))
                self.logger.warning(
                    "live scrape failed, falling back to fixtures",
                    extra={"ctx": {"source": self.source_name, "error": str(exc)}},
                )
        return self._search_fixture(query, filters)

    # ---- live path (override _parse_html per-source selector fallback) ----
    def _search_live(self, query: str, filters: dict[str, Any]) -> list[RawListing]:
        url = self.build_search_url(query, filters)
        resp = get(
            self.session,
            url,
            self.settings.SCRAPE_USER_AGENT,
            timeout=self.settings.SCRAPE_TIMEOUT_SECONDS,
            respect_robots=self.settings.RESPECT_ROBOTS_TXT,
            min_delay_seconds=self.settings.SCRAPE_MIN_DELAY_SECONDS,
        )
        if resp is None or resp.status_code >= 400:
            status = resp.status_code if resp is not None else "no_response"
            self.errors.append(f"fetch failed ({status}) for {url}")
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        listings = self._parse_jsonld(soup)
        if not listings:
            listings = self._parse_html(soup)
        return listings

    def build_search_url(self, query: str, filters: dict[str, Any]) -> str:  # pragma: no cover
        raise NotImplementedError

    def _parse_jsonld(self, soup: BeautifulSoup) -> list[RawListing]:
        """Generic schema.org Product/Offer JSON-LD parser, shared across sources."""
        listings: list[RawListing] = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            for node in data if isinstance(data, list) else [data]:
                if isinstance(node, dict) and node.get("@type") == "Product":
                    listing = self._listing_from_jsonld_product(node)
                    if listing:
                        listings.append(listing)
        return listings

    def _listing_from_jsonld_product(self, node: dict) -> Optional[RawListing]:
        try:
            name = node.get("name", "")
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price")
            availability_raw = (offers.get("availability") or "").lower()
            availability = (
                "in_stock"
                if "instock" in availability_raw
                else "out_of_stock" if "outofstock" in availability_raw else "unknown"
            )
            brand = node.get("brand", {})
            brand_name = brand.get("name") if isinstance(brand, dict) else brand
            agg = node.get("aggregateRating", {}) or {}
            return RawListing(
                source=self.source_name,
                product_name=name,
                brand=brand_name or self.infer_brand(name),
                model=name,
                product_url=offers.get("url") or node.get("url") or self.base_url,
                sku=node.get("sku"),
                image_url=node.get("image") if isinstance(node.get("image"), str) else None,
                selling_price=float(price) if price not in (None, "") else None,
                availability=availability,
                rating=float(agg.get("ratingValue")) if agg.get("ratingValue") else None,
                review_count=int(agg.get("reviewCount")) if agg.get("reviewCount") else None,
            )
        except (TypeError, ValueError):
            return None

    def _parse_html(self, soup: BeautifulSoup) -> list[RawListing]:  # pragma: no cover
        """Site-specific CSS-selector fallback. Overridden per adapter."""
        return []

    @staticmethod
    def infer_brand(name: str) -> str:
        known = ["Apple", "Samsung", "OnePlus", "Xiaomi", "Realme", "Vivo", "Oppo", "Google", "Nothing"]
        for b in known:
            if b.lower() in name.lower():
                return b
        return name.split(" ")[0] if name else "Unknown"

    # ---- fixture path -------------------------------------------------------
    def _search_fixture(self, query: str, filters: dict[str, Any]) -> list[RawListing]:
        path = os.path.join(self.settings.FIXTURES_DIR, f"{self.source_name}.json")
        if not os.path.exists(path):
            self.errors.append(
                f"no fixture data for source '{self.source_name}' (looked in {path})"
            )
            return []
        with open(path, "r", encoding="utf-8") as fh:
            raw_items = json.load(fh)

        results = []
        for item in raw_items:
            if not _matches_query(query, item.get("product_name", "")):
                continue
            if not self._passes_filters(item, filters):
                continue
            results.append(self._raw_listing_from_fixture(item))
        return results

    def _passes_filters(self, item: dict, filters: dict[str, Any]) -> bool:
        storage = filters.get("storage")
        colour = filters.get("colour")
        budget_min = filters.get("budget_min")
        budget_max = filters.get("budget_max")
        if storage and str(item.get("storage", "")).lower() != str(storage).lower():
            return False
        if colour and colour.lower() != "any" and str(item.get("colour", "")).lower() != colour.lower():
            return False
        price = item.get("selling_price")
        if price is not None:
            if budget_min is not None and price < budget_min:
                return False
            if budget_max is not None and price > budget_max:
                return False
        return True

    def _raw_listing_from_fixture(self, item: dict) -> RawListing:
        offers = [
            RawOffer(
                offer_text=o.get("offer_text", ""),
                offer_type=o.get("offer_type"),
                bank=o.get("bank"),
                offer_discount=o.get("offer_discount"),
                emi_available=o.get("emi_available", False),
                emi_tenure_months=o.get("emi_tenure_months"),
                emi_rate_annual_pct=o.get("emi_rate_annual_pct"),
            )
            for o in item.get("offers", [])
        ]
        return RawListing(
            source=self.source_name,
            product_name=item.get("product_name", ""),
            brand=item.get("brand", self.infer_brand(item.get("product_name", ""))),
            model=item.get("model", item.get("product_name", "")),
            storage=item.get("storage"),
            colour=item.get("colour"),
            sku=item.get("sku"),
            product_url=item.get("product_url", self.base_url),
            image_url=item.get("image_url"),
            currency=item.get("currency", "INR"),
            mrp=item.get("mrp"),
            selling_price=item.get("selling_price"),
            availability=item.get("availability", "unknown"),
            seller=item.get("seller", self.source_name),
            rating=item.get("rating"),
            review_count=item.get("review_count"),
            offers=offers,
        )


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


# Words that distinguish otherwise-identical model names into different products/prices
# (e.g. "iPhone 17" vs "iPhone 17 Pro", "Galaxy S25" vs "Galaxy S25 Ultra"). A query that
# doesn't mention one of these must not match a listing that has it, even though the
# listing's title is a superset of the query's tokens.
_VARIANT_QUALIFIERS = {
    "pro", "max", "plus", "ultra", "mini", "se", "lite", "fe", "note", "air", "edge",
}


def _matches_query(query: str, product_name: str) -> bool:
    """Fixture search matching. Two modes:

    - Query contains a model number (any token with a digit, e.g. "17", "s25"): treated as a
      specific-model search. Requires every query token to appear in the product's tokens
      AND forbids the product having a variant-qualifier token (see _VARIANT_QUALIFIERS)
      that the query didn't ask for -- this is what stops "iPhone 17" incorrectly matching
      "iPhone 17 Pro" while still letting "iPhone 17 Pro" match only that exact variant.
    - Query has no model number (e.g. just a brand or family name like "iPhone"): treated as
      a broad search, matched on any token overlap, same as before.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return True
    product_tokens = _tokenize(product_name)

    has_model_number = any(any(ch.isdigit() for ch in t) for t in query_tokens)
    if not has_model_number:
        return bool(query_tokens & product_tokens)

    if not query_tokens.issubset(product_tokens):
        return False
    extra_tokens = product_tokens - query_tokens
    if extra_tokens & _VARIANT_QUALIFIERS:
        return False
    return True
