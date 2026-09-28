"""
The orchestrator is the one place that ties scraping, matching, pricing, offers, EMI and
persistence together for a single user search. It is deliberately synchronous from the
caller's point of view (`run_search` returns a finished, ranked result set) but fans the
actual retailer requests out concurrently with a bounded thread pool, and never lets one
source's failure take down the whole request (spec section 8).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.extensions import db
from app.models import CrawlRun, Listing, Offer, PriceHistory, Product
from app.scrapers.registry import get_enabled_adapters
from app.services import matching, offers as offers_svc
from app.services.deal_score import compute_deal_score
from app.services.pricing import compute_discount, compute_effective_price
from app.utils.logging import get_logger
from sqlalchemy.exc import IntegrityError

logger = get_logger("epi.orchestrator")


def run_search(settings, query: str, filters: dict, sources: list[str] | None = None) -> dict:
    crawl = CrawlRun(search_query=query, filters_json=json.dumps(filters), status="running")
    db.session.add(crawl)
    db.session.commit()

    adapters = get_enabled_adapters(settings, only=sources)
    crawl.sources_attempted = len(adapters)

    per_source_errors = []
    all_raw = []  # list of (adapter.source_name, RawListing)

    with ThreadPoolExecutor(max_workers=settings.SCRAPE_MAX_WORKERS) as pool:
        future_to_adapter = {pool.submit(adapter.search, query, filters): adapter for adapter in adapters}
        for future in as_completed(future_to_adapter):
            adapter = future_to_adapter[future]
            try:
                raw_listings = future.result()
                all_raw.extend((adapter.source_name, rl) for rl in raw_listings)
                if adapter.errors:
                    per_source_errors.append({"source": adapter.source_name, "errors": adapter.errors})
            except Exception as exc:  # noqa: BLE001 - isolate a fully-crashed adapter
                logger.exception("adapter raised unexpectedly", extra={"ctx": {"source": adapter.source_name}})
                per_source_errors.append({"source": adapter.source_name, "errors": [str(exc)]})

    sources_with_data = {source for source, _ in all_raw}
    crawl.sources_succeeded = len(sources_with_data)
    crawl.sources_failed = crawl.sources_attempted - crawl.sources_succeeded
    crawl.error_summary = json.dumps(per_source_errors) if per_source_errors else None
    crawl.status = "completed" if all_raw else "failed"
    crawl.finished_at = datetime.now(timezone.utc)
    db.session.commit()

    # Adapters finish in nondeterministic thread order; sort so the canonical Product's
    # display name (taken from the first listing seen) is stable across runs.
    all_raw.sort(key=lambda pair: pair[0])

    # --- matching: group raw listings from every source into canonical Products ---
    key_to_product: dict[str, Product] = {}
    known_keys: list[str] = []
    listing_rows: list[Listing] = []

    for source, raw in all_raw:
        identity = matching.normalize_listing_identity(raw)
        key = identity["canonical_key"]
        merge_key = key if key in key_to_product else matching.find_best_existing_key(key, known_keys)
        effective_key = merge_key or key

        product = key_to_product.get(effective_key)
        if product is None:
            product = Product.query.filter_by(canonical_key=effective_key).first()
        if product is None:
            # Race condition (caught by tests/test_resilience.py's concurrency test): two
            # concurrent searches can both reach this line for the same brand-new
            # canonical_key at the same time -- both saw "doesn't exist yet" a moment ago,
            # both now try to insert it, and the DB's unique constraint on canonical_key
            # correctly rejects the second insert. A SAVEPOINT (begin_nested) scopes the
            # rollback to just this one insert attempt, so it can't discard listings/offers
            # for *other* products already flushed earlier in this same request's loop --
            # a plain db.session.rollback() here would have wiped out this whole request's
            # progress, not just the conflicting row.
            try:
                with db.session.begin_nested():
                    product = Product(
                        canonical_key=effective_key,
                        product_name=raw.product_name,
                        brand=identity["brand"],
                        model=identity["model"],
                        storage=identity["storage"],
                        colour=identity["colour"],
                        variant_id=effective_key,
                        image_url=raw.image_url,
                    )
                    db.session.add(product)
                    db.session.flush()  # get product.id without a full commit
            except IntegrityError:
                # another concurrent request won the race and inserted this exact product
                # first -- use its row instead of failing this search
                product = Product.query.filter_by(canonical_key=effective_key).first()
                if product is None:  # pragma: no cover - would mean rollback resolved nothing
                    raise

        # Register the product in this run's lookup regardless of whether it was just
        # created, reused from earlier in this loop, or found already sitting in the DB from
        # a previous crawl (that third case was previously skipped here, which meant
        # product_by_id below silently returned None for any listing that matched a
        # pre-existing product -- exactly the kind of thing that only shows up when two
        # searches for the same model run back to back, e.g. under concurrent load).
        if effective_key not in key_to_product:
            known_keys.append(effective_key)
        key_to_product[effective_key] = product

        mrp = raw.mrp
        selling_price = raw.selling_price
        discount_amount, discount_pct = compute_discount(mrp, selling_price)

        listing = Listing(
            product_id=product.id,
            crawl_id=crawl.id,
            source=source,
            product_url=raw.product_url,
            sku=raw.sku,
            currency=raw.currency,
            mrp=mrp,
            selling_price=selling_price,
            discount_amount=discount_amount,
            discount_pct=discount_pct,
            availability=raw.availability,
            seller=raw.seller,
            rating=raw.rating,
            review_count=raw.review_count,
            scraped_at=raw.scraped_at,
        )
        db.session.add(listing)
        db.session.flush()

        offer_dicts = []
        for raw_offer in raw.offers:
            parsed = offers_svc.parse_offer_text(raw_offer.offer_text, reference_price=selling_price)
            # prefer explicit structured fields the adapter already knows over regex-derived ones
            merged = {**parsed}
            if raw_offer.offer_type:
                merged["offer_type"] = raw_offer.offer_type
            if raw_offer.bank:
                merged["bank"] = raw_offer.bank
            if raw_offer.offer_discount is not None:
                merged["offer_discount"] = raw_offer.offer_discount
            if raw_offer.emi_available:
                merged["emi_available"] = True
            if raw_offer.emi_tenure_months:
                merged["emi_tenure_months"] = raw_offer.emi_tenure_months
            if raw_offer.emi_rate_annual_pct is not None:
                merged["emi_rate_annual_pct"] = raw_offer.emi_rate_annual_pct
            offer_dicts.append(merged)

            db.session.add(
                Offer(
                    listing_id=listing.id,
                    offer_text=raw_offer.offer_text,
                    offer_type=merged["offer_type"],
                    bank=merged["bank"],
                    offer_discount=merged["offer_discount"],
                    emi_available=merged["emi_available"],
                    emi_tenure_months=merged["emi_tenure_months"],
                    emi_rate_annual_pct=merged["emi_rate_annual_pct"],
                )
            )

        stackable = offers_svc.stackable_bank_discounts(offer_dicts)
        listing.effective_price = compute_effective_price(selling_price, stackable)

        db.session.add(
            PriceHistory(
                listing_id=listing.id,
                product_id=product.id,
                selling_price=selling_price,
                effective_price=listing.effective_price,
            )
        )
        listing_rows.append(listing)

    db.session.commit()

    # --- deal score + ranking (needs the full set's min/max effective price) ---
    priced = [l for l in listing_rows if l.effective_price is not None]
    if priced:
        min_price = min(l.effective_price for l in priced)
        max_price = max(l.effective_price for l in priced)
        for listing in priced:
            listing.deal_score = compute_deal_score(
                effective_price=listing.effective_price,
                min_price=min_price,
                max_price=max_price,
                discount_pct=listing.discount_pct,
                has_offers=len(listing.offers) > 0,
                availability=listing.availability,
                source=listing.source,
            )
        db.session.commit()

    ranked = sorted(listing_rows, key=lambda l: (l.effective_price is None, l.effective_price or 0))

    product_by_id = {p.id: p for p in key_to_product.values()}
    serialized_listings = []
    for listing in ranked:
        listing_dict = listing.to_dict(include_offers=True)
        product = product_by_id.get(listing.product_id)
        # Embed the full product object on every listing, not just on the recommendation's
        # top_pick -- a consumer of results[] previously had to make a separate
        # /api/product/<id> round trip per row just to get product_name/brand/storage/colour
        # for display, even though the server already had that data in hand.
        listing_dict["product"] = product.to_dict() if product else None
        serialized_listings.append(listing_dict)

    return {
        "crawl": crawl.to_dict(),
        "listings": serialized_listings,
        "products": {p.id: p.to_dict() for p in key_to_product.values()},
        "partial_failures": per_source_errors,
    }


def build_recommendation(result: dict) -> dict | None:
    """Best current price / best effective price / lowest EMI summary for the UI."""
    listings = result["listings"]
    if not listings:
        return None

    by_listed = min(listings, key=lambda l: l["selling_price"] if l["selling_price"] is not None else float("inf"))
    by_effective = min(
        (l for l in listings if l["effective_price"] is not None),
        key=lambda l: l["effective_price"],
        default=None,
    )
    top = by_effective or by_listed

    reasons = []
    if by_effective and by_effective["id"] == top["id"]:
        reasons.append("lowest effective price after eligible offers")
    if top.get("discount_pct"):
        reasons.append(f"{top['discount_pct']}% off MRP")
    if top.get("availability") == "in_stock":
        reasons.append("currently in stock")
    if top.get("deal_score"):
        reasons.append(f"deal score {top['deal_score']}/100")

    return {
        "best_listed_price": {
            "source": by_listed["source"],
            "amount": by_listed["selling_price"],
            "listing_id": by_listed["id"],
        },
        "best_effective_price": (
            {
                "source": by_effective["source"],
                "amount": by_effective["effective_price"],
                "listing_id": by_effective["id"],
            }
            if by_effective
            else None
        ),
        "top_pick": {
            "listing_id": top["id"],
            # same nested "product" object every row in results[] already carries -- see
            # orchestrator.run_search -- so this and results[].product are never out of sync
            "product": top.get("product"),
            "reasons": reasons or ["best available match for your search"],
        },
    }
