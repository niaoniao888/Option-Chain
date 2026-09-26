import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from options_panel.us_equities.market_service import ClientCapacityError, MarketService
from options_panel.us_equities.runtime import UsEquitiesRuntime


class IdleAdapter:
    ready = False
    source_name = "test"


class FailingAdapter:
    ready = True
    source_name = "fixture-provider"

    def fetch(self, _symbol):
        raise TimeoutError("offline")


class RunningThread:
    def is_alive(self):
        return True


class RuntimeReliabilityTests(unittest.TestCase):
    def test_client_capacity_preserves_existing_and_recovers_after_expiry(self):
        now = [0.0]
        service = MarketService(IdleAdapter(), monotonic=lambda: now[0])
        with patch("options_panel.us_equities.market_service.MAX_TRACKED_CLIENTS", 2):
            for name in ("one", "two"):
                service.snapshot("AAPL", client_id=name, activity_seq=1)
            with self.assertRaises(ClientCapacityError):
                service.snapshot("AAPL", client_id="three", activity_seq=1)
            service.snapshot("AAPL", client_id="one", activity_seq=2)
            self.assertEqual(len(service._client_sequences), 2)
            now[0] = 31.0
            service.snapshot("AAPL", client_id="three", activity_seq=1)
            self.assertEqual(set(service._client_sequences), {"three"})

    def test_runtime_stop_start_and_startup_error_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = UsEquitiesRuntime(Path(directory) / "data", adapter=IdleAdapter())
            try:
                with patch("options_panel.us_equities.runtime.ProcessLock.acquire", side_effect=RuntimeError("busy")):
                    runtime.start()
                self.assertIsNotNone(runtime._startup_error)
                runtime.start()
                self.assertTrue(runtime._thread.is_alive())
                self.assertIsNone(runtime._startup_error)
                runtime.stop()
                self.assertTrue(runtime.market._stop.is_set())
                runtime.start()
                self.assertTrue(runtime._thread.is_alive())
                self.assertFalse(runtime.market._stop.is_set())
            finally:
                runtime.stop()

    def test_active_data_failure_degrades_runtime_health_without_contract_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = UsEquitiesRuntime(
                Path(directory) / "data", adapter=FailingAdapter()
            )
            runtime.market.snapshot(
                "AAPL", client_id="tab", active=True, activity_seq=1
            )
            self.assertFalse(runtime.market.refresh("AAPL"))
            runtime._thread = RunningThread()
            health = runtime.health()
            self.assertEqual(health["status"], "degraded")
            self.assertEqual(health["data_status"], "failed")
            self.assertEqual(health["failure_count"], 1)

    def test_partially_loaded_active_symbols_degrade_runtime_health(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = UsEquitiesRuntime(
                Path(directory) / "data", adapter=FailingAdapter()
            )
            runtime.market.snapshot(
                "AAPL", client_id="ready-tab", active=True, activity_seq=1
            )
            runtime.market.snapshot(
                "MSFT", client_id="waiting-tab", active=True, activity_seq=1
            )
            now = runtime.market.monotonic()
            runtime.market._last_success["AAPL"] = now
            runtime.market._cache["AAPL"] = {"contracts": []}
            runtime._thread = RunningThread()
            health = runtime.health()
            self.assertEqual(health["status"], "degraded")
            self.assertEqual(health["data_status"], "partial")
            self.assertEqual(health["waiting_symbol_count"], 1)
