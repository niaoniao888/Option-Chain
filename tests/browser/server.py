from __future__ import annotations
import os
import tempfile
from pathlib import Path

_temp = tempfile.TemporaryDirectory(prefix="options-panel-browser-")
root = Path(_temp.name)
os.environ.update({
    "OPTIONS_APP_ROOT": str(Path(__file__).resolve().parents[2]),
    "OPTIONS_RUNTIME_DIR": str(root / "runtime"),
    "OPTIONS_US_DATA_DIR": str(root / "us-data"),
    "OPTIONS_LOG_DIR": str(root / "logs"),
    "OPTIONS_COLLECTOR_ENABLED": "false",
})

import uvicorn

from options_panel.api import create_app
from options_panel.config import Settings
from options_panel.modules.registry import (
    APP_ASSETS,
    MarketRegistration,
    MarketRegistry,
    StaticPageConfig,
    default_registry,
)
from options_panel.runtime.market import MarketDescriptor, SnapshotEnvelope


FIXTURE = MarketDescriptor(
    market_id="fixture-market",
    title="Fixture 期权",
    provider_id="fixture-provider",
    provider_name="Fixture Provider",
    default_instrument="FIX",
    desktop_path="/fixture-market/desktop/",
    mobile_path="/fixture-market/mobile/",
)


class FixtureRuntime:
    descriptor = FIXTURE

    def start(self):
        pass

    def stop(self):
        pass

    def health(self):
        return {"status": "healthy", "provider": "fixture-provider"}

    def snapshot_envelope(self, instrument=None):
        return SnapshotEnvelope(
            "fixture-market",
            "fixture-provider",
            instrument or "FIX",
            "fixture:1",
            "2026-10-01T12:00:00Z",
            "2026-10-01T12:00:00Z",
            "healthy",
            {
                "fetched_at": "2026-10-01T12:00:00Z",
                "server_time": "2026-10-01T12:00:00Z",
                "market_generation_ms": 1790856000000,
                "index_price": 1.2,
                "next_refresh_seconds": 60,
                "status": {"status": "healthy", "age_seconds": 0},
                "contracts": [
                    {
                        "symbol": "F-1",
                        "expiry_ms": 1791028800000,
                        "side": "CALL",
                        "strike": 1.234,
                        "remaining_seconds": 172800,
                        "annualized_pct": 9,
                        "period_return_pct": 1,
                        "exercise_probability_pct": 2,
                        "probability_display_state": "normal",
                        "time_value_status": "positive",
                        "time_value": 0.1,
                        "open_interest": 1,
                    }
                ],
            },
        )


registrations = [*default_registry().registrations()]
registrations.append(
    MarketRegistration(
        FIXTURE,
        lambda _context: FixtureRuntime(),
        static_page=StaticPageConfig(
            desktop_dir="app",
            mobile_dir="app",
            desktop_assets=APP_ASSETS,
            mobile_assets=APP_ASSETS,
        ),
    )
)
app = create_app(Settings.from_env(), registry=MarketRegistry(registrations))
uvicorn.run(app, host="127.0.0.1", port=8785)
