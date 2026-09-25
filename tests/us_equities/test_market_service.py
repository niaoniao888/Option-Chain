import sys
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from options_panel.us_equities.alpaca_adapter import AlpacaError, AuthorizationRequired, RateLimited
from options_panel.us_equities.market_service import MarketService
from options_panel.us_equities.request_throttle import GlobalRequestGate

class Clock:
    def __init__(self,value): self.value=value
    def __call__(self): return self.value

class FakeAdapter:
    ready=True; source_name="测试源"
    def __init__(self): self.error=None
    def fetch(self,symbol):
        if self.error: raise self.error
        return {"market_status":"CLOSED","calculated_at":"2026-09-24T20:00:00Z","quote_time":"2026-09-24T19:59:00Z",
                "source_delay_label":"测试","calculation_basis":"冻结快照","underlying_price":100.0,
                "contracts":[{"contract_symbol":symbol+"-C","underlying":symbol,"side":"CALL","strike":90.0,"bid":12.0,"ask":12.1,
                "multiplier":100,"standard":True,"expires_at_utc":"2026-10-24T20:00:00Z","expiry_verified":True,
                "expiration_date":"2026-10-24","quote_valid_until_utc":"2026-09-24T20:02:00Z",
                "standard_reason":"verified_standard_100_share_contract"}]}

