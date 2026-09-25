import http.client
import io
import json
import socket
import ssl
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_panel.us_equities import alpaca_adapter as aa
from options_panel.us_equities import network_diagnostics as nd


class Response:
    status = 200
    def __init__(self, payload=b"{}"): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, _limit): return self.payload


class CaptureLog:
    def __init__(self): self.rows = []
    def record(self, **row): self.rows.append(row)


class RetryTests(unittest.TestCase):
    def test_transient_failure_retries_once_and_records_both_attempts(self):
        calls, sleeps, log = [], [], CaptureLog()
        def opener(_request, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise urllib.error.URLError(socket.gaierror(11001, "secret host text"))
            return Response(b'{"ok":true}')
        client = aa.AlpacaHttp("key", "secret", opener=opener, logger=log, sleep=sleeps.append)
        self.assertEqual(client.get(aa.PAPER_HOST, "/v2/calendar"), {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.25])
        self.assertEqual([(row["attempt"], row["error_kind"]) for row in log.rows], [(1, "dns"), (2, None)])
        self.assertNotIn("secret", json.dumps(log.rows))

    def test_success_then_tls_handshake_failure_and_retry_success_are_visible(self):
        sequence = [Response(), urllib.error.URLError(ssl.SSLError("private tls text")), Response()]
        log = CaptureLog()
        def opener(_request, timeout):
            item = sequence.pop(0)
            if isinstance(item, BaseException): raise item
            return item
        client = aa.AlpacaHttp("k", "s", opener=opener, logger=log, sleep=lambda _x:None)
        client.get(aa.PAPER_HOST, "/v2/calendar")
        client.get(aa.PAPER_HOST, "/v2/calendar")
        self.assertEqual([(row["attempt"], row["error_kind"]) for row in log.rows],
                         [(1, None), (1, "tls_handshake"), (2, None)])
        self.assertNotIn("private", json.dumps(log.rows))

    def test_incomplete_read_retries_but_nonretryable_classes_do_not(self):
        count = 0
        def incomplete(_request, timeout):
            nonlocal count
            count += 1
            if count == 1: raise http.client.IncompleteRead(b"private partial", 99)
            return Response()
        log = CaptureLog()
        aa.AlpacaHttp("k", "s", opener=incomplete, logger=log, sleep=lambda _x:None).get(aa.PAPER_HOST, "/v2/calendar")
        self.assertEqual(count, 2)
        self.assertEqual(log.rows[0]["error_kind"], "connection")
        self.assertNotIn("partial", json.dumps(log.rows))

        cases = [
            (lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError(req.full_url, 400, "body", {}, io.BytesIO(b"private"))), aa.AlpacaError),
            (lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError(req.full_url, 401, "body", {}, None)), aa.AuthorizationRequired),
            (lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError(req.full_url, 429, "body", {"Retry-After":"60"}, None)), aa.RateLimited),
            (lambda req, timeout: (_ for _ in ()).throw(urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate private text"))), aa.NetworkError),
        ]
        for opener, expected in cases:
            attempts = []
            def counted(req, timeout, inner=opener): attempts.append(1); return inner(req, timeout)
            with self.subTest(expected=expected), self.assertRaises(expected):
                aa.AlpacaHttp("k", "s", opener=counted, logger=CaptureLog(), sleep=lambda _x:None).get(aa.PAPER_HOST, "/v2/calendar")
            self.assertEqual(len(attempts), 1)


class LogTests(unittest.TestCase):
    def test_daily_retention_cap_dedup_and_schema_are_bounded(self):
        now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "us-options-network-2026-06-17.jsonl").write_text("old", encoding="utf-8")  # today - 100
            keep = root / "us-options-network-2026-06-18.jsonl"  # today - 99
            keep.write_text("keep", encoding="utf-8")
            future = root / "us-options-network-2026-09-26.jsonl"
            future.write_text("future", encoding="utf-8")
            unrelated = root / "other-2020-01-01.jsonl"
            unrelated.write_text("keep", encoding="utf-8")
            log = nd.SafeJsonlLog(root, wall_clock=lambda:now, monotonic=lambda:10, suppress_seconds=30)
            log.record(endpoint="market_calendar", attempt=1, duration_ms=12, status=200, error_kind=None)
            log.record(endpoint="market_calendar", attempt=1, duration_ms=13, status=200, error_kind=None)
            log.record(endpoint="market_calendar", attempt=2, duration_ms=14, status=200, error_kind=None)
            target = root / "us-options-network-2026-09-25.jsonl"
            rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(set(rows[0]), {"time","endpoint","attempt","duration_ms","status","error_kind","errno"})
            self.assertFalse((root / "us-options-network-2026-06-17.jsonl").exists())
            self.assertFalse(future.exists())
            self.assertTrue(keep.exists() and unrelated.exists())
            with mock.patch.object(nd, "MAX_FILE_BYTES", target.stat().st_size):
                log.record(endpoint="market_calendar", attempt=1, duration_ms=1, status=500, error_kind="http_5xx")
            self.assertEqual(len(target.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__": unittest.main()

