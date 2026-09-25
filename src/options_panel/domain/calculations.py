from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any

def utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def finite_nonnegative(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalized_bid(bid: Any, unit: Any) -> float | None:
    """Return premium quoted per BTC.

    Binance bidPrice and strikePrice use the same underlying-unit basis.  The
    contract unit therefore cancels in bid*unit / strike*unit; it must be
    valid, but the quote must not be multiplied by it again.
    """
    valid_bid = finite_positive(bid)
    valid_unit = finite_positive(unit)
    if valid_bid is None or valid_unit is None:
        return None
    return valid_bid


def moneyness(side: str, strike: float, spot: float) -> tuple[str, float]:
    tolerance = max(1.0, spot * 0.0001)  # 1 USDT or one basis point.
    delta = strike - spot
    if abs(delta) <= tolerance:
        return "ATM", tolerance
    if side == "CALL":
        return ("OTM" if delta > 0 else "ITM"), tolerance
    return ("OTM" if delta < 0 else "ITM"), tolerance


def yield_metrics(side: str, bid: Any, spot: Any, strike: Any, unit: Any,
                  expiry_ms: Any, now_ms: Any, open_interest: Any = None,
                  include_nonpositive_returns: bool = False,
                  allow_zero_premium: bool = False) -> dict[str, Any]:
    """Calculate one-period and annualized time-value returns for one frozen market generation."""
    empty = {
        "intrinsic_value": None, "time_value": None, "time_value_status": "unavailable", "capital_base": None,
        "period_return_pct": None, "remaining_years": None, "annualized_pct": None,
        "calculation_index_price": None,
        "annualized_basis": "time_value_on_spot" if side == "CALL" else "time_value_on_strike",
    }
    if finite_nonnegative(open_interest) == 0:
        return empty
    premium = (finite_nonnegative(bid) if finite_positive(unit) is not None else None) if allow_zero_premium else normalized_bid(bid, unit)
    valid_spot = finite_positive(spot)
    valid_strike = finite_positive(strike)
    expiry = finite_number(expiry_ms)
    basis = finite_number(now_ms)
    if (premium is None or valid_spot is None or valid_strike is None
            or expiry is None or basis is None or side not in {"CALL", "PUT"}):
        return empty
    remaining_years = (expiry - basis) / (365.0 * 24.0 * 3600.0 * 1000.0)
    if remaining_years <= 0:
        return empty
    intrinsic = max(valid_spot - valid_strike, 0.0) if side == "CALL" else max(valid_strike - valid_spot, 0.0)
    time_value = premium - intrinsic
    time_value_status = "positive" if time_value > 0 else ("negative" if time_value < 0 else "zero")
    capital_base = valid_spot if side == "CALL" else valid_strike
    raw_period_return_pct = time_value / capital_base * 100.0
    raw_annualized = raw_period_return_pct / remaining_years
    if not all(math.isfinite(value) for value in (
            intrinsic, time_value, capital_base, raw_period_return_pct, remaining_years, raw_annualized)):
        return empty
    expose_returns = time_value > 0 or include_nonpositive_returns
    return {
        "intrinsic_value": intrinsic,
        "time_value": time_value,
        "time_value_status": time_value_status,
        "capital_base": capital_base,
        "period_return_pct": raw_period_return_pct if expose_returns else None,
        "remaining_years": remaining_years,
        "annualized_pct": raw_annualized if expose_returns else None,
        "calculation_index_price": valid_spot,
        "annualized_basis": "time_value_on_spot" if side == "CALL" else "time_value_on_strike",
    }


def annualized_components(side: str, bid: Any, spot: Any, strike: Any, unit: Any,
                          expiry_ms: Any, now_ms: Any,
                          open_interest: Any = None) -> tuple[float | None, float | None, float | None]:
    metrics = yield_metrics(side, bid, spot, strike, unit, expiry_ms, now_ms, open_interest)
    return metrics["intrinsic_value"], metrics["time_value"], metrics["annualized_pct"]


def annualized_yield(side: str, bid: Any, spot: Any, strike: Any, unit: Any,
                     expiry_ms: Any, now_ms: Any, open_interest: Any = None) -> float | None:
    return annualized_components(side, bid, spot, strike, unit, expiry_ms, now_ms, open_interest)[2]


def exercise_probability(side: str, spot: Any, strike: Any, expiry_ms: Any, calculated_at_ms: Any,
                         mark_iv: Any, risk_free_interest: Any,
                         open_interest: Any = None) -> tuple[float | None, str | None]:
    """Estimate expiry ITM probability with Black-Scholes d2 and q=0."""
    if finite_nonnegative(open_interest) == 0:
        return None, "zero_open_interest"
    valid_spot = finite_positive(spot)
    valid_strike = finite_positive(strike)
    sigma = finite_positive(mark_iv)
    rate = finite_number(risk_free_interest)
    expiry = finite_number(expiry_ms)
    basis = finite_number(calculated_at_ms)
    if valid_spot is None or valid_strike is None or side not in {"CALL", "PUT"}:
        return None, "invalid_contract"
    if expiry is None or basis is None or expiry <= basis:
        return None, "expired"
    if sigma is None:
        return None, "invalid_iv"
    if rate is None:
        return None, "invalid_risk_free_interest"
    years = (expiry - basis) / (365.0 * 86400.0 * 1000.0)
    try:
        root_t = math.sqrt(years)
        numerator = math.log(valid_spot / valid_strike) + (rate - 0.5 * sigma * sigma) * years
        denominator = sigma * root_t
        d2 = numerator / denominator
        if not all(math.isfinite(value) for value in (years, root_t, numerator, denominator, d2)):
            return None, "model_error"
        signed = d2 if side == "CALL" else -d2
        probability = 50.0 * math.erfc(-signed / math.sqrt(2.0))
    except (ArithmeticError, OverflowError, ValueError):
        return None, "model_error"
    if not math.isfinite(probability):
        return None, "model_error"
    return min(100.0, max(0.0, probability)), None


