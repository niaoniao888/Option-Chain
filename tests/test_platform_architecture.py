from __future__ import annotations

import json
import tempfile
import time
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from options_panel.api import create_app
from options_panel.config import Settings
from options_panel.modules.bitcoin import BitcoinRuntime
from options_panel.logging import LOGGER
from options_panel.modules.registry import MarketRegistration, MarketRegistry, StaticPageConfig
from options_panel.providers.registry import ProviderBinding, default_provider_registry
from options_panel.runtime.lifecycle import RuntimeLifecycle, RuntimeRecord, public_health
from options_panel.runtime.market import MarketDescriptor, SnapshotEnvelope, SnapshotResponseCache
from options_panel.runtime.snapshot import DashboardState
from options_panel.runtime.refresher import Refresher
from options_panel.us_equities.runtime import UsEquitiesRuntime


THIRD = MarketDescriptor(
    market_id="test-market", title="测试市场", provider_id="fixture",
    provider_name="Fixture Provider", default_instrument="TEST",
    desktop_path="/test/desktop/", mobile_path="/test/mobile/",
    capabilities=("snapshot", "health", "fixture"),
)


class StubRuntime:
    def __init__(self, descriptor: MarketDescriptor = THIRD, *, stop_error: bool = False,
                 health_error: bool = False):
        self.descriptor = descriptor
        self.provider_id = descriptor.provider_id
        self.started = 0
        self.stopped = 0
        self.stop_error = stop_error
        self.health_error = health_error
        self.snapshot_calls = 0

    def start(self): self.started += 1

    def stop(self):
        self.stopped += 1
        if self.stop_error:
            raise RuntimeError("private shutdown detail")

    def health(self):
        if self.health_error:
            raise RuntimeError("https://token:secret@example.invalid")
        return {
            "status": "healthy", "provider": self.provider_id,
            "message": "token=secret", "nested": {"secret": "credential"},
            "refresh_policy": {"market_refresh_seconds": 60, "secret": "hidden"},
        }

    def snapshot_envelope(self, instrument=None):
        self.snapshot_calls += 1
        return SnapshotEnvelope(self.descriptor.market_id, self.provider_id,
                                instrument or self.descriptor.default_instrument,
                                "v1", "2026-09-27T00:00:00Z",
                                "2026-09-27T00:00:00Z", "healthy", {"value": 1})


class ProtocolOnlyRuntime:
    """Fixture intentionally exposes only the MarketRuntime protocol."""

    def __init__(self):
        self.descriptor = THIRD
        self.started = 0
        self.stopped = 0

    def start(self): self.started += 1
    def stop(self): self.stopped += 1
    def health(self): return {"status": "healthy", "provider": "fixture"}
    def snapshot_envelope(self, instrument=None):
        return SnapshotEnvelope(
            self.descriptor.market_id,
            self.descriptor.provider_id,
            instrument or self.descriptor.default_instrument,
            "v1",
            "2026-09-27T00:00:00Z",
            "2026-09-27T00:00:00Z",
            "healthy",
            {"value": 1},
        )


class AliveThread:
    def __init__(self): self.joins, self.alive = 0, True
    def is_alive(self): return self.alive
    def join(self, timeout=None): self.joins += 1


class FakeLock:
    def __init__(self): self.releases = 0
    def release(self): self.releases += 1


class SnapshotAdapter:
    ready = True
    source_name = "Fixture US"

    def fetch(self, symbol):
        return {
            "symbol": symbol,
            "contracts": [],
            "underlying_price": 200.0,
            "market_status": "OPEN",
            "calculated_at": "2026-09-27T01:02:03Z",
            "quote_time": "2026-09-27T01:02:00Z",
        }


