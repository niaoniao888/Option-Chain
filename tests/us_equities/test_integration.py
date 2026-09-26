from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from options_panel.api import create_app
from options_panel.config import Settings
from options_panel.logging import LOGGER
from options_panel.runtime.snapshot import DashboardState
from options_panel.us_equities.admin import create_admin_app
from options_panel.us_equities.credential_store import CredentialError, load_credentials
from options_panel.us_equities.guide_store import DEFAULT_SECTIONS
from options_panel.us_equities.watchlist_store import WatchlistStore


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in ("web/hub", "web/app/core", "web/app/components", "web/app/markets", "web/shared", "web/us-equities", "content"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        (self.root / "web/hub/index.html").write_text("<html></html>", encoding="utf-8")
        for name in (
            "index.html", "main.js", "styles.css", "core/formats.js", "core/model.js",
            "core/polling.js", "core/state.js", "components/dashboard.js", "components/menu.js",
            "markets/bitcoin.js", "markets/registry.js", "markets/us-equities.js",
        ):
            (self.root / "web/app" / name).write_text("fixture", encoding="utf-8")
        for name in ("admin.html", "admin.js", "admin.css"):
            (self.root / "web/us-equities" / name).write_text("fixture", encoding="utf-8")
        (self.root / "content/options-guide.json").write_text(
            json.dumps({"revision": "r1", "updated_at": "2026-09-26T00:00:00Z", "sections": []}),
            encoding="utf-8",
        )
        self.data_dir = self.root / "runtime/us-equities/data"
        self.env = mock.patch.dict(os.environ, {
            "OPTIONS_DATA_DIR": str(self.root / "content"),
            "OPTIONS_US_DATA_DIR": str(self.data_dir),
            "ALPACA_API_KEY": "test-key",
            "ALPACA_API_SECRET": "test-secret",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.close_log_handlers)

    @staticmethod
    def close_log_handlers():
        for handler in list(LOGGER.handlers):
            handler.close()
            LOGGER.removeHandler(handler)

    def settings(self, base_path: str = "") -> Settings:
        return Settings(self.root, base_path=base_path, collector_enabled=False)

    def test_public_routes_validation_read_only_and_prefix(self):
        with TestClient(create_app(self.settings(), DashboardState())) as client:
            self.assertEqual(client.get("/us-equities/desktop", follow_redirects=False).headers["location"], "/us-equities/desktop/")
            self.assertEqual(client.get("/us-equities/desktop/").status_code, 200)
            self.assertEqual(client.get("/us-equities/mobile/").status_code, 200)
            self.assertEqual(client.get("/us-equities/desktop/main.js").status_code, 200)
            self.assertEqual(client.get("/us-equities/mobile/core/state.js").status_code, 200)
            self.assertEqual(client.get("/us-equities/desktop/secret.txt").status_code, 404)
            modules = client.get("/api/v1/modules").json()
            self.assertEqual([module["id"] for module in modules], ["bitcoin", "us-equities"])
            self.assertEqual(client.post("/api/v1/us-equities/watchlist", json={}).status_code, 405)
            self.assertEqual(client.get("/api/v1/us-equities/snapshot").status_code, 400)
            self.assertEqual(client.get("/api/v1/us-equities/snapshot?symbol=SPCX&active=1").status_code, 400)
            snapshot = client.get("/api/v1/us-equities/snapshot?symbol=SPCX&client_id=c1&active=1&activity_seq=1")
            self.assertEqual(snapshot.status_code, 200)
            self.assertEqual(snapshot.json()["state"], "loading")
            self.assertEqual(client.get("/api/v1/bitcoin/health").status_code, 200)

        with TestClient(create_app(self.settings("/panel"), DashboardState())) as client:
            self.assertEqual(client.get("/panel/us-equities/mobile/").status_code, 200)
            self.assertEqual(client.get("/panel/us-equities/mobile/styles.css").status_code, 200)
            self.assertEqual(client.get("/panel/api/v1/us-equities/watchlist").status_code, 200)
            us_module = client.get("/panel/api/v1/modules").json()[1]
            self.assertEqual(us_module["desktop_path"], "/panel/us-equities/desktop/")

    def test_client_capacity_returns_retryable_status(self):
        with TestClient(create_app(self.settings(), DashboardState())) as client:
            with mock.patch("options_panel.us_equities.market_service.MAX_TRACKED_CLIENTS", 1):
                first = client.get("/api/v1/us-equities/snapshot?symbol=SPCX&client_id=one&activity_seq=1")
                self.assertEqual(first.status_code, 200)
                full = client.get("/api/v1/us-equities/snapshot?symbol=SPCX&client_id=two&activity_seq=1")
                self.assertEqual(full.status_code, 429)
                self.assertEqual(full.headers["Retry-After"], "15")
                self.assertEqual(client.get("/api/v1/bitcoin/health").status_code, 200)

    def test_bad_us_data_isolated_from_bitcoin(self):
        self.data_dir.mkdir(parents=True)
        (self.data_dir / "watchlist.json").write_text("{bad", encoding="utf-8")
        with TestClient(create_app(self.settings(), DashboardState())) as client:
            self.assertEqual(client.get("/api/v1/us-equities/watchlist").status_code, 503)
            self.assertEqual(client.get("/api/v1/us-equities/snapshot?symbol=SPCX").status_code, 503)
            self.assertEqual(client.get("/api/v1/bitcoin/health").status_code, 200)
            self.assertEqual(client.get("/healthz").status_code, 200)

    def test_environment_credentials_are_atomic_and_take_precedence(self):
        with mock.patch("options_panel.us_equities.credential_store._crypt", side_effect=AssertionError("DPAPI read")):
            self.assertEqual(load_credentials(), ("test-key", "test-secret"))
        with mock.patch.dict(os.environ, {"ALPACA_API_KEY": "only", "ALPACA_API_SECRET": ""}, clear=False):
            with self.assertRaises(CredentialError):
                load_credentials()
        with mock.patch.dict(os.environ, {"OPTIONS_COLLECTOR_ENABLED": "false", "OPTIONS_BITCOIN_COLLECTOR_ENABLED": "false", "OPTIONS_US_COLLECTOR_ENABLED": "true"}, clear=False):
            settings = Settings.from_env()
            self.assertFalse(settings.collector_enabled)
            self.assertFalse(settings.bitcoin_collector_enabled)
            self.assertTrue(settings.us_collector_enabled)

    def test_watchlist_instances_observe_each_other_and_reject_stale_revision(self):
        first = WatchlistStore(self.data_dir / "watchlist.json")
        second = WatchlistStore(self.data_dir / "watchlist.json")
        initial = first.get()
        changed = second.add_document("AAPL", initial["revision"])
        self.assertEqual(first.get(), changed)
        with self.assertRaises(Exception):
            second.add_document("MSFT", initial["revision"])

        code = (
            "from pathlib import Path; import sys; "
            "from options_panel.us_equities.watchlist_store import WatchlistStore; "
            "WatchlistStore(Path(sys.argv[1])).add_document('MSFT', sys.argv[2])"
        )
        child_env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
        child = subprocess.run(
            [sys.executable, "-c", code, str(first.path), changed["revision"]],
            env=child_env,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(first.get()["symbols"], ["SPCX", "AAPL", "MSFT"])

    def test_admin_requires_bearer_and_same_origin_without_token_disclosure(self):
        token = "x" * 48
        app = create_admin_app(
            data_dir=self.data_dir,
            token=token,
            web_dir=self.root / "web",
            host="127.0.0.1",
            port=8765,
        )
        auth = {"Authorization": f"Bearer {token}"}
        same_origin = {**auth, "Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"}
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/admin.js").status_code, 200)
            self.assertEqual(client.get("/api/health").status_code, 401)
            self.assertEqual(client.get("/api/health", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            health = client.get("/api/health", headers=auth)
            self.assertEqual(health.status_code, 200)
            self.assertNotIn(token, health.text)
            current = client.get("/api/watchlist", headers=auth).json()
            denied = client.post(
                "/api/watchlist",
                headers={**auth, "Host": "127.0.0.1:8765", "Origin": "http://evil.invalid"},
                json={"symbol": "AAPL"},
            )
            self.assertEqual(denied.status_code, 403)
            added = client.post(
                "/api/watchlist",
                headers={**same_origin, "If-Match": current["revision"]},
                json={"symbol": "AAPL"},
            )
            self.assertEqual(added.status_code, 200)
            conflict = client.post(
                "/api/watchlist",
                headers={**same_origin, "If-Match": current["revision"]},
                json={"symbol": "MSFT"},
            )
            self.assertEqual(conflict.status_code, 409)
            with mock.patch(
                "options_panel.us_equities.watchlist_store.MAX_WATCHLIST_SYMBOLS", 2
            ):
                capacity = client.post(
                    "/api/watchlist",
                    headers={**same_origin, "If-Match": added.json()["revision"]},
                    json={"symbol": "MSFT"},
                )
            self.assertEqual(capacity.status_code, 429)
            self.assertIn("最多允许 2 个", capacity.json()["error"])
            guide = client.get("/api/options-guide", headers=auth).json()
            updated = client.put(
                "/api/options-guide",
                headers={**same_origin, "If-Match": guide["revision"]},
                json={"sections": DEFAULT_SECTIONS},
            )
            self.assertEqual(updated.status_code, 200)
            stale = client.put(
                "/api/options-guide",
                headers={**same_origin, "If-Match": guide["revision"]},
                json={"sections": DEFAULT_SECTIONS},
            )
            self.assertEqual(stale.status_code, 409)
            for response in (health, client.get("/api/watchlist", headers=auth), client.get("/api/options-guide", headers=auth)):
                self.assertNotIn(token, response.text)


if __name__ == "__main__":
    unittest.main()
