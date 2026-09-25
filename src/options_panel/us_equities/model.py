from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

STANDARD_MULTIPLIER = 100
SECONDS_PER_YEAR = 365.0 * 86400.0

def finite_positive(value: Any) -> float | None:
    if isinstance(value, bool): return None
    try: number = float(value)
    except (TypeError, ValueError): return None
    return number if math.isfinite(number) and number > 0 else None

def parse_verified_utc(value: str | None) -> datetime | None:
    if not value: return None
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError): return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

def time_value_and_denominator(bid: Any, strike: Any, underlying_price: Any, side: str) -> tuple[float | None, float | None, str | None]:
    premium, valid_strike, spot = finite_positive(bid), finite_positive(strike), finite_positive(underlying_price)
    if premium is None: return None, None, "no_valid_bid"
    if valid_strike is None or spot is None: return None, None, "missing_underlying_or_strike"
    normalized_side = str(side).upper()
    if normalized_side == "CALL":
        intrinsic, denominator = max(spot - valid_strike, 0.0), spot
    elif normalized_side == "PUT":
        intrinsic, denominator = max(valid_strike - spot, 0.0), valid_strike
    else:
        return None, None, "unknown_contract_side"
    time_value = premium - intrinsic
    if not math.isfinite(time_value) or time_value <= 0:
        return time_value, denominator, "non_positive_time_value"
    return time_value, denominator, None

def quote_prices_status(bid: Any, ask: Any) -> str | None:
    valid_bid, valid_ask = finite_positive(bid), finite_positive(ask)
    if valid_bid is None: return "no_valid_bid"
    if valid_ask is None: return "no_valid_ask"
    if valid_ask < valid_bid: return "inverted_quote"
    return None

def exercise_probability(bid: Any, ask: Any, side: str, spot: Any, strike: Any,
                         expires_at_utc: str | None, calculated_at_utc: str | None,
                         implied_volatility: Any, open_interest: Any = None) -> tuple[float | None, str | None]:
    """Estimate expiry ITM probability with Black-Scholes d2, fixed r=0 and q=0."""
    if isinstance(open_interest, bool):
        return None, "invalid_open_interest"
    if open_interest is not None:
        try: parsed_oi = float(open_interest)
        except (TypeError, ValueError): return None, "invalid_open_interest"
        if not math.isfinite(parsed_oi) or parsed_oi < 0: return None, "invalid_open_interest"
        if parsed_oi == 0: return None, "zero_open_interest"
    if quote_prices_status(bid, ask): return None, "invalid_option_bid_ask"
    valid_spot, valid_strike, sigma = (finite_positive(spot), finite_positive(strike),
                                       finite_positive(implied_volatility))
    normalized_side = str(side).upper()
    if valid_spot is None or valid_strike is None or normalized_side not in {"CALL", "PUT"}:
        return None, "invalid_contract"
    expiry, basis = parse_verified_utc(expires_at_utc), parse_verified_utc(calculated_at_utc)
    if expiry is None or basis is None: return None, "expiry_not_verified"
    remaining = (expiry - basis).total_seconds()
    if remaining <= 0: return None, "expired"
    if sigma is None: return None, "invalid_iv"
    try:
        years = remaining / SECONDS_PER_YEAR
        root_t = math.sqrt(years)
        sigma_squared = sigma * sigma
        numerator = math.log(valid_spot) - math.log(valid_strike) - 0.5 * sigma_squared * years
        denominator = sigma * root_t
        if (not all(math.isfinite(value) for value in
                    (years, root_t, sigma_squared, numerator, denominator)) or denominator <= 0):
            return None, "model_error"
        d2 = numerator / denominator
        if not math.isfinite(d2): return None, "model_error"
        signed = d2 if normalized_side == "CALL" else -d2
        probability = 50.0 * math.erfc(-signed / math.sqrt(2.0))
    except (ArithmeticError, OverflowError, ValueError):
        return None, "model_error"
    if not math.isfinite(probability): return None, "model_error"
    return min(100.0, max(0.0, probability)), None

def annualized_pct(bid: Any, strike: Any, underlying_price: Any, side: str, remaining_seconds: float, multiplier: Any = STANDARD_MULTIPLIER) -> float | None:
    if finite_positive(multiplier) != STANDARD_MULTIPLIER or not math.isfinite(remaining_seconds) or remaining_seconds <= 0:
        return None
    time_value, denominator, reason = time_value_and_denominator(bid, strike, underlying_price, side)
    if reason or time_value is None or denominator is None: return None
    return time_value / denominator * SECONDS_PER_YEAR / remaining_seconds * 100.0

