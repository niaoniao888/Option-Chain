import unittest

from options_panel.us_equities.metadata_cache import MetadataCache


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


class MetadataCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = MetadataCache(monotonic=self.clock, max_symbols=2)

    def test_ttls_et_day_range_expansion_and_lru(self):
        calls = {"asset": 0, "contracts": 0, "calendar": 0}
        def asset(): calls["asset"] += 1; return {"symbol": "A"}
        def contracts(): calls["contracts"] += 1; return [{"symbol": "C"}]
        def calendar(): calls["calendar"] += 1; return [{"date": "2026-09-25", "open": "09:30", "close": "16:00"}]
        self.cache.asset("A", "2026-09-25", "t1", asset)
        self.cache.asset("A", "2026-09-25", "t2", asset)
        self.cache.contracts("A", ("q",), "2026-09-25", "t1", contracts)
        self.cache.contracts("A", ("q",), "2026-09-25", "t2", contracts)
        self.cache.calendar("A", "2026-09-20", "2026-10-01", "2026-09-25", "t1", calendar)
        self.cache.calendar("A", "2026-09-22", "2026-09-30", "2026-09-25", "t2", calendar)
        self.assertEqual(calls, {"asset": 1, "contracts": 1, "calendar": 1})
        self.cache.calendar("A", "2026-09-20", "2026-10-02", "2026-09-25", "t3", calendar)
        self.clock.value = 301
        self.cache.contracts("A", ("q",), "2026-09-25", "t4", contracts)
        self.cache.asset("A", "2026-09-26", "t5", asset)
        self.assertEqual(calls, {"asset": 2, "contracts": 2, "calendar": 2})
        self.cache.asset("B", "2026-09-26", "t", lambda: {"symbol": "B"})
        self.cache.asset("C", "2026-09-26", "t", lambda: {"symbol": "C"})
        self.assertEqual(self.cache.symbol_count, 2)

    def test_failed_refresh_does_not_pollute_and_values_are_isolated(self):
        query = ("q",)
        value, _ = self.cache.contracts("A", query, "2026-09-25", "old", lambda: [{"symbol": "C", "deliverables": [{"amount": "100"}]}])
        value[0]["deliverables"][0]["amount"] = "1"
        again, stamp = self.cache.contracts("A", query, "2026-09-25", "ignored", lambda: [])
        self.assertEqual(again[0]["deliverables"][0]["amount"], "100")
        self.assertEqual(stamp, "old")
        self.clock.value = 301
        with self.assertRaises(RuntimeError):
            self.cache.contracts("A", query, "2026-09-25", "bad", lambda: (_ for _ in ()).throw(RuntimeError("page two failed")))
        restored, stamp = self.cache.contracts("A", query, "2026-09-25", "new", lambda: [{"symbol": "C2"}])
        self.assertEqual(restored, [{"symbol": "C2"}])
        self.assertEqual(stamp, "new")

    def test_clear_invalidates_credentials_scope(self):
        calls = []
        loader = lambda: calls.append(1) or {"symbol": "A"}
        self.cache.asset("A", "2026-09-25", "one", loader)
        self.cache.clear()
        self.cache.asset("A", "2026-09-25", "two", loader)
        self.assertEqual(len(calls), 2)

    def test_contract_queries_stay_bounded_and_failed_replacement_preserves_current(self):
        for day in range(20):
            query = ("gte", f"2026-10-{day + 1:02d}")
            rows, _ = self.cache.contracts("A", query, f"2026-10-{day + 1:02d}", str(day),
                                           lambda day=day: [{"symbol": f"C{day}"}])
            self.assertEqual(rows[0]["symbol"], f"C{day}")
            self.assertEqual(len(self.cache._items["A"].contracts), 1)
        current = next(iter(self.cache._items["A"].contracts.values()))
        with self.assertRaises(RuntimeError):
            self.cache.contracts("A", ("gte", "2026-11-01"), "2026-11-01", "bad",
                                 lambda: (_ for _ in ()).throw(RuntimeError("partial page")))
        self.assertEqual(len(self.cache._items["A"].contracts), 1)
        self.assertIs(next(iter(self.cache._items["A"].contracts.values())), current)

    def test_calendar_rejects_mixed_bad_reverse_and_duplicate_batches_without_pollution(self):
        good = [{"date": "2026-09-25", "open": "09:30", "close": "16:00"}]
        cached, stamp = self.cache.calendar("A", "2026-09-25", "2026-09-25", "2026-09-25", "good", lambda: good)
        self.assertEqual((cached, stamp), (good, "good"))
        bad_batches = [
            [{"date": "2026-09-24", "open": "09:30", "close": "16:00"},
             {"date": "2026-09-25", "open": "BAD", "close": "16:00"},
             {"date": "2026-09-28", "open": "09:30", "close": "16:00"}],
            [{"date": "2026-09-26", "open": "16:00", "close": "09:30"}],
            [{"date": "2026-09-26", "open": "09:30", "close": "16:00"},
             {"date": "2026-09-26", "open": "09:30", "close": "13:00"}],
            [{"date": "2026-02-30", "open": "09:30", "close": "16:00"}],
            [{"date": "2026-09-26", "open": "09:30+00:00", "close": "16:00+00:00"}],
        ]
        for index, batch in enumerate(bad_batches):
            self.clock.value = 21601 + index
            with self.assertRaises(ValueError):
                self.cache.calendar("A", "2026-09-25", "2026-09-28", "2026-09-25", "bad", lambda batch=batch: batch)
            item = self.cache._items["A"].calendar
            self.assertEqual(item.value, good)
            self.assertEqual(item.fetched_at, "good")

    def test_exact_ttl_boundaries_expire_without_et_day_change(self):
        calls = {"contracts": 0, "asset": 0, "calendar": 0}
        def contracts(): calls["contracts"] += 1; return [{"symbol": f"C{calls['contracts']}"}]
        def asset(): calls["asset"] += 1; return {"symbol": f"A{calls['asset']}"}
        def calendar():
            calls["calendar"] += 1
            return [{"date": "2026-09-25", "open": "09:30", "close": "16:00", "version": calls["calendar"]}]
        query = ("full-chain",)
        self.cache.contracts("A", query, "2026-09-25", "t0", contracts)
        self.clock.value = 299.999
        rows, stamp = self.cache.contracts("A", query, "2026-09-25", "hit", contracts)
        self.assertEqual((rows[0]["symbol"], stamp, calls["contracts"]), ("C1", "t0", 1))
        self.clock.value = 300.0
        rows, stamp = self.cache.contracts("A", query, "2026-09-25", "t300", contracts)
        self.assertEqual((rows[0]["symbol"], stamp, calls["contracts"]), ("C2", "t300", 2))

        self.clock.value = 0
        self.cache.asset("B", "2026-09-25", "a0", asset)
        self.clock.value = 86399.999
        _, stamp = self.cache.asset("B", "2026-09-25", "hit", asset)
        self.assertEqual((stamp, calls["asset"]), ("a0", 1))
        self.clock.value = 86400.0
        _, stamp = self.cache.asset("B", "2026-09-25", "a86400", asset)
        self.assertEqual((stamp, calls["asset"]), ("a86400", 2))

        self.clock.value = 0
        self.cache.calendar("D", "2026-09-25", "2026-09-25", "2026-09-25", "c0", calendar)
        self.clock.value = 21599.999
        _, stamp = self.cache.calendar("D", "2026-09-25", "2026-09-25", "2026-09-25", "hit", calendar)
        self.assertEqual((stamp, calls["calendar"]), ("c0", 1))
        self.clock.value = 21600.0
        rows, stamp = self.cache.calendar("D", "2026-09-25", "2026-09-25", "2026-09-25", "c21600", calendar)
        self.assertEqual((rows[0]["version"], stamp, calls["calendar"]), (2, "c21600", 2))


if __name__ == "__main__": unittest.main()

