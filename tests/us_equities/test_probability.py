import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from options_panel.us_equities.market_service import MarketService
from options_panel.us_equities.model import NormalizedContract, calculate_contract, exercise_probability


BASIS = "2026-01-01T00:00:00Z"
EXPIRY = "2027-01-01T00:00:00Z"


class Clock:
    def __init__(self, value): self.value = value
    def __call__(self): return self.value


class ProbabilityTests(unittest.TestCase):
    def contract(self, **changes):
        values = dict(contract_symbol="TEST-C", underlying="TEST", side="CALL", strike=100.0,
                      bid=2.0, ask=2.2, multiplier=100, standard=True,
                      expires_at_utc=EXPIRY, expiry_verified=True, expiration_date="2027-01-01",
                      implied_volatility=0.2, open_interest=None, quote_eligible=True,
                      quote_valid_until_utc="2026-01-01T00:02:00Z")
        values.update(changes)
        return NormalizedContract(**values)

    def calculate(self, contract=None, **changes):
        return calculate_contract(contract or self.contract(), underlying_price=changes.get("spot", 100.0),
                                  market_status=changes.get("market", "OPEN"), calculated_at_utc=BASIS,
                                  now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_atm_call_put_are_complements_and_not_delta(self):
        call, call_reason = exercise_probability(2, 2.2, "CALL", 100, 100, EXPIRY, BASIS, 0.2)
        put, put_reason = exercise_probability(2, 2.2, "PUT", 100, 100, EXPIRY, BASIS, 0.2)
        self.assertIsNone(call_reason); self.assertIsNone(put_reason)
        self.assertAlmostEqual(call + put, 100.0, places=10)
        self.assertAlmostEqual(call, 50 * math.erfc(0.1 / math.sqrt(2)), places=10)
        row = self.calculate(self.contract(delta=0.9))
        self.assertNotAlmostEqual(row["exercise_probability_pct"], row["delta"] * 100)
        self.assertEqual(row["probability_basis_utc"], BASIS)
        self.assertEqual(row["probability_assumptions"], {"risk_free_rate": 0.0, "dividend_yield": 0.0})

    def test_itm_otm_iv_and_open_interest_gates(self):
        itm, _ = exercise_probability(2, 2.2, "CALL", 120, 100, EXPIRY, BASIS, 0.2)
        otm, _ = exercise_probability(2, 2.2, "CALL", 80, 100, EXPIRY, BASIS, 0.2)
        self.assertGreater(itm, 50); self.assertLess(otm, 50)
        for iv in (None, 0, -0.2):
            with self.subTest(iv=iv):
                value, reason = exercise_probability(2, 2.2, "CALL", 100, 100, EXPIRY, BASIS, iv)
                self.assertIsNone(value); self.assertEqual(reason, "invalid_iv")
        self.assertEqual(exercise_probability(2, 2.2, "CALL", 100, 100, EXPIRY, BASIS, 1e308),
                         (None, "model_error"))
        extreme, extreme_reason = exercise_probability(2, 2.2, "CALL", 1e308, 1e-308,
                                                       EXPIRY, BASIS, 0.2)
        self.assertEqual(extreme, 100.0); self.assertIsNone(extreme_reason)
        self.assertEqual(exercise_probability(2, 2.2, "CALL", 100, 100, EXPIRY, BASIS, 0.2, 0),
                         (None, "zero_open_interest"))
        self.assertIsNotNone(exercise_probability(2, 2.2, "CALL", 100, 100, EXPIRY, BASIS, 0.2, None)[0])

    def test_probability_is_independent_of_tv_but_respects_outer_gates(self):
        negative_tv = self.calculate(self.contract(strike=90, bid=9, ask=9.2))
        self.assertEqual(negative_tv["calculation_status"], "non_positive_time_value")
        self.assertIsNotNone(negative_tv["exercise_probability_pct"])
        adjusted = self.calculate(self.contract(standard=False, multiplier=None, standard_reason="adjusted_contract"))
        self.assertIsNone(adjusted["exercise_probability_pct"])
        self.assertEqual(adjusted["probability_reason"], "adjusted_contract")
        invalid_quote = self.calculate(self.contract(ask=0))
        self.assertIsNone(invalid_quote["exercise_probability_pct"])
        self.assertEqual(invalid_quote["probability_reason"], "no_valid_ask")
        unverified = self.calculate(self.contract(), market="UNVERIFIED")
        self.assertEqual(unverified["probability_reason"], "market_status_unverified")

    def test_known_spcx_sample_is_distinct_from_delta(self):
        row = calculate_contract(
            self.contract(contract_symbol="SPCX261002C00140000", underlying="SPCX", strike=140,
                          bid=9, ask=9.2, expires_at_utc="2026-10-02T20:00:00Z",
                          expiration_date="2026-10-02", implied_volatility=0.2776,
                          delta=0.9518, open_interest=523),
            underlying_price=148.245, market_status="CLOSED",
            calculated_at_utc="2026-09-24T19:59:59.933771Z",
            now_utc=datetime(2026, 9, 24, 20, tzinfo=timezone.utc))
        self.assertAlmostEqual(row["exercise_probability_pct"], 91.49427613731062, places=10)
        self.assertNotAlmostEqual(row["exercise_probability_pct"], row["delta"] * 100)

    def test_expired_probability_is_cleared_without_recalculation(self):
        class Adapter:
            ready = True
            source_name = "synthetic"
            error = None
            def fetch(self, _symbol):
                if self.error: raise self.error
                return {"market_status": "OPEN", "calculated_at": BASIS, "underlying_price": 100.0,
                        "contracts": [ProbabilityTests().contract()]}

        wall = Clock(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
        mono = Clock(1.0)
        adapter = Adapter()
        service = MarketService(adapter, wall_clock=wall, monotonic=mono)
        self.assertTrue(service.refresh("TEST"))
        first = service.snapshot("TEST")["contracts"][0]
        frozen = first["exercise_probability_pct"]
        wall.value += 86400; mono.value += 1
        self.assertEqual(service.snapshot("TEST")["contracts"][0]["exercise_probability_pct"], frozen)
        adapter.error = TimeoutError("synthetic offline")
        self.assertFalse(service.refresh("TEST"))
        failed = service.snapshot("TEST")
        self.assertEqual(failed["contracts"][0]["exercise_probability_pct"], frozen)
        self.assertEqual(failed["fetch_health"], "failed")
        wall.value = datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()
        expired = service.snapshot("TEST")["contracts"][0]
        self.assertIsNone(expired["exercise_probability_pct"])
        self.assertEqual(expired["probability_reason"], "expired")


if __name__ == "__main__": unittest.main()

