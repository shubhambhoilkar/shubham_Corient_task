"""
`app.config.Config` (used directly in tests/scripts) supports attribute access
(`Config.SCRAPE_LIVE`). Flask's `current_app.config` at runtime is dict-like instead
(`current_app.config["SCRAPE_LIVE"]`). Rather than making every scraper/service branch on
which one it received, this thin wrapper normalizes both into the same attribute-access
interface, so `app/scrapers/*` and `app/services/*` only ever need to write `settings.FOO`.
"""
from __future__ import annotations


class SettingsView:
    def __init__(self, config):
        # Config class -> plain object with class attributes; Flask config -> Mapping
        if isinstance(config, dict):
            self._data = dict(config)
        else:
            # use dir()/getattr rather than vars() so inherited class attributes
            # (e.g. TestConfig subclassing Config) are picked up too
            self._data = {
                name: getattr(config, name)
                for name in dir(config)
                if name.isupper() and not name.startswith("_")
            }

    def __getattr__(self, name: str):
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
