from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import CrawlRun, Listing, PriceHistory, Product
from app.services import orchestrator
from app.services.emi import calculate_emi
from app.settings_view import SettingsView

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.post("/search")
def search():
    payload = request.get_json(silent=True) or request.form or {}
    query = (payload.get("query") or payload.get("model") or "").strip()
    if not query:
        return jsonify({"error": "query (mobile model) is required"}), 400

    filters = {
        "storage": payload.get("storage") or None,
        "colour": payload.get("colour") or None,
        "budget_min": _to_float(payload.get("budget_min")),
        "budget_max": _to_float(payload.get("budget_max")),
    }
    sources = payload.get("sources") or None  # optional list to restrict adapters

    result = orchestrator.run_search(SettingsView(current_app.config), query, filters, sources=sources)
    recommendation = orchestrator.build_recommendation(result)

    return jsonify(
        {
            "crawl": result["crawl"],
            "results": result["listings"],
            "recommendation": recommendation,
            "partial_failures": result["partial_failures"],
        }
    )


@api_bp.get("/product/<int:product_id>")
def get_product(product_id):
    product = Product.query.get_or_404(product_id)
    return jsonify(product.to_dict(include_listings=True))


@api_bp.get("/offers/<int:listing_id>")
def get_offers(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    tenure = request.args.get("tenure_months", type=int, default=12)
    down_payment = request.args.get("down_payment", type=float, default=0.0)
    annual_rate = request.args.get("annual_rate", type=float)

    base_price = listing.effective_price or listing.selling_price or 0.0
    emi_offer = next((o for o in listing.offers if o.emi_available), None)
    rate = annual_rate
    if rate is None:
        rate = (
            emi_offer.emi_rate_annual_pct
            if emi_offer and emi_offer.emi_rate_annual_pct is not None
            else current_app.config["EMI_DEFAULT_ANNUAL_RATE"]
        )

    emi = None
    try:
        emi = calculate_emi(base_price, down_payment, tenure, rate).to_dict()
    except ValueError as exc:
        emi = {"error": str(exc)}

    return jsonify(
        {
            "listing": listing.to_dict(),
            "offers": [o.to_dict() for o in listing.offers],
            "emi_estimate": emi,
        }
    )


@api_bp.get("/price-history/<int:product_id>")
def price_history(product_id):
    Product.query.get_or_404(product_id)
    rows = (
        PriceHistory.query.filter_by(product_id=product_id)
        .order_by(PriceHistory.scraped_at.asc())
        .all()
    )
    return jsonify({"product_id": product_id, "history": [r.to_dict() for r in rows]})


@api_bp.get("/crawl/<int:crawl_id>")
def get_crawl(crawl_id):
    crawl = CrawlRun.query.get_or_404(crawl_id)
    return jsonify(crawl.to_dict())


def _to_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
