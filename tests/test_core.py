from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from options_panel.domain.calculations import annualized_yield, exercise_probability, moneyness
from options_panel.runtime.refresher import ProcessLock
from options_panel.runtime.snapshot import DashboardState


class CoreTests(unittest.TestCase):
    def test_formula_and_moneyness(self):
        now = 1_700_000_000_000
        self.assertAlmostEqual(annualized_yield("CALL", 500, 100000, 100000, 1, now + 30 * 86400 * 1000, now), 6.0833333333, places=8)
        self.assertEqual(moneyness("PUT", 10100, 10000)[0], "ITM")
        self.assertIsNone(annualized_yield("CALL", 0, 10000, 10000, 1, now + 1000, now))

    def test_probability_validation(self):
        value, reason = exercise_probability("CALL", 100, 100, 1_800_000_000_000, 1_700_000_000_000, .5, .01, 1)
        self.assertIsNone(reason)
        self.assertGreater(value, 0)
        self.assertEqual(exercise_probability("CALL", 100, 100, 1, 2, .5, .01, 1), (None, "expired"))

    def test_failed_refresh_retains_snapshot(self):
        state = DashboardState()
        state.commit_catalog([])
        state.commit_market({}, 85000, 1_700_000_000_000, {}, {})
        before = state.snapshot()
        state.fail_market("temporary")
        after = state.snapshot()
        self.assertEqual(after["index_price"], before["index_price"])
        self.assertEqual(after["market_generation_ms"], before["market_generation_ms"])
        self.assertEqual(after["status"]["status"], "degraded")

    def test_process_lock_is_exclusive_and_reusable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "collector.lock"
            first, second = ProcessLock(path), ProcessLock(path)
            first.acquire()
            with self.assertRaisesRegex(RuntimeError, "already active"):
                second.acquire()
            first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
