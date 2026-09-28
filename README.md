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
```

**Or, equivalently, one command:** `make setup` does the three steps above (creates the venv,
installs dependencies, and copies `.env.example` to `.env` if `.env` doesn't already exist).
See the `Makefile` for the other shortcuts (`make test`, `make seed`, `make run`,
`make docker-up`).

**You don't strictly need to run `cp .env.example .env` yourself, either.** `run.py` and
`scripts/seed_db.py` both check for `.env` on startup and regenerate it from `.env.example`
automatically if it's missing, printing a note that they did so. This means the app cannot
fail to start over a missing `.env` — worst case, it starts with the same development
defaults that file contains. `.env.example` itself still needs to exist somewhere in the
project for that self-healing to have something to copy from; see "A note on `.env.example`"
just below for what happens if even that file goes missing.

**If `.env.example` is missing from your copy of this repository for any reason** (some tools
silently drop dotfiles during zip/upload/clone — see "A note on `.env.example`" below), create
`.env` by hand with this exact content instead:

```env
# Flask
FLASK_ENV=development

# SECRET_KEY is intentionally left unset here, not filled with a placeholder like
# "change-me-in-production". A placeholder value is still a value -- if this file were ever
# copied as-is into a real deployment, "change-me-in-production" would work silently and
# become a shared, guessable secret across every install that did the same copy-paste. With
# it unset instead: local development auto-generates a random per-run secret (with a warning
# in the logs), and production (FLASK_ENV=production) refuses to start until you set a real
# one. To generate one:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# SECRET_KEY=paste-the-generated-value-here
PORT=5000

# Database
# SQLite (default, zero-setup):
DATABASE_URL=sqlite:///epi.db
# Postgres (preferred for production):
# DATABASE_URL=postgresql+psycopg2://epi_user:epi_pass@db:5432/epi

# Scraping
# When true, adapters attempt live HTTP requests to retailer sites.
# When false, adapters serve from bundled fixtures in seed_data/fixtures/
# (useful in sandboxed/CI environments with no outbound access to retail domains,
# and to make demo runs fast and reproducible).
SCRAPE_LIVE=false

# Per-domain politeness delay (seconds) between requests to the same host
SCRAPE_MIN_DELAY_SECONDS=2.0

# HTTP client
SCRAPE_TIMEOUT_SECONDS=8
SCRAPE_MAX_RETRIES=2
SCRAPE_MAX_WORKERS=4
SCRAPE_USER_AGENT="EPI-PriceIntelligenceBot/1.0 (+https://example.com/bot; contact=bot@example.com)"

# Respect robots.txt (should always be true; kept as a switch for testing only)
RESPECT_ROBOTS_TXT=true

# EMI defaults
EMI_DEFAULT_ANNUAL_RATE=13.0
```

Then continue:

```bash
python scripts/seed_db.py         # optional: pre-populate the DB so /api/product etc. have data immediately
python run.py                     # http://localhost:5000
```

Open `http://localhost:5000`, enter a model (e.g. "iPhone 17 Pro"), and compare. No external
accounts or API keys are required — see "Live vs fixture mode" below.

### A note on `.env.example`

