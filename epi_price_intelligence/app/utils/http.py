"""
Shared HTTP plumbing for scraper adapters:

- A `requests.Session` configured with bounded retries + exponential backoff for
  transient failures (connection errors, 429, 5xx).
- Per-domain politeness delay so we don't hammer a single host even across
  different adapters/threads.
- A robots.txt check (`can_fetch`) that every adapter must call before requesting
  a page. Disallowed paths are skipped, not bypassed.
"""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.utils.logging import get_logger

logger = get_logger("epi.http")

_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
_robots_lock = threading.Lock()

_last_request_at: dict[str, float] = {}
_domain_lock = threading.Lock()


def build_session(user_agent: str, max_retries: int = 2, timeout: float = 8.0) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=0.75,  # 0.75s, 1.5s, 3s, ...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
    )
    session.request_timeout = timeout  # not native to requests; adapters read this explicitly
    return session


def can_fetch(url: str, user_agent: str, respect_robots: bool = True) -> bool:
    """Check robots.txt for `url`. Fails closed (disallow) only on an explicit Disallow;
    fails open (allow) if robots.txt is unreachable/absent, which is standard behaviour."""
    if not respect_robots:
        return True
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    with _robots_lock:
        rp = _robots_cache.get(origin)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(origin + "/robots.txt")
            try:
                rp.read()
            except Exception as exc:  # noqa: BLE001 - robots.txt fetch is best-effort
                logger.info(
                    "robots.txt unreachable, defaulting to allow",
                    extra={"ctx": {"origin": origin, "error": str(exc)}},
                )
                rp = None
            _robots_cache[origin] = rp
    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001
        return True


def polite_wait(domain: str, min_delay_seconds: float) -> None:
    """Block just long enough to keep >= min_delay_seconds between requests to the same domain."""
    with _domain_lock:
        last = _last_request_at.get(domain, 0.0)
        now = time.monotonic()
        wait_for = min_delay_seconds - (now - last)
        _last_request_at[domain] = max(now, last) + (max(wait_for, 0.0))
    if wait_for > 0:
        time.sleep(wait_for)


def get(
    session: requests.Session,
    url: str,
    user_agent: str,
    *,
    timeout: float = 8.0,
    respect_robots: bool = True,
    min_delay_seconds: float = 2.0,
    **kwargs,
) -> requests.Response | None:
    """Robots-aware, rate-limited GET. Returns None (never raises) on any failure so a
    single bad request can't crash a multi-source crawl."""
    domain = urlparse(url).netloc
    if not can_fetch(url, user_agent, respect_robots):
        logger.warning("blocked by robots.txt", extra={"ctx": {"url": url}})
        return None
    polite_wait(domain, min_delay_seconds)
    try:
        resp = session.get(url, timeout=timeout, **kwargs)
        return resp
    except requests.RequestException as exc:
        logger.warning("request failed", extra={"ctx": {"url": url, "error": str(exc)}})
        return None
