from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from options_panel.logging import log_event
from options_panel.runtime.market import MarketDescriptor


PUBLIC_HEALTH_FIELDS = {
    "app", "version", "status", "stale", "age_seconds", "provider", "source",
    "configured", "writable", "collector_enabled", "collector_running", "refresh_policy",
    "data_status", "active_symbol_count", "cache_symbol_count", "queued_symbol_count",
    "inflight_symbol_count", "failure_count", "waiting_symbol_count", "data_age_seconds",
    "contract_count",
}
PUBLIC_REFRESH_POLICY_FIELDS = {
    "market_refresh_seconds", "cache_poll_seconds", "stale_after_seconds",
    "active_window_seconds", "scheduler_tick_seconds", "task_start_interval_seconds",
    "http_start_interval_seconds", "idle_cache_seconds", "max_idle_cache_symbols",
    "max_active_symbols", "max_watchlist_symbols", "client_sequence_retention_seconds",
}


def public_health(health: Any) -> dict[str, Any]:
    """Copy only documented, scalar health data into the public status surface."""
    if not isinstance(health, dict):
        return {"status": "invalid_health"}
    result: dict[str, Any] = {}
    for key in PUBLIC_HEALTH_FIELDS:
        if key not in health:
            continue
        value = health.get(key)
        if key == "refresh_policy" and isinstance(value, dict):
            result[key] = {
                nested_key: nested_value for nested_key, nested_value in value.items()
                if nested_key in PUBLIC_REFRESH_POLICY_FIELDS
                and isinstance(nested_value, (str, int, float, bool, type(None)))
            }
        elif isinstance(value, (str, int, float, bool, type(None))):
            result[key] = value
    if not isinstance(result.get("status"), str) or not result["status"]:
        result["status"] = "unknown"
    return result


@dataclass
class RuntimeRecord:
    market_id: str
    runtime: Any | None = None
    descriptor: MarketDescriptor | None = None
    initialization_error: str | None = None
    startup_error: str | None = None
    shutdown_error: str | None = None

    def public_health(self) -> dict[str, Any]:
        if self.runtime is None:
            return {"status": "initialization_error"}
        try:
            return public_health(self.runtime.health())
        except Exception as exc:
            return {"status": "health_error", "error_type": type(exc).__name__}

    def status(self) -> dict[str, Any]:
        return {
            "market": self.market_id,
            "runtime": self.public_health(),
            "initialization_error": self.initialization_error,
            "startup_error": self.startup_error,
            "shutdown_error": self.shutdown_error,
        }


class RuntimeLifecycle:
    """Starts and stops markets independently; one failure never skips peers."""

    def __init__(self, records: dict[str, RuntimeRecord]):
        self.records = records

    def start_all(self) -> None:
        for record in self.records.values():
            if record.runtime is None:
                continue
            try:
                record.runtime.start()
                own_error = getattr(record.runtime, "startup_error", None)
                record.startup_error = "RuntimeStartError" if own_error else None
            except Exception as exc:
                record.startup_error = type(exc).__name__
                log_event(40, "market_runtime_start_failed", market=record.market_id, exception_type=type(exc).__name__)

    def stop_all(self) -> None:
        for record in reversed(tuple(self.records.values())):
            if record.runtime is None:
                continue
            try:
                record.runtime.stop()
            except Exception as exc:
                record.shutdown_error = type(exc).__name__
                log_event(40, "market_runtime_stop_failed", market=record.market_id, exception_type=type(exc).__name__)

    def status(self) -> dict[str, dict[str, Any]]:
        return {market: record.status() for market, record in self.records.items()}
