from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Protocol

from options_panel.providers.binance import (
    expiration_code,
    fetch_json,
    parse_catalog,
    parse_index,
    parse_marks,
    parse_open_interest,
    parse_quotes,
    parse_server_time,
)


class BitcoinOptionsProvider(Protocol):
    """Normalized BTC-options source used by the shared refresh scheduler."""

    source_name: str

    def catalog(self) -> list[dict[str, Any]]: ...
    def quotes(self) -> dict[str, dict[str, Any]]: ...
    def index_price(self) -> float: ...
    def server_time(self) -> int: ...
    def open_interest(self, contracts: list[dict[str, Any]], server_time_ms: int) -> dict[str, dict[str, Any]]: ...
    def marks(self) -> dict[str, dict[str, Any]]: ...


class BinanceOptionsProvider:
    """Binance EAPI adapter; endpoint and schema details stay outside Refresher."""

    source_name = "Binance Options"

    def __init__(self, fetch: Callable[[str], Any] = fetch_json):
        self.fetch = fetch

    def catalog(self) -> list[dict[str, Any]]:
        return parse_catalog(self.fetch("/eapi/v1/exchangeInfo"))

    def quotes(self) -> dict[str, dict[str, Any]]:
        return parse_quotes(self.fetch("/eapi/v1/ticker"))

    def index_price(self) -> float:
        return parse_index(self.fetch("/eapi/v1/index?underlying=BTCUSDT"))

    def server_time(self) -> int:
        return parse_server_time(self.fetch("/eapi/v1/time"))

    def open_interest(self, contracts: list[dict[str, Any]], server_time_ms: int) -> dict[str, dict[str, Any]]:
        expected_by_expiry: dict[str, set[str]] = {}
        for contract in contracts:
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

    def marks(self) -> dict[str, dict[str, Any]]:
        return parse_marks(self.fetch("/eapi/v1/mark"))
