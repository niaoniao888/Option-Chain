from __future__ import annotations

import copy
import logging
import math
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .alpaca_adapter import AuthorizationRequired
from .model import NormalizedContract, calculate_contract
from .model import parse_verified_utc
from .refresh_policy import (ACTIVE_WINDOW_SECONDS, MARKET_REFRESH_SECONDS,
                            SCHEDULER_TICK_SECONDS, STALE_AFTER_SECONDS,
                            TASK_START_INTERVAL_SECONDS, IDLE_CACHE_SECONDS,
                            MAX_IDLE_CACHE_SYMBOLS, CLIENT_SEQUENCE_RETENTION_SECONDS, MAX_TRACKED_CLIENTS)
from .refresh_policy import MAX_ACTIVE_SYMBOLS
from .request_throttle import DEFAULT_HTTP_GATE
from options_panel.logging import log_event


def adapter_configuration(adapter) -> dict[str, Any]:
    capability = getattr(adapter, "configuration_status", None)
    if callable(capability):
        result = capability()
        if isinstance(result, dict):
            return {
                "configured": bool(result.get("configured")),
                "error": result.get("error"),
            }
    return {"configured": bool(getattr(adapter, "ready", True)), "error": None}


def utc_now_iso(clock: Callable[[], float] = time.time) -> str:
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat().replace("+00:00", "Z")

class ClientCapacityError(RuntimeError):
    pass