This file is a plain-text config template with no secrets in it (see "Production configuration
checklist" below for why it's safe to commit). It **is** present in this repository/archive. If
your copy of this project is missing it, that happened somewhere in how the project was
transferred to you (some zip tools, some drag-and-drop GitHub uploads, and some file managers
silently hide or drop dotfiles — files starting with `.` — by default), not because it was never
written. Two things are done here so that can't block you:

1. A non-hidden duplicate, `env.example.txt`, ships alongside `.env.example` with identical
   content, specifically because it can't be mistaken for a hidden file by anything.
2. The full content is inlined above, in this README, so the setup instructions are
   self-contained even if both files somehow don't make it to you.

### Docker

```bash
# SECRET_KEY is required -- docker compose will refuse to start without it (see below)
cp .env.example .env
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" >> .env

docker compose up --build
```

Runs the app against Postgres instead of SQLite. `docker-compose.yml` reuses your `.env` for
shared config, then forces `FLASK_ENV=production` and points `DATABASE_URL` at the bundled
Postgres service. It deliberately does **not** ship a default `SECRET_KEY` — the
`${SECRET_KEY:?...}` syntax in that file makes `docker compose up` fail immediately with a
clear error if you haven't set one in `.env`, rather than silently starting with a value every
clone of this repo would share.

### Tests

```bash
pytest tests/ -v
```

**48 tests** across 7 files:

| File | Covers |
|---|---|
| `test_emi.py` | Reducing-balance EMI, no-cost EMI, down payment, input validation |
| `test_pricing.py` | INR parsing (currency symbols, commas, "Rs." prefixes), discount math, effective-price stacking |
| `test_matching.py` | Cross-retailer product deduplication, positional colour/model parsing, fuzzy-key merging |
| `test_config.py` | `SECRET_KEY` enforcement in production vs development |
| `test_api.py` | Every route end-to-end against a real (temp file-based) SQLite DB, including that `results[]` carries the full embedded product object |
| `test_scrapers.py` | Network timeouts/connection errors, malformed JSON-LD, unrecognized page markup, robots.txt fetch failures |
| `test_resilience.py` | Retailer crashes, all-retailers-failing, empty results, **concurrent requests**, performance smoke test |

The integration and resilience tests exist specifically because unit tests can all pass while
the app still fails the first time it's actually run end-to-end or under real concurrent
load — both of which happened in earlier iterations of this project (see "Regressions this
version specifically guards against" near the end of this file).

## Architecture

```
app/
  models.py            Product, Listing, Offer, PriceHistory, CrawlRun (SQLAlchemy)
  config.py             env-driven settings, no hardcoded secrets
  settings_view.py        see "A gotcha worth knowing" below
  scrapers/
    base.py              shared adapter interface, JSON-LD parsing, fixture fallback
    croma.py, vijay_sales.py, reliance_digital.py
    registry.py          adapter name -> class map
  services/
    matching.py           cross-retailer product normalization/dedup
    pricing.py             INR parsing, discount + effective-price calculation
    emi.py                 reducing-balance EMI calculator
    offers.py              offer-text classification (bank/EMI/exchange/cashback)
    deal_score.py           weighted 0-100 ranking score
    orchestrator.py         ties scraping + matching + persistence + ranking together
  api/routes.py          endpoints for search, product, offers, price-history, crawl
  web/routes.py           homepage + /health
  templates/, static/      server-rendered page + vanilla JS (no build step)
seed_data/fixtures/       sample scraped snapshots per retailer
scripts/seed_db.py        populates the DB from fixtures for a quick look around
tests/                    48 tests across unit, integration, and resilience suites
```

**Data flow for a search**: `POST /api/search` fans the three retailer adapters out on a
bounded thread pool, groups the raw listings into canonical products, computes discount /
effective price / EMI / a deal score, persists everything, and returns a ranked comparison with
each listing carrying its full product details inline, plus a "best deal" recommendation.

## API reference

### `POST /api/search`

Request:
```json
{"query": "iPhone 17 Pro", "storage": "256GB", "colour": null, "budget_min": null, "budget_max": null}
```

Response (trimmed):
```json
{
  "crawl": {"crawl_id": 1, "query": "iPhone 17 Pro", "sources_attempted": 3, "sources_succeeded": 3, "status": "completed"},
  "results": [
    {
      "id": 2, "source": "vijay_sales", "selling_price": 127490.0, "effective_price": 122490.0,
      "deal_score": 82.2, "availability": "in_stock",
      "product": {"id": 1, "product_name": "Apple iPhone 17 Pro (256GB) - Deep Blue", "brand": "Apple", "storage": "256GB", "colour": "Deep Blue"},
      "offers": [{"offer_text": "example offer text", "offer_type": "bank_discount", "offer_discount": 5000.0}]
    }
  ],
  "recommendation": {"top_pick": {"product": {}, "reasons": []}},
  "partial_failures": []
}
```

Every object in `results[]` carries its full `product` inline — no separate
`/api/product/<id>` call is needed just to show a result row. See "Regressions this version
specifically guards against" below for why this is called out explicitly.

### `GET /api/product/<id>` — full product detail with all its listings and offers
### `GET /api/offers/<listing_id>?tenure_months=12&down_payment=0` — offers + EMI estimate for one listing
### `GET /api/price-history/<product_id>` — price trend over time for a product
### `GET /api/crawl/<crawl_id>` — metadata for a past search
### `GET /health` — liveness check

## Live vs fixture mode

`SCRAPE_LIVE=false` (the default) serves from `seed_data/fixtures/*.json` — realistic sample
data captured in the same shape a live scrape would produce, including offer text, so the
whole search → match → price → EMI → rank pipeline is exercised without needing outbound
network access. This is also what makes `pytest` and `scripts/seed_db.py` fast and
deterministic in CI or a sandboxed environment.

`SCRAPE_LIVE=true` makes adapters attempt a real HTTP fetch first (parsing schema.org
`Product`/`Offer` JSON-LD where present, falling back to CSS selectors), and only falls back
to fixtures if the live fetch fails or returns nothing. **This is the one area of the project
that's structurally more fragile than the rest, and worth being direct about rather than
overselling:** retailer markup changes without notice, so the CSS-selector fallback in each
adapter (`croma.py` etc.) is a best-effort path that was written without access to the real,
current DOM of these sites (see "Known limitations" below for exactly what this means). A
partner API or an official feed would be the correct answer if this needed to run unattended in
production — the scraping path is what makes this project runnable and demoable without one,
not a claim that it's production-grade against sites that can change their markup at any time.

Robots.txt is checked and honoured before every live request (`app/utils/http.py:can_fetch`),
requests are rate-limited per-domain (`SCRAPE_MIN_DELAY_SECONDS`), and a descriptive
`SCRAPE_USER_AGENT` is sent — change the contact address in `.env` before pointing this at
real sites.

## Production configuration checklist

- **`SECRET_KEY` must be set explicitly.** There is no hardcoded fallback value anywhere in
  this codebase — a checked-in default secret is itself a known, public value the moment the
  repo is public, which defeats its purpose. Behaviour if it's unset:
  - `FLASK_ENV=production`: the app **refuses to start** (`RuntimeError` at boot), not a log
    line you can miss.
  - anything else: a random secret is generated for that process only, with a `WARNING` log
    line saying so. Sessions won't survive a restart in this mode — that's expected for local
    development, not something to rely on for anything real.
  - Generate a real one with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- **Use Postgres, not SQLite, for anything with real concurrent traffic.** SQLite file-level
  locking serializes writers correctly but will surface as `database is locked` errors under
  sustained concurrent write load. `docker-compose.yml` runs Postgres by default; the app code
  is identical either way (see `DATABASE_URL` in `.env.example`).
- **Set a real `SCRAPE_USER_AGENT` contact address** before running `SCRAPE_LIVE=true` against
  real sites (see "Live vs fixture mode").
- **Don't lower `SCRAPE_MIN_DELAY_SECONDS`** below 2 seconds for live scraping.

## Design decisions worth knowing about

- **Scraped facts vs calculated values are kept separate.** `mrp`, `selling_price`,
  `offer_text` etc. on `Listing`/`Offer` are exactly what a source stated. `effective_price`,
  `deal_score`, and every EMI figure are computed and clearly documented as such.
- **Offer stacking is conservative.** Only `bank_discount` and `cashback` offers are folded
  into `effective_price`; EMI and exchange offers are surfaced separately because they depend
  on a choice the user makes (financing, trade-in device) rather than being an unconditional
  price cut (`services/offers.py:stackable_bank_discounts`).
- **Product matching is positional, not a fixed vocabulary.** Colour/model are parsed from the
  title using storage as an anchor point (whatever precedes it is the model, whatever follows
  it is the colour), which generalizes to any colour name a retailer uses, rather than matching
  against a hardcoded word list that can never be complete. See
  `services/matching.py:parse_title`.
- **Fixture search disambiguates model variants.** A query with a model number (e.g. "iPhone
  17") requires every "variant qualifier" word (`Pro`, `Max`, `Ultra`, etc.) present in a
  candidate's title to also be present in the query — otherwise "iPhone 17" would also return
  "iPhone 17 Pro" listings, which are a different product at a different price
  (`scrapers/base.py:_matches_query`).
- **`CrawlRun`'s search-text column is named `search_query`, not `query`.** Flask-SQLAlchemy
  attaches a class-level `.query` property to every model for lookups
  (`CrawlRun.query.get_or_404(...)`); naming a column `query` shadows that property entirely
  and breaks every lookup on the model. Worth remembering for any new model added later.
- **Product creation handles a real race condition, not a hypothetical one.** Two concurrent
  searches can both determine "this product doesn't exist yet" for the same brand-new
  canonical key at the same moment, then both try to insert it. The second insert is correctly
  rejected by the database's unique constraint; `orchestrator.run_search` catches that
  specific case with a `SAVEPOINT` (scoped to just that one insert, so it can't discard other
  products already written earlier in the same request) and re-reads the row the other request
  just committed, rather than failing the search. Guarded by
  `tests/test_resilience.py::test_concurrent_searches_do_not_corrupt_each_others_data`.

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

## Known limitations

Stated plainly, not to lower expectations but because a limitation you know about and can name
is very different from one you find out about in production:

- **Live scraping selectors are best-effort.** They were written to a defensive, generic
  pattern (prefer JSON-LD, fall back to CSS selectors, fall back to fixtures) without the
  ability to verify them against each retailer's actual current page markup. Treat
  `app/scrapers/*.py`'s `_parse_html` methods as a starting point to adjust against real pages,
  not a finished, verified integration. `tests/test_scrapers.py` covers how the *system*
  degrades when a selector finds nothing (falls back to fixtures, logs the failure, doesn't
  crash) — it cannot cover whether a specific selector currently matches a specific live page,
  since that depends on the retailer's markup at the moment you run it.
- **Colour parsing assumes colour sits immediately after the storage token in the title**
  (true for all three retailers' current formats, and generalizes to any colour name). A
  retailer that puts colour *before* storage, or states colour without storage appearing in the
  title at all, would need an additional case in `services/matching.py:parse_title`.
- **SQLite is fine for development and light concurrent use; Postgres is the real answer for
  production.** See "Production configuration checklist" above.

## Regressions this version specifically guards against

Each of these was found by actually running the app (not just running unit tests) and each now
has a named test that would fail if it came back:

| Issue | Guarded by |
|---|---|
| Homepage/search API 500ing (config object / missing template) | `test_api.py::test_homepage_renders`, `test_api.py::test_search_returns_results_from_fixtures` |
| `CrawlRun.query` column shadowing the ORM's query interface | `test_api.py::test_crawl_endpoint_uses_renamed_search_query_column` |
| Colour normalization dropping values not on a fixed word list | `test_matching.py::test_parse_title_extracts_colour_not_in_any_fixed_wordlist` |
| "iPhone 17" search also matching "iPhone 17 Pro" | `test_api.py::test_search_disambiguates_model_from_pro_variant` |
| Hardcoded `SECRET_KEY` fallback | `test_config.py` (all 4 tests) |
| Inconsistent API shape (`results[]` missing product detail present elsewhere) | verified directly in the API reference above; every `results[]` item now carries `product` inline |
| Race condition creating the same product from two concurrent searches | `test_resilience.py::test_concurrent_searches_do_not_corrupt_each_others_data` |
| One retailer's adapter crashing taking down the whole search | `test_resilience.py::test_partial_failure_one_adapter_crashing_does_not_fail_the_whole_search` |

## Adding a new retailer

1. Write a class in `app/scrapers/<name>.py` subclassing `BaseAdapter`, implementing
   `build_search_url` and optionally `_parse_html` as a CSS fallback.
2. Add a fixture file at `seed_data/fixtures/<name>.json` in the same shape as the existing
   three, for fixture-mode testing.
3. Register it in `app/scrapers/registry.py`.

No changes to the orchestrator, models, or API routes are needed.
