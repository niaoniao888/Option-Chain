from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from options_panel.runtime.refresher import ProcessLock

from .alpaca_adapter import AlpacaAdapter, AlpacaHttp, probe_credentials
from .credential_store import CredentialError, load_credentials
from .guide_store import GuideStore
from .market_service import MarketService
from .network_diagnostics import SafeJsonlLog
from .refresh_policy import public_refresh_policy
from .watchlist_store import WatchlistStore


_HELD_COLLECTOR_LOCKS: list[ProcessLock] = []


class UsEquitiesRuntime:
    def __init__(self, data_dir: Path, *, collector_enabled: bool = True, adapter: Any | None = None):
        self.data_dir = Path(data_dir)
        self.collector_enabled = collector_enabled
        self.watchlist = WatchlistStore(self.data_dir / "watchlist.json")
        self.guide = GuideStore(self.data_dir / "options-guide.json")
        diagnostic_log = SafeJsonlLog(self.data_dir.parent / "logs")
        client_factory = lambda key, secret: AlpacaHttp(key, secret, logger=diagnostic_log)
        self.adapter = adapter or AlpacaAdapter(
            client_factory=client_factory,
            probe=lambda key, secret: probe_credentials(key, secret, client_factory=client_factory),
        )
        self.market = MarketService(self.adapter)
        self._thread: threading.Thread | None = None
        self._collector_lock: ProcessLock | None = None
        self._startup_error: str | None = None

    def start(self) -> None:
        if not self.collector_enabled or self._thread is not None:
            return
        lock = ProcessLock(self.data_dir.parent / "collector.lock")
        try:
            lock.acquire()
            thread = threading.Thread(target=self.market.run, name="us-equities-refresh", daemon=True)
            thread.start()
        except Exception as exc:
            lock.release()
            self._startup_error = f"{type(exc).__name__}: {exc}"
            return
        self._collector_lock = lock
        self._thread = thread

    def stop(self) -> None:
        thread, lock = self._thread, self._collector_lock
        if thread is not None:
            self.market.stop()
            thread.join(timeout=15)
        if lock is not None:
            if thread is not None and thread.is_alive():
                _HELD_COLLECTOR_LOCKS.append(lock)
            else:
                lock.release()
        self._thread = None
        self._collector_lock = None

    def health(self) -> dict[str, Any]:
        config_error = None
        try:
            configured = load_credentials() is not None
        except CredentialError as exc:
            configured = False
            config_error = str(exc)
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
        result: dict[str, Any] = {
            "app": "us-options-dashboard",
            "status": status,
            "source": getattr(self.adapter, "source_name", "Alpaca"),
            "configured": configured,
            "collector_enabled": self.collector_enabled,
            "collector_running": collector_running,
            "refresh_policy": public_refresh_policy(),
        }
        if config_error:
            result["configuration_error"] = config_error
        if self._startup_error:
            result["collector_error"] = self._startup_error
        return result
