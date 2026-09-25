import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from options_panel.us_equities.model import NormalizedContract, annualized_pct, calculate_contract

class ModelTests(unittest.TestCase):
    def contract(self, **changes):
        base=dict(contract_symbol="AAPL-C",underlying="AAPL",side="CALL",strike=90.0,bid=12.0,ask=12.2,
                  multiplier=100,standard=True,expires_at_utc="2026-10-24T20:00:00Z",expiry_verified=True,
                  expiration_date="2026-10-24",quote_time_utc="2026-09-24T19:00:00Z",
                  quote_valid_until_utc="2026-09-24T20:02:00Z",
                  standard_reason="verified_standard_100_share_contract")
        base.update(changes); return NormalizedContract(**base)

    def test_call_and_put_use_confirmed_time_value_denominators(self):
        seconds=30*86400
        self.assertAlmostEqual(annualized_pct(12,90,100,"CALL",seconds,100),24.3333333333)
        self.assertAlmostEqual(annualized_pct(12,110,100,"PUT",seconds,100),2/110*365/30*100)
        call=calculate_contract(self.contract(),underlying_price=100,market_status="CLOSED",
                                calculated_at_utc="2026-09-24T20:00:00Z",now_utc=datetime(2026,9,24,20,tzinfo=timezone.utc))
        self.assertEqual(call["time_value"],2)
        self.assertEqual(call["capital_base"],100)
        self.assertAlmostEqual(call["period_return_pct"],2)
        self.assertTrue(call["ranking_eligible"])

    def test_zero_negative_null_adjusted_and_bool_fail_closed(self):
        self.assertIsNone(annualized_pct(0,90,100,"CALL",86400,100))
        self.assertIsNone(annualized_pct(True,90,100,"CALL",86400,100))
        negative=calculate_contract(self.contract(bid=9),underlying_price=100,market_status="CLOSED",
                                    calculated_at_utc="2026-09-24T20:00:00Z",now_utc=datetime(2026,9,24,20,tzinfo=timezone.utc))
        self.assertEqual(negative["calculation_status"],"non_positive_time_value")
        self.assertIsNone(negative["annualized_pct"])
        adjusted=calculate_contract(self.contract(standard=False,multiplier=None,standard_reason="adjusted_contract"),
                                    underlying_price=100,market_status="CLOSED",calculated_at_utc="2026-09-24T20:00:00Z",
                                    now_utc=datetime(2026,9,24,20,tzinfo=timezone.utc))
        self.assertEqual(adjusted["calculation_status"],"adjusted_contract")

    def test_invalid_ask_or_inverted_spread_never_calculates(self):
        now=datetime(2026,9,24,20,tzinfo=timezone.utc)
        for ask,status in ((None,"no_valid_ask"),(0,"no_valid_ask"),(11,"inverted_quote"),(True,"no_valid_ask")):
            with self.subTest(ask=ask):
                row=calculate_contract(self.contract(ask=ask),underlying_price=100,market_status="CLOSED",
                                       calculated_at_utc="2026-09-24T20:00:00Z",now_utc=now)
                self.assertEqual(row["calculation_status"],status)
                self.assertFalse(row["ranking_eligible"])

    def test_expired_uses_real_now_even_when_snapshot_basis_is_old(self):
        row=calculate_contract(self.contract(expires_at_utc="2026-09-25T20:00:00Z"),underlying_price=100,
                               market_status="CLOSED",calculated_at_utc="2026-09-24T20:00:00Z",
                               now_utc=datetime(2026,9,26,tzinfo=timezone.utc))
        self.assertEqual(row["calculation_status"],"expired")
        self.assertIsNone(row["annualized_pct"])

    def test_quote_gate_and_unknown_market_status(self):
        gated=calculate_contract(self.contract(quote_eligible=False,quote_reason="stock_option_quote_skew"),underlying_price=100,
                                 market_status="OPEN",calculated_at_utc="2026-09-24T20:00:00Z",
                                 now_utc=datetime(2026,9,24,20,tzinfo=timezone.utc))
        self.assertEqual(gated["calculation_status"],"stock_option_quote_skew")
        unknown=calculate_contract(self.contract(),underlying_price=100,market_status="UNVERIFIED",
                                   calculated_at_utc="2026-09-24T20:00:00Z",
                                   now_utc=datetime(2026,9,24,20,tzinfo=timezone.utc))
        self.assertEqual(unknown["calculation_status"],"market_status_unverified")

if __name__=="__main__": unittest.main()

