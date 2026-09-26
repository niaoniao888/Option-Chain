from __future__ import annotations
import http.client, json, logging, math, socket, ssl, time, urllib.error, urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from options_panel.domain.calculations import finite_positive, finite_nonnegative, finite_number, utc_iso
from options_panel.logging import log_event
from options_panel.config import APP_ID, APP_VERSION, API_ROOT, REQUEST_TIMEOUT, FETCH_ATTEMPTS, FETCH_RETRY_DELAY

def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for nested in (getattr(current, "reason", None), current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
        pending.extend(arg for arg in current.args if isinstance(arg, BaseException))


def is_transient_transport_error(exc: BaseException) -> bool:
    transient = (ssl.SSLEOFError, TimeoutError, socket.timeout, ConnectionResetError,
                 http.client.RemoteDisconnected, http.client.IncompleteRead)
    chain = list(_exception_chain(exc))
    if any(isinstance(current, ssl.SSLCertVerificationError) for current in chain):
        return False
    if any(isinstance(current, ssl.SSLError) and not isinstance(current, ssl.SSLEOFError)
           for current in chain):
        return False
    return any(isinstance(current, transient) for current in chain)


def is_retryable_fetch_error(exc: BaseException) -> bool:
    """Classify by transport cause without overriding top-level HTTP/data semantics."""
    chain = list(_exception_chain(exc))
    if any(isinstance(current, ssl.SSLCertVerificationError) for current in chain):
        return False
    if any(isinstance(current, ssl.SSLError) and not isinstance(current, ssl.SSLEOFError)
           for current in chain):
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {500, 502, 503, 504}
    if isinstance(exc, (json.JSONDecodeError, UnicodeError)):
        return False
    return is_transient_transport_error(exc)


def fetch_json(path: str, timeout: float = REQUEST_TIMEOUT) -> Any:
    request = urllib.request.Request(
        API_ROOT + path,
        headers={"Accept": "application/json", "User-Agent": f"{APP_ID}/{APP_VERSION}"},
    )
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            log_event(
                logging.INFO, "upstream_request", path=path, attempt=attempt,
                duration_ms=round((time.monotonic() - started) * 1000, 1), result="success",
                recovered=attempt > 1,
            )
            return payload
        except Exception as exc:
            retryable = is_retryable_fetch_error(exc)
            will_retry = retryable and attempt < FETCH_ATTEMPTS
            log_event(
                logging.WARNING, "upstream_request", path=path, attempt=attempt,
                duration_ms=round((time.monotonic() - started) * 1000, 1), result="retry" if will_retry else "failed",
                exception_type=type(exc).__name__, retryable=retryable, recovered=False,
            )
            if not will_retry:
                raise
            time.sleep(FETCH_RETRY_DELAY)
    raise RuntimeError("unreachable")


def parse_catalog(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("optionSymbols"), list):
        raise ValueError("exchangeInfo 缺少 optionSymbols")
    result = []
    for item in payload["optionSymbols"]:
        if not isinstance(item, dict) or item.get("underlying") != "BTCUSDT":
            continue
        if str(item.get("status", "")).upper() != "TRADING":
            continue
        symbol = item.get("symbol")
        strike = finite_positive(item.get("strikePrice"))
        unit = finite_positive(item.get("unit"))
        side = str(item.get("side", "")).upper()
        try:
            expiry_ms = int(item.get("expiryDate"))
        except (TypeError, ValueError):
            continue
        if not symbol or strike is None or unit is None or side not in {"CALL", "PUT"}:
            continue
        result.append({
            "symbol": str(symbol), "expiry_ms": expiry_ms, "side": side,
            "strike": strike, "unit": unit, "status": "TRADING",
        })
    if not result:
        raise ValueError("未找到有效的 BTCUSDT 活跃期权合约")
    result.sort(key=lambda row: (row["expiry_ms"], row["strike"], row["side"]))
    return result


def parse_quotes(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("ticker 不是数组")
    result: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        result[str(item["symbol"])] = {
            "bid": finite_positive(item.get("bidPrice")),
            "ask": finite_positive(item.get("askPrice")),
            "last": finite_positive(item.get("lastPrice")),
            "last_trade_time_ms": item.get("closeTime"),
        }
    if not result:
        raise ValueError("ticker 未返回任何有效合约行情")
    if not any(symbol.startswith(("BTC-", "BTCUSDT-")) for symbol in result):
        raise ValueError("ticker 未返回 BTC 期权行情")
    return result


def expiration_code(expiry_ms: Any) -> str:
    try:
        value = float(expiry_ms)
    except (TypeError, ValueError) as exc:
        raise ValueError("期权到期时间无效") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("期权到期时间无效")
    return datetime.fromtimestamp(value / 1000.0, timezone.utc).strftime("%y%m%d")


def parse_open_interest(payload: Any, expected_expiration: str | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("openInterest 不是数组")
    result: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
            continue
        symbol = item["symbol"]
        parts = symbol.split("-")
        if len(parts) < 2 or parts[0] != "BTC":
            continue
        if expected_expiration is not None and parts[1] != expected_expiration:
            continue
        value = finite_nonnegative(item.get("sumOpenInterest"))
        if value is None:
            continue
        timestamp = finite_nonnegative(item.get("timestamp"))
        result[symbol] = {
            "open_interest": value,
            "open_interest_time_ms": int(timestamp) if timestamp is not None else None,
        }
    if not result:
        raise ValueError("openInterest 未返回任何有效 BTC 期权持仓量")
    return result


def parse_marks(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("mark 不是数组")
    result: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
            continue
        symbol = item["symbol"]
        if not symbol.startswith(("BTC-", "BTCUSDT-")):
            continue
        result[symbol] = {
            "mark_iv": finite_positive(item.get("markIV")),
            "risk_free_interest": finite_number(item.get("riskFreeInterest")),
            "delta": finite_number(item.get("delta")),
            "mark_price": finite_nonnegative(item.get("markPrice")),
        }
    if not result:
        raise ValueError("mark 未返回任何 BTC 期权参数")
    return result


def parse_index(payload: Any) -> float:
    if not isinstance(payload, dict):
        raise ValueError("index 响应格式错误")
    value = finite_positive(payload.get("indexPrice"))
    if value is None:
        raise ValueError("BTC 指数价格无效")
    return value


def parse_server_time(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise ValueError("time 响应格式错误")
    try:
        value = int(payload["serverTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("服务器时间无效") from exc
    if value <= 0:
        raise ValueError("服务器时间无效")
    return value