class MarketService:
    def __init__(self, adapter, *, wall_clock=time.time, monotonic=time.monotonic,
                 request_gate=DEFAULT_HTTP_GATE):
        self.adapter, self.wall_clock, self.monotonic = adapter, wall_clock, monotonic
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_access: dict[str, float] = {}
        self._last_success: dict[str, float] = {}
        self._next_attempt: dict[str, float] = {}
        self._leases: dict[str, tuple[str, float]] = {}
        self._client_sequences: dict[str, tuple[int, float]] = {}
        self._legacy_until: dict[str, float] = {}
        self._inflight: set[str] = set()
        self._last_task_started = float("-inf")
        self._last_was_nocache = False
        self._diagnostics: dict[str, dict[str, int | float | None]] = {}
        self._queued_since: dict[str, float] = {}
        self._stop = threading.Event()
        self._instance_id = uuid.uuid4().hex
        self._success_count = 0
        self.request_gate = request_gate

    def _version(self) -> str:
        return f"{self._instance_id}:{self._success_count}"

    def _pending(self, symbol: str) -> dict[str, Any]:
        configuration = adapter_configuration(self.adapter)
        configured = configuration["configured"]
        configuration_message = (
            "数据源配置无效，请检查本机管理配置"
            if configuration["error"]
            else "数据源尚未配置，请先在本机管理页完成配置"
        )
        return {"app": "us-options-dashboard", "source": getattr(self.adapter, "source_name", type(self.adapter).__name__),
                "symbol": symbol, "state": "loading" if configured else "configuration_required",
                "market_status": "UNVERIFIED", "fetch_health": "waiting_for_first_snapshot" if configured else "awaiting_configuration",
                "source_delay_label": getattr(self.adapter, "pending_source_delay_label", None),
                "freshness": "unavailable", "quote_time": None, "fetched_at": None, "calculated_at": None,
                "calculation_basis": "等待完整快照", "underlying_price": None, "contracts": [],
                "error": "正在获取首轮完整快照" if configured else configuration_message,
                "mode": "unavailable", "latest_completed_session_date": None,
                "market_status_valid_until_utc": None,
                "snapshot_version": self._version(),
                "next_refresh_seconds": 0 if configured else None}

    def _active_symbols_locked(self, now: float) -> set[str]:
        self._leases = {client: lease for client, lease in self._leases.items() if lease[1] > now}
        self._client_sequences = {client: record for client, record in self._client_sequences.items()
                                  if record[1] > now}
        self._legacy_until = {symbol: until for symbol, until in self._legacy_until.items() if until > now}
        return set(self._legacy_until) | {symbol for symbol, _until in self._leases.values()}

    def health_summary(self) -> dict[str, Any]:
        """Return bounded top-level collector metadata without projecting contracts."""
        now = self.monotonic()
        with self._lock:
            active = self._active_symbols_locked(now)
            active_failures = {
                symbol
                for symbol in active
                if int(self._diagnostics.get(symbol, {}).get("consecutive_failures", 0) or 0) > 0
                or self._cache.get(symbol, {}).get("fetch_health") == "failed"
            }
            success_ages = [
                max(0.0, now - self._last_success[symbol])
                for symbol in active
                if symbol in self._last_success
            ]
            waiting_symbols = active - active_failures - set(self._last_success)
            if not active:
                data_status = "no_active"
            elif active_failures:
                data_status = "degraded" if success_ages else "failed"
            elif waiting_symbols and success_ages:
                data_status = "partial"
            elif waiting_symbols:
                data_status = "waiting"
            elif max(success_ages) >= STALE_AFTER_SECONDS:
                data_status = "stale"
            else:
                data_status = "healthy"
            return {
                "data_status": data_status,
                "active_symbol_count": len(active),
                "cache_symbol_count": len(self._cache),
                "queued_symbol_count": len(active.intersection(self._queued_since)),
                "inflight_symbol_count": len(active.intersection(self._inflight)),
                "failure_count": len(active_failures),
                "waiting_symbol_count": len(waiting_symbols),
                "data_age_seconds": max(success_ages) if success_ages else None,
                "contract_count": sum(
                    len(value.get("contracts", ())) for value in self._cache.values()
                    if isinstance(value, dict)
                ),
            }

    def _touch_lease_locked(self, symbol: str, now: float, client_id: str | None,
                            active: bool | None, activity_seq: int | None) -> None:
        other_active = set(self._legacy_until)
        other_active.update(
            lease_symbol
            for lease_client, (lease_symbol, _until) in self._leases.items()
            if lease_client != client_id
        )
        activating = not (client_id and active is False)
        if activating and symbol not in other_active and len(other_active) >= MAX_ACTIVE_SYMBOLS:
            raise ClientCapacityError("当前活跃股票较多，请稍后重试")
        if client_id:
            tracked = self._leases.keys() | self._client_sequences.keys()
            if client_id not in tracked and len(tracked) >= MAX_TRACKED_CLIENTS:
                raise ClientCapacityError("当前访问会话较多，请稍后重试")
            if activity_seq is not None:
                previous = self._client_sequences.get(client_id)
                if previous is None or activity_seq > previous[0]:
                    self._client_sequences[client_id] = (
                        activity_seq, now + CLIENT_SEQUENCE_RETENTION_SECONDS)
                    if active is False:
                        self._leases.pop(client_id, None)
                    else:
                        self._leases[client_id] = (symbol, now + ACTIVE_WINDOW_SECONDS)
            elif active is False:
                current = self._leases.get(client_id)
                if current is not None and current[0] == symbol:
                    self._leases.pop(client_id, None)
            else:
                self._leases[client_id] = (symbol, now + ACTIVE_WINDOW_SECONDS)
        else:
            self._legacy_until[symbol] = now + ACTIVE_WINDOW_SECONDS
        if not activating:
            return
        if symbol not in self._cache:
            self._queued_since.setdefault(symbol, now)
        self._last_access[symbol] = now

    def _evict_idle_locked(self, now: float) -> None:
        active = self._active_symbols_locked(now)
        for symbol in set(self._queued_since) - active - set(self._cache):
            self._queued_since.pop(symbol, None); self._last_access.pop(symbol, None)
            self._next_attempt.pop(symbol, None); self._diagnostics.pop(symbol, None)
        idle = sorted((self._last_access.get(symbol, float("-inf")), symbol)
                      for symbol in self._cache if symbol not in active)
        remove = {symbol for touched, symbol in idle if now - touched >= IDLE_CACHE_SECONDS}
        remaining = [(touched, symbol) for touched, symbol in idle if symbol not in remove]
        if len(remaining) > MAX_IDLE_CACHE_SYMBOLS:
            remove.update(symbol for _touched, symbol in remaining[:len(remaining)-MAX_IDLE_CACHE_SYMBOLS])
        for symbol in remove:
            self._cache.pop(symbol, None); self._last_access.pop(symbol, None)
            self._last_success.pop(symbol, None); self._next_attempt.pop(symbol, None)
            self._diagnostics.pop(symbol, None); self._legacy_until.pop(symbol, None)
            self._queued_since.pop(symbol, None)

    def snapshot(self, symbol: str, if_version: str | None = None, *,
                 client_id: str | None = None, active: bool | None = None,
                 activity_seq: int | None = None) -> dict[str, Any]:
        now = self.monotonic()
        with self._lock:
            self._active_symbols_locked(now)
            self._touch_lease_locked(symbol, now, client_id, active, activity_seq)
            self._evict_idle_locked(now)
            active_symbols = self._active_symbols_locked(now)
            cached = self._cache.get(symbol)
            has_cache = cached is not None
            if cached is None:
                cached = self._pending(symbol)
            last_success = self._last_success.get(symbol)
            next_attempt = self._next_attempt.get(symbol)
            diagnostic = dict(self._diagnostics.get(symbol, {}))
            inflight = symbol in self._inflight
            cache_count = len(self._cache)
            active_count = len(active_symbols)
            last_task_started = self._last_task_started
        unchanged = if_version is not None and if_version == cached.get("snapshot_version")
        # The cache is replaced as a whole.  The light response reads only immutable
        # top-level values; large copying and row projection happen outside the lock.
        result = ({key: value for key, value in cached.items() if key != "contracts"}
                  if unchanged else copy.deepcopy(cached))
        result["unchanged"] = unchanged
        wall_now = self.wall_clock()
        result["server_time"] = utc_now_iso(lambda: wall_now)
        active_symbol = symbol in active_symbols
        gate = self.request_gate.diagnostics()
        gate_ready = self.request_gate.ready_in()
        earliest = max(next_attempt or 0.0, last_task_started + TASK_START_INTERVAL_SECONDS,
                       now + gate_ready)
        result["next_refresh_seconds"] = (max(0, math.ceil(earliest - now)) if active_symbol else None)
        result["schedule_state"] = ("refreshing" if inflight else "inactive" if not active_symbol else
                                    "cooldown" if gate["pause_remaining_seconds"] > 0 else
                                    "queued" if not has_cache else
                                    "waiting" if next_attempt is not None and next_attempt > now else
                                    "queued")
        result["diagnostics"] = {"fetch_count": int(diagnostic.get("fetch_count", 0) or 0),
                                 "queue_wait_ms": diagnostic.get("queue_wait_ms"),
                                 "fetch_duration_ms": diagnostic.get("fetch_duration_ms"),
                                 "global_request_count": gate["request_count"],
                                 "global_pause_remaining_seconds": gate["pause_remaining_seconds"],
                                 "active_symbol_count": active_count, "cache_symbol_count": cache_count}
        if last_success is not None:
            age = max(0.0, now - last_success)
            result["fetched_age_seconds"] = age
            if age >= STALE_AFTER_SECONDS:
                result["fetch_health"] = "stale"
                if result.get("state") == "ready": result["state"] = "stale"
            elif result.get("state") == "ready":
                result["fetch_health"] = "healthy"
        now_utc = datetime.fromtimestamp(wall_now, timezone.utc)
        transition = parse_verified_utc(result.get("market_status_valid_until_utc"))
        crossed_transition = transition is not None and now_utc >= transition
        rows = cached.get("contracts", [])
        if not unchanged:
            for row in result.get("contracts", []):
                expiry = parse_verified_utc(row.get("expires_at_utc"))
                if expiry is not None:
                    row["remaining_seconds"] = max(0.0, (expiry - now_utc).total_seconds())
                if expiry is not None and expiry <= now_utc:
                    row.update(calculation_status="expired", annualized_pct=None, period_return_pct=None,
                               exercise_probability_pct=None, probability_reason="expired",
                               remaining_seconds=0.0, ranking_eligible=False, ranking_reason="expired",
                               close_reference_eligible=False, close_reference_reason="expired")
                    continue
                valid_until = parse_verified_utc(row.get("quote_valid_until_utc"))
                if row.get("calculation_status") == "calculated":
                    if valid_until is None:
                        row.update(ranking_eligible=False, ranking_reason="quote_ranking_window_unverified")
                    elif now_utc > valid_until:
                        row.update(ranking_eligible=False, ranking_reason="quote_ranking_window_expired")
                    else:
                        row.update(ranking_eligible=True, ranking_reason=None)
        healthy = result.get("state") == "ready" and result.get("fetch_health") == "healthy" and not crossed_transition
        market = str(result.get("market_status", "UNVERIFIED")).upper()

        def live_eligible(row: dict[str, Any]) -> bool:
            expiry = parse_verified_utc(row.get("expires_at_utc"))
            valid_until = parse_verified_utc(row.get("quote_valid_until_utc"))
            return (row.get("calculation_status") == "calculated" and expiry is not None and expiry > now_utc
                    and valid_until is not None and now_utc <= valid_until)

        def closed_eligible(row: dict[str, Any]) -> bool:
            expiry = parse_verified_utc(row.get("expires_at_utc"))
            return row.get("close_reference_eligible") is True and expiry is not None and expiry > now_utc

        mode = "unavailable"
        if healthy and market == "OPEN" and any(live_eligible(row) for row in rows): mode = "live"
        elif healthy and market == "CLOSED" and any(closed_eligible(row) for row in rows): mode = "close_reference"
        result["mode"] = mode
        if not unchanged:
            if not healthy:
                result["mode"] = "unavailable"
                for row in result.get("contracts", []):
                    row["close_reference_eligible"] = False
                    row["close_reference_reason"] = "snapshot_not_healthy"
                    row["ranking_eligible"] = False
                    row["ranking_reason"] = "snapshot_not_healthy"
            elif market == "OPEN" and any(row.get("ranking_eligible") is True for row in result.get("contracts", [])):
                result["mode"] = "live"
                for row in result.get("contracts", []):
                    row["close_reference_eligible"] = False
                    row["close_reference_reason"] = "market_not_closed"
            elif market == "CLOSED" and any(row.get("close_reference_eligible") is True for row in result.get("contracts", [])):
                result["mode"] = "close_reference"
            else:
                result["mode"] = "unavailable"
                result["mode_reason"] = "no_eligible_contracts" if healthy else "snapshot_not_healthy"
            if crossed_transition:
                result["mode_reason"] = "market_transition_requires_refresh"
                for row in result.get("contracts", []):
                    row.update(ranking_eligible=False, ranking_reason="market_transition_requires_refresh",
                               close_reference_eligible=False, close_reference_reason="market_transition_requires_refresh")
        elif crossed_transition:
            result["mode_reason"] = "market_transition_requires_refresh"
        elif mode == "unavailable" and healthy:
            result["mode_reason"] = "no_eligible_contracts"
        active_rows = [row for row in rows
                       if (expiry := parse_verified_utc(row.get("expires_at_utc"))) is not None and expiry > now_utc]
        result["validation_status"] = {
            "contract_count": len(rows),
            "active_contract_count": len(active_rows),
            "standard_calculated_count": sum(
                row.get("standard") is True and row.get("quote_eligible") is True
                and row.get("calculation_status") == "calculated" for row in active_rows),
            "ranking_eligible_count": sum(
                (live_eligible(row) if mode == "live" else closed_eligible(row) if mode == "close_reference" else False)
                for row in active_rows),
        }
        return result

    def _refresh_impl(self, symbol: str) -> bool:
        try:
            raw = self.adapter.fetch(symbol)
            contracts = raw.get("contracts")
            if not isinstance(contracts, list): raise ValueError("adapter 未返回 contracts 数组")
            calculated_at, market = raw.get("calculated_at"), str(raw.get("market_status", "UNVERIFIED"))
            normalized = [item if isinstance(item, NormalizedContract) else NormalizedContract(**item) for item in contracts]
            rows = [calculate_contract(item, underlying_price=raw.get("underlying_price"), market_status=market,
                                       calculated_at_utc=calculated_at,
                                       now_utc=datetime.fromtimestamp(self.wall_clock(), timezone.utc)) for item in normalized]
            snapshot = {"app": "us-options-dashboard", "source": getattr(self.adapter, "source_name", type(self.adapter).__name__),
                        "symbol": symbol, "state": "ready", "market_status": market, "fetch_health": "healthy",
                        "source_delay_label": raw.get("source_delay_label"), "freshness": raw.get("freshness", "snapshot"),
                        "quote_time": raw.get("quote_time"), "fetched_at": utc_now_iso(self.wall_clock),
                        "calculated_at": calculated_at, "calculation_basis": raw.get("calculation_basis"),
                        "latest_completed_session_date": raw.get("latest_completed_session_date"),
                        "market_status_valid_until_utc": raw.get("market_status_valid_until_utc"),
                        "underlying_price": raw.get("underlying_price"), "contracts": rows,
                        "error": raw.get("notice"), "mode": "unavailable", "next_refresh_seconds": MARKET_REFRESH_SECONDS}
            completed_at = self.monotonic()
            with self._lock:
                self._success_count += 1
                snapshot["snapshot_version"] = self._version()
                self._cache[symbol] = snapshot
                self._last_success[symbol] = completed_at
                self._next_attempt[symbol] = completed_at + MARKET_REFRESH_SECONDS
            return True
        except AuthorizationRequired:
            completed_at = self.monotonic()
            with self._lock:
                current_ref = self._cache.get(symbol)
            current = dict(current_ref) if current_ref is not None else self._pending(symbol)
            current["state"], current["fetch_health"], current["error"] = (
                "authorization_required",
                "awaiting_configuration",
                "数据源授权失效，请在本机管理页重新配置",
            )
            with self._lock:
                self._next_attempt[symbol] = completed_at + MARKET_REFRESH_SECONDS
                self._cache[symbol] = current
            return False

        except Exception as exc:
            try: requested_retry = float(getattr(exc, "retry_after", MARKET_REFRESH_SECONDS))
            except (TypeError, ValueError): requested_retry = MARKET_REFRESH_SECONDS
            retry_seconds = (max(MARKET_REFRESH_SECONDS, requested_retry)
                             if math.isfinite(requested_retry) else MARKET_REFRESH_SECONDS)
            completed_at = self.monotonic()
            with self._lock:
                current_ref = self._cache.get(symbol)
            failed = dict(current_ref) if current_ref is not None else self._pending(symbol)
            if current_ref is None:
                failed.update(
                    state="error",
                    fetch_health="failed",
                    error="行情刷新失败，请稍后重试",
                )
            else:
                failed.update(
                    state="degraded",
                    fetch_health="failed",
                    error="行情刷新失败，已保留最后成功快照",
                )
            with self._lock:
                self._next_attempt[symbol] = completed_at + retry_seconds
                self._cache[symbol] = failed
            return False


    def refresh(self, symbol: str) -> bool:
        started = self.monotonic()
        with self._lock:
            if symbol in self._inflight:
                return False
            self._inflight.add(symbol)
            due = self._next_attempt.get(symbol, self._queued_since.get(symbol, started))
            self._last_task_started = started
            stats = dict(self._diagnostics.get(symbol, {}))
            stats["queue_wait_ms"] = max(0, int((started - due) * 1000))
            self._diagnostics[symbol] = stats
        success = False
        try:
            success = self._refresh_impl(symbol)
            return success
        finally:
            completed = self.monotonic()
            with self._lock:
                self._inflight.discard(symbol)
                stats = dict(self._diagnostics.get(symbol, {}))
                stats["fetch_count"] = int(stats.get("fetch_count", 0) or 0) + 1
                stats["fetch_duration_ms"] = max(0, int((completed - started) * 1000))
                previous_failures = int(stats.get("consecutive_failures", 0) or 0)
                stats["consecutive_failures"] = 0 if success else previous_failures + 1
                self._diagnostics[symbol] = stats
                self._queued_since.pop(symbol, None)
                cache_size = len(self._cache)
                contract_count = len(self._cache.get(symbol, {}).get("contracts", []))
                last_success = self._last_success.get(symbol)
                age_seconds = None if last_success is None else max(0.0, completed - last_success)
            log_event(
                logging.INFO if success else logging.WARNING,
                "market_refresh_round",
                market="us-equities",
                provider=getattr(self.adapter, "source_name", type(self.adapter).__name__),
                instrument=symbol,
                result="success" if success else "failed",
                duration_ms=stats["fetch_duration_ms"],
                consecutive_failures=stats["consecutive_failures"],
                age_seconds=age_seconds,
                queue_wait_ms=stats.get("queue_wait_ms"),
                cache_size=cache_size,
                contract_count=contract_count,
            )
    def run(self) -> None:
        while not self._stop.wait(SCHEDULER_TICK_SECONDS):
            with self._lock:
                now = self.monotonic()
                self._evict_idle_locked(now)
                active = self._active_symbols_locked(now)
                candidates = [(self._next_attempt.get(symbol, 0.0), symbol, symbol not in self._cache)
                              for symbol in active if symbol not in self._inflight
                              and now >= self._next_attempt.get(symbol, 0.0)]
            if not adapter_configuration(self.adapter)["configured"]: continue
            if (not candidates or now < self._last_task_started + TASK_START_INTERVAL_SECONDS
                    or self.request_gate.ready_in() > 0):
                continue
            no_cache = sorted((item for item in candidates if item[2]), key=lambda item: (item[0], item[1]))
            cached = sorted((item for item in candidates if not item[2]), key=lambda item: (item[0], item[1]))
            chosen = (no_cache[0] if no_cache and not self._last_was_nocache else
                      cached[0] if cached else no_cache[0] if no_cache else None)
            if chosen is None: continue
            symbol = chosen[1]
            with self._lock:
                if symbol not in self._active_symbols_locked(self.monotonic()): continue
                self._last_was_nocache = chosen[2]
            self.refresh(symbol)

    def prepare_start(self) -> None:
        """Called only after the runtime owns the collector process lock."""
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()
