import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from options_panel.us_equities.market_calendar import (calendar_sessions, expiry_cutoff_utc, latest_completed_session_key,
                             market_status, quote_session_key)

class CalendarTests(unittest.TestCase):
    def test_dst_and_early_close(self):
        sessions=calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"13:00"},
                                    {"date":"2026-11-06","open":"09:30","close":"16:00"}])
        self.assertEqual(expiry_cutoff_utc("2026-07-02",sessions),"2026-07-02T17:00:00Z")
        self.assertEqual(expiry_cutoff_utc("2026-11-06",sessions),"2026-11-06T21:00:00Z")
        self.assertEqual(market_status(datetime(2026,7,2,16,tzinfo=timezone.utc),sessions),"OPEN")
        self.assertEqual(market_status(datetime(2026,7,2,18,tzinfo=timezone.utc),sessions),"CLOSED")

    def test_empty_calendar_unverified_and_quote_session(self):
        self.assertEqual(market_status(datetime.now(timezone.utc),{}),"UNVERIFIED")
        sessions=calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"16:00"}])
        self.assertEqual(quote_session_key(datetime(2026,7,2,14,tzinfo=timezone.utc),sessions),"2026-07-02")
        self.assertIsNone(quote_session_key(datetime(2026,7,2,10,tzinfo=timezone.utc),sessions))

    def test_latest_completed_session_excludes_older_and_future_sessions(self):
        sessions=calendar_sessions([{"date":"2026-07-01","open":"09:30","close":"16:00"},
                                    {"date":"2026-07-02","open":"09:30","close":"13:00"},
                                    {"date":"2026-07-06","open":"09:30","close":"16:00"}])
        self.assertEqual(latest_completed_session_key(datetime(2026,7,4,tzinfo=timezone.utc),sessions),"2026-07-02")

if __name__=="__main__": unittest.main()

