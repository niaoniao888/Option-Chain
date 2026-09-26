from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from options_panel.content.guide_store import GuideStore
from options_panel.runtime.snapshot import DashboardState
from options_panel.runtime.collector_supervisor import CollectorSupervisor
from options_panel.runtime.lock import ProcessLock
from options_panel.runtime.market import MarketDescriptor, SnapshotEnvelope
from options_panel.runtime.refresher import Refresher
from options_panel.providers.bitcoin_options import BinanceOptionsProvider, BitcoinOptionsProvider


@dataclass
class BitcoinModule:
    state: DashboardState
    guide: GuideStore


class BitcoinRuntime:
    descriptor = MarketDescriptor(
        market_id="bitcoin", title="比特币期权面板", provider_id="binance",
        provider_name="Binance Options", default_instrument="BTCUSDT",
        desktop_path="/bitcoin/desktop/", mobile_path="/bitcoin/mobile/",
        capabilities=("snapshot", "health", "options-guide"),
    )

    def __init__(self, state: DashboardState, guide: GuideStore, runtime_dir, *,
                 collector_enabled: bool = True, provider_id: str = "binance",
                 provider_name: str = "Binance Options", provider: BitcoinOptionsProvider | None = None,
                 refresher_factory=Refresher):
        if refresher_factory is None:
            raise ValueError("bitcoin provider requires a collector factory")
        self.descriptor = replace(type(self).descriptor, provider_id=provider_id, provider_name=provider_name)
        self.state = state
        self.guide = guide
        self.module = BitcoinModule(state, guide)
        self.runtime_dir = runtime_dir
        self.collector_enabled = collector_enabled
        self.provider_id = provider_id
        if provider is None and provider_id != "binance":
            raise ValueError(f"bitcoin provider adapter is required: {provider_id}")
        self.provider = BinanceOptionsProvider() if provider is None else provider
        self.state.bind_source(
            provider_id,
            getattr(self.provider, "snapshot_source", getattr(self.provider, "source_name", provider_name)),
        )
        self.refresher_factory = refresher_factory
        self._collector = CollectorSupervisor(
            make_thread=lambda: self.refresher_factory(self.state, provider=self.provider),
            signal_stop=lambda thread: thread.stop_event.set(),
            lock_path=self.runtime_dir / "collector.lock",
            lock_factory=lambda path: ProcessLock(path),
        )
        self.startup_error: str | None = None

    @property
    def _thread(self):
        return self._collector.thread

    @_thread.setter
    def _thread(self, value):
        self._collector.thread = value

    @property
    def _collector_lock(self):
        return self._collector.lock

    @_collector_lock.setter
    def _collector_lock(self, value):
        self._collector.lock = value

    def start(self) -> None:
        if not self.collector_enabled:
            return
        try:
            self._collector.start()
        except Exception as exc:
            self.startup_error = f"{type(exc).__name__}: {exc}"
            raise
        self.startup_error = None

    def stop(self) -> None:
        self._collector.stop()

    def health(self) -> dict[str, Any]:
        value = self.state.health()
        return {**value, "provider": self.provider_id,
                "collector_enabled": self.collector_enabled,
                "collector_running": bool(self._thread and self._thread.is_alive())}

    def snapshot_envelope(self, instrument: str | None = None) -> SnapshotEnvelope:
        payload = self.state.snapshot()
        status = payload.get("status") or {}
        return SnapshotEnvelope(
            market=self.descriptor.market_id, provider=self.provider_id,
            instrument=instrument or self.descriptor.default_instrument,
            version=payload.get("market_generation_ms"), received_at=payload.get("fetched_at"),
            calculated_at=payload.get("market_generation_ms"),
            status=status.get("status", "unknown"), payload=payload,
        )
