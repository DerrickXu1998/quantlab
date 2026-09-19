"""Structured JSON logging (Constitution VI).

One JSON object per line on stderr, with stable keys plus any event-specific
fields (symbols processed, failures, timings) passed as ``extra=`` kwargs.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON line; extra fields are merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Attach the JSON handler to the root logger (idempotent)."""
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(getattr(handler, "formatter", None), JsonFormatter):
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Module logger; ensures JSON output is configured."""
    configure_logging()
    return logging.getLogger(name)
