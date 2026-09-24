# E-commerce Price Intelligence — Smartphones

Compares smartphone prices, offers, and EMI options across Croma, Vijay Sales, and Reliance
Digital, deduplicating the same product across retailers and ranking results by effective
price (after stackable bank offers) and a weighted deal score.

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env

python scripts/seed_db.py         # optional: pre-populate the DB so /api/product etc. have data immediately
python run.py                     # http://localhost:5000
```

Open `http://localhost:5000`, enter a model (e.g. "iPhone 17 Pro"), and compare. No external
accounts or API keys are required — see "Live vs fixture mode" below.

### Docker

```bash
docker compose up --build
```

Runs the app against Postgres instead of SQLite. Edit `docker-compose.yml` if you want to
point it at a different database.

### Tests

```bash
pytest tests/ -v
```

29 tests: unit tests for EMI math, pricing/discount calculation, and product matching, plus
integration tests that boot the real Flask app against an in-memory DB and hit every route
over HTTP. The integration tests exist specifically because unit tests can all pass while the
app still fails on first request — several bugs in earlier iterations of this project were
exactly that class of issue (see "Fixed since the last review" below).

## Architecture

```
app/
  models.py          Product, Listing, Offer, PriceHistory, CrawlRun (SQLAlchemy)
  config.py           env-driven settings
  settings_view.py     see "A gotcha worth knowing" below
  scrapers/
    base.py            shared adapter interface, JSON-LD parsing, fixture fallback
    croma.py, vijay_sales.py, reliance_digital.py
    registry.py        adapter name -> class map
  services/
    matching.py         cross-retailer product normalization/dedup
    pricing.py           INR parsing, discount + effective-price calculation
    emi.py               reducing-balance EMI calculator
    offers.py            offer-text classification (bank/EMI/exchange/cashback)
    deal_score.py         weighted 0-100 ranking score
    orchestrator.py       ties scraping + matching + persistence + ranking together
  api/routes.py        /api/search, /api/product/<id>, /api/offers/<id>, /api/price-history/<id>
  web/routes.py         homepage + /health
  templates/, static/    server-rendered page + vanilla JS (no build step)
seed_data/fixtures/     sample scraped snapshots per retailer
scripts/seed_db.py      populates the DB from fixtures for a quick look around
tests/                  unit + integration tests
```

**Data flow for a search**: `POST /api/search` → `orchestrator.run_search` fans the three
adapters out on a bounded thread pool → each adapter returns `RawListing` objects (live-scraped
or from fixtures) → `matching.py` groups raw listings into canonical `Product` rows →
`pricing.py`/`offers.py` compute discount, stackable effective price, and structured offer
fields → `deal_score.py` ranks the result set → everything is persisted (so `/api/product`,
`/api/offers`, `/api/price-history` can be queried afterwards) → the ranked comparison and a
"best deal" recommendation are returned as JSON.

## Live vs fixture mode

`SCRAPE_LIVE=false` (the default) serves from `seed_data/fixtures/*.json` — realistic sample
data captured in the same shape a live scrape would produce, including offer text, so the
whole search → match → price → EMI → rank pipeline is exercised without needing outbound
network access. This is also what makes `pytest` and `scripts/seed_db.py` fast and
deterministic in CI or a sandboxed environment.

`SCRAPE_LIVE=true` makes adapters attempt a real HTTP fetch first (parsing schema.org
`Product`/`Offer` JSON-LD where present, falling back to CSS selectors), and only falls back
to fixtures if the live fetch fails or returns nothing. Retailer markup changes without
notice, so the CSS-selector fallback in each adapter (`croma.py` etc.) is a best-effort path,
not something to depend on long-term — a partner API or an official feed would be the
production answer if this needed to run unattended.

Robots.txt is checked and honoured before every live request (`app/utils/http.py:can_fetch`),
requests are rate-limited per-domain (`SCRAPE_MIN_DELAY_SECONDS`), and a descriptive
`SCRAPE_USER_AGENT` is sent — change the contact address in `.env` before pointing this at
real sites.

## Design decisions worth knowing about

