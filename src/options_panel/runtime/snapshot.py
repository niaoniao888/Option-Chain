from __future__ import annotations
import copy, math, threading, time
from typing import Any, Callable
from options_panel.config import APP_ID, APP_VERSION, STALE_AFTER
from options_panel.domain.calculations import finite_positive, finite_nonnegative, finite_number, normalized_bid, moneyness, yield_metrics, exercise_probability
from options_panel.providers.binance import utc_iso

class DashboardState:
    def __init__(self, wall_clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic):
        self._lock = threading.RLock()
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self.contracts: list[dict[str, Any]] = []
        self.quotes: dict[str, dict[str, Any]] = {}
        self.open_interest: dict[str, dict[str, Any]] = {}
        self.annualized_values: dict[str, dict[str, Any]] = {}
        self.mark_data: dict[str, dict[str, Any]] = {}
        self.probabilities: dict[str, dict[str, Any]] = {}
        self.mark_warning: str | None = None
        self.index_price: float | None = None
        self.server_time_ms: int | None = None
        self.server_time_monotonic: float | None = None
        self.market_fetched_at: float | None = None
        self.market_fetched_monotonic: float | None = None
        self.catalog_fetched_at: float | None = None
        self.market_error: str | None = None
        self.catalog_error: str | None = None
        self.next_market_at = self.monotonic()
        self.next_catalog_at = self.monotonic()

    def current_server_ms(self) -> float:
        with self._lock:
            return self._current_server_ms_locked(self.monotonic(), self.wall_clock())

    def _current_server_ms_locked(self, mono_now: float, wall_now: float) -> float:
        if self.server_time_ms is None or self.server_time_monotonic is None:
            return wall_now * 1000.0
        return self.server_time_ms + (mono_now - self.server_time_monotonic) * 1000.0

    def _health_locked(self, mono_now: float) -> dict[str, Any]:
        age = (None if self.market_fetched_monotonic is None
               else max(0.0, mono_now - self.market_fetched_monotonic))
        stale = age is None or age >= STALE_AFTER
        if self.market_fetched_at is None or self.catalog_fetched_at is None:
            level = "error"
        elif stale or self.market_error or self.catalog_error or self.mark_warning:
            level = "degraded"
        else:
            level = "healthy"
        return {
            "app": APP_ID, "version": APP_VERSION, "status": level, "stale": stale,
            "age_seconds": age, "market_error": self.market_error,
            "catalog_error": self.catalog_error, "mark_warning": self.mark_warning,
        }

    def commit_catalog(self, contracts: list[dict[str, Any]]) -> None:
        with self._lock:
            self.contracts = contracts
            self.catalog_fetched_at = self.wall_clock()
            self.catalog_error = None

    def fail_catalog(self, message: str) -> None:
        with self._lock:
            self.catalog_error = message

    def active_contracts(self, server_time_ms: int) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy([
                contract for contract in self.contracts
                if contract["expiry_ms"] > server_time_ms
            ])

    def commit_market(self, quotes: dict[str, dict[str, Any]], index_price: float, server_time_ms: int,
                      open_interest: dict[str, dict[str, Any]] | None = None,
                      marks: dict[str, dict[str, Any]] | None = None,
                      mark_warning: str | None = None) -> None:
        with self._lock:
            mono_now = self.monotonic()
            wall_now = self.wall_clock()
            now_ms = float(server_time_ms)
            active_symbols = {
                contract["symbol"] for contract in self.contracts
                if contract["expiry_ms"] > now_ms
            }
            required_symbols = active_symbols.intersection(self.quotes)
            missing = sorted(required_symbols.difference(quotes))
            if missing:
                preview = ", ".join(missing[:3])
                suffix = "…" if len(missing) > 3 else ""
                raise ValueError(f"ticker 批量响应缺少 {len(missing)} 个既有活跃合约：{preview}{suffix}")
            if open_interest is not None:
                missing_oi = sorted(active_symbols.difference(open_interest))
                if missing_oi:
                    preview = ", ".join(missing_oi[:3])
                    suffix = "…" if len(missing_oi) > 3 else ""
                    raise ValueError(f"openInterest 响应缺少 {len(missing_oi)} 个活跃合约：{preview}{suffix}")
            committed_oi = open_interest if open_interest is not None else self.open_interest
            committed_marks = marks or {}
            probabilities: dict[str, dict[str, Any]] = {}
            annualized_values: dict[str, dict[str, Any]] = {}
            for contract in self.contracts:
                symbol = contract["symbol"]
                mark = committed_marks.get(symbol, {})
                oi_value = committed_oi.get(symbol, {}).get("open_interest")
                quote = quotes.get(symbol, {})
                bid = normalized_bid(quote.get("bid"), contract["unit"])
                metrics = yield_metrics(
                    contract["side"], bid, index_price, contract["strike"], contract["unit"],
                    contract["expiry_ms"], server_time_ms, oi_value,
                )
                annualized = metrics["annualized_pct"]
                mark_metrics = {
                    "mark_time_value": None,
                    "mark_period_return_pct": None,
                    "mark_annualized_pct": None,
                    "mark_annualized_calculated_at_ms": None,
                }
                if metrics["time_value_status"] in {"zero", "negative"}:
                    mark_yield = yield_metrics(
                        contract["side"], mark.get("mark_price"), index_price, contract["strike"],
                        contract["unit"], contract["expiry_ms"], server_time_ms, oi_value,
                        include_nonpositive_returns=True, allow_zero_premium=True,
                    )
                    if mark_yield["time_value_status"] != "unavailable":
                        mark_metrics = {
                            "mark_time_value": mark_yield["time_value"],
                            "mark_period_return_pct": mark_yield["period_return_pct"],
                            "mark_annualized_pct": mark_yield["annualized_pct"],
                            "mark_annualized_calculated_at_ms": server_time_ms,
                        }
                if oi_value == 0:
                    annualized_reason = "zero_open_interest"
                elif contract["expiry_ms"] <= server_time_ms:
                    annualized_reason = "expired"
                elif bid is None:
                    annualized_reason = "invalid_bid"
                elif finite_positive(index_price) is None:
                    annualized_reason = "invalid_index"
                elif metrics["time_value_status"] in {"zero", "negative"}:
                    annualized_reason = "nonpositive_time_value"
                elif annualized is None:
                    annualized_reason = "invalid_contract"
                else:
                    annualized_reason = None
                annualized_values[symbol] = {
                    **metrics,
                    **mark_metrics,
                    "annualized_calculated_at_ms": server_time_ms,
                    "annualized_unavailable_reason": annualized_reason,
                }
                try:
                    probability, reason = exercise_probability(
                        contract["side"], index_price, contract["strike"], contract["expiry_ms"],
                        server_time_ms, mark.get("mark_iv"), mark.get("risk_free_interest"), oi_value,
                    )
                except Exception:
                    probability, reason = None, "model_error"
                if not mark and reason != "zero_open_interest":
                    probability, reason = None, "mark_unavailable"
                probabilities[symbol] = {
                    **mark,
                    "exercise_probability_pct": probability,
                    "probability_calculated_at_ms": server_time_ms,
                    "exercise_probability_unavailable_reason": reason,
                }
            self.quotes = quotes
            if open_interest is not None:
                self.open_interest = open_interest
            self.mark_data = committed_marks
            self.probabilities = probabilities
            self.annualized_values = annualized_values
            self.mark_warning = mark_warning
            self.index_price = index_price
            self.server_time_ms = server_time_ms
            self.server_time_monotonic = mono_now
            self.market_fetched_at = wall_now
            self.market_fetched_monotonic = mono_now
            self.market_error = None

    def fail_market(self, message: str) -> None:
        with self._lock:
            self.market_error = message

    def refresh_deadlines(self) -> tuple[float, float]:
        with self._lock:
            return self.next_catalog_at, self.next_market_at

    def refresh_log_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "contract_count": len(self.contracts),
                "quote_count": len(self.quotes),
                "open_interest_count": len(self.open_interest),
                "mark_count": len(self.mark_data),
                "catalog_error": self.catalog_error,
                "market_error": self.market_error,
                "mark_warning": self.mark_warning,
            }

    def schedule_catalog(self, when: float) -> None:
        with self._lock:
            self.next_catalog_at = when

    def schedule_market(self, when: float) -> None:
        with self._lock:
            self.next_market_at = when

    def health(self) -> dict[str, Any]:
        with self._lock:
            return self._health_locked(self.monotonic())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            mono_now = self.monotonic()
            wall_now = self.wall_clock()
            contracts = copy.deepcopy(self.contracts)
            quotes = copy.deepcopy(self.quotes)
            open_interest = copy.deepcopy(self.open_interest)
            annualized_values = copy.deepcopy(self.annualized_values)
            probabilities = copy.deepcopy(self.probabilities)
            index_price = self.index_price
            market_generation_ms = self.server_time_ms
            market_fetched_at = self.market_fetched_at
            catalog_fetched_at = self.catalog_fetched_at
            next_market = self.next_market_at
            next_catalog = self.next_catalog_at
            now_ms = self._current_server_ms_locked(mono_now, wall_now)
            health = copy.deepcopy(self._health_locked(mono_now))
        rows = []
        for contract in contracts:
            quote = quotes.get(contract["symbol"], {})
            oi_row = open_interest.get(contract["symbol"], {})
            oi_value = oi_row.get("open_interest")
            probability_row = probabilities.get(contract["symbol"], {})
            annualized_row = annualized_values.get(contract["symbol"], {})
            bid = normalized_bid(quote.get("bid"), contract["unit"])
            ask = finite_positive(quote.get("ask")) if finite_positive(contract["unit"]) else None
            remaining_seconds = max(0.0, (contract["expiry_ms"] - now_ms) / 1000.0)
            stored_annualized = finite_number(annualized_row.get("annualized_pct"))
            stored_period_return = finite_number(annualized_row.get("period_return_pct"))
            if remaining_seconds <= 0:
                annualized = None
                period_return = None
                mark_time_value = None
                mark_period_return = None
                mark_annualized = None
                time_value_status = "expired"
                annualized_reason = "expired"
            else:
                annualized = stored_annualized
                period_return = stored_period_return
                mark_time_value = finite_number(annualized_row.get("mark_time_value"))
                mark_period_return = finite_number(annualized_row.get("mark_period_return_pct"))
                mark_annualized = finite_number(annualized_row.get("mark_annualized_pct"))
                time_value_status = annualized_row.get("time_value_status") or "unavailable"
                annualized_reason = annualized_row.get("annualized_unavailable_reason")
                if not annualized_row:
                    annualized_reason = "market_generation_unavailable"
            stored_probability = finite_nonnegative(probability_row.get("exercise_probability_pct"))
            stored_reason = probability_row.get("exercise_probability_unavailable_reason")
            if remaining_seconds <= 0:
                probability = None
                probability_reason = "expired"
                probability_state = "expired"
            elif stored_probability is not None:
                probability = stored_probability
                probability_reason = None
                probability_state = "settling" if remaining_seconds <= 1800 else "normal"
            else:
                probability = None
                probability_reason = stored_reason or "mark_unavailable"
                probability_state = "unavailable"
            valid_index = finite_positive(index_price)
            money, tolerance = (moneyness(contract["side"], contract["strike"], valid_index)
                                if valid_index is not None else (None, None))
            rows.append({
                **contract,
                "bid": bid,
                "ask": ask,
                "last": quote.get("last"),
                "last_trade_time_ms": quote.get("last_trade_time_ms"),
                "open_interest": oi_value,
                "open_interest_time_ms": oi_row.get("open_interest_time_ms"),
                "annualized_pct": annualized,
                "intrinsic_value": finite_nonnegative(annualized_row.get("intrinsic_value")),
                "time_value": finite_number(annualized_row.get("time_value")),
                "time_value_status": time_value_status,
                "capital_base": finite_positive(annualized_row.get("capital_base")),
                "period_return_pct": period_return,
                "remaining_years": finite_positive(annualized_row.get("remaining_years")),
                "calculation_index_price": finite_positive(annualized_row.get("calculation_index_price")),
                "annualized_basis": annualized_row.get("annualized_basis") or (
                    "time_value_on_spot" if contract["side"] == "CALL" else "time_value_on_strike"
                ),
                "annualized_calculated_at_ms": annualized_row.get("annualized_calculated_at_ms"),
                "annualized_unavailable_reason": annualized_reason,
                "mark_time_value": mark_time_value,
                "mark_period_return_pct": mark_period_return,
                "mark_annualized_pct": mark_annualized,
                "mark_annualized_calculated_at_ms": annualized_row.get("mark_annualized_calculated_at_ms") if remaining_seconds > 0 else None,
                "mark_iv": probability_row.get("mark_iv"),
                "risk_free_interest": probability_row.get("risk_free_interest"),
                "delta": probability_row.get("delta"),
                "mark_price": probability_row.get("mark_price"),
                "exercise_probability_pct": probability,
                "probability_calculated_at_ms": probability_row.get("probability_calculated_at_ms"),
                "exercise_probability_unavailable_reason": probability_reason,
                "probability_display_state": probability_state,
                "remaining_seconds": remaining_seconds,
                "moneyness": money,
                "atm_tolerance": tolerance,
            })
        return {
            "app": APP_ID,
            "source": "Binance Options EAPI",
            "underlying": "BTCUSDT",
            "currency": "USDT",
            "index_price": index_price,
            "market_generation_ms": market_generation_ms,
            "server_time": utc_iso(now_ms / 1000.0),
            "server_time_ms": int(now_ms),
            "fetched_at": utc_iso(market_fetched_at) if market_fetched_at is not None else None,
            "catalog_fetched_at": utc_iso(catalog_fetched_at) if catalog_fetched_at is not None else None,
            "status": health,
            "next_refresh_seconds": max(0, math.ceil(next_market - mono_now)),
            "next_catalog_refresh_seconds": max(0, math.ceil(next_catalog - mono_now)),
            "contracts": rows,
        }


