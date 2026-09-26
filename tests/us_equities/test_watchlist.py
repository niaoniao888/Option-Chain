import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from options_panel.us_equities.watchlist_store import (
    WatchlistCapacityError,
    WatchlistStore,
    normalize_symbol,
)


class WatchlistTests(unittest.TestCase):
    def test_symbol_validation_rejects_non_strings_and_bad_values(self):
        for value in (None, True, "", "A B", "../A", "_A"):
            with self.subTest(value=value), self.assertRaises(ValueError): normalize_symbol(value)
        self.assertEqual(normalize_symbol(" brk.b "), "BRK.B")

    def test_empty_watchlist_persists_without_restoring_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"watchlist.json"
            store = WatchlistStore(path); self.assertEqual(store.list(), ["SPCX"])
            store.remove("SPCX"); self.assertEqual(store.list(), [])
            self.assertEqual(WatchlistStore(path).list(), [])

    def test_failed_atomic_replace_does_not_change_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WatchlistStore(Path(folder)/"watchlist.json")
            with mock.patch("options_panel.us_equities.watchlist_store.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
                store.add("AAPL")
            self.assertEqual(store.list(), ["SPCX"])

    def test_over_limit_existing_watchlist_can_be_read_and_reduced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "watchlist.json"
            symbols = [f"S{index}" for index in range(4)]
            path.write_bytes(WatchlistStore._encode(symbols))
            store = WatchlistStore(path)
            with mock.patch(
                "options_panel.us_equities.watchlist_store.MAX_WATCHLIST_SYMBOLS", 2
            ):
                self.assertEqual(store.list(), symbols)
                with self.assertRaises(WatchlistCapacityError):
                    store.add("EXTRA")
                store.remove("S3")
                self.assertEqual(store.list(), symbols[:3])

