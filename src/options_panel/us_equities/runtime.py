from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from options_panel.runtime.collector_supervisor import CollectorSupervisor
from options_panel.runtime.lock import ProcessLock
from options_panel.runtime.market import MarketDescriptor, SnapshotEnvelope

from .alpaca_adapter import AlpacaAdapter, AlpacaHttp, probe_credentials
from .guide_store import GuideStore
from .market_service import MarketService, adapter_configuration
from .network_diagnostics import SafeJsonlLog
from .refresh_policy import public_refresh_policy
from .watchlist_store import WatchlistStore


class UsEquitiesRuntime:
    descriptor = MarketDescriptor(
        market_id="us-equities", title="美股期权面板", provider_id="alpaca",
        provider_name="Alpaca IEX / Indicative", default_instrument=None,
        desktop_path="/us-equities/desktop/", mobile_path="/us-equities/mobile/",
        capabilities=("snapshot", "health", "watchlist", "options-guide", "leases"),
    )

    def __init__(self, data_dir: Path, *, collector_enabled: bool = True,
                 adapter: Any | None = None, provider_id: str = "alpaca",
                 provider_name: str = "Alpaca IEX / Indicative"):
        self.descriptor = replace(type(self).descriptor, provider_id=provider_id, provider_name=provider_name)
        self.data_dir = Path(data_dir)
        self.collector_enabled = collector_enabled
        self.provider_id = provider_id
        self.watchlist = WatchlistStore(self.data_dir / "watchlist.json")
        self.guide = GuideStore(self.data_dir / "options-guide.json")
        diagnostic_log = SafeJsonlLog(self.data_dir.parent / "logs")
        client_factory = lambda key, secret: AlpacaHttp(key, secret, logger=diagnostic_log)
        if adapter is None and provider_id != "alpaca":
            raise ValueError(f"us-equities provider adapter is required: {provider_id}")
        self.adapter = (AlpacaAdapter(
            client_factory=client_factory,
            probe=lambda key, secret: probe_credentials(key, secret, client_factory=client_factory),
        ) if adapter is None else adapter)
        self.market = MarketService(self.adapter)
        self._collector = CollectorSupervisor(
            make_thread=self._make_thread,
            signal_stop=lambda _thread: self.market.stop(),
            lock_path=self.data_dir.parent / "collector.lock",
            lock_factory=lambda path: ProcessLock(path),
        )
        self._startup_error: str | None = None

    def _make_thread(self) -> threading.Thread:
        self.market.prepare_start()
        return threading.Thread(target=self.market.run, name="us-equities-refresh", daemon=True)

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
            self._startup_error = type(exc).__name__
            return
        self._startup_error = None

    def stop(self) -> None:
        self._collector.stop()

    @property
    def startup_error(self) -> str | None:
        return self._startup_error

    def snapshot_envelope(self, instrument: str | None = None) -> SnapshotEnvelope:
        if not instrument:
            raise ValueError("us-equities snapshot requires an instrument")
        payload = self.market.snapshot(instrument)
        return SnapshotEnvelope(
            market=self.descriptor.market_id, provider=self.provider_id,
            instrument=instrument, version=payload.get("snapshot_version"),
            received_at=payload.get("fetched_at"),
            calculated_at=payload.get("calculated_at"),
            status=payload.get("fetch_health") or payload.get("state", "unknown"),
            payload=payload,
        )

    def health(self) -> dict[str, Any]:
        configuration = adapter_configuration(self.adapter)
        configured = configuration["configured"]
        config_error = configuration["error"]
        collector_running = bool(self._thread and self._thread.is_alive())
        if self._startup_error:
            status = "collector_error"
        elif config_error:
            status = "configuration_error"
        elif not configured:
            status = "configuration_required"
        elif not self.collector_enabled:
            status = "collector_disabled"
        elif collector_running:
            status = "healthy"
        else:
            status = "collector_stopped"
        data_health = self.market.health_summary()
        if status == "healthy" and data_health["data_status"] in {
            "failed", "degraded", "partial", "stale",
        }:
            status = "degraded"
        result: dict[str, Any] = {
            "app": "us-options-dashboard",
            "status": status,
            "source": getattr(self.adapter, "source_name", "Alpaca"),
            "configured": configured,
            "writable": False,
            "collector_enabled": self.collector_enabled,
            "collector_running": collector_running,
            "refresh_policy": public_refresh_policy(),
            **data_health,
        }
        if config_error:
            result["configuration_error"] = "数据源配置无效，请检查本机管理配置"
        if self._startup_error:
            result["collector_error"] = "行情采集器启动失败"
            result["collector_error_type"] = self._startup_error
        return result
