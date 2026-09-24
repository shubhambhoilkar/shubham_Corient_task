import json
import logging
import sys
import time


class JsonFormatter(logging.Formatter):
    """Minimal structured (JSON-lines) log formatter so scrape/crawl events are greppable."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # allow callers to pass structured context via `extra={"ctx": {...}}`
        ctx = getattr(record, "ctx", None)
        if ctx:
            payload.update(ctx)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level=logging.INFO):
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. reload in debug mode)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
