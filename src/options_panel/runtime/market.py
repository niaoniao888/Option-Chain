from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class MarketDescriptor:
    market_id: str
    title: str
    provider_id: str
    provider_name: str
    default_instrument: str | None
    desktop_path: str
    mobile_path: str
    status: str = "available"
    capabilities: tuple[str, ...] = ("snapshot", "health")

    def public(self, base_path: str = "") -> dict[str, str]:
        return {
            "id": self.market_id,
            "title": self.title,
            "status": self.status,
            "desktop_path": base_path + self.desktop_path,
            "mobile_path": base_path + self.mobile_path,
            "provider": self.provider_name,
        }


@dataclass(frozen=True)
class SnapshotEnvelope:
    market: str
    provider: str
    instrument: str | None
    version: str | int | None
    received_at: str | int | None
    calculated_at: str | int | None
    status: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketRuntime(Protocol):
    descriptor: MarketDescriptor

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> dict[str, Any]: ...
    def snapshot_envelope(self, instrument: str | None = None) -> SnapshotEnvelope: ...


CacheKey = tuple[str, str, str]


class SnapshotResponseCache:
    """Short JSON cache isolated by market, provider and instrument."""

    def __init__(self, ttl: float = 1.0, max_entries: int = 256,
                 monotonic: Callable[[], float] = time.monotonic):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.ttl, self.max_entries, self.monotonic = ttl, max_entries, monotonic
        self._lock = threading.Lock()
        self._items: OrderedDict[CacheKey, tuple[float, bytes]] = OrderedDict()

    @staticmethod
    def key(market: str, provider: str, instrument: str | None) -> CacheKey:
        return market, provider, instrument or ""

    def body(self, key: CacheKey, snapshot: Callable[[], dict[str, Any]]) -> bytes:
        now = self.monotonic()
        with self._lock:
            cached = self._items.get(key)
            if cached is not None and now < cached[0]:
                self._items.move_to_end(key)
                return cached[1]
            for expired in tuple(item for item, value in self._items.items() if now >= value[0]):
                self._items.pop(expired, None)
            body = json.dumps(snapshot(), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self._items.pop(key, None)
            while len(self._items) >= self.max_entries:
                self._items.popitem(last=False)
            self._items[key] = (now + self.ttl, body)
            return body
