import io
import json
import logging
import ssl
import sys
import tempfile
import urllib.error
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import legacy_support as server
from options_panel.logging import JsonFormatter


class Response:
    def __init__(self, body=b'{"ok":true}', status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        if isinstance(self.body, BaseException):
            raise self.body
        return self.body


class FetchRetryTests(unittest.TestCase):
    def call(self, effects):
        with mock.patch.object(server.urllib.request, "urlopen", side_effect=effects) as opened, \
             mock.patch.object(server.time, "sleep") as slept:
            result = server.fetch_json("/eapi/v1/time")
        return result, opened.call_count, slept.call_count

    def test_ssl_eof_retries_once_and_recovers(self):
        error = urllib.error.URLError(ssl.SSLEOFError(8, "EOF"))
        result, calls, sleeps = self.call([error, Response()])
        self.assertEqual(result, {"ok": True})
        self.assertEqual((calls, sleeps), (2, 1))

    def test_ssl_eof_exhaustion_stops_after_two_attempts(self):
        error = urllib.error.URLError(ssl.SSLEOFError(8, "EOF"))
        with mock.patch.object(server.urllib.request, "urlopen", side_effect=[error, error]) as opened, \
             mock.patch.object(server.time, "sleep"):
            with self.assertRaises(urllib.error.URLError):
                server.fetch_json("/eapi/v1/ticker")
        self.assertEqual(opened.call_count, 2)

    def test_raw_read_eof_and_incomplete_read_are_retried(self):
        for error in (ssl.SSLEOFError(8, "raw EOF"), server.http.client.IncompleteRead(b"partial", 10)):
            with self.subTest(error=type(error).__name__):
                result, calls, sleeps = self.call([Response(error), Response()])
                self.assertEqual(result, {"ok": True})
                self.assertEqual((calls, sleeps), (2, 1))

    def test_raw_timeout_and_connection_reset_are_retried(self):
        for error in (TimeoutError("read timed out"), ConnectionResetError("reset by peer")):
            with self.subTest(error=type(error).__name__):
                result, calls, sleeps = self.call([Response(error), Response()])
                self.assertEqual(result, {"ok": True})
                self.assertEqual((calls, sleeps), (2, 1))

    def test_selected_5xx_retries(self):
        error = urllib.error.HTTPError("https://example.invalid", 503, "busy", {}, io.BytesIO(b"secret-body"))
        result, calls, sleeps = self.call([error, Response()])
        self.assertEqual(result, {"ok": True})
        self.assertEqual((calls, sleeps), (2, 1))

    def test_certificate_404_and_bad_json_do_not_retry(self):
        cases = [
            urllib.error.URLError(ssl.SSLCertVerificationError(1, "bad certificate")),
            urllib.error.HTTPError("https://example.invalid", 404, "missing", {}, None),
            None,
        ]
        for error in cases:
            effect = error if error is not None else Response(b"not-json")
            with self.subTest(error=type(error).__name__ if error else "json"), \
                 mock.patch.object(server.urllib.request, "urlopen", side_effect=[effect]) as opened, \
                 mock.patch.object(server.time, "sleep") as slept:
                with self.assertRaises(Exception):
                    server.fetch_json("/eapi/v1/index")
                self.assertEqual(opened.call_count, 1)
                slept.assert_not_called()

    def test_http_429_does_not_retry(self):
        error = urllib.error.HTTPError("https://example.invalid", 429, "rate limited", {}, None)
        with mock.patch.object(server.urllib.request, "urlopen", side_effect=[error]) as opened, \
             mock.patch.object(server.time, "sleep") as slept:
            with self.assertRaises(urllib.error.HTTPError):
                server.fetch_json("/eapi/v1/ticker")
        self.assertEqual(opened.call_count, 1)
        slept.assert_not_called()

    def test_upstream_exception_detail_is_not_logged(self):
        secret = "token=FAKE-CREDENTIAL-123"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        server.LOGGER.addHandler(handler)
        self.addCleanup(server.LOGGER.removeHandler, handler)
        error = TimeoutError(f"https://example.invalid/?{secret}")
        with mock.patch.object(
            server.urllib.request, "urlopen", side_effect=[error, error]
        ), mock.patch.object(server.time, "sleep"), self.assertRaises(TimeoutError):
            server.fetch_json("/eapi/v1/ticker")
        self.assertNotIn(secret, stream.getvalue())
        self.assertIn("TimeoutError", stream.getvalue())

    def test_top_level_semantics_and_ssl_veto_override_transient_context(self):
        rate_limited = urllib.error.HTTPError("https://example.invalid", 429, "limited", {}, None)
        rate_limited.__context__ = TimeoutError("nested timeout")
        bad_json = json.JSONDecodeError("bad", "x", 0)
        bad_json.__context__ = ConnectionResetError("nested reset")
        service_error = urllib.error.HTTPError("https://example.invalid", 503, "busy", {}, None)
        service_error.__context__ = ssl.SSLCertVerificationError(1, "bad certificate")
        for error in (rate_limited, bad_json, service_error):
            with self.subTest(error=type(error).__name__, detail=str(error)), \
                 mock.patch.object(server.urllib.request, "urlopen", side_effect=[error]) as opened, \
                 mock.patch.object(server.time, "sleep") as slept:
                with self.assertRaises(type(error)):
                    server.fetch_json("/eapi/v1/ticker")
                self.assertEqual(opened.call_count, 1)
                slept.assert_not_called()


class LoopReliabilityTests(unittest.TestCase):
    def test_huge_failure_count_caps_without_overflow(self):
        self.assertEqual(server.Refresher.backoff(60, 1025), server.MAX_BACKOFF)
        self.assertEqual(server.Refresher.backoff(60, 10 ** 6), server.MAX_BACKOFF)

    def test_outer_loop_survives_one_exception_and_recovers(self):
        class Event:
            stopped = False
            waits = []

            def is_set(self):
                return self.stopped

            def wait(self, delay):
                self.waits.append(delay)
                return self.stopped

        class State:
            def __init__(self):
                self.calls = 0
                self.errors = []

            def monotonic(self):
                return 10.0

            def refresh_deadlines(self):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("one round broke")
                return 999.0, 0.0

            def fail_market(self, message):
                self.errors.append(message)

            def refresh_log_stats(self):
                return {
                    "contract_count": 0, "quote_count": 0, "open_interest_count": 0,
                    "mark_count": 0, "catalog_error": None, "market_error": None,
                    "mark_warning": None,
                }

            def schedule_market(self, when):
                self.scheduled = when

        class RecoveringRefresher(server.Refresher):
            def refresh_market(self):
                self.stop_event.stopped = True
                return True

        state = State()
        refresher = RecoveringRefresher(state, lambda path: None)
        refresher.stop_event = Event()
        refresher.run()
        self.assertEqual(state.errors[0], "后台刷新暂时不可用，请稍后重试")
        self.assertEqual(refresher.stop_event.waits[0], 5.0)
        self.assertEqual(state.scheduled, 70.0)


if __name__ == "__main__":
    unittest.main()
