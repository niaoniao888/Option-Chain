from __future__ import annotations

import math
import threading
import time
from typing import Callable


class GlobalRequestGate:
    """Reserve globally spaced HTTP start slots without holding a lock while sleeping."""

    def __init__(self, *, minimum_interval: float = 1.0,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.minimum_interval = minimum_interval
        self.monotonic, self.sleep = monotonic, sleep
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._paused_until = 0.0
        self._request_count = 0

    def acquire(self) -> float:
        waited = 0.0
        while True:
            with self._lock:
                now = self.monotonic()
                delay = max(self._next_start, self._paused_until) - now
                if delay <= 0:
                    self._next_start = now + self.minimum_interval
                    self._request_count += 1
                    return waited
            delay = max(0.0, delay)
            waited += delay
            self.sleep(delay)

    def pause(self, seconds: float) -> None:
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
            seconds = 60.0
        with self._lock:
            self._paused_until = max(self._paused_until, self.monotonic() + max(60.0, seconds))

    def diagnostics(self) -> dict[str, int | float]:
        with self._lock:
            return {"request_count": self._request_count,
                    "pause_remaining_seconds": max(0.0, self._paused_until - self.monotonic())}

    def ready_in(self) -> float:
        with self._lock:
            return max(0.0, max(self._next_start, self._paused_until) - self.monotonic())


DEFAULT_HTTP_GATE = GlobalRequestGate()

