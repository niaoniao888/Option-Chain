from __future__ import annotations

MARKET_REFRESH_SECONDS = 60.0
CACHE_POLL_SECONDS = 5.0
STALE_AFTER_SECONDS = 120.0
ACTIVE_WINDOW_SECONDS = 15.0
SCHEDULER_TICK_SECONDS = 1.0
TASK_START_INTERVAL_SECONDS = 5.0
HTTP_START_INTERVAL_SECONDS = 1.0
IDLE_CACHE_SECONDS = 30 * 60.0
MAX_IDLE_CACHE_SYMBOLS = 10
CLIENT_SEQUENCE_RETENTION_SECONDS = 30.0


def public_refresh_policy() -> dict[str, int | float]:
    return {
        "market_refresh_seconds": MARKET_REFRESH_SECONDS,
        "cache_poll_seconds": CACHE_POLL_SECONDS,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "active_window_seconds": ACTIVE_WINDOW_SECONDS,
        "scheduler_tick_seconds": SCHEDULER_TICK_SECONDS,
        "task_start_interval_seconds": TASK_START_INTERVAL_SECONDS,
        "http_start_interval_seconds": HTTP_START_INTERVAL_SECONDS,
        "idle_cache_seconds": IDLE_CACHE_SECONDS,
        "max_idle_cache_symbols": MAX_IDLE_CACHE_SYMBOLS,
        "client_sequence_retention_seconds": CLIENT_SEQUENCE_RETENTION_SECONDS,
    }