class MarketServiceTests(unittest.TestCase):
    def setUp(self):
        self.wall=Clock(datetime(2026,9,24,20,tzinfo=timezone.utc).timestamp()); self.mono=Clock(100)
        self.adapter=FakeAdapter(); self.gate=GlobalRequestGate(monotonic=self.mono,sleep=lambda seconds:None)
        self.service=MarketService(self.adapter,wall_clock=self.wall,monotonic=self.mono,request_gate=self.gate)

    def test_cache_freezes_apr_failure_retains_and_recovery(self):
        self.assertTrue(self.service.refresh("SPCX")); first=self.service.snapshot("SPCX")
        apr=first["contracts"][0]["annualized_pct"]
        self.wall.value+=3600; self.mono.value+=60
        self.assertEqual(self.service.snapshot("SPCX")["contracts"][0]["annualized_pct"],apr)
        self.adapter.error=TimeoutError("offline"); self.assertFalse(self.service.refresh("SPCX"))
        self.assertEqual(self.service.snapshot("SPCX")["contracts"][0]["annualized_pct"],apr)
        self.assertEqual(self.service.snapshot("SPCX")["state"],"degraded")
        self.adapter.error=None; self.mono.value+=60; self.assertTrue(self.service.refresh("SPCX"))

    def test_versioned_light_snapshot_omits_contracts_and_avoids_deepcopy(self):
        self.assertTrue(self.service.refresh("SPCX"))
        full=self.service.snapshot("SPCX")
        self.assertFalse(full["unchanged"]); self.assertIn("contracts",full)
        version=full["snapshot_version"]
        with mock.patch("options_panel.us_equities.market_service.copy.deepcopy",side_effect=AssertionError("large copy")):
            light=self.service.snapshot("SPCX",if_version=version)
        self.assertTrue(light["unchanged"]); self.assertNotIn("contracts",light)
        self.assertEqual(light["snapshot_version"],version)
        self.assertIn("server_time",light); self.assertIn("next_refresh_seconds",light)
        self.assertEqual(light["validation_status"]["contract_count"],1)
        self.assertEqual(light["validation_status"]["active_contract_count"],1)

    def test_client_leases_merge_replace_release_and_expire_at_fifteen_seconds(self):
        self.service.snapshot("AAPL",client_id="tab-a",active=True)
        self.service.snapshot("AAPL",client_id="tab-b",active=True)
        self.assertEqual(self.service._active_symbols_locked(self.mono.value),{"AAPL"})
        self.service.snapshot("MSFT",client_id="tab-a",active=True)
        self.assertEqual(self.service._active_symbols_locked(self.mono.value),{"AAPL","MSFT"})
        released=self.service.snapshot("MSFT",client_id="tab-a",active=False)
        self.assertEqual(released["schedule_state"],"inactive")
        self.assertEqual(self.service._active_symbols_locked(self.mono.value),{"AAPL"})
        self.mono.value+=15
        self.assertEqual(self.service._active_symbols_locked(self.mono.value),set())

    def test_sequenced_activity_ignores_late_release_and_old_active(self):
        client="tab-race"
        self.service.snapshot("AAPL",client_id=client,active=True,activity_seq=1)
        self.service.snapshot("MSFT",client_id=client,active=True,activity_seq=3)
        self.service.snapshot("AAPL",client_id=client,active=False,activity_seq=2)
        self.assertEqual(self.service._leases[client][0],"MSFT")
        self.service.snapshot("MSFT",client_id=client,active=False,activity_seq=4)
        self.service.snapshot("MSFT",client_id=client,active=True,activity_seq=3)
        self.assertNotIn(client,self.service._leases)
        self.service.snapshot("MSFT",client_id=client,active=True,activity_seq=5)
        self.service.snapshot("MSFT",client_id=client,active=False,activity_seq=4)
        self.assertEqual(self.service._leases[client][0],"MSFT")

    def test_same_symbol_hide_resume_sequence_and_record_cleanup(self):
        client="tab-same"
        self.service.snapshot("AAPL",client_id=client,active=True,activity_seq=10)
        self.service.snapshot("AAPL",client_id=client,active=False,activity_seq=11)
        self.service.snapshot("AAPL",client_id=client,active=True,activity_seq=12)
        self.service.snapshot("AAPL",client_id=client,active=False,activity_seq=11)
        self.assertEqual(self.service._leases[client][0],"AAPL")
        self.mono.value+=30
        self.service._active_symbols_locked(self.mono.value)
        self.assertNotIn(client,self.service._client_sequences)
        self.assertNotIn(client,self.service._leases)
        self.service.snapshot("MSFT",client_id=client,active=True,activity_seq=1)
        self.assertEqual(self.service._leases[client][0],"MSFT")

    def test_legacy_release_only_removes_matching_symbol(self):
        client="legacy-tab"
        self.service.snapshot("MSFT",client_id=client,active=True)
        self.service.snapshot("AAPL",client_id=client,active=False)
        self.assertEqual(self.service._leases[client][0],"MSFT")

    def test_legacy_reads_are_active_for_fifteen_seconds(self):
        self.service.snapshot("SPCX")
        self.mono.value+=14.999
        self.assertIn("SPCX",self.service._active_symbols_locked(self.mono.value))
        self.mono.value+=0.001
        self.assertNotIn("SPCX",self.service._active_symbols_locked(self.mono.value))

    def test_idle_cache_lru_limit_and_age_cleanup_include_scheduler_state(self):
        for index in range(12):
            symbol=f"S{index:02d}"; self.service._cache[symbol]={"symbol":symbol,"contracts":[]}
            self.service._last_access[symbol]=index
            self.service._last_success[symbol]=index; self.service._next_attempt[symbol]=index
            self.service._diagnostics[symbol]={"fetch_count":1}
        self.mono.value=20
        with self.service._lock:self.service._evict_idle_locked(self.mono.value)
        self.assertEqual(len(self.service._cache),10)
        self.assertNotIn("S00",self.service._next_attempt); self.assertNotIn("S01",self.service._diagnostics)
        self.mono.value=2000
        with self.service._lock:self.service._evict_idle_locked(self.mono.value)
        self.assertEqual(self.service._cache,{})

    def test_failure_changes_status_without_changing_version_or_cached_object(self):
        self.assertTrue(self.service.refresh("SPCX"))
        before_ref=self.service._cache["SPCX"]
        version=before_ref["snapshot_version"]
        self.adapter.error=TimeoutError("offline")
        self.assertFalse(self.service.refresh("SPCX"))
        self.assertIsNot(self.service._cache["SPCX"],before_ref)
        self.assertEqual(before_ref["state"],"ready")
        light=self.service.snapshot("SPCX",if_version=version)
        self.assertTrue(light["unchanged"]); self.assertEqual(light["state"],"degraded")
        self.assertEqual(light["fetch_health"],"failed")
        self.adapter.error=None; self.mono.value+=60
        self.assertTrue(self.service.refresh("SPCX"))
        self.assertNotEqual(self.service.snapshot("SPCX")["snapshot_version"],version)

    def test_invalid_calendar_refresh_keeps_last_complete_snapshot(self):
        self.assertTrue(self.service.refresh("SPCX"))
        before = self.service.snapshot("SPCX")
        self.adapter.error = AlpacaError("官方交易日历响应无效")
        self.mono.value += 60
        self.assertFalse(self.service.refresh("SPCX"))
        after = self.service.snapshot("SPCX")
        self.assertEqual(after["snapshot_version"], before["snapshot_version"])
        self.assertEqual(after["contracts"][0]["contract_symbol"], before["contracts"][0]["contract_symbol"])
        self.assertEqual(after["contracts"][0]["annualized_pct"], before["contracts"][0]["annualized_pct"])
        self.assertEqual(after["contracts"][0]["period_return_pct"], before["contracts"][0]["period_return_pct"])
        self.assertFalse(after["contracts"][0]["ranking_eligible"])
        self.assertEqual(after["state"], "degraded")
        self.assertEqual(after["fetch_health"], "failed")

    def test_stale_and_expiry_are_derived_without_mutating_apr(self):
        self.service.refresh("SPCX"); self.mono.value+=121
        self.assertEqual(self.service.snapshot("SPCX")["fetch_health"],"stale")
        self.wall.value=datetime(2026,10,25,tzinfo=timezone.utc).timestamp()
        row=self.service.snapshot("SPCX")["contracts"][0]
        self.assertEqual(row["calculation_status"],"expired"); self.assertIsNone(row["annualized_pct"])

    def test_cached_apr_is_preserved_when_real_quote_ranking_window_expires(self):
        self.service.refresh("SPCX")
        initial=self.service.snapshot("SPCX")["contracts"][0]
        self.assertTrue(initial["ranking_eligible"]); apr=initial["annualized_pct"]
        self.wall.value+=119
        self.assertTrue(self.service.snapshot("SPCX")["contracts"][0]["ranking_eligible"])
        self.wall.value+=2
        expired=self.service.snapshot("SPCX")["contracts"][0]
        self.assertFalse(expired["ranking_eligible"])
        self.assertEqual(expired["ranking_reason"],"quote_ranking_window_expired")
        self.assertEqual(expired["annualized_pct"],apr)

    def test_auth_and_429_have_distinct_safe_states_and_backoff(self):
        self.adapter.error=AuthorizationRequired("权限不足")
        self.assertFalse(self.service.refresh("SPCX"))
        self.assertEqual(self.service.snapshot("SPCX")["state"],"authorization_required")
        self.adapter.error=RateLimited("稍后重试",90); self.mono.value+=60
        self.assertFalse(self.service.refresh("SPCX"))
        self.assertGreaterEqual(self.service._next_attempt["SPCX"]-self.mono.value,90)

    def test_refresh_timing_starts_when_each_attempt_completes(self):
        mono = Clock(100)
        wall = Clock(datetime(2026,9,24,20,tzinfo=timezone.utc).timestamp())
        base = FakeAdapter()
        class SlowAdapter:
            ready=True; source_name="慢速合成源"
            delay=7; error=None
            def fetch(self, symbol):
                mono.value += self.delay
                if self.error: raise self.error
                return base.fetch(symbol)
        adapter = SlowAdapter()
        service = MarketService(adapter, wall_clock=wall, monotonic=mono)
        self.assertTrue(service.refresh("SPCX"))
        self.assertEqual(service._last_success["SPCX"], 107)
        self.assertEqual(service._next_attempt["SPCX"], 167)
        first = service.snapshot("SPCX")
        self.assertEqual(first["fetched_age_seconds"], 0)
        self.assertEqual(first["next_refresh_seconds"], 60)

        mono.value = 200; adapter.delay = 8; adapter.error = TimeoutError("offline")
        self.assertFalse(service.refresh("SPCX"))
        self.assertEqual(service._next_attempt["SPCX"], 268)
        self.assertEqual(service._last_success["SPCX"], 107)

        mono.value = 300; adapter.delay = 9; adapter.error = AuthorizationRequired("权限不足")
        self.assertFalse(service.refresh("SPCX"))
        self.assertEqual(service._next_attempt["SPCX"], 369)
        self.assertEqual(service._last_success["SPCX"], 107)

        mono.value = 400; adapter.delay = 10; adapter.error = RateLimited("稍后重试", 90)
        self.assertFalse(service.refresh("SPCX"))
        self.assertEqual(service._next_attempt["SPCX"], 500)
        self.assertEqual(service._last_success["SPCX"], 107)

    def test_nonfinite_retry_after_falls_back_to_refresh_interval(self):
        class InvalidRetry(TimeoutError):
            def __init__(self, value): self.retry_after=value
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.adapter.error=InvalidRetry(value)
                self.assertFalse(self.service.refresh("SPCX"))
                self.assertEqual(self.service._next_attempt["SPCX"]-self.mono.value,60)

    def test_scheduler_rechecks_time_and_activity_for_each_symbol(self):
        mono = Clock(100)
        base = FakeAdapter()
        class AdvancingAdapter:
            ready=True; source_name="合成源"
            calls=[]
            def fetch(self, symbol):
                self.calls.append(symbol)
                mono.value += 30
                return base.fetch(symbol)
        class OneTick:
            def __init__(self): self.calls=[]
            def wait(self, seconds):
                self.calls.append(seconds)
                return len(self.calls)>1
            def set(self): pass
        adapter=AdvancingAdapter()
        service=MarketService(adapter,monotonic=mono)
        service._last_access={"A":100,"B":100}; service._legacy_until={"A":115,"B":115}; service._next_attempt={"A":0,"B":0}
        stop=OneTick(); service._stop=stop
        service.run()
        self.assertEqual(adapter.calls,["A"])
        self.assertEqual(stop.calls,[1.0,1.0])

    def test_scheduler_prioritizes_one_uncached_then_oldest_cached_with_five_second_starts(self):
        mono=Clock(100); base=FakeAdapter()
        class RecordingAdapter:
            ready=True; source_name="公平队列"
            calls=[]
            def fetch(self,symbol): self.calls.append((symbol,mono.value)); return base.fetch(symbol)
        class Ticks:
            def __init__(self): self.count=0
            def wait(self,_seconds): self.count+=1; mono.value+=1; return self.count>12
            def set(self): pass
        adapter=RecordingAdapter(); service=MarketService(adapter,monotonic=mono)
        service._legacy_until={symbol:200 for symbol in ("A","B","C")}
        service._last_access={symbol:100 for symbol in ("A","B","C")}
        service._cache["A"]={"symbol":"A","contracts":[]}
        service._next_attempt={"A":0,"B":0,"C":0}; service._stop=Ticks()
        service.run()
        self.assertEqual([symbol for symbol,_time in adapter.calls[:3]],["B","A","C"])
        self.assertTrue(all(right-left>=5 for (_s,left),(_t,right) in zip(adapter.calls,adapter.calls[1:])))

    def test_same_symbol_inflight_is_deduplicated(self):
        self.service._inflight.add("SPCX")
        self.assertFalse(self.service.refresh("SPCX"))
        self.assertEqual(self.service._diagnostics.get("SPCX"),None)

    def test_global_http_pause_keeps_task_queued_before_refreshing(self):
        mono=Clock(100); gate=GlobalRequestGate(monotonic=mono,sleep=lambda seconds:None); gate.pause(60)
        adapter=FakeAdapter(); calls=[]
        original=adapter.fetch
        adapter.fetch=lambda symbol:(calls.append(symbol),original(symbol))[1]
        service=MarketService(adapter,monotonic=mono,request_gate=gate)
        service.snapshot("SPCX",client_id="tab-a",active=True)
        class OneTick:
            count=0
            def wait(self,_seconds): self.count+=1; return self.count>1
            def set(self): pass
        service._stop=OneTick(); service.run()
        self.assertEqual(calls,[])
        status=service.snapshot("SPCX",client_id="tab-a",active=True)
        self.assertEqual(status["schedule_state"],"cooldown")
        self.assertGreaterEqual(status["next_refresh_seconds"],60)

    def test_schedule_diagnostics_follow_refresh_without_sensitive_content(self):
        waiting=self.service.snapshot("SPCX",client_id="tab-a",active=True)
        self.assertEqual(waiting["schedule_state"],"queued")
        self.assertTrue(self.service.refresh("SPCX"))
        status=self.service.snapshot("SPCX",client_id="tab-a",active=True)
        self.assertEqual(status["schedule_state"],"waiting")
        self.assertEqual(status["diagnostics"]["fetch_count"],1)
        self.assertIn("global_request_count",status["diagnostics"])
        self.assertNotIn("credentials",status["diagnostics"])

if __name__=="__main__": unittest.main()
