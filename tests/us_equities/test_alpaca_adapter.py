import io
import sys
import unittest
import urllib.error
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from options_panel.us_equities import alpaca_adapter as aa
from options_panel.us_equities.market_service import MarketService
from options_panel.us_equities.request_throttle import GlobalRequestGate

class Response:
    def __init__(self,payload=b"{}"): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,_limit): return self.payload

class AlpacaHttpTests(unittest.TestCase):
    @staticmethod
    def _metadata_client_fixture():
        base={"size":"100","multiplier":"100","underlying_asset_id":"asset-1",
              "root_symbol":"SPCX","underlying_symbol":"SPCX","style":"american",
              "expiration_date":"2026-10-16","strike_price":"100","type":"call","symbol":"SPCX261016C00100000"}
        class Client:
            def __init__(self):
                self.counts={"asset":0,"contracts":0,"calendar":0,"stock":0,"snapshots":0}
                self.amount="100"; self.partial_page_failure=False
            def get(self,host,path,params=None):
                if path=="/v2/assets/SPCX": self.counts["asset"]+=1; return {"class":"us_equity","symbol":"SPCX"}
                if path=="/v2/options/contracts":
                    self.counts["contracts"]+=1
                    if params and params.get("page_token")=="page-2":
                        if self.partial_page_failure: raise aa.AlpacaError("page two failed")
                        return {"option_contracts":[]}
                    row={**base,"deliverables":[{"type":"equity","symbol":"SPCX","amount":self.amount,"asset_id":"asset-1"}]}
                    if self.partial_page_failure: return {"option_contracts":[row],"next_page_token":"page-2"}
                    return {"option_contracts":[row]}
                if path=="/v2/calendar":
                    self.counts["calendar"]+=1
                    return [{"date":"2026-09-25","open":"09:30","close":"16:00"},
                            {"date":"2026-10-16","open":"09:30","close":"16:00"}]
                if path=="/v2/stocks/SPCX/quotes/latest":
                    self.counts["stock"]+=1; return {"quote":{"bp":99,"ap":101,"t":"2026-09-25T17:59:30Z"}}
                if path=="/v1beta1/options/snapshots/SPCX":
                    self.counts["snapshots"]+=1
                    return {"snapshots":{"SPCX261016C00100000":{"latestQuote":{"bp":3,"ap":3.2,"t":"2026-09-25T17:59:20Z"},"impliedVolatility":.2,"greeks":{"delta":.5}}}}
                raise AssertionError(path)
        return Client()

    def test_adapter_metadata_hits_but_quotes_refresh_and_credentials_change_clears(self):
        client=self._metadata_client_fixture(); mono=[0.0]; credentials=[("k1","s1")]; probes=[]
        adapter=aa.AlpacaAdapter(credentials_loader=lambda:credentials[0],client_factory=lambda *_:client,
                                 probe=lambda *args:probes.append(args) or {"ok":True},
                                 now=lambda:datetime(2026,9,25,18,0,tzinfo=timezone.utc),monotonic=lambda:mono[0])
        adapter.fetch("SPCX"); adapter.fetch("SPCX")
        self.assertEqual(client.counts,{"asset":1,"contracts":1,"calendar":1,"stock":2,"snapshots":2})
        credentials[0]=("k2","s2")
        adapter.fetch("SPCX")
        self.assertEqual(client.counts,{"asset":2,"contracts":2,"calendar":2,"stock":3,"snapshots":3})
        self.assertEqual(probes,[("k1","s1"),("k2","s2")])

    def test_contract_ttl_rechecks_deliverables_and_partial_page_failure_keeps_service_version(self):
        client=self._metadata_client_fixture(); mono=[0.0]
        adapter=aa.AlpacaAdapter(credentials_loader=lambda:("k","s"),client_factory=lambda *_:client,
                                 probe=lambda *_:{"ok":True},now=lambda:datetime(2026,9,25,18,0,tzinfo=timezone.utc),
                                 monotonic=lambda:mono[0])
        first=adapter.fetch("SPCX")
        self.assertTrue(first["contracts"][0].standard)
        mono[0]=300.0; client.amount="10"
        second=adapter.fetch("SPCX")
        self.assertFalse(second["contracts"][0].standard)
        self.assertEqual(second["contracts"][0].standard_reason,"adjusted_or_unknown_deliverable")

        wall=lambda:datetime(2026,9,25,18,0,tzinfo=timezone.utc).timestamp()
        service=MarketService(adapter,wall_clock=wall,monotonic=lambda:mono[0],
                              request_gate=GlobalRequestGate(monotonic=lambda:mono[0],sleep=lambda _:None))
        mono[0]=600.0; client.amount="100"
        self.assertTrue(service.refresh("SPCX")); before=service.snapshot("SPCX")
        cached_contracts=adapter._metadata._items["SPCX"].contracts
        cached_symbol=next(iter(cached_contracts.values())).value[0]["symbol"]
        mono[0]=900.0; client.partial_page_failure=True
        self.assertFalse(service.refresh("SPCX"))
        after=service.snapshot("SPCX")
        self.assertEqual(after["snapshot_version"],before["snapshot_version"])
        self.assertEqual(next(iter(adapter._metadata._items["SPCX"].contracts.values())).value[0]["symbol"],cached_symbol)
        self.assertEqual(after["contracts"][0]["annualized_pct"],before["contracts"][0]["annualized_pct"])

    def test_path_whitelist_and_auth_body_redaction(self):
        http=aa.AlpacaHttp("KEY-SECRET","VERY-SECRET",opener=lambda req,timeout: Response())
        with self.assertRaises(aa.AlpacaError): http.get(aa.PAPER_HOST,"/v2/orders")
        def unauthorized(req,timeout):
            raise urllib.error.HTTPError(req.full_url,401,"bad",{},io.BytesIO(b'KEY-SECRET VERY-SECRET private body'))
        http=aa.AlpacaHttp("KEY-SECRET","VERY-SECRET",opener=unauthorized)
        with self.assertRaises(aa.AuthorizationRequired) as caught: http.get(aa.PAPER_HOST,"/v2/calendar")
        self.assertNotIn("KEY-SECRET",str(caught.exception)); self.assertNotIn("private body",str(caught.exception))

    def test_429_retry_after_is_at_least_sixty(self):
        def limited(req,timeout): raise urllib.error.HTTPError(req.full_url,429,"rate",{"Retry-After":"90"},None)
        with self.assertRaises(aa.RateLimited) as caught:
            aa.AlpacaHttp("k","s",opener=limited).get(aa.PAPER_HOST,"/v2/calendar")
        self.assertEqual(caught.exception.retry_after,90)

    def test_pagination_all_or_error(self):
        class Client:
            def __init__(self): self.n=0
            def get(self,*args):
                self.n+=1
                return {"snapshots":{"ONE":{"latestQuote":{}}},"next_page_token":"next"} if self.n==1 else {"snapshots":{"TWO":{"latestQuote":{}}}}
        rows=aa._page(Client(),aa.DATA_HOST,"/v1beta1/options/snapshots/AAPL",{"limit":1000},"snapshots")
        self.assertEqual({r["symbol"] for r in rows},{"ONE","TWO"})
        class Broken:
            def get(self,*args): return {"next_page_token":"x"}
        with self.assertRaises(aa.AlpacaError): aa._page(Broken(),aa.DATA_HOST,"/v1beta1/options/snapshots/AAPL",{},"snapshots")
        class Malformed:
            def get(self,*args): return {"snapshots":{"ONE":None}}
        with self.assertRaises(aa.AlpacaError): aa._page(Malformed(),aa.DATA_HOST,"/v1beta1/options/snapshots/AAPL",{},"snapshots")
        class Repeated:
            def get(self,*args): return {"snapshots":{},"next_page_token":"same"}
        with self.assertRaises(aa.AlpacaError): aa._page(Repeated(),aa.DATA_HOST,"/v1beta1/options/snapshots/AAPL",{},"snapshots")

    def test_standard_gate_requires_explicit_amount_multiplier_and_single_equity(self):
        base={"size":"100","multiplier":"100","underlying_asset_id":"asset-1","deliverables":[{"type":"equity","symbol":"SPCX","amount":"100","asset_id":"asset-1","delayed_settlement":False}],
              "root_symbol":"SPCX","underlying_symbol":"SPCX","style":"american"}
        self.assertTrue(aa._standard_contract(base,"SPCX",True)[0])
        for change in ({"multiplier":None},{"deliverables":[]},{"deliverables":[{"type":"equity","symbol":"SPCX","amount":"10"}]}):
            row={**base,**change}
            self.assertFalse(aa._standard_contract(row,"SPCX",True)[0])

    def test_goog_is_verified_but_etf_and_mismatched_asset_are_rejected(self):
        self.assertTrue(aa._asset_is_individual_stock("GOOG", {"class":"us_equity", "symbol":"GOOG"}))
        self.assertFalse(aa._asset_is_individual_stock("SPY", {"class":"us_equity", "symbol":"SPY"}))
        self.assertFalse(aa._asset_is_individual_stock("GOOG", {"class":"us_equity", "symbol":"GOOGL"}))
        self.assertFalse(aa._asset_is_individual_stock("GOOG", {"class":"crypto", "symbol":"GOOG"}))
        contract={"size":"100", "multiplier":"100", "underlying_asset_id":"goog-id",
                  "deliverables":[{"type":"equity", "symbol":"GOOG", "amount":"100",
                                   "asset_id":"goog-id", "delayed_settlement":False}],
                  "root_symbol":"GOOG", "underlying_symbol":"GOOG", "style":"american"}
        self.assertTrue(aa._standard_contract(contract, "GOOG", True)[0])
        self.assertFalse(aa._standard_contract(contract, "GOOGL", True)[0])

    def test_unknown_snapshot_forces_one_metadata_refresh_and_remains_display_only(self):
        base={"size":"100","multiplier":"100","underlying_asset_id":"asset-1",
              "deliverables":[{"type":"equity","symbol":"SPCX","amount":"100","asset_id":"asset-1"}],
              "root_symbol":"SPCX","underlying_symbol":"SPCX","style":"american",
              "expiration_date":"2026-10-16","strike_price":"100","type":"call"}
        class Client:
            contract_calls=0
            def get(self,host,path,params=None):
                if path=="/v2/assets/SPCX": return {"class":"us_equity","symbol":"SPCX"}
                if path=="/v2/options/contracts":
                    self.contract_calls+=1
                    return {"option_contracts":[{**base,"symbol":"KNOWN"}]}
                if path=="/v2/calendar":
                    return [{"date":"2026-09-25","open":"09:30","close":"16:00"},{"date":"2026-10-16","open":"09:30","close":"16:00"}]
                if path=="/v2/stocks/SPCX/quotes/latest": return {"quote":{"bp":99,"ap":101,"t":"2026-09-25T18:00:00Z"}}
                if path=="/v1beta1/options/snapshots/SPCX":
                    quote={"bp":1,"ap":1.2,"t":"2026-09-25T18:00:00Z"}
                    return {"snapshots":{"KNOWN":{"latestQuote":quote},"UNKNOWN":{"latestQuote":quote,"impliedVolatility":.2}}}
                raise AssertionError(path)
        client=Client()
        adapter=aa.AlpacaAdapter(credentials_loader=lambda:("k","s"),client_factory=lambda *_:client,
                                 probe=lambda *_:{"ok":True},now=lambda:datetime(2026,9,25,18,0,1,tzinfo=timezone.utc))
        result=adapter.fetch("SPCX")
        self.assertEqual(client.contract_calls,2)
        unknown=next(row for row in result["contracts"] if row.contract_symbol=="UNKNOWN")
        self.assertFalse(unknown.standard); self.assertFalse(unknown.quote_eligible)
        self.assertEqual(unknown.standard_reason,"contract_metadata_unavailable")
        self.assertIsNone(unknown.strike)
        self.assertIn("metadata_fetched_at",unknown.contract_metadata)

    def test_adapter_uses_source_time_and_rejects_quote_skew_with_null_metrics(self):
        base_contract={"size":"100","multiplier":"100","underlying_asset_id":"asset-1","deliverables":[{"type":"equity","symbol":"SPCX","amount":"100","asset_id":"asset-1","delayed_settlement":False}],
                       "root_symbol":"SPCX","underlying_symbol":"SPCX","style":"american","expiration_date":"2026-10-16",
                       "strike_price":"100","open_interest":"-1","open_interest_date":"2026-09-24"}
        class Client:
            def get(self,host,path,params=None):
                if path=="/v2/assets/SPCX": return {"class":"us_equity","symbol":"SPCX","name":"Space Exploration Technologies Corp Class A Common Stock"}
                if path=="/v2/options/contracts":
                    return {"option_contracts":[{**base_contract,"symbol":"SPCX261016C00100000","type":"call"},
                                                {**base_contract,"symbol":"SPCX261016P00100000","type":"put"}]}
                if path=="/v2/calendar":
                    return [{"date":"2026-09-25","open":"09:30","close":"16:00"},
                            {"date":"2026-10-16","open":"09:30","close":"16:00"}]
                if path=="/v2/stocks/SPCX/quotes/latest": return {"quote":{"bp":99,"ap":101,"t":"2026-09-25T17:59:30Z"}}
                if path=="/v1beta1/options/snapshots/SPCX":
                    return {"snapshots":{
                        "SPCX261016C00100000":{"latestQuote":{"bp":3,"ap":3.2,"t":"2026-09-25T17:59:00Z"},"impliedVolatility":-1,"greeks":{"delta":0.5}},
                        "SPCX261016P00100000":{"latestQuote":{"bp":3,"ap":3.2,"t":"2026-09-25T17:50:00Z"},"impliedVolatility":0.2,"greeks":{"delta":-0.5}}}}
                raise AssertionError(path)
        client=Client()
        adapter=aa.AlpacaAdapter(credentials_loader=lambda:("k","s"),client_factory=lambda *_:client,
                                 probe=lambda *_:{"ok":True},
                                 now=lambda:datetime(2026,9,25,18,0,tzinfo=timezone.utc))
        result=adapter.fetch("SPCX")
        self.assertEqual(result["calculated_at"],"2026-09-25T17:59:30Z")
        calls={row.side:row for row in result["contracts"]}
        self.assertTrue(calls["CALL"].quote_eligible)
        self.assertEqual(calls["CALL"].quote_valid_until_utc,"2026-09-25T18:01:00Z")
        self.assertEqual(calls["CALL"].contract_metadata["multiplier"],"100")
        self.assertEqual(calls["CALL"].contract_metadata["strike_price"],"100")
        self.assertEqual(calls["CALL"].contract_metadata["expiration_date"],"2026-10-16")
        self.assertEqual(calls["CALL"].contract_metadata["type"],"call")
        self.assertEqual(calls["CALL"].contract_metadata["deliverables"][0]["amount"],"100")
        self.assertIsNone(calls["CALL"].implied_volatility)
        self.assertIsNone(calls["CALL"].open_interest)
        self.assertFalse(calls["PUT"].quote_eligible)
        self.assertEqual(calls["PUT"].quote_reason,"stock_option_quote_skew")

    def probe_client(self, *, missing_put=False, missing_standard_field=False):
        today=date.today()
        expiries=[(today+timedelta(days=30)).isoformat(),(today+timedelta(days=60)).isoformat()]
        base={"size":"100","multiplier":"100","underlying_asset_id":"asset-aapl",
              "deliverables":[{"type":"equity","symbol":"AAPL","amount":"100","asset_id":"asset-aapl","delayed_settlement":False}],
              "root_symbol":"AAPL","underlying_symbol":"AAPL","style":"american","strike_price":"200"}
        if missing_standard_field: base.pop("multiplier")
        calls=[{**base,"symbol":f"AAPL{index}C","type":"call","expiration_date":expiry} for index,expiry in enumerate(expiries)]
        puts=[{**base,"symbol":f"AAPL{index}P","type":"put","expiration_date":expiry} for index,expiry in enumerate(expiries)]
        if missing_put: puts=puts[:1]
        selected={row["symbol"] for row in calls+puts}
        probe_now=datetime.now(timezone.utc)
        now_et=probe_now.astimezone(aa.EASTERN)
        in_open=now_et.weekday()<5 and time(9,30)<=now_et.time().replace(tzinfo=None)<time(16,0)
        quote_day=now_et.date()
        if not in_open and (now_et.weekday()>=5 or now_et.time().replace(tzinfo=None)<time(16,0)):
            quote_day-=timedelta(days=1)
            while quote_day.weekday()>=5: quote_day-=timedelta(days=1)
        quote_at=(probe_now-timedelta(seconds=30)) if in_open else datetime.combine(quote_day,time(15,59,30),aa.EASTERN).astimezone(timezone.utc)
        calendar_days={quote_day,now_et.date()}
        calendar_rows=[{"date":day.isoformat(),"open":"09:30","close":"16:00"} for day in sorted(calendar_days) if day.weekday()<5]
        class Client:
            def get(self,_host,path,params=None):
                if path=="/v2/stocks/AAPL/quotes/latest":
                    return {"quote":{"bp":199,"ap":201,"t":quote_at.isoformat().replace("+00:00","Z")}}
                if path=="/v2/assets/AAPL":
                    return {"class":"us_equity","symbol":"AAPL","name":"Apple Inc. Common Stock"}
                if path=="/v2/calendar":
                    return calendar_rows
                if path=="/v2/options/contracts":
                    return {"option_contracts":calls if params.get("type")=="call" else puts}
                if path=="/v1beta1/options/snapshots":
                    symbols=params["symbols"].split(",")
                    return {"snapshots":{symbol:{"latestQuote":{"bp":2,"ap":2.2,"t":"2026-09-25T17:59:00Z"}} for symbol in symbols if symbol in selected}}
                raise AssertionError(path)
        return Client()

    def test_closed_invalid_latest_uses_latest_valid_historical_page_and_source_time(self):
        sessions=aa.calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"16:00"}])
        class Client:
            def __init__(self): self.history_calls=[]
            def get(self,_host,path,params=None):
                if path.endswith("/quotes/latest"): return {"quote":{"bp":100,"ap":0,"t":"2026-07-02T20:00:02Z"}}
                if path.endswith("/quotes"):
                    self.history_calls.append(dict(params))
                    if "page_token" not in params:
                        return {"quotes":[{"bp":100,"ap":0,"t":"2026-07-02T19:59:59Z"}],"next_page_token":"p2"}
                    return {"quotes":[{"bp":99,"ap":101,"t":"2026-07-02T19:59:30Z"}]}
                raise AssertionError(path)
        client=Client()
        quote,label=aa._stock_reference_quote(client,"AAPL",datetime(2026,7,3,12,tzinfo=timezone.utc),sessions)
        self.assertEqual(label,"最近收盘前有效 IEX 报价")
        self.assertEqual(quote["t"],"2026-07-02T19:59:30Z")
        self.assertEqual(len(client.history_calls),2)
        self.assertEqual(client.history_calls[0]["feed"],"iex")
        self.assertEqual(client.history_calls[0]["sort"],"desc")
        self.assertEqual(client.history_calls[0]["limit"],10000)
        self.assertEqual(client.history_calls[0]["start"],"2026-07-02T19:58:00Z")
        self.assertEqual(client.history_calls[0]["end"],"2026-07-02T20:00:00Z")

    def test_closed_without_valid_history_fails_and_open_never_falls_back(self):
        closed_sessions=aa.calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"16:00"}])
        class EmptyHistory:
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quote":{"bp":100,"ap":0,"t":"2026-07-02T20:00:02Z"}}
                return {"quotes":[{"bp":100,"ap":0,"t":"2026-07-02T19:59:00Z"}]}
        with self.assertRaises(aa.StockQuoteUnavailable):
            aa._stock_reference_quote(EmptyHistory(),"AAPL",datetime(2026,7,3,12,tzinfo=timezone.utc),closed_sessions)
        open_sessions=aa.calendar_sessions([{"date":"2026-07-06","open":"09:30","close":"16:00"}])
        class OpenClient:
            def __init__(self): self.historical=False
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quote":{"bp":100,"ap":0,"t":"2026-07-06T14:00:00Z"}}
                self.historical=True; raise AssertionError("盘中不得请求历史收盘报价")
        client=OpenClient()
        with self.assertRaises(aa.StockQuoteUnavailable):
            aa._stock_reference_quote(client,"AAPL",datetime(2026,7,6,14,1,tzinfo=timezone.utc),open_sessions)
        self.assertFalse(client.historical)

    def test_successful_http_with_missing_latest_quote_falls_back_only_when_closed(self):
        closed_sessions=aa.calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"16:00"}])
        class ClosedClient:
            def __init__(self): self.historical=False
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quote":None}
                self.historical=True
                return {"quotes":[{"bp":99,"ap":101,"t":"2026-07-02T19:59:30Z"}]}
        closed=ClosedClient()
        quote,label=aa._stock_reference_quote(closed,"AAPL",datetime(2026,7,3,12,tzinfo=timezone.utc),closed_sessions)
        self.assertTrue(closed.historical)
        self.assertEqual(quote["t"],"2026-07-02T19:59:30Z")
        self.assertEqual(label,"最近收盘前有效 IEX 报价")

        open_sessions=aa.calendar_sessions([{"date":"2026-07-06","open":"09:30","close":"16:00"}])
        class OpenClient:
            def __init__(self): self.historical=False
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quotes":{"AAPL":"malformed"}}
                self.historical=True; raise AssertionError("盘中不得请求历史报价")
        opened=OpenClient()
        with self.assertRaises(aa.StockQuoteUnavailable):
            aa._stock_reference_quote(opened,"AAPL",datetime(2026,7,6,14,1,tzinfo=timezone.utc),open_sessions)
        self.assertFalse(opened.historical)

    def test_latest_quote_uses_receive_time_with_bounded_future_tolerance(self):
        sessions=aa.calendar_sessions([{"date":"2026-07-06","open":"09:30","close":"16:00"}])
        request_started=datetime(2026,7,6,13,29,59,500000,tzinfo=timezone.utc)
        received=datetime(2026,7,6,13,30,0,400000,tzinfo=timezone.utc)
        class Client:
            historical=False
            def __init__(self,quote): self.quote=quote
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quote":self.quote}
                self.historical=True; raise AssertionError("开盘后不得请求历史报价")
        quote={"bp":99,"ap":101,"t":"2026-07-06T13:30:00.600000Z"}
        client=Client(quote)
        actual,_=aa._stock_reference_quote(client,"AAPL",request_started,sessions,received_clock=lambda:received)
        self.assertEqual(actual["t"],quote["t"])
        self.assertFalse(client.historical)

        close_received=datetime(2026,7,6,20,0,0,400000,tzinfo=timezone.utc)
        close_quote={"bp":99,"ap":101,"t":"2026-07-06T19:59:59.900000Z"}
        closed_actual,_=aa._stock_reference_quote(Client(close_quote),"AAPL",
            datetime(2026,7,6,19,59,59,500000,tzinfo=timezone.utc),sessions,
            received_clock=lambda:close_received)
        self.assertEqual(closed_actual["t"],close_quote["t"])

        at_limit={**quote,"t":"2026-07-06T13:30:02.400000Z"}
        self.assertIsNotNone(aa._valid_stock_quote(at_limit,"2026-07-06",sessions,not_after=received,
                                                   future_tolerance_seconds=aa.FUTURE_QUOTE_TOLERANCE_SECONDS))
        beyond={**quote,"t":"2026-07-06T13:30:02.400001Z"}
        self.assertIsNone(aa._valid_stock_quote(beyond,"2026-07-06",sessions,not_after=received,
                                                future_tolerance_seconds=aa.FUTURE_QUOTE_TOLERANCE_SECONDS))

        crossing_sessions=aa.calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"16:00"},
                                                {"date":"2026-07-06","open":"09:30","close":"16:00"}])
        class Crossing:
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quote":None}
                return {"quotes":[{"bp":99,"ap":101,"t":"2026-07-02T19:59:59Z"}]}
        receive_times=iter([datetime(2026,7,6,13,29,59,900000,tzinfo=timezone.utc),
                            datetime(2026,7,6,13,30,0,100000,tzinfo=timezone.utc)])
        with self.assertRaisesRegex(aa.StockQuoteUnavailable,"市场已开盘"):
            aa._stock_reference_quote(Crossing(),"AAPL",request_started,crossing_sessions,
                                      received_clock=lambda:next(receive_times))

    def test_future_timestamp_and_invalid_price_have_distinct_errors_and_close_is_strict(self):
        open_sessions=aa.calendar_sessions([{"date":"2026-07-06","open":"09:30","close":"16:00"}])
        received=datetime(2026,7,6,14,0,tzinfo=timezone.utc)
        class Latest:
            def __init__(self,quote): self.quote=quote
            def get(self,_host,path,params=None): return {"quote":self.quote}
        with self.assertRaisesRegex(aa.StockQuoteUnavailable,"时间晚于接收时刻"):
            aa._stock_reference_quote(Latest({"bp":99,"ap":101,"t":"2026-07-06T14:00:02.001Z"}),"AAPL",received,open_sessions,received_clock=lambda:received)
        with self.assertRaisesRegex(aa.StockQuoteUnavailable,"bid/ask 无效"):
            aa._stock_reference_quote(Latest({"bp":99,"ap":0,"t":"2026-07-06T14:00:00Z"}),"AAPL",received,open_sessions,received_clock=lambda:received)

        closed_sessions=aa.calendar_sessions([{"date":"2026-07-02","open":"09:30","close":"16:00"}])
        class Closed:
            def get(self,_host,path,params=None):
                if path.endswith("/latest"): return {"quote":None}
                return {"quotes":[{"bp":99,"ap":101,"t":"2026-07-02T20:00:00.001Z"}]}
        with self.assertRaisesRegex(aa.StockQuoteUnavailable,"没有有效 IEX"):
            aa._stock_reference_quote(Closed(),"AAPL",datetime(2026,7,3,12,tzinfo=timezone.utc),closed_sessions,
                                      received_clock=lambda:datetime(2026,7,3,12,tzinfo=timezone.utc))

    def test_fetch_accepts_small_receive_race_but_rejects_option_beyond_tolerance(self):
        base_contract={"size":"100","multiplier":"100","underlying_asset_id":"asset-1",
                       "deliverables":[{"type":"equity","symbol":"SPCX","amount":"100","asset_id":"asset-1","delayed_settlement":False}],
                       "root_symbol":"SPCX","underlying_symbol":"SPCX","style":"american","expiration_date":"2026-10-16",
                       "strike_price":"100","open_interest":"1","open_interest_date":"2026-09-24",
                       "symbol":"SPCX261016C00100000","type":"call"}
        class Client:
            def __init__(self,option_time): self.option_time=option_time
            def get(self,_host,path,params=None):
                if path=="/v2/assets/SPCX": return {"class":"us_equity","symbol":"SPCX","name":"Space Exploration Technologies Corp Class A Common Stock"}
                if path=="/v2/options/contracts": return {"option_contracts":[base_contract]}
                if path=="/v2/calendar": return [{"date":"2026-09-25","open":"09:30","close":"16:00"},{"date":"2026-10-16","open":"09:30","close":"16:00"}]
                if path=="/v2/stocks/SPCX/quotes/latest": return {"quote":{"bp":99,"ap":101,"t":"2026-09-25T18:00:00.600000Z"}}
                if path=="/v1beta1/options/snapshots/SPCX": return {"snapshots":{"SPCX261016C00100000":{"latestQuote":{"bp":3,"ap":3.2,"t":self.option_time},"impliedVolatility":.2,"greeks":{"delta":.5}}}}
                raise AssertionError(path)
        def run(option_time):
            values=iter([datetime(2026,9,25,17,59,58,tzinfo=timezone.utc),
                         datetime(2026,9,25,17,59,59,tzinfo=timezone.utc),
                         datetime(2026,9,25,18,0,tzinfo=timezone.utc),
                         datetime(2026,9,25,18,0,tzinfo=timezone.utc)])
            adapter=aa.AlpacaAdapter(credentials_loader=lambda:("k","s"),client_factory=lambda *_:Client(option_time),
                                     probe=lambda *_:{"ok":True},now=lambda:next(values))
            return adapter.fetch("SPCX")
        accepted=run("2026-09-25T18:00:01.900000Z")
        self.assertEqual(accepted["calculated_at"],"2026-09-25T18:00:00.600000Z")
        self.assertTrue(accepted["contracts"][0].quote_eligible)
        rejected=run("2026-09-25T18:00:02.000001Z")
        self.assertFalse(rejected["contracts"][0].quote_eligible)
        self.assertEqual(rejected["contracts"][0].quote_reason,"quote_time_in_future")

    def test_probe_stock_quote_unavailable_has_fixed_error_code(self):
        now_et=datetime.now(timezone.utc).astimezone(aa.EASTERN)
        prior=now_et.date()-timedelta(days=1)
        while prior.weekday()>=5: prior-=timedelta(days=1)
        class Client:
            def get(self,_host,path,params=None):
                if path=="/v2/calendar": return [{"date":prior.isoformat(),"open":"09:30","close":"16:00"}]
                if path.endswith("/quotes/latest"): return {"quote":{"bp":100,"ap":0,"t":"2026-01-01T20:00:00Z"}}
                if path.endswith("/quotes"): return {"quotes":[]}
                raise AssertionError(path)
        with mock.patch.object(aa,"AlpacaHttp",return_value=Client()):
            result=aa.probe_credentials("key","secret")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"],"stock_quote_unavailable")

    def test_probe_credentials_complete_two_expiry_sample_allows_missing_iv_greeks(self):
        with mock.patch.object(aa,"AlpacaHttp",return_value=self.probe_client()):
            result=aa.probe_credentials("key","secret")
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["option_snapshots"],4)
        self.assertEqual(len(result["expirations"]),2)

    def test_probe_credentials_rejects_missing_side_or_standard_metadata(self):
        for client in (self.probe_client(missing_put=True),self.probe_client(missing_standard_field=True)):
            with self.subTest(client=client), mock.patch.object(aa,"AlpacaHttp",return_value=client):
                result=aa.probe_credentials("key","secret")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"],"sample_incomplete")

if __name__=="__main__": unittest.main()

