from __future__ import annotations

import json
import http.client
import math
import urllib.error
import urllib.parse
import urllib.request
import re
import socket
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .market_calendar import (EASTERN, calendar_sessions, expiry_cutoff_utc, latest_completed_session_key,
                             market_status, quote_session_key, session_close_utc)
from .model import NormalizedContract, parse_verified_utc
from .network_diagnostics import DEFAULT_LOG, endpoint_category
from .request_throttle import DEFAULT_HTTP_GATE
from .metadata_cache import MetadataCache

try:
    from .credential_store import CredentialError, load_credentials
except ImportError:  # Allows the data/model tests to run before the credential UI is installed.
    class CredentialError(RuntimeError):
        pass
    def load_credentials():
        return None

DATA_HOST = "data.alpaca.markets"
PAPER_HOST = "paper-api.alpaca.markets"
SOURCE_NAME = "Alpaca 免费参考行情（股票 IEX / 期权 Indicative）"
MAX_SKEW_SECONDS = 120.0
FUTURE_QUOTE_TOLERANCE_SECONDS = 2.0
# Reviewed against official issuer/asset metadata. Expanding this set is a
# deliberate data-review action; unknown symbols remain display-only.
VERIFIED_INDIVIDUAL_STOCKS = frozenset({"AAPL", "GOOG", "GOOGL", "META", "MSFT", "NVDA", "SPCX"})

class AlpacaError(RuntimeError):
    pass

class AuthorizationRequired(AlpacaError):
    pass

class NetworkError(AlpacaError):
    pass

class StockQuoteUnavailable(AlpacaError):
    pass

class RateLimited(AlpacaError):
    def __init__(self, message: str, retry_after: float = 60.0):
        super().__init__(message)
        self.retry_after = max(60.0, retry_after)

def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool): return None
    try: number = float(value)
    except (TypeError, ValueError): return None
    return number if math.isfinite(number) else None

def _nonnegative_float(value: Any) -> float | None:
    number = _safe_float(value)
    return number if number is not None and number >= 0 else None

def _timestamp_too_far_future(value: datetime, received_at: datetime) -> bool:
    return value > received_at + timedelta(seconds=FUTURE_QUOTE_TOLERANCE_SECONDS)

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _default_open(request, *, timeout):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)

def _allowed_path(host: str, path: str) -> bool:
    if host == DATA_HOST:
        return bool(re.fullmatch(r"/v2/stocks/[A-Z0-9.\-]+/quotes(?:/latest)?", path) or
                    re.fullmatch(r"/v1beta1/options/snapshots(?:/[A-Z0-9.\-]+)?", path))
    if host == PAPER_HOST:
        return path in {"/v2/options/contracts", "/v2/calendar"} or bool(re.fullmatch(r"/v2/assets/[A-Z0-9.\-]+", path))
    return False

def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current)); yield current
        reason = getattr(current, "reason", None)
        current = reason if isinstance(reason, BaseException) else current.__cause__

def _network_kind(exc: BaseException) -> tuple[str, int | None, bool]:
    chain = list(_exception_chain(exc))
    errno = next((getattr(item, "errno", None) for item in chain if isinstance(getattr(item, "errno", None), int)), None)
    if any(isinstance(item, ssl.SSLCertVerificationError) for item in chain): return "tls_certificate", errno, False
    if any(isinstance(item, socket.gaierror) for item in chain): return "dns", errno, True
    if any(isinstance(item, (TimeoutError, socket.timeout)) for item in chain): return "timeout", errno, True
    if any(isinstance(item, ssl.SSLError) for item in chain): return "tls_handshake", errno, True
    if any(isinstance(item, (ConnectionError, ConnectionResetError, ConnectionRefusedError, http.client.HTTPException)) for item in chain): return "connection", errno, True
    return "network", errno, True

