import os
import secrets


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # No hardcoded fallback secret. A checked-in default like "dev-secret-key" is itself a
    # known, guessable secret the moment it's public (which it is, in this repo) -- that
    # defeats the purpose of having one. If SECRET_KEY isn't set, app/__init__.py either
    # generates a random ephemeral one (development) or refuses to start (production);
    # see create_app() for that logic. Never add a literal default back here.
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///epi.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SCRAPE_LIVE = _bool("SCRAPE_LIVE", "false")
    SCRAPE_MIN_DELAY_SECONDS = float(os.getenv("SCRAPE_MIN_DELAY_SECONDS", "2.0"))
    SCRAPE_TIMEOUT_SECONDS = float(os.getenv("SCRAPE_TIMEOUT_SECONDS", "8"))
    SCRAPE_MAX_RETRIES = int(os.getenv("SCRAPE_MAX_RETRIES", "2"))
    SCRAPE_MAX_WORKERS = int(os.getenv("SCRAPE_MAX_WORKERS", "4"))
    SCRAPE_USER_AGENT = os.getenv(
        "SCRAPE_USER_AGENT",
        "EPI-PriceIntelligenceBot/1.0 (+https://example.com/bot; contact=bot@example.com)",
    )
    RESPECT_ROBOTS_TXT = _bool("RESPECT_ROBOTS_TXT", "true")

    EMI_DEFAULT_ANNUAL_RATE = float(os.getenv("EMI_DEFAULT_ANNUAL_RATE", "13.0"))

    # Resolved relative to this file's location (not the process cwd), so it's correct
    # regardless of where `python run.py` / gunicorn / pytest is invoked from. Overridable
    # via env for unusual deployment layouts. If this is ever wrong, adapters degrade to
    # "zero results" silently per-source rather than crashing -- see the startup check in
    # app/__init__.py that logs a loud warning if this path doesn't exist, so a misconfigured
    # path is caught at boot instead of showing up as a confusing empty search result.
    FIXTURES_DIR = os.getenv(
        "FIXTURES_DIR",
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "seed_data",
            "fixtures",
        ),
    )


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SCRAPE_LIVE = False
