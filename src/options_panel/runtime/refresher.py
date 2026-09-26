from __future__ import annotations
import logging, time
from typing import Any, Callable
import threading
from options_panel.config import MARKET_INTERVAL, CATALOG_INTERVAL, MAX_BACKOFF
from options_panel.logging import LOGGER, log_event
from options_panel.providers.binance import fetch_json
from options_panel.providers.bitcoin_options import BinanceOptionsProvider, BitcoinOptionsProvider
from options_panel.runtime.snapshot import DashboardState
from options_panel.runtime.lock import ProcessLock

class Refresher(threading.Thread):
    def __init__(self, state: DashboardState, fetch: Callable[[str], Any] = fetch_json, *,
                 provider: BitcoinOptionsProvider | None = None):
        super().__init__(name="bitcoin-options-cache-refresh", daemon=True)
        self.state = state
        self.fetch = fetch
        self.provider = provider or BinanceOptionsProvider(fetch)
        self.stop_event = threading.Event()
        self.market_failures = 0
        self.catalog_failures = 0

    @staticmethod
    def backoff(interval: float, failures: int) -> float:
        if failures <= 0:
            return interval
        if failures >= 7:
            return MAX_BACKOFF
        return min(MAX_BACKOFF, max(5.0, 5.0 * (2 ** (failures - 1))))

    def refresh_catalog(self) -> bool:
        try:
            self.state.commit_catalog(self.provider.catalog())
            self.catalog_failures = 0
            return True
        except Exception as exc:  # Boundary: network and remote schema failures.
            self.catalog_failures += 1
            self.state.fail_catalog(f"合约目录刷新失败：{exc}")
            return False

    def fetch_open_interest(self, server_time_ms: int) -> dict[str, dict[str, Any]]:
        return self.provider.open_interest(self.state.active_contracts(server_time_ms), server_time_ms)

    def refresh_market(self) -> bool:
        try:
            quotes = self.provider.quotes()
            index_price = self.provider.index_price()
            active_filter_time = self.provider.server_time()
            open_interest = self.fetch_open_interest(active_filter_time)
            try:
                marks = self.provider.marks()
                mark_problems = [
                    contract["symbol"] for contract in self.state.active_contracts(active_filter_time)
                    if contract["symbol"] not in marks
                    or marks[contract["symbol"]].get("mark_iv") is None
                    or marks[contract["symbol"]].get("risk_free_interest") is None
                ]
                mark_warning = (f"行权概率参数有 {len(mark_problems)} 个活跃合约缺失或无效"
                                if mark_problems else None)
            except Exception as exc:
                marks = {}
                mark_warning = f"行权概率参数刷新失败：{exc}"
            final_server_time = self.provider.server_time()
            self.state.commit_market(quotes, index_price, final_server_time, open_interest, marks, mark_warning)
            self.market_failures = 0
            return True
        except Exception as exc:
            self.market_failures += 1
            self.state.fail_market(f"行情刷新失败：{exc}")
            return False

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                now = self.state.monotonic()
                next_catalog, next_market = self.state.refresh_deadlines()
                if now >= next_catalog:
                    previous = self.catalog_failures
                    started = time.monotonic()
                    success = self.refresh_catalog()
                    delay = self.backoff(CATALOG_INTERVAL, 0 if success else self.catalog_failures)
                    self.state.schedule_catalog(now + delay)
                    stats = self.state.refresh_log_stats()
                    log_event(
                        logging.INFO if success else logging.WARNING, "catalog_refresh_round",
                        result="success" if success else "failed",
                        duration_ms=round((time.monotonic() - started) * 1000, 1),
                        consecutive_failures=self.catalog_failures, scheduled_interval_seconds=delay,
                        recovered=success and previous > 0, contract_count=stats["contract_count"],
                        error=stats["catalog_error"],
                    )
                now = self.state.monotonic()
                _, next_market = self.state.refresh_deadlines()
                if now >= next_market:
                    previous = self.market_failures
                    started = time.monotonic()
                    success = self.refresh_market()
                    delay = self.backoff(MARKET_INTERVAL, 0 if success else self.market_failures)
                    self.state.schedule_market(now + delay)
                    stats = self.state.refresh_log_stats()
                    log_event(
                        logging.INFO if success else logging.WARNING, "market_refresh_round",
                        result="success" if success else "failed",
                        duration_ms=round((time.monotonic() - started) * 1000, 1),
                        consecutive_failures=self.market_failures, scheduled_interval_seconds=delay,
                        recovered=success and previous > 0,
                        contract_count=stats["contract_count"], quote_count=stats["quote_count"],
                        open_interest_count=stats["open_interest_count"], mark_count=stats["mark_count"],
                        error=stats["market_error"], mark_warning=stats["mark_warning"],
                    )
                next_catalog, next_market = self.state.refresh_deadlines()
                wait_for = max(0.2, min(next_catalog, next_market) - self.state.monotonic())
                self.stop_event.wait(min(wait_for, 1.0))
            except Exception as exc:
                self.state.fail_market(f"后台刷新循环异常：{type(exc).__name__}: {exc}")
                LOGGER.exception(
                    "refresh_loop_error",
                    extra={"event_name": "refresh_loop_error", "event_fields": {
                        "exception_type": type(exc).__name__, "reason": str(exc),
                    }},
                )
                self.stop_event.wait(5.0)
