from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("options_panel")
LOGGER.addHandler(logging.NullHandler())
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        item: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
        }
        item.update(getattr(record, "event_fields", {}))
        if record.exc_info:
            item["exception_type"] = record.exc_info[0].__name__
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def configure_logging(log_dir: Path, *, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 5) -> None:
    if any(not isinstance(handler, logging.NullHandler) for handler in LOGGER.handlers):
        return
    fallback = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / "options-panel.log", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    except OSError as exc:
        handler = logging.StreamHandler()
        fallback = type(exc).__name__
    handler.setFormatter(JsonFormatter())
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if fallback:
        log_event(logging.WARNING, "logging_console_fallback", exception_type=fallback)


def log_event(level: int, event: str, **fields: Any) -> None:
    LOGGER.log(level, event, extra={"event_name": event, "event_fields": fields})
