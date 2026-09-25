from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_ID = "btc-options-panel"
APP_VERSION = "2.0.0"
API_ROOT = "https://eapi.binance.com"
MARKET_INTERVAL = 60.0
CATALOG_INTERVAL = 600.0
STALE_AFTER = 120.0
MAX_BACKOFF = 300.0
REQUEST_TIMEOUT = 12.0
FETCH_ATTEMPTS = 2
FETCH_RETRY_DELAY = 0.5


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_base_path(value: str) -> str:
    value = value.strip()
    if not value or value == "/":
        return ""
    return "/" + value.strip("/")


@dataclass(frozen=True)
class Settings:
    app_root: Path
    host: str = "127.0.0.1"
    port: int = 8780
    base_path: str = ""
    collector_enabled: bool = True
    bitcoin_collector_enabled: bool = True
    us_collector_enabled: bool = True
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver")
    forwarded_headers: bool = False

    @property
    def web_dir(self) -> Path:
        return self.app_root / "web"

    @property
    def content_dir(self) -> Path:
        return self.app_root / "content"

    @property
    def data_dir(self) -> Path:
        return Path(os.getenv("OPTIONS_DATA_DIR", str(self.content_dir)))

    @property
    def runtime_dir(self) -> Path:
        return Path(os.getenv("OPTIONS_RUNTIME_DIR", str(self.app_root / "runtime")))

    @property
    def us_data_dir(self) -> Path:
        return Path(os.getenv("OPTIONS_US_DATA_DIR", str(self.runtime_dir / "us-equities" / "data")))

    @property
    def log_dir(self) -> Path:
        return Path(os.getenv("OPTIONS_LOG_DIR", str(self.runtime_dir / "logs")))

    @classmethod
    def from_env(cls) -> "Settings":
        default_root = Path(__file__).resolve().parents[2]
        root = Path(os.getenv("OPTIONS_APP_ROOT", str(default_root))).resolve()
        allowed = tuple(x.strip() for x in os.getenv("OPTIONS_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if x.strip())
        return cls(
            app_root=root,
            host=os.getenv("OPTIONS_HOST", "127.0.0.1"),
            port=int(os.getenv("OPTIONS_PORT", "8780")),
            base_path=normalize_base_path(os.getenv("OPTIONS_BASE_PATH", "")),
            collector_enabled=_boolean("OPTIONS_COLLECTOR_ENABLED", True),
            bitcoin_collector_enabled=_boolean("OPTIONS_BITCOIN_COLLECTOR_ENABLED", True),
            us_collector_enabled=_boolean("OPTIONS_US_COLLECTOR_ENABLED", True),
            allowed_hosts=allowed or ("127.0.0.1", "localhost"),
            forwarded_headers=_boolean("OPTIONS_FORWARDED_HEADERS", False),
        )
