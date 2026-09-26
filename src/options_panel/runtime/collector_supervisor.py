from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Any, Callable

from options_panel.runtime.lock import ProcessLock


class CollectorSupervisor:
    """Own one collector thread and its process lock without owning its run loop."""

    _retained_lock = threading.RLock()
    _retained_owners: dict[str, "CollectorSupervisor"] = {}

    def __init__(
        self,
        *,
        make_thread: Callable[[], Any],
        signal_stop: Callable[[Any], None],
        lock_path: Path,
        join_timeout: float = 15,
        lock_factory: Callable[[Path], Any] = ProcessLock,
    ):
        self.make_thread = make_thread
        self.signal_stop = signal_stop
        self.lock_path = Path(lock_path)
        self.join_timeout = join_timeout
        self.lock_factory = lock_factory
        self.thread: Any | None = None
        self.lock: Any | None = None

    @property
    def _owner_key(self) -> str:
        return os.path.normcase(str(self.lock_path.resolve()))

    @property
    def running(self) -> bool:
        return bool(self.thread is not None and self.thread.is_alive())

    def _release_completed(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        if self.lock is not None:
            self.lock.release()
        self.thread = None
        self.lock = None
        with self._retained_lock:
            if self._retained_owners.get(self._owner_key) is self:
                self._retained_owners.pop(self._owner_key, None)

    def _reap_completed_owner(self) -> None:
        with self._retained_lock:
            owner = self._retained_owners.get(self._owner_key)
            if owner is None or owner is self or owner.running:
                return
            owner._release_completed()

    def _retain_owner(self) -> None:
        with self._retained_lock:
            self._retained_owners[self._owner_key] = self

    @classmethod
    def retained_owner_count(cls) -> int:
        """Return the number of live or not-yet-reaped collector owners."""
        with cls._retained_lock:
            return len(cls._retained_owners)

    def start(self) -> bool:
        if self.thread is not None:
            if self.thread.is_alive():
                return False
            self._release_completed()
        self._reap_completed_owner()
        lock = self.lock_factory(self.lock_path)
        try:
            lock.acquire()
            thread = self.make_thread()
            thread.start()
        except Exception:
            lock.release()
            raise
        self.lock = lock
        self.thread = thread
        self._retain_owner()
        return True

    def stop(self) -> bool:
        if self.thread is None:
            self._reap_completed_owner()
            return True
        if not self.thread.is_alive():
            self._release_completed()
            return True
        self.signal_stop(self.thread)
        self.thread.join(timeout=self.join_timeout)
        if self.thread.is_alive():
            return False
        self._release_completed()
        return True
