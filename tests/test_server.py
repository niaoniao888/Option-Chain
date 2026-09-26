import copy
import concurrent.futures
import http.client
import io
import json
import logging
import math
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import legacy_support as server
from options_panel.logging import JsonFormatter


class Clock:
    def __init__(self, value=1_700_000_000.0): self.value = value
    def __call__(self): return self.value


class FormulaTests(unittest.TestCase):
    def test_six_point_zero_eight_three_three_three_three_percent(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        self.assertAlmostEqual(server.annualized_yield("CALL", 500, 100000, 100000, 1, expiry, now), 6.0833333333, places=8)

    def test_call_put_and_atm(self):
        self.assertEqual(server.moneyness("CALL", 10100, 10000)[0], "OTM")
        self.assertEqual(server.moneyness("CALL", 9900, 10000)[0], "ITM")
        self.assertEqual(server.moneyness("PUT", 9900, 10000)[0], "OTM")
        self.assertEqual(server.moneyness("PUT", 10100, 10000)[0], "ITM")
        self.assertEqual(server.moneyness("CALL", 10000.5, 10000)[0], "ATM")

    def test_unit_cancels_and_is_validated(self):
        self.assertEqual(server.normalized_bid("123.4", "0.01"), 123.4)
        self.assertIsNone(server.normalized_bid(123.4, 0))
        self.assertIsNone(server.normalized_bid(123.4, "NaN"))

    def test_sub_day_expiry_and_expired(self):
        now = 1_700_000_000_000
        value = server.annualized_yield("CALL", 10, 10000, 10000, 1, now + 12 * 3600 * 1000, now)
        self.assertAlmostEqual(value, 73.0)
        self.assertIsNone(server.annualized_yield("CALL", 10, 10000, 10000, 1, now, now))
        self.assertIsNone(server.annualized_yield("CALL", 10, 10000, 10000, 1, now - 1, now))

    def test_zero_missing_nan(self):
        expiry = 2_000_000_000_000
        for bid in (0, None, "", "NaN", float("inf")):
            self.assertIsNone(server.annualized_yield("CALL", bid, 10000, 10000, 1, expiry, 1_000_000_000_000))

    def test_timezone_serialization_is_utc_and_frontend_declares_shanghai(self):
        self.assertTrue(server.utc_iso(0).endswith("Z"))
        js = (Path(__file__).resolve().parents[1] / "web" / "app" / "core" / "formats.js").read_text(encoding="utf-8")
        self.assertIn('timeZone: "Asia/Shanghai"', js)

    def test_empty_ticker_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未返回"):
            server.parse_quotes([])
        with self.assertRaisesRegex(ValueError, "BTC"):
            server.parse_quotes([{"symbol":"ETH-260925-10000-C","bidPrice":"1"}])

    def test_open_interest_zero_positive_and_invalid_values(self):
        parsed = server.parse_open_interest([
            {"symbol":"BTC-260925-77000-C","sumOpenInterest":"0.0","timestamp":"1700000000000"},
            {"symbol":"BTC-260925-78000-C","sumOpenInterest":"1.25","timestamp":"1700000000001"},
            {"symbol":"BTC-260925-79000-C","sumOpenInterest":"-1","timestamp":"1700000000002"},
            {"symbol":"BTC-260925-80000-C","sumOpenInterest":True,"timestamp":"1700000000003"},
            {"symbol":"BTC-260925-81000-C","sumOpenInterest":"NaN","timestamp":"1700000000004"},
            {"symbol":"BTC-260926-77000-C","sumOpenInterest":"3","timestamp":"1700000000005"},
        ], "260925")
        self.assertEqual(parsed["BTC-260925-77000-C"]["open_interest"], 0.0)
        self.assertEqual(parsed["BTC-260925-78000-C"]["open_interest"], 1.25)
        self.assertEqual(parsed["BTC-260925-77000-C"]["open_interest_time_ms"], 1_700_000_000_000)
        self.assertNotIn("BTC-260925-79000-C", parsed)
        self.assertNotIn("BTC-260925-80000-C", parsed)
        self.assertNotIn("BTC-260925-81000-C", parsed)
        self.assertNotIn("BTC-260926-77000-C", parsed)
        with self.assertRaisesRegex(ValueError, "持仓量"):
            server.parse_open_interest([{"symbol":"BTC-260925-1-C","sumOpenInterest":""}], "260925")

    def test_zero_open_interest_disables_otherwise_valid_yield(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        self.assertIsNone(server.annualized_yield("CALL", 500, 100000, 100000, 1, expiry, now, 0.0))
        self.assertAlmostEqual(server.annualized_yield("CALL", 500, 100000, 100000, 1, expiry, now, 1.0), 6.0833333333, places=8)
        self.assertAlmostEqual(server.annualized_yield("CALL", 500, 100000, 100000, 1, expiry, now, None), 6.0833333333, places=8)

    def test_time_value_annualized_put_positive_and_negative(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        intrinsic, time_value, annualized = server.annualized_components(
            "PUT", 10500, 90000, 100000, 1, expiry, now, 1,
        )
        self.assertEqual(intrinsic, 10000.0)
        self.assertEqual(time_value, 500.0)
        self.assertAlmostEqual(annualized, 6.0833333333, places=8)
        intrinsic, time_value, annualized = server.annualized_components(
            "PUT", 9900, 90000, 100000, 1, expiry, now, 1,
        )
        self.assertEqual(intrinsic, 10000.0)
        self.assertEqual(time_value, -100.0)
        self.assertIsNone(annualized)
        metrics = server.yield_metrics("PUT", 9900, 90000, 100000, 1, expiry, now, 1)
        self.assertEqual(metrics["time_value_status"], "negative")
        self.assertIsNone(metrics["period_return_pct"])

    def test_strategy_period_and_annualized_metrics_use_side_specific_capital(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        call = server.yield_metrics("CALL", 10500, 100000, 90000, 1, expiry, now, 1)
        put = server.yield_metrics("PUT", 10500, 90000, 100000, 1, expiry, now, 1)
        for metrics in (call, put):
            self.assertEqual(metrics["intrinsic_value"], 10000.0)
            self.assertEqual(metrics["time_value"], 500.0)
            self.assertEqual(metrics["capital_base"], 100000.0)
            self.assertEqual(metrics["period_return_pct"], 0.5)
            self.assertAlmostEqual(metrics["annualized_pct"], 6.0833333333, places=8)
            self.assertEqual(metrics["calculation_index_price"], 100000.0 if metrics is call else 90000.0)
        self.assertEqual(call["annualized_basis"], "time_value_on_spot")
        self.assertEqual(put["annualized_basis"], "time_value_on_strike")

    def test_fractional_second_remaining_years_is_not_rounded(self):
        now = 1_700_000_000_000
        seconds = 7.42 * 86400 + 0.375
        metrics = server.yield_metrics("CALL", 500, 100000, 100000, 1, now + seconds * 1000, now, 1)
        self.assertAlmostEqual(metrics["remaining_years"], seconds / (365 * 24 * 3600), places=13)
        self.assertAlmostEqual(metrics["annualized_pct"], metrics["period_return_pct"] / metrics["remaining_years"], places=12)

    def test_time_value_annualized_call_otm_zero_and_invalid_index(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        intrinsic, time_value, annualized = server.annualized_components(
            "CALL", 500, 90000, 100000, 1, expiry, now, 1,
        )
        self.assertEqual((intrinsic, time_value), (0.0, 500.0))
        self.assertAlmostEqual(annualized, 6.7592592593, places=8)
        self.assertEqual(server.annualized_components("CALL", 10000, 110000, 100000, 1, expiry, now, 1),
                         (10000.0, 0.0, None))
        zero = server.yield_metrics("CALL", 10000, 110000, 100000, 1, expiry, now, 1)
        self.assertEqual(zero["time_value_status"], "zero")
        self.assertIsNone(zero["period_return_pct"])
        for spot in (None, 0, "NaN", float("inf")):
            self.assertEqual(server.annualized_components("CALL", 500, spot, 100000, 1, expiry, now, 1),
                             (None, None, None))

    def test_exercise_probability_standard_example(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        call, call_reason = server.exercise_probability("CALL", 100000, 110000, expiry, now, .5, .05, 1)
        put, put_reason = server.exercise_probability("PUT", 100000, 110000, expiry, now, .5, .05, 1)
        self.assertAlmostEqual(call, 23.950313, places=6)
        self.assertAlmostEqual(put, 76.049687, places=6)
        self.assertIsNone(call_reason)
        self.assertIsNone(put_reason)

    def test_exercise_probability_validation_and_extreme_values(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        for rate in (0, -.02):
            value, reason = server.exercise_probability("CALL", 100000, 100000, expiry, now, .5, rate, 1)
            self.assertIsNotNone(value)
            self.assertIsNone(reason)
        for iv, rate, reason in ((0, .05, "invalid_iv"), ("NaN", .05, "invalid_iv"), (.5, None, "invalid_risk_free_interest")):
            self.assertEqual(server.exercise_probability("CALL", 100000, 100000, expiry, now, iv, rate, 1), (None, reason))
        self.assertEqual(server.exercise_probability("CALL", 100000, 100000, expiry, now, 1e308, .05, 1), (None, "model_error"))
        self.assertEqual(server.exercise_probability("CALL", 100000, 100000, expiry, now, .5, .05, 0), (None, "zero_open_interest"))

    def test_parse_marks_keeps_bad_contract_isolated(self):
        parsed = server.parse_marks([
            {"symbol":"BTC-260925-100000-C","markIV":"0.5","riskFreeInterest":"-0.01","delta":"0.4","markPrice":"100"},
            {"symbol":"BTC-260925-110000-P","markIV":"bad","riskFreeInterest":None,"delta":"bad","markPrice":"-1"},
            {"symbol":"ETH-260925-10000-C","markIV":"0.8","riskFreeInterest":"0.1"},
        ])
        self.assertEqual(parsed["BTC-260925-100000-C"]["risk_free_interest"], -.01)
        self.assertIsNone(parsed["BTC-260925-110000-P"]["mark_iv"])
        self.assertIsNone(parsed["BTC-260925-110000-P"]["risk_free_interest"])
        with self.assertRaisesRegex(ValueError, "mark"):
            server.parse_marks({"not":"a list"})


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.wall = Clock()
        self.mono = Clock(10.0)
        self.state = server.DashboardState(self.wall, self.mono)
        self.state.commit_catalog([{"symbol":"BTC-X","expiry_ms":2_000_000_000_000,"side":"CALL","strike":10000.0,"unit":1.0,"status":"TRADING"}])
        self.state.commit_market({"BTC-X":{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":1}}, 10000.0, 1_700_000_000_000)

    def test_failed_refresh_retains_cache_and_fetched_at(self):
        fetched = self.state.market_fetched_at
        quotes = self.state.quotes.copy()
        self.state.fail_market("行情刷新失败：timeout")
        self.assertEqual(self.state.market_fetched_at, fetched)
        self.assertEqual(self.state.quotes, quotes)
        self.assertEqual(self.state.health()["status"], "degraded")

    def test_stale_at_120_seconds_and_recovery(self):
        self.mono.value += 119.9
        self.assertFalse(self.state.health()["stale"])
        self.mono.value += 0.1
        self.assertTrue(self.state.health()["stale"])
        self.state.commit_market(self.state.quotes, 10001.0, 1_700_000_120_000)
        self.assertEqual(self.state.health()["status"], "healthy")
        self.assertFalse(self.state.health()["stale"])

    def test_wall_clock_rollback_cannot_hide_stale_data(self):
        self.wall.value -= 600
        self.mono.value += 600
        health = self.state.health()
        self.assertTrue(health["stale"])
        self.assertEqual(health["age_seconds"], 600)

    def test_catalog_failure_is_not_silently_healthy(self):
        self.state.fail_catalog("合约目录刷新失败：timeout")
        self.assertEqual(self.state.health()["status"], "degraded")

    def test_multiple_snapshots_share_one_cache(self):
        first = self.state.snapshot()
        self.mono.value += 45
        second = self.state.snapshot()
        self.assertEqual(first["fetched_at"], second["fetched_at"])
        self.assertEqual(first["contracts"][0]["bid"], second["contracts"][0]["bid"])
        self.assertEqual(first["contracts"][0]["annualized_pct"], second["contracts"][0]["annualized_pct"])
        self.assertEqual(first["contracts"][0]["annualized_calculated_at_ms"], 1_700_000_000_000)
        self.assertEqual(first["contracts"][0]["intrinsic_value"], 0.0)
        self.assertEqual(first["contracts"][0]["time_value"], 100.0)
        self.assertEqual(first["contracts"][0]["annualized_basis"], "time_value_on_spot")
        self.assertEqual(first["contracts"][0]["period_return_pct"], 1.0)
        self.assertEqual(first["contracts"][0]["capital_base"], 10000.0)
        self.assertEqual(first["contracts"][0]["calculation_index_price"], 10000.0)
        self.assertEqual(first["market_generation_ms"], 1_700_000_000_000)

    def test_snapshot_serializes_negative_time_value_status_and_mark_reference(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        contract = {"symbol":"BTC-P","expiry_ms":expiry,"side":"PUT","strike":100000.0,"unit":1.0,"status":"TRADING"}
        self.state.commit_catalog([contract])
        marks = {"BTC-P":{"mark_iv":.5,"risk_free_interest":.05,"delta":-.5,"mark_price":9900.0}}
        self.state.commit_market({"BTC-P":{"bid":9900.0,"ask":9910.0,"last":9900.0,"last_trade_time_ms":1}},
                                 90000.0, now, {"BTC-P":{"open_interest":1.0,"open_interest_time_ms":now}}, marks)
        row = self.state.snapshot()["contracts"][0]
        self.assertEqual(row["intrinsic_value"], 10000.0)
        self.assertEqual(row["time_value"], -100.0)
        self.assertEqual(row["time_value_status"], "negative")
        self.assertIsNone(row["period_return_pct"])
        self.assertIsNone(row["annualized_pct"])
        self.assertEqual(row["mark_time_value"], -100.0)
        self.assertAlmostEqual(row["mark_annualized_pct"], -1.2166666667, places=8)
        json.dumps(self.state.snapshot(), allow_nan=False)

    def test_zero_bid_time_value_and_current_mark_reference_lifecycle(self):
        now = 1_700_000_000_000
        expiry = now + 30 * 86400 * 1000
        contract = {"symbol":"BTC-P","expiry_ms":expiry,"side":"PUT","strike":100000.0,"unit":1.0,"status":"TRADING"}
        quote = {"BTC-P":{"bid":10000.0,"ask":10010.0,"last":10000.0,"last_trade_time_ms":1}}
        oi = {"BTC-P":{"open_interest":1.0,"open_interest_time_ms":now}}
        mark = {"BTC-P":{"mark_iv":.5,"risk_free_interest":.05,"delta":-.5,"mark_price":10500.0}}
        self.state.commit_catalog([contract])
        self.state.commit_market(quote, 90000.0, now, oi, mark)
        row = self.state.snapshot()["contracts"][0]
        self.assertEqual(row["time_value_status"], "zero")
        self.assertIsNone(row["period_return_pct"])
        self.assertIsNone(row["annualized_pct"])
        self.assertEqual(row["mark_time_value"], 500.0)
        self.assertAlmostEqual(row["mark_annualized_pct"], 6.0833333333, places=8)
        self.assertEqual(row["mark_annualized_calculated_at_ms"], now)
        self.state.commit_market(quote, 90000.0, now + 1000, oi, {}, "mark failed")
        row = self.state.snapshot()["contracts"][0]
        self.assertIsNone(row["mark_time_value"])
        self.assertIsNone(row["mark_annualized_pct"])
        self.state.commit_market(quote, 90000.0, now + 2000, oi, {"BTC-P":{"mark_price":0.0}})
        row = self.state.snapshot()["contracts"][0]
        self.assertEqual(row["mark_time_value"], -10000.0)
        self.assertAlmostEqual(row["mark_annualized_pct"], -121.6667605455, places=6)
        self.mono.value += 30 * 86400 + 1
        expired = self.state.snapshot()["contracts"][0]
        self.assertEqual(expired["time_value_status"], "expired")
        self.assertIsNone(expired["mark_time_value"])
        self.assertIsNone(expired["mark_annualized_pct"])

    def test_invalid_index_does_not_calculate_annualized(self):
        self.state.commit_market(self.state.quotes, None, 1_700_000_060_000)
        row = self.state.snapshot()["contracts"][0]
        self.assertIsNone(row["annualized_pct"])
        self.assertIsNone(row["period_return_pct"])
        self.assertIsNone(row["intrinsic_value"])
        self.assertIsNone(row["time_value"])
        self.assertEqual(row["annualized_unavailable_reason"], "invalid_index")

    def test_snapshot_captures_one_atomic_generation(self):
        entered = threading.Event()
        release = threading.Event()
        commit_started = threading.Event()

        class BlockingQuotes(dict):
            def __deepcopy__(self, memo):
                entered.set()
                self.assert_released = release.wait(2)
                return dict(self)

        with self.state._lock:
            self.state.quotes = BlockingQuotes(self.state.quotes)
        snapshots = []
        snapshot_thread = threading.Thread(target=lambda: snapshots.append(self.state.snapshot()))
        snapshot_thread.start()
        self.assertTrue(entered.wait(1))
        self.wall.value += 50
        self.mono.value += 50

        def commit_new_generation():
            commit_started.set()
            self.state.commit_market(
                {"BTC-X":{"bid":200.0,"ask":201.0,"last":199.0,"last_trade_time_ms":2}},
                11000.0,
                1_700_000_050_000,
            )

        commit_thread = threading.Thread(target=commit_new_generation)
        commit_thread.start()
        self.assertTrue(commit_started.wait(1))
        release.set()
        snapshot_thread.join(2)
        commit_thread.join(2)
        self.assertFalse(snapshot_thread.is_alive())
        self.assertFalse(commit_thread.is_alive())
        snapshot = snapshots[0]
        self.assertEqual(snapshot["contracts"][0]["bid"], 100.0)
        self.assertEqual(snapshot["index_price"], 10000.0)
        self.assertEqual(snapshot["server_time_ms"], 1_700_000_000_000)
        self.assertEqual(snapshot["status"]["age_seconds"], 0.0)
        self.assertEqual(self.state.quotes["BTC-X"]["bid"], 200.0)

    def test_partial_batch_is_rejected_then_full_batch_recovers(self):
        second = {"symbol":"BTC-Y","expiry_ms":2_000_000_000_000,"side":"PUT","strike":9000.0,"unit":1.0,"status":"TRADING"}
        self.state.commit_catalog([self.state.contracts[0], second])
        self.state.commit_market({
            "BTC-X":{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":1},
            "BTC-Y":{"bid":90.0,"ask":91.0,"last":89.0,"last_trade_time_ms":1},
        }, 10000.0, 1_700_000_000_000)
        fetched = self.state.market_fetched_at
        ticker = [{"symbol":"BTC-X","bidPrice":"110","askPrice":"111"}]

        def fetch(path):
            if path.endswith("/ticker"): return ticker
            if "index?" in path: return {"indexPrice":"10010"}
            return {"serverTime":1_700_000_060_000}

        refresher = server.Refresher(self.state, fetch)
        refresher.fetch_open_interest = lambda _server_time: {
            contract["symbol"]: {"open_interest": 1.0, "open_interest_time_ms": 1}
            for contract in self.state.contracts
        }
        self.assertFalse(refresher.refresh_market())
        self.assertEqual(self.state.market_fetched_at, fetched)
        self.assertEqual(self.state.quotes["BTC-X"]["bid"], 100.0)
        self.assertEqual(self.state.market_error, "行情刷新失败，请稍后重试")
        ticker.append({"symbol":"BTC-Y","bidPrice":"95","askPrice":"96"})
        self.wall.value += 60
        self.mono.value += 60
        self.assertTrue(refresher.refresh_market())
        self.assertEqual(self.state.quotes["BTC-X"]["bid"], 110.0)
        self.assertIsNone(self.state.market_error)

    def test_provider_exception_detail_never_reaches_bitcoin_snapshot(self):
        secret = "token=FAKE-CREDENTIAL-123"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        server.LOGGER.addHandler(handler)
        self.addCleanup(server.LOGGER.removeHandler, handler)

        def fetch(_path):
            raise RuntimeError(f"https://example.invalid/?{secret}")

        refresher = server.Refresher(self.state, fetch)
        self.assertFalse(refresher.refresh_market())
        snapshot = self.state.snapshot()
        self.assertNotIn(secret, json.dumps(snapshot, ensure_ascii=False))
        self.assertEqual(
            snapshot["status"]["market_error"],
            "行情刷新失败，请稍后重试",
        )
        self.assertNotIn(secret, stream.getvalue())
        self.assertIn('"exception_type":"RuntimeError"', stream.getvalue())

    def test_explicit_null_rows_are_complete(self):
        second = {"symbol":"BTC-Y","expiry_ms":2_000_000_000_000,"side":"PUT","strike":9000.0,"unit":1.0,"status":"TRADING"}
        self.state.commit_catalog([self.state.contracts[0], second])
        self.state.commit_market({
            "BTC-X":{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":1},
            "BTC-Y":{"bid":90.0,"ask":91.0,"last":89.0,"last_trade_time_ms":1},
        }, 10000.0, 1_700_000_000_000)
        self.state.commit_market({
            "BTC-X":{"bid":None,"ask":101.0,"last":99.0,"last_trade_time_ms":2},
            "BTC-Y":{"bid":None,"ask":None,"last":None,"last_trade_time_ms":2},
        }, 10001.0, 1_700_000_060_000)
        self.assertIsNone(self.state.quotes["BTC-X"]["bid"])
        row = self.state.snapshot()["contracts"][0]
        self.assertIsNone(row["annualized_pct"])
        self.assertIsNone(row["period_return_pct"])
        self.assertIsNone(row["intrinsic_value"])
        self.assertIsNone(row["time_value"])
        self.assertIsNone(row["mark_time_value"])
        self.assertIsNone(row["mark_annualized_pct"])
        self.assertEqual(row["annualized_unavailable_reason"], "invalid_bid")
        self.assertEqual(row["annualized_calculated_at_ms"], 1_700_000_060_000)
        self.assertEqual(self.state.health()["status"], "healthy")

    def test_failed_market_keeps_annualized_generation_then_recovery_replaces_it(self):
        first = self.state.snapshot()["contracts"][0]
        frozen = first["annualized_pct"]
        generation = copy.deepcopy(self.state.annualized_values)
        self.mono.value += 60
        self.state.fail_market("行情刷新失败：timeout")
        failed = self.state.snapshot()["contracts"][0]
        self.assertEqual(failed["annualized_pct"], frozen)
        self.assertEqual(failed["period_return_pct"], first["period_return_pct"])
        self.assertEqual(self.state.annualized_values, generation)
        quote = {"BTC-X":{"bid":200.0,"ask":201.0,"last":199.0,"last_trade_time_ms":2}}
        self.state.commit_market(quote, 10001.0, 1_700_000_060_000)
        recovered = self.state.snapshot()["contracts"][0]
        self.assertNotEqual(recovered["annualized_pct"], frozen)
        self.assertEqual(recovered["calculation_index_price"], 10001.0)
        self.assertEqual(recovered["annualized_calculated_at_ms"], 1_700_000_060_000)

    def test_new_catalog_contract_has_no_old_generation_annualized_value(self):
        new_contract = {"symbol":"BTC-NEW","expiry_ms":2_000_000_000_000,"side":"PUT","strike":9000.0,"unit":1.0,"status":"TRADING"}
        self.state.commit_catalog([self.state.contracts[0], new_contract])
        row = next(item for item in self.state.snapshot()["contracts"] if item["symbol"] == "BTC-NEW")
        self.assertIsNone(row["annualized_pct"])
        self.assertIsNone(row["period_return_pct"])
        self.assertIsNone(row["annualized_calculated_at_ms"])
        self.assertEqual(row["annualized_basis"], "time_value_on_strike")
        self.assertEqual(row["annualized_unavailable_reason"], "market_generation_unavailable")

    def test_expiry_suppresses_frozen_annualized_value(self):
        symbol = self.state.contracts[0]["symbol"]
        expiry = 1_700_000_000_000 + 60_000
        self.state.commit_catalog([{**self.state.contracts[0], "expiry_ms": expiry}])
        self.state.commit_market({symbol:{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":2}}, 10000.0, 1_700_000_000_000)
        self.assertIsNotNone(self.state.snapshot()["contracts"][0]["annualized_pct"])
        self.mono.value += 61
        expired = self.state.snapshot()["contracts"][0]
        self.assertIsNone(expired["annualized_pct"])
        self.assertIsNone(expired["period_return_pct"])
        self.assertEqual(expired["annualized_unavailable_reason"], "expired")

    def test_expired_or_removed_contract_is_not_required(self):
        expired = {**self.state.contracts[0], "expiry_ms":1_700_000_000_000}
        new_contract = {"symbol":"BTC-NEW","expiry_ms":2_000_000_000_000,"side":"PUT","strike":9000.0,"unit":1.0,"status":"TRADING"}
        self.state.commit_catalog([expired, new_contract])
        self.state.commit_market({
            "BTC-NEW":{"bid":10.0,"ask":11.0,"last":9.0,"last_trade_time_ms":2}
        }, 10001.0, 1_700_000_060_000)
        self.assertNotIn("BTC-X", self.state.quotes)

    def test_initial_batch_allows_new_contract_without_row(self):
        wall, mono = Clock(), Clock(10)
        state = server.DashboardState(wall, mono)
        state.commit_catalog([
            {"symbol":"BTC-A","expiry_ms":2_000_000_000_000,"side":"CALL","strike":10000.0,"unit":1.0,"status":"TRADING"},
            {"symbol":"BTC-B","expiry_ms":2_000_000_000_000,"side":"PUT","strike":9000.0,"unit":1.0,"status":"TRADING"},
        ])
        state.commit_market({"BTC-A":{"bid":1.0,"ask":2.0,"last":1.5,"last_trade_time_ms":1}}, 10000.0, 1_700_000_000_000)
        snapshot = state.snapshot()
        missing = next(row for row in snapshot["contracts"] if row["symbol"] == "BTC-B")
        self.assertIsNone(missing["bid"])

    def test_zero_open_interest_snapshot_and_missing_batch_recovery(self):
        symbol = self.state.contracts[0]["symbol"]
        quote = {symbol:{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":2}}
        zero = {symbol:{"open_interest":0.0,"open_interest_time_ms":1_700_000_000_123}}
        self.state.commit_market(quote, 10000.0, 1_700_000_000_000, zero)
        row = self.state.snapshot()["contracts"][0]
        self.assertEqual(row["open_interest"], 0.0)
        self.assertEqual(row["open_interest_time_ms"], 1_700_000_000_123)
        self.assertIsNone(row["annualized_pct"])
        self.assertIsNone(row["period_return_pct"])
        self.assertIsNone(row["intrinsic_value"])
        self.assertIsNone(row["time_value"])
        self.assertIsNone(row["mark_time_value"])
        self.assertIsNone(row["mark_annualized_pct"])
        self.assertEqual(row["annualized_unavailable_reason"], "zero_open_interest")
        fetched = self.state.market_fetched_at
        with self.assertRaisesRegex(ValueError, "openInterest 响应缺少"):
            self.state.commit_market(quote, 10001.0, 1_700_000_060_000, {})
        self.assertEqual(self.state.market_fetched_at, fetched)
        self.assertEqual(self.state.open_interest, zero)
        positive = {symbol:{"open_interest":2.0,"open_interest_time_ms":1_700_000_060_123}}
        self.state.commit_market(quote, 10001.0, 1_700_000_060_000, positive)
        recovered = self.state.snapshot()["contracts"][0]
        self.assertEqual(recovered["open_interest"], 2.0)
        self.assertIsNotNone(recovered["annualized_pct"])

    def test_probability_is_fixed_until_next_commit_and_window_overrides_it(self):
        symbol = self.state.contracts[0]["symbol"]
        expiry = 1_700_000_000_000 + 3600 * 1000
        self.state.commit_catalog([{**self.state.contracts[0], "expiry_ms": expiry}])
        quote = {symbol:{"bid":None,"ask":101.0,"last":99.0,"last_trade_time_ms":2}}
        oi = {symbol:{"open_interest":1.0,"open_interest_time_ms":1}}
        marks = {symbol:{"mark_iv":.5,"risk_free_interest":.05,"delta":.1,"mark_price":100.0}}
        self.state.commit_market(quote, 10000.0, 1_700_000_000_000, oi, marks)
        first = self.state.snapshot()["contracts"][0]
        self.assertIsNone(first["bid"])
        self.assertIsNone(first["mark_time_value"])
        self.assertIsNone(first["mark_annualized_pct"])
        self.assertIsNotNone(first["exercise_probability_pct"])
        self.assertEqual(first["probability_display_state"], "normal")
        fixed = first["exercise_probability_pct"]
        self.mono.value += 1801
        settling = self.state.snapshot()["contracts"][0]
        self.assertEqual(settling["exercise_probability_pct"], fixed)
        self.assertEqual(settling["probability_display_state"], "settling")
        self.mono.value += 1800
        expired = self.state.snapshot()["contracts"][0]
        self.assertIsNone(expired["exercise_probability_pct"])
        self.assertEqual(expired["exercise_probability_unavailable_reason"], "expired")
        self.assertEqual(expired["probability_display_state"], "expired")

    def test_zero_open_interest_disables_probability_and_core_failure_keeps_generation(self):
        symbol = self.state.contracts[0]["symbol"]
        quote = {symbol:{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":2}}
        zero = {symbol:{"open_interest":0.0,"open_interest_time_ms":1}}
        marks = {symbol:{"mark_iv":.5,"risk_free_interest":.05,"delta":.1,"mark_price":100.0}}
        self.state.commit_market(quote, 10000.0, 1_700_000_000_000, zero, marks)
        row = self.state.snapshot()["contracts"][0]
        self.assertIsNone(row["exercise_probability_pct"])
        self.assertEqual(row["exercise_probability_unavailable_reason"], "zero_open_interest")
        generation = self.state.probabilities.copy()
        fetched = self.state.market_fetched_at
        with self.assertRaisesRegex(ValueError, "openInterest"):
            self.state.commit_market(quote, 10001.0, 1_700_000_060_000, {}, {})
        self.assertEqual(self.state.probabilities, generation)
        self.assertEqual(self.state.market_fetched_at, fetched)

    def test_mark_failure_commits_core_without_reusing_old_parameters(self):
        symbol = self.state.contracts[0]["symbol"]
        quote = {symbol:{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":2}}
        oi = {symbol:{"open_interest":1.0,"open_interest_time_ms":1}}
        old_marks = {symbol:{"mark_iv":.5,"risk_free_interest":.05,"delta":.1,"mark_price":100.0}}
        self.state.commit_market(quote, 10000.0, 1_700_000_000_000, oi, old_marks)
        old_annualized = self.state.snapshot()["contracts"][0]["annualized_pct"]
        self.wall.value += 60
        self.mono.value += 60
        self.state.commit_market(quote, 10001.0, 1_700_000_060_000, oi, {}, "行权概率参数刷新失败：timeout")
        snapshot = self.state.snapshot()
        row = snapshot["contracts"][0]
        self.assertIsNone(row["mark_iv"])
        self.assertIsNone(row["exercise_probability_pct"])
        self.assertEqual(row["exercise_probability_unavailable_reason"], "mark_unavailable")
        self.assertNotEqual(row["annualized_pct"], old_annualized)
        self.assertEqual(row["annualized_calculated_at_ms"], 1_700_000_060_000)
        self.assertEqual(row["calculation_index_price"], 10001.0)
        self.assertIn("timeout", snapshot["status"]["mark_warning"])
        self.assertIsNone(snapshot["status"]["market_error"])

    def test_refresh_fetches_one_mark_batch_before_final_time(self):
        wall, mono = Clock(), Clock(10)
        state = server.DashboardState(wall, mono)
        symbol = "BTC-330518-10000-C"
        contract = {"symbol":symbol,"expiry_ms":2_000_000_000_000,"side":"CALL","strike":10000.0,"unit":1.0,"status":"TRADING"}
        state.commit_catalog([contract])
        calls = []
        times = [1_700_000_000_000, 1_700_000_002_000]
        def fetch(path):
            calls.append(path)
            if path.endswith("/ticker"): return [{"symbol":symbol,"bidPrice":"100","askPrice":"101"}]
            if "index?" in path: return {"indexPrice":"10000"}
            if path.endswith("/time"): return {"serverTime":times.pop(0)}
            if "openInterest?" in path: return [{"symbol":symbol,"sumOpenInterest":"1","timestamp":"1"}]
            if path.endswith("/mark"): return [{"symbol":symbol,"markIV":".5","riskFreeInterest":".05","delta":".4","markPrice":"100"}]
            raise AssertionError(path)
        self.assertTrue(server.Refresher(state, fetch).refresh_market())
        self.assertEqual(calls.count("/eapi/v1/mark"), 1)
        self.assertLess(calls.index("/eapi/v1/mark"), len(calls)-1)
        self.assertEqual(calls[-1], "/eapi/v1/time")
        row = state.snapshot()["contracts"][0]
        self.assertEqual(row["probability_calculated_at_ms"], 1_700_000_002_000)

    def test_mark_batch_failure_does_not_fail_core_refresh(self):
        wall, mono = Clock(), Clock(10)
        state = server.DashboardState(wall, mono)
        symbol = "BTC-330518-10000-C"
        state.commit_catalog([{"symbol":symbol,"expiry_ms":2_000_000_000_000,"side":"CALL","strike":10000.0,"unit":1.0,"status":"TRADING"}])
        times = [1_700_000_000_000, 1_700_000_002_000]
        def fetch(path):
            if path.endswith("/ticker"): return [{"symbol":symbol,"bidPrice":"100","askPrice":"101"}]
            if "index?" in path: return {"indexPrice":"10000"}
            if path.endswith("/time"): return {"serverTime":times.pop(0)}
            if "openInterest?" in path: return [{"symbol":symbol,"sumOpenInterest":"1","timestamp":"1"}]
            if path.endswith("/mark"): raise TimeoutError("mark timeout")
            raise AssertionError(path)
        self.assertTrue(server.Refresher(state, fetch).refresh_market())
        snapshot = state.snapshot()
        self.assertEqual(snapshot["index_price"], 10000.0)
        self.assertIsNone(snapshot["contracts"][0]["exercise_probability_pct"])
        self.assertEqual(snapshot["contracts"][0]["exercise_probability_unavailable_reason"], "mark_unavailable")
        self.assertEqual(
            snapshot["status"]["mark_warning"],
            "行权概率参数刷新失败，请稍后重试",
        )
        self.assertIsNone(snapshot["status"]["market_error"])

    def test_open_interest_fetch_merges_expirations_and_skips_expired(self):
        wall, mono = Clock(), Clock(10)
        state = server.DashboardState(wall, mono)
        def milliseconds(value): return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)
        server_time = milliseconds("2026-01-01T00:00:00")
        contracts = [
            {"symbol":"BTC-260110-10000-C","expiry_ms":milliseconds("2026-01-10T08:00:00"),"side":"CALL","strike":10000.0,"unit":1.0,"status":"TRADING"},
            {"symbol":"BTC-260220-11000-P","expiry_ms":milliseconds("2026-02-20T08:00:00"),"side":"PUT","strike":11000.0,"unit":1.0,"status":"TRADING"},
            {"symbol":"BTC-251220-9000-C","expiry_ms":milliseconds("2025-12-20T08:00:00"),"side":"CALL","strike":9000.0,"unit":1.0,"status":"TRADING"},
        ]
        state.commit_catalog(contracts)
        calls = []
        def fetch(path):
            calls.append(path)
            code = path.rsplit("=", 1)[1]
            symbol = next(contract["symbol"] for contract in contracts if f"-{code}-" in contract["symbol"])
            return [{"symbol":symbol,"sumOpenInterest":"1","timestamp":"1700000000000"}]
        result = server.Refresher(state, fetch).fetch_open_interest(server_time)
        self.assertEqual(set(result), {"BTC-260110-10000-C", "BTC-260220-11000-P"})
        self.assertEqual(len(calls), 2)
        self.assertFalse(any("251220" in path for path in calls))

    def test_refresh_market_uses_final_time_after_open_interest_and_recovers(self):
        wall, mono = Clock(), Clock(10)
        state = server.DashboardState(wall, mono)
        symbol = "BTC-330518-10000-C"
        contract = {"symbol":symbol,"expiry_ms":2_000_000_000_000,"side":"CALL","strike":10000.0,"unit":1.0,"status":"TRADING"}
        quote = {symbol:{"bid":100.0,"ask":101.0,"last":99.0,"last_trade_time_ms":1}}
        original_oi = {symbol:{"open_interest":1.0,"open_interest_time_ms":1_700_000_000_000}}
        state.commit_catalog([contract])
        state.commit_market(quote, 10000.0, 1_700_000_000_000, original_oi)
        fetched = state.market_fetched_at
        calls, time_values = [], [1_700_000_010_000, 1_700_000_020_000, 1_700_000_025_000]
        oi_payload = []
        def fetch(path):
            nonlocal oi_payload
            calls.append(path)
            if path.endswith("/ticker"):
                return [{"symbol":symbol,"bidPrice":"110","askPrice":"111"}]
            if "index?" in path:
                return {"indexPrice":"10010"}
            if path.endswith("/time"):
                return {"serverTime":time_values.pop(0)}
            if "openInterest?" in path:
                return oi_payload
            raise AssertionError(path)
        refresher = server.Refresher(state, fetch)
        self.assertFalse(refresher.refresh_market())
        self.assertEqual(state.market_fetched_at, fetched)
        self.assertEqual(state.open_interest, original_oi)
        self.assertEqual(state.market_error, "行情刷新失败，请稍后重试")
        oi_payload = [{"symbol":symbol,"sumOpenInterest":"2.5","timestamp":"1700000024000"}]
        calls.clear()
        self.assertTrue(refresher.refresh_market())
        self.assertEqual(calls[-1], "/eapi/v1/time")
        self.assertEqual(state.server_time_ms, 1_700_000_025_000)
        self.assertEqual(state.open_interest[symbol]["open_interest"], 2.5)
        self.assertIsNone(state.market_error)



if __name__ == "__main__":
    unittest.main()