class AlpacaHttp:
    def __init__(self, api_key: str, secret: str, *, opener: Callable = _default_open, timeout: float = 15.0,
                 logger=None, monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, request_gate=None):
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}
        self._opener, self._timeout = opener, timeout
        class _NoLog:
            @staticmethod
            def record(**_kwargs): return None
        self._logger = logger if logger is not None else (DEFAULT_LOG if opener is _default_open else _NoLog())
        self._monotonic, self._sleep = monotonic, sleep
        self._request_gate = request_gate if request_gate is not None else (DEFAULT_HTTP_GATE if opener is _default_open else None)

    def get(self, host: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if not _allowed_path(host, path):
            raise AlpacaError("请求目标不在允许的只读接口范围内")
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        request = urllib.request.Request(urllib.parse.urlunsplit(("https", host, path, query, "")), headers=self._headers, method="GET")
        category = endpoint_category(host, path)
        for attempt in (1, 2):
            if self._request_gate is not None:
                self._request_gate.acquire()
            started = self._monotonic()
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    body = response.read(50 * 1024 * 1024 + 1)
                    status = getattr(response, "status", 200)
                    if len(body) > 50 * 1024 * 1024:
                        self._logger.record(endpoint=category, attempt=attempt, duration_ms=int((self._monotonic()-started)*1000), status=status, error_kind="response_too_large")
                        raise AlpacaError("行情响应超过安全大小限制")
                    try: payload = json.loads(body.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeError):
                        self._logger.record(endpoint=category, attempt=attempt, duration_ms=int((self._monotonic()-started)*1000), status=status, error_kind="response_format")
                        raise AlpacaError("Alpaca 只读接口响应格式无效") from None
                    self._logger.record(endpoint=category, attempt=attempt, duration_ms=int((self._monotonic()-started)*1000), status=status, error_kind=None)
                    return payload
            except urllib.error.HTTPError as exc:
                duration = int((self._monotonic()-started)*1000)
                if exc.code in {401, 403}:
                    self._logger.record(endpoint=category, attempt=attempt, duration_ms=duration, status=exc.code, error_kind="authorization")
                    raise AuthorizationRequired("Alpaca 凭据无效或当前免费权限不足") from None
                if exc.code == 429:
                    self._logger.record(endpoint=category, attempt=attempt, duration_ms=duration, status=429, error_kind="rate_limited")
                    try: retry = float(exc.headers.get("Retry-After", "60"))
                    except (TypeError, ValueError): retry = 60.0
                    if self._request_gate is not None:
                        self._request_gate.pause(retry)
                    raise RateLimited("Alpaca 请求过于频繁，已等待后再试", retry) from None
                kind = "http_5xx" if 500 <= exc.code <= 599 else ("redirect_blocked" if 300 <= exc.code <= 399 else "http_4xx")
                self._logger.record(endpoint=category, attempt=attempt, duration_ms=duration, status=exc.code, error_kind=kind)
                if kind == "http_5xx" and attempt == 1:
                    self._sleep(0.25); continue
                if kind == "http_5xx": raise NetworkError("Alpaca 只读接口服务暂时不可用") from None
                raise AlpacaError(f"Alpaca 只读接口返回 HTTP {exc.code}") from None
            except AlpacaError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                kind, error_number, retryable = _network_kind(exc)
                self._logger.record(endpoint=category, attempt=attempt, duration_ms=int((self._monotonic()-started)*1000), status=None, error_kind=kind, errno=error_number)
                if retryable and attempt == 1:
                    self._sleep(0.25); continue
                if kind == "tls_certificate": raise NetworkError("Alpaca TLS 证书校验失败") from None
                labels = {"dns":"域名解析失败", "timeout":"连接超时", "connection":"连接中断", "tls_handshake":"TLS 握手失败"}
                raise NetworkError(f"Alpaca 只读接口{labels.get(kind, '网络暂时不可用')}") from None
        raise NetworkError("Alpaca 只读接口网络暂时不可用")

def _page(client: AlpacaHttp, host: str, path: str, params: dict[str, Any], item_key: str, *, max_pages: int = 200) -> list[dict]:
    items: list[dict] = []
    token = None
    seen_tokens: set[str] = set()
    for _ in range(max_pages):
        page_params = dict(params)
        if token: page_params["page_token"] = token
        payload = client.get(host, path, page_params)
        values = payload.get(item_key) if isinstance(payload, dict) else None
        if not isinstance(values, (list, dict)): raise AlpacaError("Alpaca 分页响应缺少预期数据")
        if isinstance(values, dict):
            if any(not isinstance(value, dict) for value in values.values()):
                raise AlpacaError("Alpaca 分页响应包含畸形记录")
            items.extend({**value, "symbol": symbol} for symbol, value in values.items())
        else:
            if any(not isinstance(value, dict) for value in values):
                raise AlpacaError("Alpaca 分页响应包含畸形记录")
            items.extend(values)
        token = payload.get("next_page_token")
        if not token: return items
        if not isinstance(token, str) or token in seen_tokens:
            raise AlpacaError("Alpaca 分页令牌重复或无效")
        seen_tokens.add(token)
    raise AlpacaError("Alpaca 分页数量异常，已停止本轮快照")

def _quote(payload: dict, symbol: str) -> dict:
    quote = payload.get("quote") if isinstance(payload, dict) else None
    if not isinstance(quote, dict):
        quotes = payload.get("quotes") if isinstance(payload, dict) else None
        quote = quotes.get(symbol) if isinstance(quotes, dict) else None
    if not isinstance(quote, dict): raise AlpacaError("股票 IEX 报价缺少 quote")
    return quote

def _stock_quote_failure(quote: dict, expected_session: str, sessions: dict[str, tuple[datetime, datetime]],
                         *, not_after: datetime, future_tolerance_seconds: float = 0.0) -> str | None:
    bid, ask = _safe_float(quote.get("bp")), _safe_float(quote.get("ap"))
    quoted_at = parse_verified_utc(quote.get("t"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return "invalid_price"
    if quoted_at is None:
        return "missing_timestamp"
    if quoted_at > not_after + timedelta(seconds=max(0.0, future_tolerance_seconds)):
        return "future_timestamp"
    return None if quote_session_key(quoted_at, sessions) == expected_session else "wrong_session"

def _valid_stock_quote(quote: dict, expected_session: str, sessions: dict[str, tuple[datetime, datetime]],
                       *, not_after: datetime, future_tolerance_seconds: float = 0.0) -> tuple[float, float, datetime] | None:
    if _stock_quote_failure(quote, expected_session, sessions, not_after=not_after,
                            future_tolerance_seconds=future_tolerance_seconds) is not None:
        return None
    return _safe_float(quote.get("bp")), _safe_float(quote.get("ap")), parse_verified_utc(quote.get("t"))

def _stock_reference_quote(client: AlpacaHttp, symbol: str, now: datetime,
                           sessions: dict[str, tuple[datetime, datetime]], *,
                           received_clock: Callable[[], datetime] | None = None) -> tuple[dict[str, Any], str]:
    clock = received_clock or (lambda: now)
    latest_payload = client.get(DATA_HOST, f"/v2/stocks/{urllib.parse.quote(symbol, safe='')}/quotes/latest", {"feed": "iex"})
    received_at = clock().astimezone(timezone.utc)
    status = market_status(received_at, sessions)
    current_session = received_at.astimezone(EASTERN).date().isoformat() if status == "OPEN" else None
    completed_session = latest_completed_session_key(received_at, sessions)
    expected_session = current_session if status == "OPEN" else completed_session
    if expected_session is None:
        raise StockQuoteUnavailable("没有可核实的美股交易时段，无法取得股票参考价")
    try:
        latest = _quote(latest_payload, symbol)
    except AlpacaError:
        # The HTTP request itself succeeded; a missing/null/malformed quote is
        # an invalid latest value, not a transport/auth failure.
        latest = {}
    failure = _stock_quote_failure(latest, expected_session, sessions, not_after=received_at,
                                   future_tolerance_seconds=FUTURE_QUOTE_TOLERANCE_SECONDS)
    if failure is None:
        return latest, "最新有效 IEX 双边报价"
    if status == "OPEN":
        if failure == "future_timestamp":
            raise StockQuoteUnavailable("盘中最新 IEX 报价时间晚于接收时刻允许范围")
        if failure == "invalid_price":
            raise StockQuoteUnavailable("盘中最新 IEX bid/ask 无效，禁止用旧收盘数据替代")
        raise StockQuoteUnavailable("盘中最新 IEX 报价时间或交易时段无效，禁止用旧收盘数据替代")
    session = sessions.get(completed_session)
    if session is None:
        raise StockQuoteUnavailable("最近已完成交易时段未核实，无法取得股票参考价")
    closed_at = session[1].astimezone(timezone.utc)
    started_at = closed_at - timedelta(seconds=MAX_SKEW_SECONDS)
    params = {"feed": "iex", "start": started_at.isoformat().replace("+00:00", "Z"),
              "end": closed_at.isoformat().replace("+00:00", "Z"), "sort": "desc", "limit": 10000}
    token = None
    seen_tokens: set[str] = set()
    path = f"/v2/stocks/{urllib.parse.quote(symbol, safe='')}/quotes"
    for _ in range(200):
        page_params = dict(params)
        if token: page_params["page_token"] = token
        payload = client.get(DATA_HOST, path, page_params)
        page_received_at = clock().astimezone(timezone.utc)
        if market_status(page_received_at, sessions) == "OPEN":
            raise StockQuoteUnavailable("市场已开盘，禁止继续使用历史收盘报价")
        quotes = payload.get("quotes") if isinstance(payload, dict) else None
        if not isinstance(quotes, list) or any(not isinstance(quote, dict) for quote in quotes):
            raise StockQuoteUnavailable("历史 IEX 分页响应格式无效")
        for quote in quotes:  # API requested sort=desc: first valid record is the newest.
            valid = _valid_stock_quote(quote, completed_session, sessions, not_after=closed_at)
            if valid is not None and valid[2] >= started_at:
                return quote, "最近收盘前有效 IEX 报价"
        token = payload.get("next_page_token")
        if not token:
            raise StockQuoteUnavailable("最近收盘前 120 秒没有有效 IEX 双边报价")
        if not isinstance(token, str) or token in seen_tokens:
            raise StockQuoteUnavailable("历史 IEX 分页令牌重复或无效")
        seen_tokens.add(token)
    raise StockQuoteUnavailable("历史 IEX 分页数量异常，已停止查找")

def _sample_contracts(client: AlpacaHttp, spot: float) -> tuple[list[str], list[str]]:
    today = date.today()
    common = {"underlying_symbols": "AAPL", "expiration_date_gte": today.isoformat(), "expiration_date_lte": (today + timedelta(days=180)).isoformat(), "show_deliverables": "true", "limit": 10000}
    calls = _page(client, PAPER_HOST, "/v2/options/contracts", {**common, "type": "call"}, "option_contracts", max_pages=20)
    puts = _page(client, PAPER_HOST, "/v2/options/contracts", {**common, "type": "put"}, "option_contracts", max_pages=20)
    call_dates, put_dates = {str(r.get("expiration_date")) for r in calls}, {str(r.get("expiration_date")) for r in puts}
    expirations = sorted((call_dates & put_dates) - {"None"})
    if len(expirations) < 2: raise AlpacaError("AAPL 未取得两个不同到期日且各含 Call/Put 的样本合约")
    selected: list[str] = []
    for expiry in expirations[:2]:
        expiry_calls = [r for r in calls if str(r.get("expiration_date")) == expiry and r.get("symbol") and _safe_float(r.get("strike_price")) is not None]
        expiry_puts = [r for r in puts if str(r.get("expiration_date")) == expiry and r.get("symbol") and _safe_float(r.get("strike_price")) is not None]
        call = min(expiry_calls, key=lambda r: abs(float(r["strike_price"]) - spot), default=None)
        put = min(expiry_puts, key=lambda r: abs(float(r["strike_price"]) - spot), default=None)
        if not call or not put: raise AlpacaError("AAPL 样本合约组合不完整")
        for contract in (call, put):
            standard, _ = _standard_contract(contract, "AAPL", True)
            if not standard: raise AlpacaError("AAPL 样本未通过标准100股单一权益交割物核验")
            selected.append(contract["symbol"])
    if len(selected) < 4: raise AlpacaError("AAPL 样本缺少两个到期日的 Call/Put")
    return selected[:4], expirations

def probe_credentials(api_key: str, secret: str, *, client_factory=None) -> dict[str, Any]:
    checked = _iso_now()
    if not isinstance(api_key, str) or not api_key.strip() or not isinstance(secret, str) or not secret.strip():
        return {"ok": False, "error_code": "invalid_input", "message": "请输入完整的 Alpaca Paper API Key 和 Secret", "checked_at": checked, "expirations": []}
    try:
        client = (client_factory or AlpacaHttp)(api_key.strip(), secret.strip())
        probe_now = datetime.now(timezone.utc)
        eastern_day = probe_now.astimezone(EASTERN).date()
        calendar = client.get(PAPER_HOST, "/v2/calendar", {"start": (eastern_day-timedelta(days=7)).isoformat(), "end": (eastern_day + timedelta(days=14)).isoformat()})
        sessions = calendar_sessions(calendar) if isinstance(calendar, list) else {}
        if not sessions: raise AlpacaError("官方交易日历样本结构无效")
        stock, _stock_source = _stock_reference_quote(
            client, "AAPL", probe_now, sessions,
            received_clock=lambda: datetime.now(timezone.utc))
        stock_bp, stock_ap = _safe_float(stock.get("bp")), _safe_float(stock.get("ap"))
        if stock_bp is None or stock_ap is None or stock_bp <= 0 or stock_ap <= 0 or stock_ap < stock_bp or parse_verified_utc(stock.get("t")) is None:
            raise AlpacaError("AAPL IEX 样本缺少有效 bid/ask/时间戳")
        asset = client.get(PAPER_HOST, "/v2/assets/AAPL")
        if not isinstance(asset, dict) or not _asset_is_individual_stock("AAPL", asset): raise AlpacaError("AAPL 资产元数据核验失败")
        symbols, expirations = _sample_contracts(client, (stock_bp + stock_ap) / 2.0)
        snapshots = client.get(DATA_HOST, "/v1beta1/options/snapshots", {"symbols": ",".join(symbols), "feed": "indicative", "limit": 100})
        values = snapshots.get("snapshots") if isinstance(snapshots, dict) else None
        if not isinstance(values, dict) or not all(symbol in values for symbol in symbols):
            raise AlpacaError("AAPL Indicative 样本快照不完整")
        for symbol in symbols:
            quote = values[symbol].get("latestQuote") if isinstance(values[symbol], dict) else None
            bp, ap = (_safe_float(quote.get("bp")), _safe_float(quote.get("ap"))) if isinstance(quote, dict) else (None, None)
            if bp is None or ap is None or bp <= 0 or ap <= 0 or ap < bp or parse_verified_utc(quote.get("t")) is None:
                raise AlpacaError("AAPL Indicative 样本缺少有效 bid/ask/时间戳")
        return {"ok": True, "error_code": None, "message": "AAPL 样本验证通过：IEX 股票报价、两个到期日 Call/Put Indicative、合约元数据与日历均可访问", "checked_at": checked, "expirations": expirations[:2], "counts": {"stock_quotes": 1, "option_snapshots": len(symbols)}}
    except AuthorizationRequired as exc:
        return {"ok": False, "error_code": "authorization_required", "message": str(exc), "checked_at": checked, "expirations": []}
    except RateLimited as exc:
        return {"ok": False, "error_code": "rate_limited", "message": str(exc), "checked_at": checked, "expirations": [], "retry_after": exc.retry_after}
    except NetworkError as exc:
        return {"ok": False, "error_code": "network_error", "message": str(exc), "checked_at": checked, "expirations": []}
    except StockQuoteUnavailable as exc:
        return {"ok": False, "error_code": "stock_quote_unavailable", "message": str(exc), "checked_at": checked, "expirations": []}
    except Exception as exc:
        if isinstance(exc, AlpacaError):
            code, message = "sample_incomplete", str(exc)
        else:
            code, message = "network_error", "验证请求失败，请检查网络后重试"
        return {"ok": False, "error_code": code, "message": message, "checked_at": checked, "expirations": []}

def _asset_is_individual_stock(symbol: str, asset: dict) -> bool:
    return symbol in VERIFIED_INDIVIDUAL_STOCKS and str(asset.get("class", "")).lower() == "us_equity" and str(asset.get("symbol", "")).upper() == symbol

def _standard_contract(row: dict, underlying: str, stock_verified: bool) -> tuple[bool, str]:
    if not stock_verified: return False, "underlying_not_verified_individual_stock"
    if str(row.get("size")) != "100": return False, "non_standard_contract_size"
    if _safe_float(row.get("multiplier")) != 100: return False, "multiplier_not_verified"
    deliverables = row.get("deliverables")
    if not isinstance(deliverables, list) or len(deliverables) != 1: return False, "single_equity_deliverable_not_verified"
    deliverable = deliverables[0]
    if not isinstance(deliverable, dict): return False, "single_equity_deliverable_not_verified"
    kind = str(deliverable.get("type") or deliverable.get("asset_class") or "").lower()
    delivered_symbol = str(deliverable.get("symbol") or deliverable.get("underlying_symbol") or "").upper()
    quantity = _safe_float(deliverable.get("amount"))
    if kind not in {"equity", "us_equity", "stock"} or delivered_symbol != underlying or quantity != 100:
        return False, "adjusted_or_unknown_deliverable"
    if deliverable.get("delayed_settlement") is True: return False, "delayed_settlement_contract"
    underlying_asset_id, delivered_asset_id = row.get("underlying_asset_id"), deliverable.get("asset_id")
    if not underlying_asset_id or not delivered_asset_id or str(underlying_asset_id) != str(delivered_asset_id):
        return False, "deliverable_asset_not_verified"
    if str(row.get("root_symbol", "")).upper() != underlying or str(row.get("underlying_symbol", "")).upper() != underlying:
        return False, "contract_underlying_mismatch"
    if str(row.get("style", "")).lower() != "american": return False, "exercise_style_not_supported"
    return True, "verified_standard_100_share_contract"

def _safe_contract_metadata(row: dict, metadata_fetched_at: str | None = None) -> dict[str, Any]:
    def scalar(value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int)): return value
        if isinstance(value, float) and math.isfinite(value): return value
        return None
    deliverables: list[dict[str, Any]] | None = None
    allowed_deliverable = ("type", "symbol", "asset_id", "amount", "allocation_percentage",
                           "settlement_type", "settlement_method", "delayed_settlement")
    if isinstance(row.get("deliverables"), list):
        deliverables = []
        for item in row["deliverables"]:
            if isinstance(item, dict):
                deliverables.append({key: scalar(item.get(key)) for key in allowed_deliverable if key in item})
    return {
        "symbol": str(row.get("symbol") or ""),
        "strike_price": scalar(row.get("strike_price")),
        "expiration_date": scalar(row.get("expiration_date")),
        "type": scalar(row.get("type")),
        "size": scalar(row.get("size")),
        "multiplier": scalar(row.get("multiplier")),
        "root_symbol": str(row.get("root_symbol") or ""),
        "underlying_symbol": str(row.get("underlying_symbol") or ""),
        "style": str(row.get("style") or ""),
        "deliverables": deliverables,
        "metadata_fetched_at": metadata_fetched_at,
    }

class AlpacaAdapter:
    source_name = SOURCE_NAME
    def __init__(self, *, credentials_loader=load_credentials, client_factory=AlpacaHttp, probe=probe_credentials,
                 now: Callable[[], datetime] | None = None, monotonic: Callable[[], float] = time.monotonic,
                 metadata_cache: MetadataCache | None = None):
        self._credentials_loader, self._client_factory = credentials_loader, client_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._probe = probe
        self._validated: tuple[str, str] | None = None
        self._metadata = metadata_cache or MetadataCache(monotonic=monotonic)

    def _credentials(self) -> tuple[str, str] | None:
        try: return self._credentials_loader()
        except CredentialError as exc: raise AuthorizationRequired(str(exc)) from None

    @property
    def ready(self) -> bool:
        try: return self._credentials() is not None
        except AuthorizationRequired: return False

    def configuration_status(self) -> dict[str, Any]:
        try:
            return {"configured": self._credentials() is not None, "error": None}
        except AuthorizationRequired:
            return {"configured": False, "error": "AuthorizationRequired"}

    def _validated_client(self) -> AlpacaHttp:
        credentials = self._credentials()
        if credentials is None: raise AuthorizationRequired("待配置 Alpaca 凭据，请参阅项目配置说明")
        if self._validated != credentials:
            self._metadata.clear()
            result = self._probe(*credentials)
            if not result.get("ok"): raise AuthorizationRequired(str(result.get("message") or "Alpaca 样本验证失败"))
            self._validated = credentials
        return self._client_factory(*credentials)

    def fetch(self, symbol: str) -> dict[str, Any]:
        client, symbol = self._validated_client(), symbol.upper()
        started = self._now().astimezone(timezone.utc)
        fetched_at = started.isoformat().replace("+00:00", "Z")
        et_day = started.astimezone(EASTERN).date().isoformat()
        end_date = date(2035, 12, 31)
        try:
            asset, _asset_fetched_at = self._metadata.asset(
                symbol, et_day, fetched_at,
                lambda: client.get(PAPER_HOST, f"/v2/assets/{urllib.parse.quote(symbol, safe='')}"))
            contract_params = {"underlying_symbols": symbol, "expiration_date_gte": et_day, "expiration_date_lte": end_date.isoformat(), "show_deliverables": "true", "limit": 10000}
            contract_query = tuple(sorted(contract_params.items()))
            load_contracts = lambda: _page(client, PAPER_HOST, "/v2/options/contracts", contract_params, "option_contracts")
            contracts, contracts_fetched_at = self._metadata.contracts(symbol, contract_query, et_day, fetched_at, load_contracts)
        except ValueError as exc:
            raise AlpacaError("Alpaca 合约或资产元数据无效") from None
        expiries = [str(row.get("expiration_date")) for row in contracts if row.get("expiration_date")]
        if not expiries: raise AlpacaError("期权合约元数据缺少到期日")
        max_expiry = max(expiries)
        calendar_start = (started.astimezone(EASTERN).date()-timedelta(days=7)).isoformat()
        try:
            calendar, _calendar_fetched_at = self._metadata.calendar(
                symbol, calendar_start, max_expiry, et_day, fetched_at,
                lambda: client.get(PAPER_HOST, "/v2/calendar", {"start": calendar_start, "end": max_expiry}))
        except ValueError:
            raise AlpacaError("官方交易日历响应无效") from None
        sessions = calendar_sessions(calendar)
        stock_quote, stock_source = _stock_reference_quote(
            client, symbol, self._now().astimezone(timezone.utc), sessions,
            received_clock=self._now)
        stock_bid, stock_ask = _safe_float(stock_quote.get("bp")), _safe_float(stock_quote.get("ap"))
        if stock_bid is None or stock_ask is None or stock_bid <= 0 or stock_ask <= 0 or stock_ask < stock_bid:
            raise AlpacaError("股票 IEX 报价没有有效 bid/ask，不能建立本轮快照")
        spot, stock_time = (stock_bid + stock_ask) / 2.0, parse_verified_utc(stock_quote.get("t"))
        if stock_time is None: raise AlpacaError("股票 IEX 报价缺少有效时间戳")
        snapshots = _page(client, DATA_HOST, f"/v1beta1/options/snapshots/{urllib.parse.quote(symbol, safe='')}", {"feed": "indicative", "limit": 1000}, "snapshots")
        snapshot_map = {str(row.get("symbol")): {key: value for key, value in row.items() if key != "symbol"}
                        for row in snapshots if row.get("symbol")}
        known = {str(row.get("symbol") or "") for row in contracts}
        if set(snapshot_map) - known:
            try:
                contracts, contracts_fetched_at = self._metadata.contracts(
                    symbol, contract_query, et_day, fetched_at, load_contracts, force=True)
            except ValueError:
                raise AlpacaError("Alpaca 合约元数据刷新无效") from None
            refreshed_expiries = [str(row.get("expiration_date")) for row in contracts if row.get("expiration_date")]
            if refreshed_expiries and max(refreshed_expiries) > max_expiry:
                max_expiry = max(refreshed_expiries)
                try:
                    calendar, _calendar_fetched_at = self._metadata.calendar(
                        symbol, calendar_start, max_expiry, et_day, fetched_at,
                        lambda: client.get(PAPER_HOST, "/v2/calendar", {"start": calendar_start, "end": max_expiry}))
                    sessions = calendar_sessions(calendar)
                except ValueError:
                    raise AlpacaError("官方交易日历响应无效") from None
        now = self._now().astimezone(timezone.utc)
        status = market_status(now, sessions)
        transitions = []
        for opened, closed in sessions.values():
            opened_utc, closed_utc = opened.astimezone(timezone.utc), closed.astimezone(timezone.utc)
            if status == "OPEN" and opened_utc <= now < closed_utc:
                transitions.append(closed_utc)
            elif status == "CLOSED" and opened_utc > now:
                transitions.append(opened_utc)
        status_valid_until = min(transitions).isoformat().replace("+00:00", "Z") if transitions else None
        stock_verified = isinstance(asset, dict) and _asset_is_individual_stock(symbol, asset)
        latest_completed = latest_completed_session_key(now, sessions)
        current_session = now.astimezone(EASTERN).date().isoformat() if status == "OPEN" else None
        rows: list[NormalizedContract] = []
        for meta in contracts:
            contract_symbol = str(meta.get("symbol") or "")
            snap = snapshot_map.get(contract_symbol, {})
            quote = snap.get("latestQuote") if isinstance(snap.get("latestQuote"), dict) else {}
            option_time = parse_verified_utc(quote.get("t"))
            standard, standard_reason = _standard_contract(meta, symbol, stock_verified)
            cutoff = expiry_cutoff_utc(str(meta.get("expiration_date")), sessions)
            eligible, quote_reason = True, None
            stock_session = quote_session_key(stock_time, sessions)
            option_session = quote_session_key(option_time, sessions) if option_time else None
            quote_valid_until = None
            bid, ask = _safe_float(quote.get("bp")), _safe_float(quote.get("ap"))
            if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
                eligible, quote_reason = False, "invalid_option_bid_ask"
            elif option_time is None:
                eligible, quote_reason = False, "quote_time_missing"
            elif _timestamp_too_far_future(stock_time, now) or _timestamp_too_far_future(option_time, now):
                eligible, quote_reason = False, "quote_time_in_future"
            elif stock_session is None or option_session is None or stock_session != option_session:
                eligible, quote_reason = False, "quotes_not_same_verified_session"
            elif status == "OPEN" and stock_session != current_session:
                eligible, quote_reason = False, "quotes_not_current_open_session"
            elif status == "CLOSED" and (latest_completed is None or stock_session != latest_completed):
                eligible, quote_reason = False, "quotes_not_latest_completed_session"
            elif status not in {"OPEN", "CLOSED"}:
                eligible, quote_reason = False, "market_status_unverified"
            elif abs((option_time - stock_time).total_seconds()) > MAX_SKEW_SECONDS:
                eligible, quote_reason = False, "stock_option_quote_skew"
            elif status == "OPEN":
                if abs((now - stock_time).total_seconds()) > MAX_SKEW_SECONDS or abs((now - option_time).total_seconds()) > MAX_SKEW_SECONDS:
                    eligible, quote_reason = False, "stale_intraday_quote"
            if eligible and option_time is not None:
                close = session_close_utc(stock_session, sessions)
                deadline = min(stock_time + timedelta(seconds=MAX_SKEW_SECONDS),
                               option_time + timedelta(seconds=MAX_SKEW_SECONDS),
                               close) if close else None
                quote_valid_until = deadline.isoformat().replace("+00:00", "Z") if deadline else None
            greeks = snap.get("greeks") if isinstance(snap.get("greeks"), dict) else {}
            raw_multiplier = _safe_float(meta.get("multiplier"))
            normalized_multiplier = int(raw_multiplier) if raw_multiplier is not None and raw_multiplier.is_integer() else None
            rows.append(NormalizedContract(
                contract_symbol=contract_symbol, underlying=symbol, side=str(meta.get("type", "")).upper(),
                strike=_safe_float(meta.get("strike_price")), bid=bid, ask=ask,
                multiplier=normalized_multiplier, standard=standard, expires_at_utc=cutoff, expiry_verified=cutoff is not None,
                expiration_date=str(meta.get("expiration_date")) if meta.get("expiration_date") else None,
                quote_time_utc=option_time.isoformat().replace("+00:00", "Z") if option_time else None,
                implied_volatility=_nonnegative_float(snap.get("impliedVolatility")), delta=_safe_float(greeks.get("delta")),
                open_interest=_nonnegative_float(meta.get("open_interest")), open_interest_date=meta.get("open_interest_date"),
                standard_reason=standard_reason, quote_eligible=eligible, quote_reason=quote_reason,
                quote_valid_until_utc=quote_valid_until, quote_session_date=option_session,
                latest_completed_session_date=latest_completed,
                contract_metadata=_safe_contract_metadata(meta, contracts_fetched_at)))
        known = {row.contract_symbol for row in rows}
        for contract_symbol in sorted(set(snapshot_map) - known):
            snap = snapshot_map[contract_symbol]
            quote = snap.get("latestQuote") if isinstance(snap.get("latestQuote"), dict) else {}
            option_time = parse_verified_utc(quote.get("t"))
            greeks = snap.get("greeks") if isinstance(snap.get("greeks"), dict) else {}
            rows.append(NormalizedContract(
                contract_symbol=contract_symbol, underlying=symbol, side="", strike=None,
                bid=_safe_float(quote.get("bp")), ask=_safe_float(quote.get("ap")), multiplier=None,
                standard=False, expires_at_utc=None, expiry_verified=False,
                quote_time_utc=option_time.isoformat().replace("+00:00", "Z") if option_time else None,
                implied_volatility=_nonnegative_float(snap.get("impliedVolatility")), delta=_safe_float(greeks.get("delta")),
                standard_reason="contract_metadata_unavailable", quote_eligible=False,
                quote_reason="contract_metadata_unavailable",
                contract_metadata=_safe_contract_metadata({"symbol": contract_symbol}, contracts_fetched_at)))
        captured = stock_time.isoformat().replace("+00:00", "Z")
        source_detail = f"股票 {stock_source}；期权 Indicative（免费调整参考源，非真实 OPRA）"
        return {"market_status": status, "calculated_at": captured, "quote_time": stock_time.isoformat().replace("+00:00", "Z"),
                "market_status_valid_until_utc": status_valid_until,
                "source_delay_label": source_detail, "freshness": "snapshot",
                "calculation_basis": f"本轮快照冻结于股票源报价 {captured}（{stock_source}）；到期截止按 Alpaca 美股日历收盘时间（含提前收市）",
                "latest_completed_session_date": latest_completed,
                "underlying_price": spot, "contracts": rows,
                "notice": None if stock_verified else "标的未由官方资产名称核实为个股普通股，合约仅展示且不计算参考年化"}