@dataclass(frozen=True)
class NormalizedContract:
    contract_symbol: str
    underlying: str
    side: str
    strike: float | None
    bid: float | None
    ask: float | None
    multiplier: int | None
    standard: bool
    expires_at_utc: str | None
    expiry_verified: bool
    expiration_date: str | None = None
    quote_time_utc: str | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    open_interest: float | None = None
    open_interest_date: str | None = None
    standard_reason: str | None = None
    quote_eligible: bool = True
    quote_reason: str | None = None
    quote_valid_until_utc: str | None = None
    quote_session_date: str | None = None
    latest_completed_session_date: str | None = None
    contract_metadata: dict[str, Any] = field(default_factory=dict)

def calculate_contract(contract: NormalizedContract, *, underlying_price: Any, market_status: str, calculated_at_utc: str, now_utc: datetime | None = None) -> dict[str, Any]:
    row = asdict(contract)
    row.update(calculation_status="unavailable", annualized_pct=None, period_return_pct=None, capital_base=None,
               time_value=None, remaining_seconds=None, calculation_basis_utc=calculated_at_utc,
               exercise_probability_pct=None, probability_basis_utc=None,
               probability_model="black_scholes_d2_expiry_itm_approximation",
               probability_reason="calculation_unavailable",
               probability_assumptions={"risk_free_rate": 0.0, "dividend_yield": 0.0},
               ranking_eligible=False, ranking_reason="calculation_unavailable",
               close_reference_eligible=False, close_reference_reason="calculation_unavailable")
    expiry = parse_verified_utc(contract.expires_at_utc) if contract.expiry_verified else None
    real_now = now_utc or datetime.now(timezone.utc)
    if expiry is not None and expiry <= real_now:
        row["remaining_seconds"], row["calculation_status"], row["probability_reason"] = 0.0, "expired", "expired"; return row
    if not contract.standard or contract.multiplier != STANDARD_MULTIPLIER:
        row["calculation_status"] = contract.standard_reason or "non_standard_contract"
        row["probability_reason"] = row["calculation_status"]; return row
    if not contract.quote_eligible:
        row["calculation_status"] = contract.quote_reason or "quote_not_eligible"
        row["probability_reason"] = row["calculation_status"]; return row
    basis = parse_verified_utc(calculated_at_utc)
    if expiry is None or basis is None:
        row["calculation_status"] = row["probability_reason"] = "expiry_not_verified"; return row
    row["probability_basis_utc"] = calculated_at_utc
    remaining = (expiry - basis).total_seconds()
    row["remaining_seconds"] = max(0.0, remaining)
    if remaining <= 0:
        row["calculation_status"] = row["probability_reason"] = "expired"; return row
    if str(market_status).upper() not in {"OPEN", "CLOSED"}:
        row["calculation_status"] = row["probability_reason"] = "market_status_unverified"; return row
    quote_status = quote_prices_status(contract.bid, contract.ask)
    if quote_status:
        row["calculation_status"], row["ranking_reason"], row["probability_reason"] = quote_status, quote_status, quote_status; return row
    probability, probability_reason = exercise_probability(
        contract.bid, contract.ask, contract.side, underlying_price, contract.strike,
        contract.expires_at_utc, calculated_at_utc, contract.implied_volatility, contract.open_interest)
    row["exercise_probability_pct"], row["probability_reason"] = probability, probability_reason
    tv, denominator, reason = time_value_and_denominator(contract.bid, contract.strike, underlying_price, contract.side)
    row["time_value"] = tv
    if reason:
        row["calculation_status"] = reason; return row
    row["capital_base"] = denominator
    row["period_return_pct"] = tv / denominator * 100.0 if tv is not None and denominator else None
    value = annualized_pct(contract.bid, contract.strike, underlying_price, contract.side, remaining, contract.multiplier)
    if value is None: return row
    row["annualized_pct"], row["calculation_status"] = value, "calculated"
    if (str(market_status).upper() == "CLOSED" and contract.quote_session_date
            and contract.quote_session_date == contract.latest_completed_session_date):
        row["close_reference_eligible"], row["close_reference_reason"] = True, None
    elif str(market_status).upper() == "CLOSED":
        row["close_reference_reason"] = "quotes_not_latest_completed_session"
    else:
        row["close_reference_reason"] = "market_not_closed"
    valid_until = parse_verified_utc(contract.quote_valid_until_utc)
    if valid_until is not None and real_now <= valid_until:
        row["ranking_eligible"], row["ranking_reason"] = True, None
    else:
        row["ranking_reason"] = "quote_ranking_window_expired" if valid_until else "quote_ranking_window_unverified"
    return row