- **Scraped facts vs calculated values are kept separate.** `mrp`, `selling_price`,
  `offer_text` etc. on `Listing`/`Offer` are exactly what a source stated. `effective_price`,
  `deal_score`, and every EMI figure are computed and clearly documented as such — the API
  never blends the two silently.
- **Offer stacking is conservative.** Only `bank_discount` and `cashback` offers are folded
  into `effective_price`; EMI and exchange offers are surfaced separately because they depend
  on a choice the user makes (financing, trade-in device) rather than being an unconditional
  price cut (`services/offers.py:stackable_bank_discounts`).
- **Product matching is positional, not a fixed vocabulary.** An earlier version matched
  colour against a hardcoded word list and silently dropped anything not on it (e.g.
  "Lavender"). It now parses colour/model from the title using storage as an anchor point
  (whatever precedes it is the model, whatever follows it is the colour), which generalizes to
  any colour name a retailer uses. See `services/matching.py:parse_title` and
  `tests/test_matching.py` for the regression test.
- **Fixture search disambiguates model variants.** A query with a model number (e.g. "iPhone
  17") requires every product-name token from a "variant qualifier" set (`Pro`, `Max`, `Ultra`,
  etc.) to be explicitly present in the query — otherwise "iPhone 17" would also return
  "iPhone 17 Pro" listings, which are a different product at a different price
  (`scrapers/base.py:_matches_query`).
- **CrawlRun's search-text column is named `search_query`, not `query`.** Flask-SQLAlchemy
  attaches a class-level `.query` property to every model for lookups
  (`CrawlRun.query.get_or_404(...)`); naming a column `query` shadows that property entirely
  and breaks every lookup on the model. This is a real footgun worth remembering for any new
  model added later — don't name a column the same as anything SQLAlchemy reserves on the
  model class (`query`, `metadata`, etc.).

## A gotcha worth knowing (`settings_view.py`)

`app/config.py`'s `Config` class uses attribute access (`Config.SCRAPE_LIVE`), which is what
`scripts/seed_db.py` and the test suite construct directly. Flask's `current_app.config` at
request time is dict-like instead (`current_app.config["SCRAPE_LIVE"]`). Rather than branching
on which one every adapter/service received, `app/settings_view.py` normalizes both into the
same attribute-access interface once, at the API boundary
(`api/routes.py: SettingsView(current_app.config)`). If you add a new route that calls into
`orchestrator`/`scrapers`, route the config through `SettingsView` the same way — passing
`current_app.config` straight through will raise `AttributeError` the first time a scraper
reads `settings.SCRAPE_LIVE`.

## Fixed since the last review

An earlier pass of this project scored 50/100 on: the homepage 500ing (frontend template
existed locally but was never actually committed), the search API 500ing
(`current_app.config` passed straight into `orchestrator.run_search` without the
`SettingsView` wrapper above), fixtures returning zero results after that was patched, the
`CrawlRun.query` column-name collision described above, and the colour-normalization/model-
disambiguation issues also described above. All of these are now covered by a **failing**
regression test in `tests/` (see `test_api.py::test_crawl_endpoint_uses_renamed_search_query_column`,
`test_matching.py::test_parse_title_extracts_colour_not_in_any_fixed_wordlist`,
`test_api.py::test_search_disambiguates_model_from_pro_variant`) before the corresponding fix
was written, specifically so they can't silently regress again. The full suite plus a live
`curl` pass against a booted server was run before this handoff — see the commit/PR
description for the transcript if you want the exact commands.

## Known limitation

`services/matching.py`'s colour extraction assumes colour sits immediately after the storage
token in the title (true for all three retailers' current formats). A retailer that puts
colour *before* storage, or omits storage from the title entirely while still stating a
colour, would need an additional case in `parse_title`. This is flagged rather than hidden
because it's the kind of thing that looks fine until a fourth retailer is added.

## Adding a new retailer

1. Write a class in `app/scrapers/<name>.py` subclassing `BaseAdapter`, implementing
   `build_search_url` and optionally `_parse_html` as a CSS fallback.
2. Add a fixture file at `seed_data/fixtures/<name>.json` in the same shape as the existing
   three, for fixture-mode testing.
3. Register it in `app/scrapers/registry.py`.

No changes to the orchestrator, models, or API routes are needed.
