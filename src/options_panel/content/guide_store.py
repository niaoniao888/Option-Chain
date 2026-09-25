from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any


class GuideError(RuntimeError):
    pass


class GuideStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cached_mtime_ns: int | None = None
        self._cached: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        with self._lock:
            try:
                stamp = self.path.stat().st_mtime_ns
                if self._cached is None or stamp != self._cached_mtime_ns:
                    value = json.loads(self.path.read_text(encoding="utf-8"))
                    self._validate(value)
                    self._cached, self._cached_mtime_ns = value, stamp
                return copy.deepcopy(self._cached)
            except (OSError, ValueError, TypeError) as exc:
                raise GuideError(f"说明文档不可用：{type(exc).__name__}") from exc

    @staticmethod
    def _validate(value: Any) -> None:
        if not isinstance(value, dict) or not isinstance(value.get("revision"), str) or not isinstance(value.get("sections"), list):
            raise ValueError("invalid guide document")
        for section in value["sections"]:
            if not isinstance(section, dict) or not all(isinstance(section.get(k), str) for k in ("id", "title")) or not isinstance(section.get("topics"), list):
                raise ValueError("invalid guide section")
            for topic in section["topics"]:
                if not isinstance(topic, dict) or not all(isinstance(topic.get(k), str) for k in ("id", "title", "body")):
                    raise ValueError("invalid guide topic")
