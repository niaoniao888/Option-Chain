import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from options_panel.us_equities.request_throttle import GlobalRequestGate
from options_panel.us_equities.alpaca_adapter import AlpacaHttp, RateLimited


class Clock:
    def __init__(self, value=0.0): self.value=value
    def __call__(self): return self.value
    def sleep(self, seconds): self.value += seconds


class RequestGateTests(unittest.TestCase):
    def test_attempts_start_one_second_apart_and_count_only_after_wait(self):
        clock=Clock(); gate=GlobalRequestGate(monotonic=clock,sleep=clock.sleep)
        self.assertEqual(gate.acquire(),0)
        self.assertEqual(gate.diagnostics()["request_count"],1)
        self.assertEqual(gate.acquire(),1)
        self.assertEqual(clock.value,1)
        self.assertEqual(gate.diagnostics()["request_count"],2)

    def test_global_pause_is_rechecked_before_start(self):
        clock=Clock(); gate=GlobalRequestGate(monotonic=clock,sleep=clock.sleep)
        gate.acquire(); gate.pause(90)
        self.assertEqual(gate.ready_in(),90)
        self.assertEqual(gate.acquire(),90)
        self.assertEqual(gate.diagnostics()["request_count"],2)

    def test_http_429_pauses_a_different_client_and_counts_actual_attempts(self):
        clock=Clock(); gate=GlobalRequestGate(monotonic=clock,sleep=clock.sleep)
        def limited(request,timeout):
            raise urllib.error.HTTPError(request.full_url,429,"limited",{"Retry-After":"75"},None)
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*_args): return False
            def read(self,_limit): return b'{}'
        first=AlpacaHttp("k","s",opener=limited,monotonic=clock,sleep=clock.sleep,request_gate=gate)
        second=AlpacaHttp("k","s",opener=lambda _request,timeout:Response(),monotonic=clock,sleep=clock.sleep,request_gate=gate)
        with self.assertRaises(RateLimited): first.get("data.alpaca.markets","/v2/stocks/AAPL/quotes/latest")
        self.assertEqual(gate.diagnostics()["request_count"],1)
        second.get("data.alpaca.markets","/v2/stocks/AAPL/quotes/latest")
        self.assertEqual(clock.value,75)
        self.assertEqual(gate.diagnostics()["request_count"],2)


if __name__ == "__main__": unittest.main()