class FixtureBitcoinProvider:
    source_name = "Fixture Binance"

    def __init__(self):
        self.calls = []

    def catalog(self):
        self.calls.append("catalog")
        return []

    def quotes(self):
        self.calls.append("quotes")
        return {"BTC-TEST": {"bid": 1.0, "ask": 1.1, "last": 1.05}}

    def index_price(self):
        self.calls.append("index")
        return 85000.0

    def server_time(self):
        self.calls.append("time")
        return 1_800_000_000_000

    def open_interest(self, contracts, server_time_ms):
        self.calls.append("open-interest")
        return {}

    def marks(self):
        self.calls.append("marks")
        return {}


class FalseyBitcoinProvider(FixtureBitcoinProvider):
    def __bool__(self): return False


class FalseyUsAdapter(SnapshotAdapter):
    def __bool__(self): return False


class PlatformArchitectureTests(unittest.TestCase):
    @contextmanager
    def app_root(self):
        with tempfile.TemporaryDirectory() as directory:
            try:
                yield Path(directory)
            finally:
                for handler in list(LOGGER.handlers):
                    handler.close()
                    LOGGER.removeHandler(handler)

    def settings(self, root: Path, **changes) -> Settings:
        values = dict(app_root=root, collector_enabled=False)
        values.update(changes)
        return Settings(**values)

    def test_cache_key_isolates_markets_and_eviction_is_bounded(self):
        clock = [0.0]
        cache = SnapshotResponseCache(ttl=10, max_entries=2, monotonic=lambda: clock[0])
        calls = []
        produce = lambda value: lambda: calls.append(value) or {"value": value}
        btc = cache.key("bitcoin", "binance", "BTCUSDT")
        us = cache.key("us-equities", "alpaca", "AAPL")
        other = cache.key("us-equities", "alpaca", "MSFT")
        self.assertNotEqual(btc, us)
        self.assertEqual(json.loads(cache.body(btc, produce("btc"))), {"value": "btc"})
        cache.body(us, produce("aapl")); cache.body(btc, produce("unused"))
        cache.body(other, produce("msft"))
        self.assertEqual(len(cache._items), 2)
        self.assertNotIn(us, cache._items)
        clock[0] = 11
        cache.body(us, produce("fresh"))
        self.assertEqual(set(cache._items), {us})
        self.assertNotIn("unused", calls)

    def test_snapshot_envelope_keeps_original_payload_and_times(self):
        state = DashboardState()
        state.commit_catalog([])
        state.commit_market({}, 85000, 1_700_000_000_000, {}, {})
        with tempfile.TemporaryDirectory() as directory:
            from options_panel.content.guide_store import GuideStore
            runtime = BitcoinRuntime(state, GuideStore(Path(directory) / "guide.json"), Path(directory), collector_enabled=False)
            envelope = runtime.snapshot_envelope()
            same_generation = runtime.snapshot_envelope()
            state.commit_market({}, 86000, 1_700_000_001_000, {}, {})
            next_generation = runtime.snapshot_envelope()
        self.assertEqual((envelope.market, envelope.provider, envelope.instrument), ("bitcoin", "binance", "BTCUSDT"))
        self.assertEqual(envelope.payload["index_price"], 85000)
        self.assertIn("contracts", envelope.payload)
        self.assertTrue(envelope.version)
        self.assertTrue(envelope.received_at)
        self.assertIsInstance(envelope.calculated_at, int)
        self.assertEqual(envelope.calculated_at, envelope.payload["market_generation_ms"])
        self.assertEqual(envelope.received_at, envelope.payload["fetched_at"])
        self.assertEqual(envelope.version, same_generation.version)
        self.assertNotEqual(envelope.version, next_generation.version)
        self.assertEqual(envelope.version, envelope.payload["market_generation_ms"])

        with tempfile.TemporaryDirectory() as directory:
            us_runtime = UsEquitiesRuntime(
                Path(directory) / "data", collector_enabled=False,
                adapter=SnapshotAdapter(), provider_id="fixture-us", provider_name="Fixture US",
            )
            pending = us_runtime.snapshot_envelope("AAPL").payload
            self.assertEqual(pending["source"], "Fixture US")
            self.assertIsNone(pending["source_delay_label"])
            us_runtime.market.wall_clock = lambda: 1_800_000_000.0
            self.assertTrue(us_runtime.market.refresh("AAPL"))
            us_envelope = us_runtime.snapshot_envelope("AAPL")
        self.assertEqual((us_envelope.market, us_envelope.provider, us_envelope.instrument),
                         ("us-equities", "fixture-us", "AAPL"))
        self.assertTrue(us_envelope.version)
        self.assertTrue(us_envelope.received_at)
        self.assertEqual(us_envelope.calculated_at, "2026-09-27T01:02:03Z")
        self.assertEqual(us_envelope.received_at, us_envelope.payload["fetched_at"])

    def test_registry_accepts_third_market_without_app_core_changes(self):
        runtime = ProtocolOnlyRuntime()
        def install_fixture_route(app, platform, registration):
            app.add_api_route(
                platform.settings.base_path + "/api/v1/test-market/feature",
                lambda: {"capability": registration.descriptor.capabilities[-1]},
                methods=["GET"],
            )
        registry = MarketRegistry((MarketRegistration(
            THIRD, lambda _context: runtime,
            static_page=StaticPageConfig("test-market", "test-market", (), ()),
            route_installer=install_fixture_route,
        ),))
        with self.app_root() as root:
            page = root / "web" / "test-market" / "index.html"
            page.parent.mkdir(parents=True)
            page.write_text("fixture market shell", encoding="utf-8")
            with TestClient(create_app(self.settings(root, base_path="/panel"), DashboardState(), registry)) as client:
                modules = client.get("/panel/api/v1/modules").json()
                status = client.get("/panel/api/v1/status").json()
                self.assertEqual(modules[0]["id"], "test-market")
                self.assertEqual(modules[0]["provider"], "Fixture Provider")
                self.assertEqual(status["markets"]["test-market"]["runtime"]["status"], "healthy")
                self.assertNotIn("secret", json.dumps(status))
                self.assertEqual(client.get("/panel/api/v1/test-market/health").json()["provider"], "fixture")
                snapshot = client.get("/panel/api/v1/test-market/snapshot").json()
                self.assertEqual((snapshot["market"], snapshot["payload"]), ("test-market", {"value": 1}))
                self.assertEqual(client.get("/panel/api/v1/test-market/snapshot").status_code, 200)
                self.assertEqual(client.get("/panel/api/v1/test-market/feature").json(),
                                 {"capability": "fixture"})
                self.assertEqual(client.get("/panel/test/desktop/").text, "fixture market shell")
                self.assertEqual(client.get("/panel/test/mobile/").status_code, 200)
                self.assertEqual(runtime.started, 1)
        self.assertEqual(runtime.stopped, 1)

    def test_initialization_failure_is_isolated_and_public_error_is_sanitized(self):
        good = StubRuntime()
        bad_descriptor = MarketDescriptor("bad", "Bad", "bad", "Bad", None, "/bad/", "/bad/")
        def bad_factory(_context):
            raise ValueError("https://user:secret@example.invalid")
        registry = MarketRegistry((
            MarketRegistration(bad_descriptor, bad_factory),
            MarketRegistration(THIRD, lambda _context: good),
        ))
        with self.app_root() as root:
            with TestClient(create_app(self.settings(root), DashboardState(), registry)) as client:
                response = client.get("/api/v1/status")
                modules = client.get("/api/v1/modules").json()
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("secret", response.text)
                self.assertEqual(response.json()["markets"]["bad"]["initialization_error"], "ValueError")
                self.assertEqual((modules[0]["status"], modules[0]["provider"]), ("unavailable", "bad"))
                self.assertEqual(good.started, 1)

    def test_unknown_configured_provider_does_not_fall_back(self):
        with self.app_root() as root:
            settings = self.settings(root, bitcoin_provider="unknown-provider")
            with TestClient(create_app(settings, DashboardState())) as client:
                status = client.get("/api/v1/status").json()
                self.assertEqual(status["markets"]["bitcoin"]["initialization_error"], "ValueError")
                self.assertEqual(client.get("/api/v1/bitcoin/health").status_code, 503)
                bitcoin = next(item for item in client.get("/api/v1/modules").json() if item["id"] == "bitcoin")
                self.assertEqual((bitcoin["status"], bitcoin["provider"]),
                                 ("unavailable", "unknown-provider"))
                self.assertIn("us-equities", status["markets"])
        with self.app_root() as root:
            settings = self.settings(root, us_equities_provider="unknown-provider")
            with TestClient(create_app(settings, DashboardState())) as client:
                status = client.get("/api/v1/status").json()
                self.assertEqual(status["markets"]["us-equities"]["initialization_error"], "ValueError")
                self.assertEqual(client.get("/api/v1/us-equities/health").status_code, 503)
                self.assertIsNone(status["markets"]["bitcoin"]["initialization_error"])

    def test_missing_and_falsey_provider_adapters_never_silently_fall_back(self):
        providers = default_provider_registry()
        providers.register(
            "bitcoin", "missing-btc",
            lambda _settings: ProviderBinding("bitcoin", "missing-btc", "Missing BTC"),
        )
        providers.register(
            "us-equities", "missing-us",
            lambda _settings: ProviderBinding("us-equities", "missing-us", "Missing US"),
        )
        with self.app_root() as root:
            settings = self.settings(
                root, bitcoin_provider="missing-btc", us_equities_provider="missing-us",
            )
            with TestClient(create_app(settings, DashboardState(), provider_registry=providers)) as client:
                status = client.get("/api/v1/status").json()["markets"]
                self.assertEqual(status["bitcoin"]["initialization_error"], "ValueError")
                self.assertEqual(status["us-equities"]["initialization_error"], "ValueError")
                modules = {item["id"]: item for item in client.get("/api/v1/modules").json()}
                self.assertEqual((modules["bitcoin"]["status"], modules["bitcoin"]["provider"]),
                                 ("unavailable", "missing-btc"))
                self.assertEqual((modules["us-equities"]["status"], modules["us-equities"]["provider"]),
                                 ("unavailable", "missing-us"))

        falsey_btc = FalseyBitcoinProvider()
        falsey_us = FalseyUsAdapter()
        with tempfile.TemporaryDirectory() as directory:
            from options_panel.content.guide_store import GuideStore
            btc_runtime = BitcoinRuntime(
                DashboardState(), GuideStore(Path(directory) / "guide.json"), Path(directory),
                collector_enabled=False, provider_id="falsey-btc", provider=falsey_btc,
            )
            us_runtime = UsEquitiesRuntime(
                Path(directory) / "us", collector_enabled=False,
                provider_id="falsey-us", provider_name="Falsey US", adapter=falsey_us,
            )
        self.assertIs(btc_runtime.provider, falsey_btc)
        self.assertIs(us_runtime.adapter, falsey_us)
        refresher = Refresher(DashboardState(), provider=falsey_btc)
        self.assertIs(refresher.provider, falsey_btc)
        self.assertTrue(refresher.refresh_catalog())
        self.assertTrue(refresher.refresh_market())
        self.assertEqual(
            falsey_btc.calls,
            ["catalog", "quotes", "index", "time", "open-interest", "marks", "time"],
        )
        health = us_runtime.health()
        self.assertTrue(health["configured"])
        self.assertEqual(health["source"], "Fixture US")
        self.assertEqual(public_health({"provider": "fixture"}),
                         {"provider": "fixture", "status": "unknown"})
        self.assertEqual(
            public_health({
                "data_status": "failed", "active_symbol_count": 1,
                "cache_symbol_count": 2, "queued_symbol_count": 1,
                "inflight_symbol_count": 0, "failure_count": 1,
                "waiting_symbol_count": 1, "data_age_seconds": 12.5,
                "contract_count": 20,
                "secret": "hidden",
            }),
            {
                "status": "unknown", "data_status": "failed",
                "active_symbol_count": 1, "cache_symbol_count": 2,
                "queued_symbol_count": 1, "inflight_symbol_count": 0,
                "failure_count": 1, "waiting_symbol_count": 1,
                "data_age_seconds": 12.5,
                "contract_count": 20,
            },
        )

    def test_broken_provider_selector_is_isolated(self):
        good = StubRuntime()
        broken = MarketRegistration(
            MarketDescriptor(
                "broken", "Broken", "fallback", "Fallback", None,
                "/broken/desktop/", "/broken/mobile/",
            ),
            lambda _context: (_ for _ in ()).throw(RuntimeError("private token")),
            provider_selector=lambda _settings: (_ for _ in ()).throw(
                ValueError("private selector token")
            ),
        )
        registry = MarketRegistry((
            broken,
            MarketRegistration(THIRD, lambda _context: good),
        ))
        with self.app_root() as root:
            with TestClient(create_app(self.settings(root), DashboardState(), registry)) as client:
                status = client.get("/api/v1/status").json()["markets"]
                self.assertEqual(status["broken"]["initialization_error"], "RuntimeError")
                self.assertEqual(status["test-market"]["runtime"]["status"], "healthy")
                self.assertNotIn("token", json.dumps(status))
                modules = {item["id"]: item for item in client.get("/api/v1/modules").json()}
                self.assertEqual(modules["broken"]["provider_id"], "fallback")

    def test_runtime_market_and_provider_identity_mismatch_is_isolated(self):
        mismatched_market = StubRuntime(replace(THIRD, market_id="other-market"))
        mismatched_provider = StubRuntime(replace(THIRD, provider_id="other-provider"))
        good = StubRuntime()
        registry = MarketRegistry((
            MarketRegistration(
                replace(THIRD, market_id="bad-market"),
                lambda _context: mismatched_market,
            ),
            MarketRegistration(
                replace(THIRD, market_id="bad-provider"),
                lambda _context: mismatched_provider,
            ),
            MarketRegistration(THIRD, lambda _context: good),
        ))
        with self.app_root() as root:
            with TestClient(create_app(self.settings(root), DashboardState(), registry)) as client:
                status = client.get("/api/v1/status").json()["markets"]
                self.assertEqual(status["bad-market"]["initialization_error"], "ValueError")
                self.assertEqual(status["bad-provider"]["initialization_error"], "ValueError")
                self.assertEqual(status["test-market"]["runtime"]["status"], "healthy")
                self.assertEqual(good.started, 1)

    def test_replacement_provider_is_registry_data(self):
        providers = default_provider_registry()
        fixture = FixtureBitcoinProvider()
        providers.register(
            "bitcoin", "fixture-binance",
            lambda _settings: ProviderBinding(
                "bitcoin", "fixture-binance", "Fixture Binance",
                adapter=fixture,
            ),
        )
        with self.app_root() as root:
            settings = self.settings(
                root, collector_enabled=True, bitcoin_provider="fixture-binance",
                us_collector_enabled=False,
            )
            with TestClient(create_app(settings, DashboardState(), provider_registry=providers)) as client:
                runtime = client.app.state.platform.runtime("bitcoin")
                self.assertIsInstance(runtime, BitcoinRuntime)
                deadline = time.monotonic() + 2
                while runtime.state.market_fetched_at is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIsNotNone(runtime.state.market_fetched_at)
                self.assertEqual(fixture.calls[:7],
                                 ["catalog", "quotes", "index", "time", "open-interest", "marks", "time"])
                self.assertEqual(client.get("/api/v1/modules").json()[0]["provider"], "Fixture Binance")
                self.assertEqual(client.get("/api/v1/status").json()["markets"]["bitcoin"]["runtime"]["provider"], "fixture-binance")
                envelope = runtime.snapshot_envelope()
                self.assertEqual((envelope.market, envelope.provider, envelope.instrument),
                                 ("bitcoin", "fixture-binance", "BTCUSDT"))
                self.assertEqual(envelope.payload["source"], "Fixture Binance")
                self.assertEqual(
                    client.get("/api/v1/bitcoin/snapshot").json()["source"],
                    "Fixture Binance",
                )

    def test_populated_bitcoin_state_cannot_be_relabeled_for_another_provider(self):
        state = DashboardState()
        state.commit_catalog([])
        with tempfile.TemporaryDirectory() as directory:
            from options_panel.content.guide_store import GuideStore
            with self.assertRaisesRegex(ValueError, "different provider"):
                BitcoinRuntime(
                    state,
                    GuideStore(Path(directory) / "guide.json"),
                    Path(directory),
                    collector_enabled=False,
                    provider_id="fixture-binance",
                    provider=FixtureBitcoinProvider(),
                )

    def test_replacement_us_provider_identity_reaches_http_and_envelope(self):
        providers = default_provider_registry()
        adapter = SnapshotAdapter()
        providers.register(
            "us-equities",
            "fixture-us",
            lambda _settings: ProviderBinding(
                "us-equities", "fixture-us", "Fixture US", adapter=adapter
            ),
        )
        with self.app_root() as root:
            settings = self.settings(
                root,
                us_equities_provider="fixture-us",
                us_collector_enabled=False,
            )
            with TestClient(
                create_app(
                    settings,
                    DashboardState(),
                    provider_registry=providers,
                )
            ) as client:
                runtime = client.app.state.platform.runtime("us-equities")
                envelope = runtime.snapshot_envelope("SPCX")
                response = client.get(
                    "/api/v1/us-equities/snapshot", params={"symbol": "SPCX"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["source"], "Fixture US")
                self.assertIsNone(response.json()["source_delay_label"])
                self.assertEqual(
                    (envelope.market, envelope.provider, envelope.payload["source"]),
                    ("us-equities", "fixture-us", "Fixture US"),
                )

    def test_shutdown_failure_does_not_skip_peer_and_alive_thread_cannot_restart(self):
        first, broken = StubRuntime(), StubRuntime(stop_error=True)
        lifecycle = RuntimeLifecycle({
            "first": RuntimeRecord("first", first),
            "broken": RuntimeRecord("broken", broken),
        })
        lifecycle.stop_all()
        self.assertEqual((first.stopped, broken.stopped), (1, 1))
        self.assertEqual(lifecycle.records["broken"].shutdown_error, "RuntimeError")

        with tempfile.TemporaryDirectory() as directory:
            runtime = UsEquitiesRuntime(Path(directory) / "data", collector_enabled=True, adapter=type("Adapter", (), {"ready": False, "source_name": "test"})())
            thread, lock = AliveThread(), FakeLock()
            runtime._thread, runtime._collector_lock = thread, lock
            runtime.stop()
            runtime.start()
            self.assertIs(runtime._thread, thread)
            self.assertEqual(thread.joins, 1)
            self.assertEqual(lock.releases, 0)
            thread.alive = False
            runtime.stop()
            runtime.stop()
            self.assertIsNone(runtime._thread)
            self.assertEqual(lock.releases, 1)

    def test_start_failure_releases_lock_and_status_health_failure_is_sanitized(self):
        state = DashboardState()
        with tempfile.TemporaryDirectory() as directory:
            from options_panel.content.guide_store import GuideStore
            runtime = BitcoinRuntime(
                state, GuideStore(Path(directory) / "guide.json"), Path(directory),
                refresher_factory=lambda _state, **_kwargs: type("BrokenThread", (), {"start": lambda self: (_ for _ in ()).throw(RuntimeError("secret"))})(),
            )
            lock = FakeLock()
            lock.acquire = lambda: None
            with mock.patch("options_panel.modules.bitcoin.ProcessLock", return_value=lock):
                with self.assertRaises(RuntimeError):
                    runtime.start()
            self.assertEqual(lock.releases, 1)
            self.assertIsNone(runtime._thread)

        record = RuntimeRecord("test-market", StubRuntime(health_error=True))
        public = record.status()
        self.assertEqual(public["runtime"], {"status": "health_error", "error_type": "RuntimeError"})
        self.assertNotIn("secret", json.dumps(public))


if __name__ == "__main__":
    unittest.main()
