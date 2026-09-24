"""
Data model
==========

Product      canonical, deduplicated product/variant (e.g. "iPhone 17 Pro / 256GB / Deep Blue")
Listing      one retailer's snapshot of that product at scrape time (price, availability, seller...)
Offer        a bank/card/EMI/exchange offer attached to a Listing at scrape time
PriceHistory one row per (listing, scrape) so price trends can be charted
CrawlRun     metadata about one end-to-end search/scrape execution (for observability)

A Listing is intentionally immutable-ish: every scrape of the same retailer page creates a
*new* Listing row (with its own scraped_at/crawl_id) rather than overwriting the last one, which
is what makes PriceHistory possible without a separate write path. Product is the only table that
is updated in place, because it represents "the same real-world item" across time and sources.
"""
from datetime import datetime, timezone

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class CrawlRun(db.Model):
    __tablename__ = "crawl_runs"

    id = db.Column(db.Integer, primary_key=True)
    # IMPORTANT: never name a column `query` (or any other name Flask-SQLAlchemy/SQLAlchemy
    # reserves on the model class, e.g. `metadata`). db.Model attaches a class-level `.query`
    # property that is how every other model in this file is looked up
    # (Product.query.get_or_404(...), etc). A same-named column attribute on a subclass shadows
    # that property for that subclass, silently replacing the query interface with a plain
    # column accessor -- CrawlRun.query.get_or_404(...) then breaks. Column is named
    # `search_query` instead; the JSON API still exposes it as "query" in to_dict() below,
    # so this is purely an internal rename with no external contract change.
    search_query = db.Column(db.String(255), nullable=False)
    filters_json = db.Column(db.Text, nullable=True)  # JSON-encoded search filters
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), default="running")  # running|completed|failed
    sources_attempted = db.Column(db.Integer, default=0)
    sources_succeeded = db.Column(db.Integer, default=0)
    sources_failed = db.Column(db.Integer, default=0)
    error_summary = db.Column(db.Text, nullable=True)  # JSON list of {source, error}

    listings = db.relationship("Listing", back_populates="crawl_run")

    def to_dict(self):
        return {
            "crawl_id": self.id,
            "query": self.search_query,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "sources_attempted": self.sources_attempted,
            "sources_succeeded": self.sources_succeeded,
            "sources_failed": self.sources_failed,
            "error_summary": self.error_summary,
        }


class Product(db.Model):
    """Canonical product/variant, deduplicated across retailers."""

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    canonical_key = db.Column(db.String(255), unique=True, nullable=False, index=True)

    product_name = db.Column(db.String(255), nullable=False)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(150), nullable=False)
    storage = db.Column(db.String(50), nullable=True)
    colour = db.Column(db.String(50), nullable=True)
    variant_id = db.Column(db.String(150), nullable=True)  # brand:model:storage:colour slug
    image_url = db.Column(db.String(1000), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    listings = db.relationship(
        "Listing", back_populates="product", cascade="all, delete-orphan"
    )

    def to_dict(self, include_listings=False):
        data = {
            "id": self.id,
            "product_name": self.product_name,
            "brand": self.brand,
            "model": self.model,
            "storage": self.storage,
            "colour": self.colour,
            "variant_id": self.variant_id,
            "image_url": self.image_url,
        }
        if include_listings:
            data["listings"] = [l.to_dict(include_offers=True) for l in self.listings]
        return data


class Listing(db.Model):
    """A single retailer's snapshot of a product at one point in time."""

    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    crawl_id = db.Column(db.Integer, db.ForeignKey("crawl_runs.id"), nullable=True, index=True)

    source = db.Column(db.String(100), nullable=False)  # e.g. "croma", "vijay_sales"
    product_url = db.Column(db.String(1000), nullable=False)
    sku = db.Column(db.String(150), nullable=True)

    currency = db.Column(db.String(10), default="INR")
    mrp = db.Column(db.Float, nullable=True)
    selling_price = db.Column(db.Float, nullable=True)
    discount_amount = db.Column(db.Float, nullable=True)
    discount_pct = db.Column(db.Float, nullable=True)

    availability = db.Column(db.String(30), default="unknown")  # in_stock|out_of_stock|unknown
    seller = db.Column(db.String(150), nullable=True)
    rating = db.Column(db.Float, nullable=True)
    review_count = db.Column(db.Integer, nullable=True)

    # calculated, not scraped -- kept distinct from scraped facts per spec section 9
    effective_price = db.Column(db.Float, nullable=True)
    deal_score = db.Column(db.Float, nullable=True)

    scraped_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)

    product = db.relationship("Product", back_populates="listings")
    crawl_run = db.relationship("CrawlRun", back_populates="listings")
    offers = db.relationship("Offer", back_populates="listing", cascade="all, delete-orphan")
    price_history = db.relationship(
        "PriceHistory", back_populates="listing", cascade="all, delete-orphan"
    )

    def to_dict(self, include_offers=False):
        data = {
            "id": self.id,
            "product_id": self.product_id,
            "crawl_id": self.crawl_id,
            "source": self.source,
            "product_url": self.product_url,
            "sku": self.sku,
            "currency": self.currency,
            "mrp": self.mrp,
            "selling_price": self.selling_price,
            "discount_amount": self.discount_amount,
            "discount_pct": self.discount_pct,
            "availability": self.availability,
            "seller": self.seller,
            "rating": self.rating,
            "review_count": self.review_count,
            "effective_price": self.effective_price,
            "deal_score": self.deal_score,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
        }
        if include_offers:
            data["offers"] = [o.to_dict() for o in self.offers]
        return data


class Offer(db.Model):
    """A bank/card/EMI/exchange offer captured verbatim from a listing's source page."""

    __tablename__ = "offers"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False, index=True)

    offer_text = db.Column(db.Text, nullable=False)
    offer_type = db.Column(db.String(50), nullable=True)  # bank_discount|card_cashback|
    # exchange|no_cost_emi|low_cost_emi|coupon|other
    bank = db.Column(db.String(100), nullable=True)
    offer_discount = db.Column(db.Float, nullable=True)  # absolute INR value, if extractable

    emi_available = db.Column(db.Boolean, default=False)
    emi_tenure_months = db.Column(db.Integer, nullable=True)
    emi_rate_annual_pct = db.Column(db.Float, nullable=True)  # None/0 => no-cost EMI
    emi_monthly = db.Column(db.Float, nullable=True)

    listing = db.relationship("Listing", back_populates="offers")

    def to_dict(self):
        return {
            "id": self.id,
            "listing_id": self.listing_id,
            "offer_text": self.offer_text,
            "offer_type": self.offer_type,
            "bank": self.bank,
            "offer_discount": self.offer_discount,
            "emi_available": self.emi_available,
            "emi_tenure_months": self.emi_tenure_months,
            "emi_rate_annual_pct": self.emi_rate_annual_pct,
            "emi_monthly": self.emi_monthly,
        }


class PriceHistory(db.Model):
    __tablename__ = "price_history"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)

    selling_price = db.Column(db.Float, nullable=True)
    effective_price = db.Column(db.Float, nullable=True)
    scraped_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)

    listing = db.relationship("Listing", back_populates="price_history")

    def to_dict(self):
        return {
            "selling_price": self.selling_price,
            "effective_price": self.effective_price,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
        }
