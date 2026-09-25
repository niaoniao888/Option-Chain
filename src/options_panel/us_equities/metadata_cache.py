from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, Callable


@dataclass
class _Item:
    value: Any
    stored_at: float
    et_day: str
    fetched_at: str
    start: str | None = None
    end: str | None = None


@dataclass
class _Bucket:
    asset: _Item | None = None
    contracts: dict[tuple, _Item] = field(default_factory=dict)
    calendar: _Item | None = None


class MetadataCache:
    """Small process-local cache. Values are copied at both boundaries."""

    def __init__(self, *, monotonic: Callable[[], float], max_symbols: int = 32):
        self._clock = monotonic
        self._max_symbols = max_symbols
        self._items: OrderedDict[str, _Bucket] = OrderedDict()

    def clear(self) -> None:
        self._items.clear()

    def _bucket(self, symbol: str) -> _Bucket:
        bucket = self._items.get(symbol)
        if bucket is None:
            bucket = _Bucket()
            self._items[symbol] = bucket
            while len(self._items) > self._max_symbols:
                self._items.popitem(last=False)
        else:
            self._items.move_to_end(symbol)
        return bucket

    def _valid(self, item: _Item | None, ttl: float, et_day: str) -> bool:
        return bool(item and item.et_day == et_day and 0 <= self._clock() - item.stored_at < ttl)

    def asset(self, symbol: str, et_day: str, fetched_at: str, loader: Callable[[], Any], *, ttl: float = 86400) -> tuple[dict, str]:
        bucket = self._bucket(symbol)
        if self._valid(bucket.asset, ttl, et_day):
            return deepcopy(bucket.asset.value), bucket.asset.fetched_at
        value = loader()
        if not isinstance(value, dict) or not value:
            raise ValueError("asset metadata is empty or malformed")
        item = _Item(deepcopy(value), self._clock(), et_day, fetched_at)
        bucket.asset = item
        return deepcopy(value), fetched_at

    def contracts(self, symbol: str, query: tuple, et_day: str, fetched_at: str,
                  loader: Callable[[], Any], *, force: bool = False, ttl: float = 300) -> tuple[list[dict], str]:
        bucket = self._bucket(symbol)
        item = bucket.contracts.get(query)
        if not force and self._valid(item, ttl, et_day):
            return deepcopy(item.value), item.fetched_at
        value = loader()
        if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
            raise ValueError("contract metadata is empty or malformed")
        replacement = _Item(deepcopy(value), self._clock(), et_day, fetched_at)
        # This adapter has one complete-chain query per symbol. Replacing the
        # mapping prevents the daily expiration lower bound from accumulating
        # obsolete query keys forever. A failed loader never reaches this line.
        bucket.contracts = {query: replacement}
        return deepcopy(value), fetched_at

    def calendar(self, symbol: str, start: str, end: str, et_day: str, fetched_at: str,
                 loader: Callable[[], Any], *, ttl: float = 21600) -> tuple[list[dict], str]:
        bucket = self._bucket(symbol)
        item = bucket.calendar
        covers = bool(item and item.start and item.end and item.start <= start and item.end >= end)
        if covers and self._valid(item, ttl, et_day):
            return deepcopy(item.value), item.fetched_at
        value = loader()
        if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
            raise ValueError("calendar metadata is empty or malformed")
        seen_dates: set[str] = set()
        for row in value:
            day, opened, closed = row.get("date"), row.get("open"), row.get("close")
            if not all(isinstance(item, str) for item in (day, opened, closed)):
                raise ValueError("calendar metadata is empty or malformed")
            try:
                parsed_day = date.fromisoformat(day)
                parsed_open = time.fromisoformat(opened)
                parsed_close = time.fromisoformat(closed)
            except ValueError:
                raise ValueError("calendar metadata is empty or malformed") from None
            if (parsed_day.isoformat() != day or parsed_open.tzinfo is not None or parsed_close.tzinfo is not None
                    or parsed_open >= parsed_close or day in seen_dates):
                raise ValueError("calendar metadata is empty or malformed")
            seen_dates.add(day)
        replacement = _Item(deepcopy(value), self._clock(), et_day, fetched_at, start, end)
        bucket.calendar = replacement
        return deepcopy(value), fetched_at

    @property
    def symbol_count(self) -> int:
        return len(self._items)

