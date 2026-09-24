"""
Seeds the database with a sample crawl using the bundled fixture data, so an evaluator can
inspect a populated database (and hit the read endpoints) without running a live search first.

Usage:
    python scripts/seed_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.services import orchestrator
from app.settings_view import SettingsView


SEED_QUERIES = [
    ("iPhone 17 Pro", {"storage": "256GB", "colour": None, "budget_min": None, "budget_max": None}),
    ("iPhone 17", {"storage": "256GB", "colour": None, "budget_min": None, "budget_max": None}),
]


def main():
    app = create_app()
    with app.app_context():
        settings = SettingsView(app.config)
        for query, filters in SEED_QUERIES:
            result = orchestrator.run_search(settings, query, filters)
            print(
                f"Seeded '{query}': crawl #{result['crawl']['crawl_id']}, "
                f"{len(result['listings'])} listings across "
                f"{result['crawl']['sources_succeeded']} sources"
            )


if __name__ == "__main__":
    main()
