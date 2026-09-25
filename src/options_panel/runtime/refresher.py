from __future__ import annotations
import logging, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
import threading
from options_panel.config import MARKET_INTERVAL, CATALOG_INTERVAL, MAX_BACKOFF
from options_panel.logging import LOGGER, log_event
from options_panel.providers.binance import fetch_json, parse_catalog, parse_quotes, parse_index, parse_server_time, parse_marks, parse_open_interest, expiration_code
from options_panel.runtime.snapshot import DashboardState

class Refresher(threading.Thread):
    def __init__(self, state: DashboardState, fetch: Callable[[str], Any] = fetch_json):
        super().__init__(name="binance-cache-refresh", daemon=True)
        self.state = state
        self.fetch = fetch
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
            self.state.commit_catalog(parse_catalog(self.fetch("/eapi/v1/exchangeInfo")))
            self.catalog_failures = 0
            return True
        except Exception as exc:  # Boundary: network and remote schema failures.
            self.catalog_failures += 1
            self.state.fail_catalog(f"合约目录刷新失败：{exc}")
            return False

    def fetch_open_interest(self, server_time_ms: int) -> dict[str, dict[str, Any]]:
        expected_by_expiry: dict[str, set[str]] = {}
        for contract in self.state.active_contracts(server_time_ms):
            code = expiration_code(contract["expiry_ms"])
            expected_by_expiry.setdefault(code, set()).add(contract["symbol"])
        if not expected_by_expiry:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(expected_by_expiry)), thread_name_prefix="binance-oi") as pool:
            futures = {
                pool.submit(self.fetch, f"/eapi/v1/openInterest?underlyingAsset=BTC&expiration={code}"): code
                for code in expected_by_expiry
            }
            for future in as_completed(futures):
                code = futures[future]
                parsed = parse_open_interest(future.result(), code)
                for symbol in expected_by_expiry[code]:
                    if symbol in parsed:
                        result[symbol] = parsed[symbol]
        return result

    def refresh_market(self) -> bool:
        try:
            quotes = parse_quotes(self.fetch("/eapi/v1/ticker"))
            index_price = parse_index(self.fetch("/eapi/v1/index?underlying=BTCUSDT"))
            active_filter_time = parse_server_time(self.fetch("/eapi/v1/time"))
            open_interest = self.fetch_open_interest(active_filter_time)
            try:
                marks = parse_marks(self.fetch("/eapi/v1/mark"))
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
            final_server_time = parse_server_time(self.fetch("/eapi/v1/time"))
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



class ProcessLock:
    """Cross-platform advisory lock held by an open file descriptor."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise RuntimeError("runtime collector already active") from exc
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()
