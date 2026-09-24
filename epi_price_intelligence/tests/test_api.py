"""
These hit the actual Flask app + real SQLite-in-memory DB + fixture data, the same way a
browser or curl would. Unit tests can all pass while the app still 500s on first request if
a route wires things together wrong (wrong config object type, a shadowed ORM attribute,
etc) -- these tests exist specifically to catch that class of bug before a person does.
"""
import json


def test_homepage_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Price Intelligence" in resp.data


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_search_requires_query(client):
    resp = client.post("/api/search", json={})
    assert resp.status_code == 400


def test_search_returns_results_from_fixtures(client):
    resp = client.post("/api/search", json={"query": "iPhone 17 Pro", "storage": "256GB"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["crawl"]["query"] == "iPhone 17 Pro"
    assert data["crawl"]["sources_attempted"] == 3
    assert data["crawl"]["sources_succeeded"] == 3

    # all three retailers carry this exact variant in fixtures -- must not come back empty
    assert len(data["results"]) == 3
    sources = {r["source"] for r in data["results"]}
    assert sources == {"croma", "vijay_sales", "reliance_digital"}

    assert data["recommendation"] is not None
    assert data["recommendation"]["best_effective_price"]["amount"] > 0


def test_search_disambiguates_model_from_pro_variant(client):
    """Regression test: 'iPhone 17' must not also return 'iPhone 17 Pro' listings."""
    resp = client.post("/api/search", json={"query": "iPhone 17", "storage": "256GB"})
    assert resp.status_code == 200
    data = resp.get_json()
    for r in data["results"]:
        product = json.loads(json.dumps(r))  # already plain dict; keeps this test self-contained
        assert "pro" not in _product_name_for(client, product["product_id"]).lower()


def test_search_pro_query_only_returns_pro_variant(client):
    resp = client.post("/api/search", json={"query": "iPhone 17 Pro", "storage": "256GB"})
    data = resp.get_json()
    assert len(data["results"]) == 3
    for r in data["results"]:
        assert "pro" in _product_name_for(client, r["product_id"]).lower()


def test_product_detail_endpoint(client):
    search_resp = client.post("/api/search", json={"query": "iPhone 17 Pro", "storage": "256GB"})
    product_id = search_resp.get_json()["results"][0]["product_id"]

    resp = client.get(f"/api/product/{product_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == product_id
    assert len(data["listings"]) >= 1


def test_offers_endpoint_returns_emi_estimate(client):
    search_resp = client.post("/api/search", json={"query": "iPhone 17 Pro", "storage": "256GB"})
    listing_id = search_resp.get_json()["results"][0]["id"]

    resp = client.get(f"/api/offers/{listing_id}?tenure_months=12&down_payment=0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "monthly_emi" in data["emi_estimate"]
    assert data["emi_estimate"]["monthly_emi"] > 0


def test_price_history_endpoint(client):
    search_resp = client.post("/api/search", json={"query": "iPhone 17 Pro", "storage": "256GB"})
    product_id = search_resp.get_json()["results"][0]["product_id"]

    resp = client.get(f"/api/price-history/{product_id}")
    assert resp.status_code == 200
    assert len(resp.get_json()["history"]) >= 1


def test_crawl_endpoint_uses_renamed_search_query_column(client):
    """Regression test: CrawlRun previously had a column literally named `query`, which
    shadows Flask-SQLAlchemy's `Model.query` class attribute and breaks
    `CrawlRun.query.get_or_404(...)` outright. This must keep working."""
    search_resp = client.post("/api/search", json={"query": "iPhone 17 Pro", "storage": "256GB"})
    crawl_id = search_resp.get_json()["crawl"]["crawl_id"]

    resp = client.get(f"/api/crawl/{crawl_id}")
    assert resp.status_code == 200
    assert resp.get_json()["query"] == "iPhone 17 Pro"


def _product_name_for(client, product_id) -> str:
    return client.get(f"/api/product/{product_id}").get_json()["product_name"]
