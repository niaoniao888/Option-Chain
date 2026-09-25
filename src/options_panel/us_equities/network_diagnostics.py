from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

LOG_NAME = re.compile(r"^us-options-network-(\d{4}-\d{2}-\d{2})\.jsonl$")
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_LINE_BYTES = 2048
RETENTION_DAYS = 100


def endpoint_category(host: str, path: str) -> str:
    if path.endswith("/quotes/latest"): return "stock_quote_latest"
    if path.endswith("/quotes"): return "stock_quotes_history"
    if "/options/snapshots" in path: return "option_snapshots"
    if path == "/v2/options/contracts": return "option_contracts"
    if path == "/v2/calendar": return "market_calendar"
    if path.startswith("/v2/assets/"): return "asset_metadata"
    if host == "local": return "local_http"
    return "allowed_read_endpoint"


class SafeJsonlLog:
    def __init__(self, directory: Path, *, wall_clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic, suppress_seconds: float = 30.0):
        self.directory = Path(directory)
        self.wall_clock, self.monotonic = wall_clock, monotonic
        self.suppress_seconds = suppress_seconds
        self._lock = threading.Lock()
        self._last: dict[tuple[Any, ...], float] = {}

    def _utc_now(self) -> datetime:
        return datetime.fromtimestamp(self.wall_clock(), timezone.utc)

    def _cleanup(self, today: date) -> None:
        cutoff = today.toordinal() - RETENTION_DAYS
        try: entries = list(self.directory.iterdir())
        except OSError: return
        for entry in entries:
            match = LOG_NAME.fullmatch(entry.name)
            if not match or not entry.is_file(): continue
            try: stamp = date.fromisoformat(match.group(1))
            except ValueError: continue
            if stamp.toordinal() <= cutoff or stamp > today:
                try: entry.unlink()
                except OSError: pass

    def record(self, *, endpoint: str, attempt: int, duration_ms: int,
               status: int | None, error_kind: str | None, errno: int | None = None) -> None:
        safe_endpoint = endpoint if endpoint in {
            "stock_quote_latest", "stock_quotes_history", "option_snapshots", "option_contracts",
            "market_calendar", "asset_metadata", "allowed_read_endpoint", "local_http",
        } else "allowed_read_endpoint"
        safe_kind = error_kind if error_kind in {
            None, "authorization", "rate_limited", "http_4xx", "http_5xx", "redirect_blocked",
            "dns", "timeout", "connection", "tls_certificate", "tls_handshake",
            "response_too_large", "response_format", "network", "local_http_error",
        } else "network"
        safe_status = status if isinstance(status, int) and 100 <= status <= 599 else None
        safe_errno = errno if isinstance(errno, int) and -99999 <= errno <= 99999 else None
        now_mono = self.monotonic()
        signature = (safe_endpoint, max(1, min(int(attempt), 2)), safe_status, safe_kind, safe_errno)
        with self._lock:
            last = self._last.get(signature)
            if last is not None and now_mono - last < self.suppress_seconds:
                return
            self._last[signature] = now_mono
            now = self._utc_now()
            payload = {"time": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                       "endpoint": safe_endpoint, "attempt": max(1, min(int(attempt), 2)),
                       "duration_ms": max(0, min(int(duration_ms), 120000)),
                       "status": safe_status, "error_kind": safe_kind, "errno": safe_errno}
            line = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            if len(line) > MAX_LINE_BYTES: return
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                self._cleanup(now.date())
                target = self.directory / f"us-options-network-{now.date().isoformat()}.jsonl"
                size = target.stat().st_size if target.exists() else 0
                if size + len(line) > MAX_FILE_BYTES: return
                with target.open("ab") as handle:
                    handle.write(line); handle.flush(); os.fsync(handle.fileno())
            except OSError:
                return


DEFAULT_LOG = SafeJsonlLog(Path(os.environ.get(
    "OPTIONS_US_LOG_DIR",
    str(Path(__file__).resolve().parents[3] / "runtime" / "us-equities" / "logs"),
)))
